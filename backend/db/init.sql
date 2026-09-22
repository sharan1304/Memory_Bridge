-- MENNBridge event log and session tracking.
-- SharedMENN owns memory content/embeddings; Postgres only tracks
-- MCP tool call events and session bookkeeping for the dashboard.

CREATE TABLE IF NOT EXISTS event_log (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    agent TEXT NOT NULL CHECK (agent IN ('claude-code', 'codex')),
    tool TEXT NOT NULL CHECK (tool IN ('get_context', 'checkpoint')),
    memories_affected TEXT[] NOT NULL DEFAULT '{}',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_event_log_project ON event_log (project_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    agent TEXT NOT NULL CHECK (agent IN ('claude-code', 'codex')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions (project_id);
