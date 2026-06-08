"""
Database layer — async SQLite via aiosqlite.
Handles schema migrations, record persistence, and query helpers.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from agent.models import RecallRecord, RunSummary

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 2


class Database:
    """Async SQLite database for recall records and run audit log."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def __aenter__(self) -> "Database":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._migrate()
        logger.debug("Database connected: %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ── Migrations ────────────────────────────────────────────────────────────

    async def _migrate(self) -> None:
        assert self._db is not None
        async with self._db.execute("PRAGMA user_version") as cur:
            row = await cur.fetchone()
        version = row[0] if row else 0

        if version < 1:
            logger.info("Applying DB migration v1 (initial schema)…")
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS recalls (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    recall_number           TEXT NOT NULL,
                    product_description     TEXT,
                    recalling_firm          TEXT,
                    classification          TEXT,
                    status                  TEXT,
                    voluntary_mandated      TEXT,
                    report_date             TEXT,
                    recall_initiation_date  TEXT,
                    reason_for_recall       TEXT,
                    category                TEXT,
                    endpoint                TEXT,
                    state                   TEXT,
                    country                 TEXT,
                    distribution_pattern    TEXT,
                    quantity                TEXT,
                    source_url              TEXT,
                    content_hash            TEXT UNIQUE NOT NULL,
                    fetched_at              TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_recall_number ON recalls(recall_number);
                CREATE INDEX IF NOT EXISTS idx_category      ON recalls(category);
                CREATE INDEX IF NOT EXISTS idx_report_date   ON recalls(report_date);
                CREATE INDEX IF NOT EXISTS idx_classification ON recalls(classification);

                CREATE TABLE IF NOT EXISTS runs (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id            TEXT UNIQUE NOT NULL,
                    started_at        TEXT,
                    finished_at       TEXT,
                    total_fetched     INTEGER DEFAULT 0,
                    total_new         INTEGER DEFAULT 0,
                    total_duplicates  INTEGER DEFAULT 0,
                    total_errors      INTEGER DEFAULT 0,
                    categories_polled TEXT,    -- JSON array
                    error_messages    TEXT      -- JSON array
                );
            """)

        if version < 2:
            logger.info("Applying DB migration v2 (recall_number index)…")
            await self._db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_recall_number_hash "
                "ON recalls(recall_number, content_hash)"
            )

        await self._db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        await self._db.commit()

    # ── Write operations ──────────────────────────────────────────────────────

    async def insert_recalls(self, records: list[RecallRecord]) -> int:
        """Insert records, ignoring duplicates. Returns count of inserted rows."""
        if not records:
            return 0
        assert self._db is not None
        inserted = 0
        async with self._db.cursor() as cur:
            for r in records:
                try:
                    await cur.execute(
                        """
                        INSERT OR IGNORE INTO recalls (
                            recall_number, product_description, recalling_firm,
                            classification, status, voluntary_mandated,
                            report_date, recall_initiation_date, reason_for_recall,
                            category, endpoint, state, country,
                            distribution_pattern, quantity, source_url,
                            content_hash, fetched_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            r.recall_number, r.product_description, r.recalling_firm,
                            r.classification, r.status, r.voluntary_mandated,
                            r.report_date, r.recall_initiation_date, r.reason_for_recall,
                            r.category, r.endpoint, r.state, r.country,
                            r.distribution_pattern, r.quantity, r.source_url,
                            r.content_hash, r.fetched_at,
                        ),
                    )
                    if cur.rowcount:
                        inserted += 1
                except aiosqlite.IntegrityError:
                    pass
        await self._db.commit()
        logger.debug("Inserted %d / %d records into DB.", inserted, len(records))
        return inserted

    async def save_run_summary(self, summary: RunSummary) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, started_at, finished_at,
                total_fetched, total_new, total_duplicates, total_errors,
                categories_polled, error_messages
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                summary.run_id, summary.started_at, summary.finished_at,
                summary.total_fetched, summary.total_new,
                summary.total_duplicates, summary.total_errors,
                json.dumps(summary.categories_polled),
                json.dumps(summary.error_messages),
            ),
        )
        await self._db.commit()

    # ── Read operations ───────────────────────────────────────────────────────

    async def get_known_recall_numbers(self) -> set[str]:
        assert self._db is not None
        async with self._db.execute("SELECT recall_number FROM recalls") as cur:
            rows = await cur.fetchall()
        return {row[0].strip().upper() for row in rows if row[0]}

    async def get_known_hashes(self) -> set[str]:
        assert self._db is not None
        async with self._db.execute("SELECT content_hash FROM recalls") as cur:
            rows = await cur.fetchall()
        return {row[0] for row in rows if row[0]}

    async def get_latest_report_date(self, category: str) -> Optional[str]:
        """Return the most recent report_date seen for a given category."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT MAX(report_date) FROM recalls WHERE category = ?", (category,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row and row[0] else None

    async def get_recent(self, n: int = 20) -> list[dict]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM recalls ORDER BY fetched_at DESC LIMIT ?", (n,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_by_category(self, category: str, limit: int = 50) -> list[dict]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM recalls WHERE category=? ORDER BY report_date DESC LIMIT ?",
            (category, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_by_classification(self, classification: str, limit: int = 50) -> list[dict]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM recalls WHERE classification LIKE ? ORDER BY report_date DESC LIMIT ?",
            (f"%{classification}%", limit),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def count_stats(self) -> dict:
        """Return aggregate statistics for the stats CLI command."""
        assert self._db is not None
        stats: dict = {}

        async with self._db.execute("SELECT COUNT(*) FROM recalls") as cur:
            row = await cur.fetchone()
        stats["total_recalls"] = row[0] if row else 0

        async with self._db.execute(
            "SELECT category, COUNT(*) as cnt FROM recalls GROUP BY category"
        ) as cur:
            rows = await cur.fetchall()
        stats["by_category"] = {row[0]: row[1] for row in rows}

        async with self._db.execute(
            "SELECT classification, COUNT(*) as cnt FROM recalls GROUP BY classification"
        ) as cur:
            rows = await cur.fetchall()
        stats["by_classification"] = {row[0]: row[1] for row in rows}

        async with self._db.execute(
            "SELECT status, COUNT(*) as cnt FROM recalls GROUP BY status"
        ) as cur:
            rows = await cur.fetchall()
        stats["by_status"] = {row[0]: row[1] for row in rows}

        async with self._db.execute(
            "SELECT COUNT(*), started_at FROM runs ORDER BY started_at DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        stats["total_runs"] = row[0] if row else 0
        stats["last_run"] = row[1] if row else "never"

        return stats

    async def get_all_for_export(self) -> list[dict]:
        assert self._db is not None
        async with self._db.execute("SELECT * FROM recalls ORDER BY report_date DESC") as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]
