"""
Shared data models for the FDA Recall Monitor agent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────────────────
# RecallRecord
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RecallRecord:
    """Normalised representation of a single FDA recall / enforcement action."""

    recall_number: str
    product_description: str
    recalling_firm: str
    classification: str           # "Class I" | "Class II" | "Class III" | ""
    status: str                   # "Ongoing" | "Completed" | "Terminated" | …
    voluntary_mandated: str
    report_date: str              # YYYYMMDD
    recall_initiation_date: str
    reason_for_recall: str
    category: str                 # "drug" | "device" | "food"
    endpoint: str                 # "enforcement" | "recall"
    state: str                    # US state abbreviation or ""
    country: str
    distribution_pattern: str
    quantity: str
    source_url: str
    content_hash: str = field(default="")
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        # Only compute hash if not already supplied (e.g. when reconstructing from DB)
        if not self.content_hash:
            self.content_hash = self._compute_hash()

    @classmethod
    def from_db_row(cls, row: dict) -> "RecallRecord":
        """Reconstruct a RecallRecord from a database row without rehashing."""
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: (v or "") for k, v in row.items() if k in fields})

    def _compute_hash(self) -> str:
        """Deterministic SHA-256 fingerprint for deduplication."""
        blob = "|".join([
            self.recall_number.strip().lower(),
            self.product_description.strip().lower()[:200],
            self.recalling_firm.strip().lower(),
            self.report_date.strip(),
            self.voluntary_mandated.strip().lower(),
        ])
        return hashlib.sha256(blob.encode()).hexdigest()

    @property
    def class_label(self) -> str:
        """Normalise classification to a short label."""
        c = self.classification.upper()
        if "I" in c and "II" not in c and "III" not in c:
            return "Class I"
        if "II" in c and "III" not in c:
            return "Class II"
        if "III" in c:
            return "Class III"
        return self.classification or "Unknown"

    @property
    def is_class_i(self) -> bool:
        return "I" in self.classification.upper() and "II" not in self.classification.upper()

    def to_dict(self) -> dict:
        return {
            "recall_number": self.recall_number,
            "product_description": self.product_description,
            "recalling_firm": self.recalling_firm,
            "classification": self.classification,
            "class_label": self.class_label,
            "status": self.status,
            "voluntary_mandated": self.voluntary_mandated,
            "report_date": self.report_date,
            "recall_initiation_date": self.recall_initiation_date,
            "reason_for_recall": self.reason_for_recall,
            "category": self.category,
            "endpoint": self.endpoint,
            "state": self.state,
            "country": self.country,
            "distribution_pattern": self.distribution_pattern,
            "quantity": self.quantity,
            "source_url": self.source_url,
            "content_hash": self.content_hash,
            "fetched_at": self.fetched_at,
        }


# ─────────────────────────────────────────────────────────────────────────────
# RunSummary
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RunSummary:
    """Audit record for a single poll run."""

    run_id: str
    started_at: str
    finished_at: str
    total_fetched: int
    total_new: int
    total_duplicates: int
    total_errors: int
    categories_polled: list[str]
    error_messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_fetched": self.total_fetched,
            "total_new": self.total_new,
            "total_duplicates": self.total_duplicates,
            "total_errors": self.total_errors,
            "categories_polled": self.categories_polled,
            "error_messages": self.error_messages,
        }
