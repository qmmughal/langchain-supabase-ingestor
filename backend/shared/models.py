"""
Pydantic models for the LangChain + Supabase ingestion system.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RuleMode(str, Enum):
    keyword = "keyword"
    semantic = "semantic"
    llm_agent = "llm_agent"


class RunStatus(str, Enum):
    success = "success"
    partial = "partial"
    error = "error"


# ---------------------------------------------------------------------------
# Data Source
# ---------------------------------------------------------------------------

class DataSource(BaseModel):
    id: UUID | None = None
    name: str
    description: str | None = None
    url: str
    items_path: str = "$[*]"
    poll_interval_seconds: int = 300
    headers: dict[str, str] = Field(default_factory=dict)
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Raw Event
# ---------------------------------------------------------------------------

class RawEvent(BaseModel):
    id: UUID | None = None
    source_id: UUID
    source_name: str
    external_id: str | None = None
    raw_payload: dict[str, Any]
    fetched_at: datetime | None = None


# ---------------------------------------------------------------------------
# Processed Document
# ---------------------------------------------------------------------------

class ProcessedDocument(BaseModel):
    id: UUID | None = None
    raw_event_id: UUID | None = None
    source_id: UUID | None = None
    source_name: str | None = None
    title: str | None = None
    content: str
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    severity: Severity = Severity.info
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    processed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Alert Rule
# ---------------------------------------------------------------------------

class AlertRule(BaseModel):
    id: UUID | None = None
    name: str
    description: str | None = None
    is_active: bool = True
    mode: RuleMode
    keywords: list[str] = Field(default_factory=list)
    similarity_threshold: float = 0.80
    reference_text: str | None = None
    agent_prompt: str | None = None
    filter_source_ids: list[UUID] = Field(default_factory=list)
    filter_severity: list[Severity] = Field(default_factory=list)
    alert_title: str | None = None
    alert_severity: Severity = Severity.medium
    cooldown_seconds: int = 300
    last_fired_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Alert Log Entry
# ---------------------------------------------------------------------------

class AlertLogEntry(BaseModel):
    id: UUID | None = None
    rule_id: UUID
    rule_name: str
    document_id: UUID | None = None
    source_name: str | None = None
    matched_content: str | None = None
    match_score: float | None = None
    mode_used: RuleMode
    alert_title: str | None = None
    alert_body: str | None = None
    severity: Severity | None = None
    delivered_at: datetime | None = None
    is_read: bool = False
    read_at: datetime | None = None


# ---------------------------------------------------------------------------
# Ingestor Run
# ---------------------------------------------------------------------------

class IngestorRun(BaseModel):
    id: UUID | None = None
    source_id: UUID | None = None
    source_name: str | None = None
    status: RunStatus
    items_fetched: int = 0
    items_new: int = 0
    items_processed: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# API response models
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    id: UUID
    title: str | None
    content: str
    summary: str | None
    tags: list[str]
    severity: str
    source_name: str | None
    processed_at: datetime | None
    similarity: float


class PaginatedResponse(BaseModel):
    data: list[Any]
    total: int
    page: int
    page_size: int
