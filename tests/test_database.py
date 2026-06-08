"""
Tests for agent/database.py — uses in-memory SQLite.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from agent.database import Database
from agent.models import RecallRecord, RunSummary


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_record(
    recall_number: str = "D-0001-2024",
    category: str = "food",
    classification: str = "Class I",
    report_date: str = "20240315",
) -> RecallRecord:
    return RecallRecord(
        recall_number=recall_number,
        product_description=f"Product for {recall_number}",
        recalling_firm="Test Firm LLC",
        classification=classification,
        status="Ongoing",
        voluntary_mandated="Voluntary",
        report_date=report_date,
        recall_initiation_date="20240310",
        reason_for_recall="Test reason",
        category=category,
        endpoint="enforcement",
        state="TX",
        country="US",
        distribution_pattern="TX, CA",
        quantity="500 units",
        source_url="https://example.com",
    )


def _make_summary(run_id: str = "abc12345") -> RunSummary:
    return RunSummary(
        run_id=run_id,
        started_at="2024-03-15T10:00:00",
        finished_at="2024-03-15T10:01:00",
        total_fetched=10,
        total_new=8,
        total_duplicates=2,
        total_errors=0,
        categories_polled=["food", "drug"],
    )


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    """In-memory (well, tmp_path) database for each test."""
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insert_and_retrieve(db: Database):
    record = _make_record()
    inserted = await db.insert_recalls([record])
    assert inserted == 1

    rows = await db.get_recent(10)
    assert len(rows) == 1
    assert rows[0]["recall_number"] == "D-0001-2024"
    assert rows[0]["classification"] == "Class I"


@pytest.mark.asyncio
async def test_insert_duplicate_ignored(db: Database):
    """Inserting the same record twice should not duplicate it."""
    record = _make_record()
    first = await db.insert_recalls([record])
    second = await db.insert_recalls([record])
    assert first == 1
    assert second == 0   # OR IGNORE silently skips

    rows = await db.get_recent(10)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_known_recall_numbers(db: Database):
    r1 = _make_record(recall_number="A-001")
    r2 = _make_record(recall_number="B-002")
    await db.insert_recalls([r1, r2])

    known = await db.get_known_recall_numbers()
    assert "A-001" in known
    assert "B-002" in known


@pytest.mark.asyncio
async def test_get_known_hashes(db: Database):
    record = _make_record()
    await db.insert_recalls([record])

    hashes = await db.get_known_hashes()
    assert record.content_hash in hashes


@pytest.mark.asyncio
async def test_get_latest_report_date(db: Database):
    old = _make_record(recall_number="OLD-001", report_date="20230101")
    new = _make_record(recall_number="NEW-001", report_date="20240315")
    await db.insert_recalls([old, new])

    latest = await db.get_latest_report_date("food")
    assert latest == "20240315"


@pytest.mark.asyncio
async def test_get_by_category(db: Database):
    food = _make_record(recall_number="F-001", category="food")
    drug = _make_record(recall_number="D-001", category="drug")
    await db.insert_recalls([food, drug])

    food_rows = await db.get_by_category("food")
    assert len(food_rows) == 1
    assert food_rows[0]["category"] == "food"


@pytest.mark.asyncio
async def test_count_stats(db: Database):
    records = [
        _make_record(recall_number="A-001", category="food", classification="Class I"),
        _make_record(recall_number="A-002", category="food", classification="Class II"),
        _make_record(recall_number="A-003", category="drug", classification="Class I"),
    ]
    await db.insert_recalls(records)

    stats = await db.count_stats()
    assert stats["total_recalls"] == 3
    assert stats["by_category"]["food"] == 2
    assert stats["by_category"]["drug"] == 1
    assert stats["by_classification"]["Class I"] == 2


@pytest.mark.asyncio
async def test_save_and_retrieve_run_summary(db: Database):
    summary = _make_summary()
    await db.save_run_summary(summary)
    stats = await db.count_stats()
    # total_runs counts from runs table
    assert stats["total_runs"] >= 1


@pytest.mark.asyncio
async def test_get_all_for_export(db: Database):
    records = [_make_record(recall_number=f"R-{i:03d}") for i in range(5)]
    await db.insert_recalls(records)

    all_rows = await db.get_all_for_export()
    assert len(all_rows) == 5
