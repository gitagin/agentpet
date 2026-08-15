PRAGMA foreign_keys = ON;

ALTER TABLE memory_evidence ADD COLUMN evidence_key TEXT;

UPDATE memory_evidence
SET evidence_key = 'legacy:' || id
WHERE evidence_key IS NULL OR TRIM(evidence_key) = '';

CREATE UNIQUE INDEX IF NOT EXISTS ux_memory_evidence_evidence_key
ON memory_evidence(evidence_key)
WHERE evidence_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS post_reply_memory_jobs (
    id TEXT PRIMARY KEY,
    agent_run_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    assistant_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    stage_states_json TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_post_reply_memory_jobs_status
ON post_reply_memory_jobs(status, updated_at);
