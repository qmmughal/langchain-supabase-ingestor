-- ============================================================
-- 001_schema.sql
-- LangChain + Supabase Real-Time Ingestion & Alerting System
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- ============================================================
-- TABLE: data_sources
-- Registry of REST API endpoints to poll
-- ============================================================
CREATE TABLE IF NOT EXISTS data_sources (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    url         TEXT NOT NULL,
    -- JSONPath or jmespath expression to extract items from response
    items_path  TEXT DEFAULT '$[*]',
    -- seconds between polls
    poll_interval_seconds INTEGER NOT NULL DEFAULT 300,
    headers     JSONB DEFAULT '{}',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- TABLE: raw_events
-- One row per item fetched from a data source
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id       UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    source_name     TEXT NOT NULL,
    -- Stable identifier from the source to deduplicate
    external_id     TEXT,
    raw_payload     JSONB NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint prevents duplicate ingestion
    UNIQUE (source_id, external_id)
);

CREATE INDEX idx_raw_events_source_id   ON raw_events(source_id);
CREATE INDEX idx_raw_events_fetched_at  ON raw_events(fetched_at DESC);
CREATE INDEX idx_raw_events_external_id ON raw_events(source_id, external_id);

-- ============================================================
-- TABLE: processed_documents
-- LangChain-processed, chunked, and embedded documents
-- ============================================================
CREATE TABLE IF NOT EXISTS processed_documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_event_id    UUID REFERENCES raw_events(id) ON DELETE CASCADE,
    source_id       UUID REFERENCES data_sources(id) ON DELETE SET NULL,
    source_name     TEXT,

    -- Extracted content
    title           TEXT,
    content         TEXT NOT NULL,
    summary         TEXT,
    tags            TEXT[] DEFAULT '{}',
    severity        TEXT CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')) DEFAULT 'info',
    metadata        JSONB DEFAULT '{}',

    -- pgvector embedding (nomic-embed-text produces 768-dim vectors)
    embedding       vector(768),

    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_proc_docs_source_id     ON processed_documents(source_id);
CREATE INDEX idx_proc_docs_processed_at  ON processed_documents(processed_at DESC);
CREATE INDEX idx_proc_docs_severity      ON processed_documents(severity);
CREATE INDEX idx_proc_docs_tags          ON processed_documents USING GIN(tags);

-- IVFFlat index for approximate nearest-neighbour search
-- (Rebuild with higher lists value once you have > 1000 rows)
CREATE INDEX idx_proc_docs_embedding ON processed_documents
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- ============================================================
-- TABLE: alert_rules
-- User-defined rules evaluated against each new processed_document
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_rules (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,

    -- Rule evaluation mode
    mode            TEXT NOT NULL CHECK (mode IN ('keyword', 'semantic', 'llm_agent')),

    -- KEYWORD mode: match any of these terms (case-insensitive) in title/content/tags
    keywords        TEXT[] DEFAULT '{}',

    -- SEMANTIC mode: similarity threshold (0.0 – 1.0) and reference text
    similarity_threshold  FLOAT DEFAULT 0.80,
    reference_text        TEXT,

    -- LLM_AGENT mode: natural-language instruction for the agent
    agent_prompt    TEXT,

    -- Filters applied to ALL modes before evaluation
    filter_source_ids  UUID[] DEFAULT '{}',   -- empty = all sources
    filter_severity    TEXT[] DEFAULT '{}',   -- empty = all severities

    -- Alert metadata
    alert_title     TEXT,
    alert_severity  TEXT CHECK (alert_severity IN ('info', 'low', 'medium', 'high', 'critical')) DEFAULT 'medium',

    -- Cooldown: don't fire again within N seconds for the same rule
    cooldown_seconds  INTEGER DEFAULT 300,
    last_fired_at     TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- TABLE: alert_log
-- Record of every alert that has been fired
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id         UUID NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
    rule_name       TEXT NOT NULL,
    document_id     UUID REFERENCES processed_documents(id) ON DELETE SET NULL,
    source_name     TEXT,

    -- Snapshot of the triggering content
    matched_content TEXT,
    match_score     FLOAT,          -- similarity score or NULL for keyword match
    mode_used       TEXT NOT NULL,

    -- Generated alert
    alert_title     TEXT,
    alert_body      TEXT,
    severity        TEXT,

    -- Delivery
    delivered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_read         BOOLEAN NOT NULL DEFAULT FALSE,
    read_at         TIMESTAMPTZ
);

CREATE INDEX idx_alert_log_rule_id       ON alert_log(rule_id);
CREATE INDEX idx_alert_log_document_id   ON alert_log(document_id);
CREATE INDEX idx_alert_log_delivered_at  ON alert_log(delivered_at DESC);
CREATE INDEX idx_alert_log_is_read       ON alert_log(is_read) WHERE is_read = FALSE;

-- ============================================================
-- TABLE: ingestor_runs
-- Audit log of each polling run
-- ============================================================
CREATE TABLE IF NOT EXISTS ingestor_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id       UUID REFERENCES data_sources(id) ON DELETE SET NULL,
    source_name     TEXT,
    status          TEXT NOT NULL CHECK (status IN ('success', 'partial', 'error')),
    items_fetched   INTEGER DEFAULT 0,
    items_new       INTEGER DEFAULT 0,
    items_processed INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX idx_ingestor_runs_source_id   ON ingestor_runs(source_id);
CREATE INDEX idx_ingestor_runs_started_at  ON ingestor_runs(started_at DESC);

-- ============================================================
-- Utility: auto-update updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_data_sources_updated_at
    BEFORE UPDATE ON data_sources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_alert_rules_updated_at
    BEFORE UPDATE ON alert_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- Utility: semantic search function
-- ============================================================
CREATE OR REPLACE FUNCTION search_documents(
    query_embedding vector(768),
    match_threshold FLOAT DEFAULT 0.7,
    match_count     INT   DEFAULT 20
)
RETURNS TABLE (
    id              UUID,
    title           TEXT,
    content         TEXT,
    summary         TEXT,
    tags            TEXT[],
    severity        TEXT,
    source_name     TEXT,
    processed_at    TIMESTAMPTZ,
    similarity      FLOAT
)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        pd.id,
        pd.title,
        pd.content,
        pd.summary,
        pd.tags,
        pd.severity,
        pd.source_name,
        pd.processed_at,
        1 - (pd.embedding <=> query_embedding) AS similarity
    FROM processed_documents pd
    WHERE pd.embedding IS NOT NULL
      AND 1 - (pd.embedding <=> query_embedding) >= match_threshold
    ORDER BY pd.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
