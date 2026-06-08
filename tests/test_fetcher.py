"""
Tests for agent/fetcher.py — uses pytest-httpx to mock openFDA responses.
"""

from __future__ import annotations

import json
import pytest
import httpx
from pytest_httpx import HTTPXMock

from agent.config import AgentConfig
from agent.fetcher import FDAFetcher, _make_url
from agent.models import RecallRecord


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _mock_fda_response(results: list[dict], total: int = None) -> dict:
    """Build a minimal openFDA enforcement API response envelope."""
    return {
        "meta": {
            "disclaimer": "test",
            "results": {"skip": 0, "limit": 100, "total": total or len(results)},
        },
        "results": results,
    }


_SAMPLE_ENFORCEMENT = {
    "recall_number": "D-0001-2024",
    "product_description": "Peanut Butter Crackers 12oz",
    "recalling_firm": "Acme Foods Inc.",
    "classification": "Class I",
    "status": "Ongoing",
    "voluntary_mandated": "Voluntary: Firm Initiated",
    "report_date": "20240315",
    "recall_initiation_date": "20240310",
    "reason_for_recall": "Undeclared peanuts",
    "state": "CA",
    "country": "US",
    "distribution_pattern": "Nationwide",
    "quantity": "1,200 cases",
}


@pytest.fixture
def config(tmp_path) -> AgentConfig:
    """Minimal config pointing to a temp DB."""
    cfg = AgentConfig(config_path=None)
    cfg._raw.agent.db_path = str(tmp_path / "test.db")
    return cfg


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_since_returns_records(httpx_mock: HTTPXMock, config: AgentConfig):
    """Fetcher should yield RecallRecord objects from a mocked API response."""
    httpx_mock.add_response(json=_mock_fda_response([_SAMPLE_ENFORCEMENT]))

    records = []
    async with FDAFetcher(config) as fetcher:
        async for r in fetcher.fetch_since("food", "enforcement"):
            records.append(r)

    assert len(records) == 1
    r = records[0]
    assert isinstance(r, RecallRecord)
    assert r.recall_number == "D-0001-2024"
    assert r.product_description == "Peanut Butter Crackers 12oz"
    assert r.classification == "Class I"
    assert r.category == "food"
    assert r.endpoint == "enforcement"


@pytest.mark.asyncio
async def test_fetch_since_404_returns_empty(httpx_mock: HTTPXMock, config: AgentConfig):
    """A 404 from openFDA (no results) should yield no records, not raise."""
    httpx_mock.add_response(status_code=404)

    records = []
    async with FDAFetcher(config) as fetcher:
        async for r in fetcher.fetch_since("drug", "enforcement"):
            records.append(r)

    assert records == []


@pytest.mark.asyncio
async def test_record_content_hash_is_deterministic(httpx_mock: HTTPXMock, config: AgentConfig):
    """Two identical records should produce the same content hash."""
    httpx_mock.add_response(json=_mock_fda_response([_SAMPLE_ENFORCEMENT]))

    records = []
    async with FDAFetcher(config) as fetcher:
        async for r in fetcher.fetch_since("food", "enforcement"):
            records.append(r)

    from agent.models import RecallRecord
    dup = RecallRecord(
        recall_number=_SAMPLE_ENFORCEMENT["recall_number"],
        product_description=_SAMPLE_ENFORCEMENT["product_description"],
        recalling_firm=_SAMPLE_ENFORCEMENT["recalling_firm"],
        classification=_SAMPLE_ENFORCEMENT["classification"],
        status=_SAMPLE_ENFORCEMENT["status"],
        voluntary_mandated=_SAMPLE_ENFORCEMENT["voluntary_mandated"],
        report_date=_SAMPLE_ENFORCEMENT["report_date"],
        recall_initiation_date=_SAMPLE_ENFORCEMENT["recall_initiation_date"],
        reason_for_recall=_SAMPLE_ENFORCEMENT["reason_for_recall"],
        category="food", endpoint="enforcement",
        state="CA", country="US",
        distribution_pattern="", quantity="", source_url="",
    )
    assert records[0].content_hash == dup.content_hash


@pytest.mark.asyncio
async def test_class_label_parsing():
    """class_label property should normalise FDA classification strings."""
    from agent.models import RecallRecord

    def _make(cls: str) -> RecallRecord:
        return RecallRecord(
            recall_number="X", product_description="p", recalling_firm="f",
            classification=cls, status="", voluntary_mandated="",
            report_date="20240101", recall_initiation_date="", reason_for_recall="",
            category="drug", endpoint="enforcement",
            state="", country="", distribution_pattern="", quantity="", source_url="",
        )

    assert _make("Class I").class_label == "Class I"
    assert _make("Class II").class_label == "Class II"
    assert _make("Class III").class_label == "Class III"
    assert _make("CLASS I").class_label == "Class I"
    assert _make("").class_label == "Unknown"
