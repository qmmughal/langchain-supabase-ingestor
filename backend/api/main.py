"""
FastAPI REST API for the dashboard.

Endpoints:
  GET  /health                    — Health check
  GET  /sources                   — List data sources
  POST /sources                   — Create a data source
  GET  /events                    — List raw events (paginated)
  GET  /documents                 — List processed documents (paginated)
  POST /documents/search          — Semantic vector search
  GET  /rules                     — List alert rules
  POST /rules                     — Create an alert rule
  PUT  /rules/{id}                — Update an alert rule
  DELETE /rules/{id}              — Delete an alert rule
  GET  /alerts                    — List alert log (paginated)
  PATCH /alerts/{id}/read         — Mark alert as read
  GET  /stats                     — Dashboard summary stats
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.shared.models import AlertRule, DataSource, RuleMode, Severity
from backend.shared.ollama_client import embed_text
from backend.shared.supabase_client import get_supabase

app = FastAPI(
    title="LangChain + Supabase Ingestor API",
    description="REST API for the real-time data ingestion and alerting dashboard",
    version="1.0.0",
)

# Allow the Next.js frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class CreateSourceRequest(BaseModel):
    name: str
    description: str | None = None
    url: str
    items_path: str = "$[*]"
    poll_interval_seconds: int = 300
    headers: dict[str, str] = {}
    is_active: bool = True


class CreateRuleRequest(BaseModel):
    name: str
    description: str | None = None
    mode: RuleMode
    keywords: list[str] = []
    similarity_threshold: float = 0.80
    reference_text: str | None = None
    agent_prompt: str | None = None
    filter_source_ids: list[str] = []
    filter_severity: list[str] = []
    alert_title: str | None = None
    alert_severity: str = "medium"
    cooldown_seconds: int = 300
    is_active: bool = True


class SemanticSearchRequest(BaseModel):
    query: str
    threshold: float = 0.70
    limit: int = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db():
    return get_supabase()


def _paginate(table: str, page: int, page_size: int, filters: dict | None = None, order: str = "created_at", desc: bool = True):
    db = _db()
    offset = (page - 1) * page_size
    q = db.table(table).select("*", count="exact")
    if filters:
        for col, val in filters.items():
            q = q.eq(col, val)
    q = q.order(order, desc=desc).range(offset, offset + page_size - 1)
    resp = q.execute()
    return {"data": resp.data, "total": resp.count or 0, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---- Data Sources ----

@app.get("/sources")
def list_sources():
    resp = _db().table("data_sources").select("*").order("name").execute()
    return {"data": resp.data}


@app.post("/sources", status_code=201)
def create_source(body: CreateSourceRequest):
    resp = _db().table("data_sources").insert(body.model_dump()).execute()
    if not resp.data:
        raise HTTPException(500, "Failed to create source")
    return resp.data[0]


@app.patch("/sources/{source_id}")
def update_source(source_id: str, body: dict):
    body.pop("id", None)
    resp = _db().table("data_sources").update(body).eq("id", source_id).execute()
    if not resp.data:
        raise HTTPException(404, "Source not found")
    return resp.data[0]


@app.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str):
    _db().table("data_sources").delete().eq("id", source_id).execute()


# ---- Raw Events ----

@app.get("/events")
def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_name: str | None = None,
):
    db = _db()
    offset = (page - 1) * page_size
    q = db.table("raw_events").select("*", count="exact")
    if source_name:
        q = q.eq("source_name", source_name)
    q = q.order("fetched_at", desc=True).range(offset, offset + page_size - 1)
    resp = q.execute()
    return {"data": resp.data, "total": resp.count or 0, "page": page, "page_size": page_size}


# ---- Processed Documents ----

@app.get("/documents")
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_name: str | None = None,
    severity: str | None = None,
    tag: str | None = None,
):
    db = _db()
    offset = (page - 1) * page_size
    q = db.table("processed_documents").select(
        "id,title,summary,tags,severity,source_name,processed_at,metadata",
        count="exact"
    )
    if source_name:
        q = q.eq("source_name", source_name)
    if severity:
        q = q.eq("severity", severity)
    if tag:
        q = q.contains("tags", [tag])
    q = q.order("processed_at", desc=True).range(offset, offset + page_size - 1)
    resp = q.execute()
    return {"data": resp.data, "total": resp.count or 0, "page": page, "page_size": page_size}


@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    resp = _db().table("processed_documents").select("*").eq("id", doc_id).single().execute()
    if not resp.data:
        raise HTTPException(404, "Document not found")
    return resp.data


@app.post("/documents/search")
def semantic_search(body: SemanticSearchRequest):
    """Vector similarity search over processed_documents."""
    try:
        query_vec = embed_text(body.query)
    except Exception as exc:
        raise HTTPException(503, f"Embedding service unavailable: {exc}")

    db = _db()
    resp = db.rpc(
        "search_documents",
        {
            "query_embedding": query_vec,
            "match_threshold": body.threshold,
            "match_count": body.limit,
        },
    ).execute()
    return {"data": resp.data, "query": body.query}


# ---- Alert Rules ----

@app.get("/rules")
def list_rules():
    resp = _db().table("alert_rules").select("*").order("created_at", desc=True).execute()
    return {"data": resp.data}


@app.post("/rules", status_code=201)
def create_rule(body: CreateRuleRequest):
    data = body.model_dump()
    # Convert lists of UUIDs to strings for Supabase
    data["filter_source_ids"] = [str(uid) for uid in data.get("filter_source_ids", [])]
    resp = _db().table("alert_rules").insert(data).execute()
    if not resp.data:
        raise HTTPException(500, "Failed to create rule")
    return resp.data[0]


@app.put("/rules/{rule_id}")
def update_rule(rule_id: str, body: CreateRuleRequest):
    data = body.model_dump()
    data["filter_source_ids"] = [str(uid) for uid in data.get("filter_source_ids", [])]
    resp = _db().table("alert_rules").update(data).eq("id", rule_id).execute()
    if not resp.data:
        raise HTTPException(404, "Rule not found")
    return resp.data[0]


@app.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str):
    _db().table("alert_rules").delete().eq("id", rule_id).execute()


# ---- Alert Log ----

@app.get("/alerts")
def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    unread_only: bool = False,
):
    db = _db()
    offset = (page - 1) * page_size
    q = db.table("alert_log").select("*", count="exact")
    if unread_only:
        q = q.eq("is_read", False)
    q = q.order("delivered_at", desc=True).range(offset, offset + page_size - 1)
    resp = q.execute()
    return {"data": resp.data, "total": resp.count or 0, "page": page, "page_size": page_size}


@app.patch("/alerts/{alert_id}/read")
def mark_read(alert_id: str):
    resp = (
        _db()
        .table("alert_log")
        .update({"is_read": True, "read_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", alert_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, "Alert not found")
    return resp.data[0]


@app.post("/alerts/mark-all-read")
def mark_all_read():
    _db().table("alert_log").update(
        {"is_read": True, "read_at": datetime.now(timezone.utc).isoformat()}
    ).eq("is_read", False).execute()
    return {"status": "ok"}


# ---- Stats ----

@app.get("/stats")
def stats():
    db = _db()
    docs_count = db.table("processed_documents").select("id", count="exact").execute().count or 0
    events_count = db.table("raw_events").select("id", count="exact").execute().count or 0
    alerts_unread = db.table("alert_log").select("id", count="exact").eq("is_read", False).execute().count or 0
    rules_active = db.table("alert_rules").select("id", count="exact").eq("is_active", True).execute().count or 0
    sources_active = db.table("data_sources").select("id", count="exact").eq("is_active", True).execute().count or 0

    # Severity breakdown
    severity_rows = (
        db.table("processed_documents")
        .select("severity")
        .execute()
        .data or []
    )
    severity_counts: dict[str, int] = {}
    for row in severity_rows:
        sev = row.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    return {
        "documents_total": docs_count,
        "events_total": events_count,
        "alerts_unread": alerts_unread,
        "rules_active": rules_active,
        "sources_active": sources_active,
        "severity_breakdown": severity_counts,
    }
