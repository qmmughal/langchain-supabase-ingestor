"""
Scheduler — APScheduler-driven polling loop.
Runs the full pipeline (fetch → dedup → persist → report → notify) on a cron schedule.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from agent.config import AgentConfig
from agent.database import Database
from agent.deduplicator import Deduplicator
from agent.fetcher import FDAFetcher
from agent.models import RunSummary
from agent.notifier import Notifier
from agent.reporter import HtmlReporter, NdjsonLogger, TerminalReporter

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


async def run_pipeline(config: AgentConfig, dry_run: bool = False) -> RunSummary:
    """
    Execute one full monitoring cycle:
    1. Load known keys from DB
    2. For each active endpoint, fetch records since last seen date
    3. Deduplicate against DB and within the current batch
    4. Persist new records
    5. Generate HTML report + NDJSON log
    6. Fire notifications
    7. Save run audit record
    """
    run_id = str(uuid.uuid4())[:8]
    started_at = datetime.now(timezone.utc).isoformat()
    logger.info("=" * 60)
    logger.info("Run %s started at %s", run_id, started_at)

    total_fetched = 0
    total_new = 0
    total_duplicates = 0
    total_errors = 0
    error_messages: list[str] = []
    all_new_records = []
    categories_polled: list[str] = []

    async with Database(config.db_path) as db:
        # Seed deduplicator from DB state
        known_numbers = await db.get_known_recall_numbers()
        known_hashes = await db.get_known_hashes()
        dedup = Deduplicator(known_numbers, known_hashes)

        async with FDAFetcher(config) as fetcher:
            for ep_cfg in config.active_endpoints:
                cat, ep = ep_cfg.category, ep_cfg.endpoint
                ep_label = f"{cat}/{ep}"
                if cat not in categories_polled:
                    categories_polled.append(cat)

                # Use the most recent date seen for this category as the start date
                latest_date_str = await db.get_latest_report_date(cat)
                since_dt: Optional[datetime] = None
                if latest_date_str and len(latest_date_str) == 8:
                    try:
                        since_dt = datetime.strptime(latest_date_str, "%Y%m%d")
                    except ValueError:
                        pass

                batch: list = []
                try:
                    async for record in fetcher.fetch_since(cat, ep, since_dt):
                        total_fetched += 1
                        batch.append(record)
                except Exception as exc:
                    msg = f"Error fetching {ep_label}: {exc}"
                    logger.error(msg)
                    total_errors += 1
                    error_messages.append(msg)
                    continue

                new_records = dedup.filter(batch)
                total_new += len(new_records)
                total_duplicates += len(batch) - len(new_records)
                all_new_records.extend(new_records)

                if not dry_run and new_records:
                    inserted = await db.insert_recalls(new_records)
                    logger.info("%s -> %d new records persisted.", ep_label, inserted)
                elif dry_run:
                    logger.info("[DRY RUN] %s -> %d new records (not persisted).", ep_label, len(new_records))

        # ── Reports ───────────────────────────────────────────────────────────
        finished_at = datetime.now(timezone.utc).isoformat()
        summary = RunSummary(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            total_fetched=total_fetched,
            total_new=total_new,
            total_duplicates=total_duplicates,
            total_errors=total_errors,
            categories_polled=categories_polled,
            error_messages=error_messages,
        )

        terminal = TerminalReporter()
        terminal.print_summary(summary)

        if all_new_records:
            terminal.print_recalls(all_new_records, title=f"New Recalls — Run {run_id}")

            if not dry_run:
                # NDJSON log
                ndjson = NdjsonLogger(config.log_path)
                ndjson.append(all_new_records)

                # HTML report
                if _TEMPLATES_DIR.exists():
                    html_reporter = HtmlReporter(_TEMPLATES_DIR)
                    recent = await db.get_recent(200)
                    from agent.models import RecallRecord
                    recent_records = [RecallRecord.from_db_row(r) for r in recent]
                    html_reporter.render(recent_records, summary, config.report_path)

                # Notifications
                notifier = Notifier(config)
                notifier.notify(all_new_records)

        if not dry_run:
            await db.save_run_summary(summary)

    logger.info("Run %s complete -- %d new / %d dupes / %d errors.", run_id, total_new, total_duplicates, total_errors)
    return summary


def start_scheduler(config: AgentConfig) -> None:
    """Start the blocking APScheduler loop."""
    scheduler = BlockingScheduler(timezone="UTC")
    trigger = CronTrigger.from_crontab(config.schedule_cron, timezone="UTC")

    def _job() -> None:
        asyncio.run(run_pipeline(config))

    scheduler.add_job(_job, trigger, id="fda_recall_poll", name="FDA Recall Monitor Poll")
    logger.info(
        "Scheduler started -- cron: %s (UTC). Press Ctrl+C to stop.",
        config.schedule_cron,
    )

    # Run immediately on startup, then follow the cron schedule
    try:
        _job()
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
