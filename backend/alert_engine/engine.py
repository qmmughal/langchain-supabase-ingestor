"""
Alert engine – subscribes to Supabase Realtime and evaluates alert rules.

When a new `processed_documents` row is inserted, this engine:
  1. Loads all active alert rules from Supabase
  2. Evaluates the document against each rule (keyword / semantic / LLM)
  3. Writes matched alerts to the `alert_log` table
  4. Supabase Realtime then pushes the alert to the dashboard

Usage:
    python -m backend.alert_engine.engine
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from realtime import AsyncRealtimeClient, RealtimeSubscribeStates

from backend.alert_engine.evaluator import evaluate_all_rules
from backend.shared.models import AlertRule, ProcessedDocument, RuleMode, Severity
from backend.shared.supabase_client import get_supabase

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def load_active_rules() -> list[AlertRule]:
    """Fetch all active alert rules from Supabase."""
    db = get_supabase()
    resp = db.table("alert_rules").select("*").eq("is_active", True).execute()
    rules = []
    for row in resp.data:
        try:
            rules.append(AlertRule(**row))
        except Exception as exc:
            logger.warning("Could not parse rule row: %s — %s", row, exc)
    return rules


def insert_alert_log(
    rule: AlertRule,
    doc: ProcessedDocument,
    result: "EvaluationResult",  # type: ignore[name-defined]
    alert_body: str | None,
) -> None:
    """Insert a new alert into alert_log."""
    from backend.alert_engine.evaluator import EvaluationResult

    db = get_supabase()
    row = {
        "rule_id": str(rule.id),
        "rule_name": rule.name,
        "document_id": str(doc.id) if doc.id else None,
        "source_name": doc.source_name,
        "matched_content": (doc.content[:500] if doc.content else None),
        "match_score": result.score,
        "mode_used": result.mode_used.value,
        "alert_title": rule.alert_title or doc.title or "Alert triggered",
        "alert_body": alert_body,
        "severity": rule.alert_severity.value if rule.alert_severity else "medium",
    }
    try:
        db.table("alert_log").insert(row).execute()
        # Update rule's last_fired_at
        db.table("alert_rules").update(
            {"last_fired_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", str(rule.id)).execute()
        logger.info("Alert logged: rule='%s' doc='%s'", rule.name, doc.title)
    except Exception as exc:
        logger.error("Failed to insert alert log: %s", exc)


def _is_in_cooldown(rule: AlertRule) -> bool:
    """Return True if the rule is still within its cooldown period."""
    if not rule.last_fired_at or not rule.cooldown_seconds:
        return False
    elapsed = (datetime.now(timezone.utc) - rule.last_fired_at).total_seconds()
    return elapsed < rule.cooldown_seconds


def _build_alert_body(rule: AlertRule, doc: ProcessedDocument, reason: str) -> str:
    parts = []
    if doc.summary:
        parts.append(f"**Summary:** {doc.summary}")
    if doc.tags:
        parts.append(f"**Tags:** {', '.join(doc.tags)}")
    parts.append(f"**Source:** {doc.source_name or 'unknown'}")
    parts.append(f"**Match:** {reason}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------

async def handle_new_document(payload: dict) -> None:
    """Called when a new row is inserted into processed_documents."""
    record = payload.get("record", {})
    if not record:
        return

    try:
        doc = ProcessedDocument(
            id=record.get("id"),
            raw_event_id=record.get("raw_event_id"),
            source_id=record.get("source_id"),
            source_name=record.get("source_name"),
            title=record.get("title"),
            content=record.get("content", ""),
            summary=record.get("summary"),
            tags=record.get("tags") or [],
            severity=Severity(record.get("severity", "info")),
            metadata=record.get("metadata") or {},
            embedding=record.get("embedding"),
        )
    except Exception as exc:
        logger.warning("Could not parse document from realtime payload: %s", exc)
        return

    logger.info(
        "New document received: '%s' from '%s'", doc.title, doc.source_name
    )

    rules = load_active_rules()
    if not rules:
        return

    matches = evaluate_all_rules(rules, doc)
    for rule, result in matches:
        if _is_in_cooldown(rule):
            logger.info(
                "Rule '%s' in cooldown, skipping alert for doc '%s'",
                rule.name,
                doc.title,
            )
            continue
        alert_body = _build_alert_body(rule, doc, result.reason)
        insert_alert_log(rule, doc, result, alert_body)


# ---------------------------------------------------------------------------
# Realtime subscription
# ---------------------------------------------------------------------------

async def run_engine() -> None:
    """Connect to Supabase Realtime and listen for new processed_documents."""
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    # Supabase Realtime websocket URL
    ws_url = supabase_url.replace("https://", "wss://") + "/realtime/v1"

    logger.info("Connecting to Supabase Realtime at %s ...", ws_url)

    client = AsyncRealtimeClient(ws_url, token=supabase_key)
    await client.connect()

    channel = client.channel("processed_documents_inserts")

    async def on_insert(payload: dict, *_: object, **__: object) -> None:
        await handle_new_document(payload)

    await (
        channel.on_postgres_changes(
            event="INSERT",
            schema="public",
            table="processed_documents",
            callback=on_insert,
        )
        .subscribe()
    )

    logger.info("Alert engine running — waiting for new documents...")
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Alert engine shutting down...")
    finally:
        await client.close()


def main() -> None:
    asyncio.run(run_engine())


if __name__ == "__main__":
    main()
