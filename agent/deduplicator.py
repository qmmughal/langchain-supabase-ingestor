"""
Deduplicator — filters out records already seen in a previous run.

Two deduplication strategies (both applied):
  1. recall_number  — FDA-assigned globally unique identifier
  2. content_hash   — SHA-256 of key fields (catches records with no number)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agent.models import RecallRecord

logger = logging.getLogger(__name__)


@dataclass
class DeduplicationResult:
    new_records: list[RecallRecord]
    duplicate_count: int
    seen_recall_numbers: set[str]
    seen_hashes: set[str]


class Deduplicator:
    """
    Stateful in-memory deduplicator for a single poll run.

    The caller is responsible for seeding `known_recall_numbers` and
    `known_hashes` from the database before filtering a batch.
    """

    def __init__(
        self,
        known_recall_numbers: set[str] | None = None,
        known_hashes: set[str] | None = None,
    ) -> None:
        self._recall_numbers: set[str] = known_recall_numbers or set()
        self._hashes: set[str] = known_hashes or set()
        self._duplicate_count = 0
        self._new_count = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def filter(self, records: list[RecallRecord]) -> list[RecallRecord]:
        """
        Return only records not seen before; update internal state for
        subsequent calls within the same run.
        """
        new: list[RecallRecord] = []
        for record in records:
            if self._is_duplicate(record):
                self._duplicate_count += 1
                logger.debug("Duplicate skipped: %s (%s)", record.recall_number, record.content_hash[:12])
            else:
                self._accept(record)
                new.append(record)

        self._new_count += len(new)
        logger.info(
            "Deduplication pass: %d new / %d duplicates (session totals: %d new / %d dupes)",
            len(new), len(records) - len(new), self._new_count, self._duplicate_count,
        )
        return new

    def filter_one(self, record: RecallRecord) -> bool:
        """Return True if the record is new (not a duplicate)."""
        if self._is_duplicate(record):
            self._duplicate_count += 1
            return False
        self._accept(record)
        self._new_count += 1
        return True

    @property
    def stats(self) -> dict[str, int]:
        return {
            "new": self._new_count,
            "duplicates": self._duplicate_count,
            "total_seen": len(self._recall_numbers),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_duplicate(self, record: RecallRecord) -> bool:
        """Check both recall_number and content_hash."""
        rn = record.recall_number.strip().upper()
        # recall_number "UNKNOWN" is not a reliable key
        if rn and rn != "UNKNOWN" and rn in self._recall_numbers:
            return True
        if record.content_hash and record.content_hash in self._hashes:
            return True
        return False

    def _accept(self, record: RecallRecord) -> None:
        """Register a new record's keys to prevent future duplicates."""
        rn = record.recall_number.strip().upper()
        if rn and rn != "UNKNOWN":
            self._recall_numbers.add(rn)
        if record.content_hash:
            self._hashes.add(record.content_hash)
