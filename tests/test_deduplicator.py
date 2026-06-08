"""
Tests for agent/deduplicator.py
"""

from __future__ import annotations

import pytest

from agent.deduplicator import Deduplicator
from agent.models import RecallRecord


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_record(
    recall_number: str = "D-0001-2024",
    product: str = "Peanut Butter",
    firm: str = "Acme Foods",
    report_date: str = "20240315",
) -> RecallRecord:
    return RecallRecord(
        recall_number=recall_number,
        product_description=product,
        recalling_firm=firm,
        classification="Class I",
        status="Ongoing",
        voluntary_mandated="Voluntary",
        report_date=report_date,
        recall_initiation_date="20240310",
        reason_for_recall="Contamination",
        category="food",
        endpoint="enforcement",
        state="CA",
        country="US",
        distribution_pattern="Nationwide",
        quantity="100 cases",
        source_url="https://example.com",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_new_record_passes_through():
    dedup = Deduplicator()
    record = _make_record()
    result = dedup.filter([record])
    assert len(result) == 1
    assert result[0].recall_number == "D-0001-2024"


def test_duplicate_recall_number_filtered():
    """A record with a previously seen recall_number should be dropped."""
    dedup = Deduplicator(known_recall_numbers={"D-0001-2024"})
    record = _make_record(recall_number="D-0001-2024")
    result = dedup.filter([record])
    assert result == []
    assert dedup.stats["duplicates"] == 1


def test_duplicate_hash_filtered():
    """A record with the same content hash (different recall_number) should be dropped."""
    record = _make_record(recall_number="UNKNOWN")
    dedup = Deduplicator(known_hashes={record.content_hash})
    result = dedup.filter([record])
    assert result == []


def test_within_batch_deduplication():
    """Identical records within the same batch should be deduplicated."""
    dedup = Deduplicator()
    record = _make_record()
    # Feed the same record twice in one batch
    result = dedup.filter([record, record])
    assert len(result) == 1
    assert dedup.stats["duplicates"] == 1


def test_different_records_both_pass():
    dedup = Deduplicator()
    r1 = _make_record(recall_number="D-0001-2024", product="Product A")
    r2 = _make_record(recall_number="D-0002-2024", product="Product B")
    result = dedup.filter([r1, r2])
    assert len(result) == 2


def test_filter_one_interface():
    dedup = Deduplicator()
    r = _make_record()
    assert dedup.filter_one(r) is True   # first time: new
    assert dedup.filter_one(r) is False  # second time: duplicate


def test_stats_accumulate_across_calls():
    dedup = Deduplicator()
    r1 = _make_record(recall_number="D-0001", product="A")
    r2 = _make_record(recall_number="D-0002", product="B")
    dedup.filter([r1])
    dedup.filter([r1, r2])  # r1 is now a dup, r2 is new
    assert dedup.stats["new"] == 2
    assert dedup.stats["duplicates"] == 1


def test_unknown_recall_number_uses_hash():
    """Records with 'UNKNOWN' recall_number should dedup purely by content_hash."""
    dedup = Deduplicator()
    r1 = _make_record(recall_number="UNKNOWN", product="X", firm="Y")
    r2 = _make_record(recall_number="UNKNOWN", product="X", firm="Y")  # same content
    result = dedup.filter([r1, r2])
    assert len(result) == 1


def test_unknown_recall_number_different_content_both_pass():
    dedup = Deduplicator()
    r1 = _make_record(recall_number="UNKNOWN", product="X", firm="Y")
    r2 = _make_record(recall_number="UNKNOWN", product="Z", firm="W")  # different content
    result = dedup.filter([r1, r2])
    assert len(result) == 2
