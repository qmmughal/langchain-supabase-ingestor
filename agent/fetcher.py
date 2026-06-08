"""
Fetcher — queries openFDA enforcement and recall endpoints.
Handles pagination, retries, and record normalisation into RecallRecord objects.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Optional
from urllib.parse import urlencode

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agent.config import AgentConfig
from agent.models import RecallRecord

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.fda.gov"
_PAGE_SIZE = 100   # openFDA max per request


class _NoResultsError(Exception):
    """Sentinel raised when openFDA returns 404 (no matching records)."""
    pass


def _make_url(category: str, endpoint: str) -> str:
    return f"{_BASE_URL}/{category}/{endpoint}.json"


def _format_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _source_url(category: str, endpoint: str, recall_number: str) -> str:
    return f"https://api.fda.gov/{category}/{endpoint}.json?search=recall_number:{recall_number}"


def _parse_record(raw: dict, category: str, endpoint: str) -> RecallRecord:
    """Convert a raw openFDA JSON object into a normalised RecallRecord."""
    get = lambda k, d="": (raw.get(k) or d).strip()
    return RecallRecord(
        recall_number=get("recall_number", "UNKNOWN"),
        product_description=get("product_description"),
        recalling_firm=get("recalling_firm"),
        classification=get("classification"),
        status=get("status"),
        voluntary_mandated=get("voluntary_mandated"),
        report_date=get("report_date"),
        recall_initiation_date=get("recall_initiation_date"),
        reason_for_recall=get("reason_for_recall"),
        category=category,
        endpoint=endpoint,
        state=get("state"),
        country=get("country"),
        distribution_pattern=get("distribution_pattern"),
        quantity=get("quantity"),
        source_url=_source_url(category, endpoint, get("recall_number", "")),
    )


class FDAFetcher:
    """Async fetcher for openFDA enforcement/recall endpoints."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        headers = {"User-Agent": "fda-recall-monitor/0.1 (github.com/fda-recall-monitor)"}
        if config.fda_api_key:
            headers["api_key"] = config.fda_api_key
            logger.debug("FDA API key loaded.")
        else:
            logger.warning(
                "No FDA_API_KEY set -- limited to 1,000 requests/day. "
                "Register free at https://open.fda.gov/apis/authentication/"
            )
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        )

    async def __aenter__(self) -> "FDAFetcher":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_since(
        self,
        category: str,
        endpoint: str,
        since_date: Optional[datetime] = None,
    ) -> AsyncIterator[RecallRecord]:
        """Yield RecallRecords fetched from the given endpoint since *since_date*."""
        if since_date is None:
            since_date = datetime.now(timezone.utc) - timedelta(days=self.config.initial_lookback_days)

        from_str = _format_date(since_date)
        to_str = _format_date(datetime.now(timezone.utc))
        date_field = "report_date"
        search = f"{date_field}:[{from_str}+TO+{to_str}]"

        url = _make_url(category, endpoint)
        skip = 0
        total_fetched = 0
        max_records = self.config.max_records_per_poll

        logger.info(
            "Fetching %s/%s | date range %s → %s",
            category, endpoint, from_str, to_str,
        )

        while total_fetched < max_records:
            limit = min(_PAGE_SIZE, max_records - total_fetched)
            params: dict[str, str | int] = {
                "search": search,
                "limit": limit,
                "skip": skip,
            }
            if self.config.fda_api_key:
                params["api_key"] = self.config.fda_api_key

            try:
                data = await self._get_json(url, params)
            except _NoResultsError:
                logger.info("No records found for %s/%s in date range.", category, endpoint)
                return

            results = data.get("results", [])
            if not results:
                break

            for raw in results:
                record = _parse_record(raw, category, endpoint)
                total_fetched += 1
                yield record

            meta = data.get("meta", {}).get("results", {})
            api_total = meta.get("total", 0)
            skip += len(results)

            logger.debug(
                "%s/%s — fetched %d/%d (API total=%d)",
                category, endpoint, total_fetched, max_records, api_total,
            )

            if skip >= api_total or len(results) < limit:
                break

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_json(self, url: str, params: dict) -> dict:
        """GET JSON with exponential back-off retry (network errors only).
        404 raises _NoResultsError immediately (no retry).
        """
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(httpx.RequestError),
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            reraise=True,
        ):
            with attempt:
                response = await self._client.get(url, params=params)
                if response.status_code == 404:
                    raise _NoResultsError()
                if response.status_code == 429:
                    logger.warning("Rate-limited by openFDA -- backing off...")
                    raise httpx.HTTPStatusError(
                        "429 Too Many Requests", request=response.request, response=response
                    )
                response.raise_for_status()
                return response.json()
        raise RuntimeError("Unreachable")  # tenacity reraises on exhaustion
