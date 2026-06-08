-- ============================================================
-- 003_rls.sql
-- Row-Level Security policies
-- ============================================================

-- Enable RLS on all tables
ALTER TABLE data_sources        ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_events          ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_rules         ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_log           ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestor_runs       ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- Service-role bypass (backend services use service role key)
-- ============================================================
-- Service role already bypasses RLS by default in Supabase.
-- The policies below grant anon/authenticated users read access
-- for the dashboard (using the anon key + JWT).

-- data_sources: read by authenticated users
CREATE POLICY "Authenticated users can read data_sources"
    ON data_sources FOR SELECT
    TO authenticated
    USING (TRUE);

CREATE POLICY "Authenticated users can manage data_sources"
    ON data_sources FOR ALL
    TO authenticated
    USING (TRUE)
    WITH CHECK (TRUE);

-- raw_events: read-only for authenticated
CREATE POLICY "Authenticated users can read raw_events"
    ON raw_events FOR SELECT
    TO authenticated
    USING (TRUE);

-- processed_documents: read-only for authenticated
CREATE POLICY "Authenticated users can read processed_documents"
    ON processed_documents FOR SELECT
    TO authenticated
    USING (TRUE);

-- alert_rules: full CRUD for authenticated users
CREATE POLICY "Authenticated users can manage alert_rules"
    ON alert_rules FOR ALL
    TO authenticated
    USING (TRUE)
    WITH CHECK (TRUE);

-- alert_log: read + update (mark as read) for authenticated
CREATE POLICY "Authenticated users can read alert_log"
    ON alert_log FOR SELECT
    TO authenticated
    USING (TRUE);

CREATE POLICY "Authenticated users can update alert_log"
    ON alert_log FOR UPDATE
    TO authenticated
    USING (TRUE)
    WITH CHECK (TRUE);

-- ingestor_runs: read-only for authenticated
CREATE POLICY "Authenticated users can read ingestor_runs"
    ON ingestor_runs FOR SELECT
    TO authenticated
    USING (TRUE);

-- ============================================================
-- Seed default data sources
-- ============================================================
INSERT INTO data_sources (name, description, url, items_path, poll_interval_seconds, headers)
VALUES
(
    'GitHub Public Events',
    'GitHub public events API – returns recent events across all public repos',
    'https://api.github.com/events',
    '$[*]',
    60,
    '{"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}'
),
(
    'Open-Meteo Weather (Berlin)',
    'Current weather conditions for Berlin via Open-Meteo (no API key required)',
    'https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&current=temperature_2m,wind_speed_10m,precipitation&timezone=auto',
    '$.current',
    300,
    '{}'
),
(
    'FDA Drug Recalls',
    'OpenFDA drug enforcement (recall) reports',
    'https://api.fda.gov/drug/enforcement.json?limit=10&sort=recall_initiation_date:desc',
    '$.results[*]',
    600,
    '{}'
)
ON CONFLICT (name) DO NOTHING;
