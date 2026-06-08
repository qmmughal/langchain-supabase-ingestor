-- ============================================================
-- 002_realtime.sql
-- Enable Supabase Realtime on key tables
-- ============================================================

-- Add tables to the realtime publication
-- (Supabase creates a 'supabase_realtime' publication by default)
ALTER PUBLICATION supabase_realtime ADD TABLE processed_documents;
ALTER PUBLICATION supabase_realtime ADD TABLE alert_log;
ALTER PUBLICATION supabase_realtime ADD TABLE raw_events;
ALTER PUBLICATION supabase_realtime ADD TABLE ingestor_runs;

-- Enable row-level changes (INSERT, UPDATE, DELETE) to be broadcast
-- For alert_log: broadcast inserts so dashboard gets live notifications
-- For processed_documents: broadcast inserts for the live event feed
