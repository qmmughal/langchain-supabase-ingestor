"""
Ingestor entry point.

Fetches all active data sources from Supabase, polls each one on its
configured schedule, and persists new events + processed documents.

Usage:
    python -m backend.ingestor.main              # run once
    python -m backend.ingestor.main --loop       # run continuously
    python -m backend.ingestor.main --source "FDA Drug Recalls"  # single source
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from backend.ingestor.loaders import AsyncRestApiLoader
from backend.ingestor.pipeline import process_events_batch
from backend.shared.models import DataSource, IngestorRun, RunStatus
from backend.shared.ollama_client import ollama_available
from backend.shared.supabase_client import get_supabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def load_active_sources(source_name: str | None = None) -> list[DataSource]:
    """Load active data sources from Supabase."""
    db = get_supabase()
    q = db.table("data_sources").select("*").eq("is_active", True)
    if source_name:
        q = q.eq("name", source_name)
    resp = q.execute()
    sources = []
    for row in resp.data:
        sources.append(DataSource(**row))
    return sources


def upsert_raw_events(events: list[Any]) -> list[Any]:
    """Upsert raw events; return only newly-inserted rows."""
    if not events:
        return []
    db = get_supabase()
    rows = [
        {
            "source_id": str(e.source_id),
            "source_name": e.source_name,
            "external_id": e.external_id,
            "raw_payload": e.raw_payload,
        }
        for e in events
    ]
    resp = (
        db.table("raw_events")
        .upsert(rows, on_conflict="source_id,external_id", ignore_duplicates=True)
        .execute()
    )
    return resp.data or []


def fetch_new_raw_events(
    source_id: UUID, external_ids: list[str]
) -> list[dict[str, Any]]:
    """Fetch raw_event rows that were actually inserted (for pipeline input)."""
    if not external_ids:
        return []
    db = get_supabase()
    resp = (
        db.table("raw_events")
        .select("*")
        .eq("source_id", str(source_id))
        .in_("external_id", external_ids[:500])  # Supabase IN limit
        .execute()
    )
    return resp.data or []


def upsert_processed_documents(docs: list[Any]) -> int:
    """Insert processed documents. Returns number inserted."""
    if not docs:
        return 0
    db = get_supabase()
    rows = []
    for d in docs:
        row: dict[str, Any] = {
            "source_id": str(d.source_id) if d.source_id else None,
            "source_name": d.source_name,
            "title": d.title,
            "content": d.content,
            "summary": d.summary,
            "tags": d.tags,
            "severity": d.severity.value if d.severity else "info",
            "metadata": d.metadata,
        }
        if d.raw_event_id:
            row["raw_event_id"] = str(d.raw_event_id)
        if d.embedding:
            row["embedding"] = d.embedding
        rows.append(row)

    resp = db.table("processed_documents").insert(rows).execute()
    return len(resp.data or [])


def log_ingestor_run(run: IngestorRun) -> None:
    db = get_supabase()
    db.table("ingestor_runs").insert(
        {
            "source_id": str(run.source_id) if run.source_id else None,
            "source_name": run.source_name,
            "status": run.status.value,
            "items_fetched": run.items_fetched,
            "items_new": run.items_new,
            "items_processed": run.items_processed,
            "error_message": run.error_message,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


# ---------------------------------------------------------------------------
# Per-source ingestion
# ---------------------------------------------------------------------------

async def ingest_source(source: DataSource, use_llm: bool = True) -> IngestorRun:
    """Run the full ingestion pipeline for a single data source."""
    started = datetime.now(timezone.utc)
    run = IngestorRun(
        source_id=source.id,
        source_name=source.name,
        status=RunStatus.success,
        started_at=started,
    )

    try:
        # 1. Fetch events from REST API
        loader = AsyncRestApiLoader(source)
        events = await loader.fetch()
        run.items_fetched = len(events)

        if not events:
            logger.info("No items fetched from '%s'", source.name)
            log_ingestor_run(run)
            return run

        # 2. Upsert raw events (deduplication happens here)
        inserted = upsert_raw_events(events)
        run.items_new = len(inserted)
        logger.info(
            "'%s': %d fetched, %d new", source.name, run.items_fetched, run.items_new
        )

        if run.items_new == 0:
            log_ingestor_run(run)
            return run

        # 3. Retrieve the inserted rows (we need their UUIDs)
        new_ext_ids = [e.external_id for e in events if e.external_id]
        new_rows = fetch_new_raw_events(source.id, new_ext_ids)

        # Reconstruct RawEvent objects with real UUIDs
        from backend.shared.models import RawEvent
        enriched_events = [
            RawEvent(
                id=row["id"],
                source_id=row["source_id"],
                source_name=row["source_name"],
                external_id=row["external_id"],
                raw_payload=row["raw_payload"],
            )
            for row in new_rows
        ]

        # 4. Run LangChain pipeline
        docs = await asyncio.get_event_loop().run_in_executor(
            None, process_events_batch, enriched_events, use_llm
        )

        # 5. Persist processed documents
        inserted_docs = upsert_processed_documents(docs)
        run.items_processed = inserted_docs
        logger.info("'%s': %d documents processed", source.name, inserted_docs)

    except Exception as exc:
        logger.exception("Fatal error processing source '%s': %s", source.name, exc)
        run.status = RunStatus.error
        run.error_message = str(exc)

    log_ingestor_run(run)
    return run


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_all(source_name: str | None = None, use_llm: bool = True) -> None:
    """Run ingestion for all active sources (or a single named source)."""
    sources = load_active_sources(source_name)
    if not sources:
        logger.warning("No active sources found%s", f" matching '{source_name}'" if source_name else "")
        return

    logger.info("Ingesting %d source(s)...", len(sources))
    tasks = [ingest_source(s, use_llm=use_llm) for s in sources]
    runs = await asyncio.gather(*tasks)

    for run in runs:
        status_icon = "✓" if run.status == RunStatus.success else "✗"
        logger.info(
            "%s %s — fetched=%d new=%d processed=%d",
            status_icon,
            run.source_name,
            run.items_fetched,
            run.items_new,
            run.items_processed,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="LangChain + Supabase Ingestor")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--source", type=str, default=None, help="Ingest a single named source")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM processing (embeddings + metadata)")
    parser.add_argument("--interval", type=int, default=60, help="Loop interval in seconds (default 60)")
    args = parser.parse_args()

    use_llm = not args.no_llm

    if use_llm and not ollama_available():
        logger.error(
            "Ollama is not running at the configured URL. "
            "Start Ollama or use --no-llm to skip LLM processing."
        )
        sys.exit(1)

    if args.loop:
        logger.info("Starting ingestor loop (interval=%ds)...", args.interval)
        while True:
            asyncio.run(run_all(args.source, use_llm=use_llm))
            logger.info("Sleeping %ds...", args.interval)
            time.sleep(args.interval)
    else:
        asyncio.run(run_all(args.source, use_llm=use_llm))


if __name__ == "__main__":
    main()
