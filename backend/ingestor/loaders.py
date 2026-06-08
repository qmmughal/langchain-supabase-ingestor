"""
REST API source loaders for the ingestor.

Each loader polls a REST endpoint, extracts items using a jmespath expression,
and yields RawEvent objects ready for upsert to Supabase.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Generator
from uuid import UUID

import httpx
import jmespath

from backend.shared.models import DataSource, RawEvent

logger = logging.getLogger(__name__)


def _stable_id(payload: dict[str, Any]) -> str:
    """Generate a deterministic ID from a payload for deduplication."""
    serialised = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()[:32]


def _extract_items(response_data: Any, items_path: str) -> list[dict[str, Any]]:
    """
    Extract a list of items from a JSON response using jmespath.

    Handles two common structures:
    - items_path = '$[*]'         → top-level array
    - items_path = '$.results[*]' → nested path
    - items_path = '$.current'    → single object (wrapped in list)
    """
    # Strip leading '$.' or '$' for jmespath compatibility
    path = items_path.lstrip("$").lstrip(".").replace("[*]", "[]")
    # Handle bare '$[*]' meaning root array
    if not path or path == "[]":
        data = response_data if isinstance(response_data, list) else [response_data]
    else:
        data = jmespath.search(path, response_data)

    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, (dict, str, int, float))]
    return [{"value": data}]


class RestApiLoader:
    """
    Polls a REST endpoint and yields RawEvent objects.

    Args:
        source: DataSource configuration
        timeout: HTTP request timeout in seconds
    """

    def __init__(self, source: DataSource, timeout: float = 15.0):
        self.source = source
        self.timeout = timeout
        self._client = httpx.Client(
            headers={"User-Agent": "LangChainIngestor/1.0", **source.headers},
            timeout=timeout,
            follow_redirects=True,
        )

    def fetch(self) -> Generator[RawEvent, None, None]:
        """Fetch the endpoint and yield one RawEvent per extracted item."""
        logger.info("Polling source '%s': %s", self.source.name, self.source.url)
        try:
            response = self._client.get(self.source.url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HTTP %s from '%s': %s",
                exc.response.status_code,
                self.source.name,
                exc.response.text[:200],
            )
            return
        except httpx.RequestError as exc:
            logger.error("Request error for '%s': %s", self.source.name, exc)
            return
        except Exception as exc:
            logger.error("Unexpected error for '%s': %s", self.source.name, exc)
            return

        items = _extract_items(data, self.source.items_path)
        logger.info("Extracted %d items from '%s'", len(items), self.source.name)

        for item in items:
            # Normalise item to dict
            if not isinstance(item, dict):
                item = {"value": item}

            # Try to find a stable external ID from the payload
            external_id = (
                str(item.get("id") or item.get("ID") or item.get("recall_number") or "")
                or _stable_id(item)
            )

            yield RawEvent(
                source_id=self.source.id,
                source_name=self.source.name,
                external_id=external_id,
                raw_payload=item,
            )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RestApiLoader":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------

class AsyncRestApiLoader:
    """Async version of RestApiLoader for use in asyncio contexts."""

    def __init__(self, source: DataSource, timeout: float = 15.0):
        self.source = source
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        logger.info("Async polling source '%s': %s", self.source.name, self.source.url)
        headers = {"User-Agent": "LangChainIngestor/1.0", **self.source.headers}
        events: list[RawEvent] = []

        async with httpx.AsyncClient(
            headers=headers, timeout=self.timeout, follow_redirects=True
        ) as client:
            try:
                response = await client.get(self.source.url)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "HTTP %s from '%s'", exc.response.status_code, self.source.name
                )
                return events
            except Exception as exc:
                logger.error("Error fetching '%s': %s", self.source.name, exc)
                return events

        items = _extract_items(data, self.source.items_path)
        for item in items:
            if not isinstance(item, dict):
                item = {"value": item}
            external_id = (
                str(item.get("id") or item.get("ID") or item.get("recall_number") or "")
                or _stable_id(item)
            )
            events.append(
                RawEvent(
                    source_id=self.source.id,
                    source_name=self.source.name,
                    external_id=external_id,
                    raw_payload=item,
                )
            )

        logger.info(
            "Async extracted %d items from '%s'", len(events), self.source.name
        )
        return events
