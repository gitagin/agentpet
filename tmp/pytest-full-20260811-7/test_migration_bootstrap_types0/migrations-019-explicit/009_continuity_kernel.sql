PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS continuity_state (
    state_key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_proposal_id TEXT,
    source_conversation_id TEXT,
    source_message_id TEXT,
    agent_run_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS continuity_proposals (
    id TEXT PRIMARY KEY,
    proposal_hash TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_conversation_id TEXT,
    source_message_id TEXT,
    agent_run_id TEXT,
    status TEXT NOT NULL,
    rejected_reason TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_continuity_proposals_status
ON continuity_proposals(status, created_at);

CREATE INDEX IF NOT EXISTS idx_continuity_proposals_source
ON continuity_proposals(agent_run_id, source_message_id);

CREATE TABLE IF NOT EXISTS continuity_events (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES continuity_proposals(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);
