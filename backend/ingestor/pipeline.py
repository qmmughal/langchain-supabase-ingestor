"""
LangChain ingestion pipeline.

For each RawEvent:
1. Convert payload to text
2. Split into chunks (for long documents)
3. Generate embeddings (Ollama / nomic-embed-text)
4. Summarise and extract tags + severity via LLM
5. Upsert ProcessedDocument(s) to Supabase

The pipeline is intentionally chunked so large payloads are handled cleanly,
but most API events produce a single short document.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from backend.shared.models import (
    ProcessedDocument,
    RawEvent,
    Severity,
)
from backend.shared.ollama_client import embed_texts, get_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Text splitter – 1 000 token chunks with 200-token overlap
# ---------------------------------------------------------------------------
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
)

# ---------------------------------------------------------------------------
# LLM prompt for metadata extraction
# ---------------------------------------------------------------------------
_METADATA_PROMPT = PromptTemplate.from_template(
    """You are a data analyst. Analyse the following event text and respond with
a JSON object containing exactly these keys:
  "title":    short title (≤ 12 words),
  "summary":  one-sentence summary (≤ 30 words),
  "tags":     list of 1-5 lowercase topic tags,
  "severity": one of [info, low, medium, high, critical]

Event text:
{text}

Respond ONLY with valid JSON. No markdown fences.
"""
)


def _payload_to_text(payload: dict[str, Any]) -> str:
    """Convert an arbitrary JSON payload to a readable text string."""
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            parts.append(f"{key}: {json.dumps(value, default=str)[:300]}")
        else:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def _parse_metadata_response(text: str) -> dict[str, Any]:
    """Parse the LLM JSON response, tolerating minor formatting issues."""
    # Strip markdown fences if the model ignores instructions
    text = re.sub(r"```(?:json)?", "", text).strip("`").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Attempt to extract first {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}
    return data


def _validate_severity(raw: Any) -> Severity:
    try:
        return Severity(str(raw).lower())
    except ValueError:
        return Severity.info


# ---------------------------------------------------------------------------
# Public pipeline function
# ---------------------------------------------------------------------------

def process_event(
    event: RawEvent,
    use_llm: bool = True,
) -> list[ProcessedDocument]:
    """
    Run the LangChain ingestion pipeline on a single RawEvent.

    Returns a list of ProcessedDocument objects (one per chunk, typically one).
    """
    raw_text = _payload_to_text(event.raw_payload)
    chunks = _splitter.split_text(raw_text)

    if not chunks:
        logger.warning("Empty event payload from source '%s'", event.source_name)
        return []

    # Embed all chunks at once
    try:
        vectors = embed_texts(chunks)
    except Exception as exc:
        logger.error("Embedding failed for event '%s': %s", event.external_id, exc)
        vectors = [None] * len(chunks)

    docs: list[ProcessedDocument] = []

    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        metadata: dict[str, Any] = {
            "chunk_index": i,
            "total_chunks": len(chunks),
            "source_url": str(event.raw_payload.get("url") or ""),
        }

        title: str | None = None
        summary: str | None = None
        tags: list[str] = []
        severity = Severity.info

        if use_llm:
            try:
                llm = get_llm(temperature=0.0)
                chain = _METADATA_PROMPT | llm | StrOutputParser()
                response = chain.invoke({"text": chunk[:2000]})
                parsed = _parse_metadata_response(response)

                title = parsed.get("title") or None
                summary = parsed.get("summary") or None
                raw_tags = parsed.get("tags", [])
                tags = [t.lower().strip() for t in raw_tags if isinstance(t, str)]
                severity = _validate_severity(parsed.get("severity", "info"))
            except Exception as exc:
                logger.warning("LLM metadata extraction failed: %s", exc)

        # Fallback title from payload keys
        if not title:
            for key in ("type", "action", "event", "name", "title", "product_description"):
                val = event.raw_payload.get(key)
                if val and isinstance(val, str):
                    title = f"{event.source_name}: {val[:80]}"
                    break
            if not title:
                title = f"{event.source_name} event"

        docs.append(
            ProcessedDocument(
                raw_event_id=event.id,
                source_id=event.source_id,
                source_name=event.source_name,
                title=title,
                content=chunk,
                summary=summary,
                tags=tags,
                severity=severity,
                metadata=metadata,
                embedding=vector,
            )
        )

    return docs


def process_events_batch(
    events: list[RawEvent],
    use_llm: bool = True,
) -> list[ProcessedDocument]:
    """Process a batch of RawEvents and return all resulting documents."""
    all_docs: list[ProcessedDocument] = []
    for event in events:
        try:
            docs = process_event(event, use_llm=use_llm)
            all_docs.extend(docs)
        except Exception as exc:
            logger.error(
                "Pipeline error for event '%s' from '%s': %s",
                event.external_id,
                event.source_name,
                exc,
            )
    return all_docs
