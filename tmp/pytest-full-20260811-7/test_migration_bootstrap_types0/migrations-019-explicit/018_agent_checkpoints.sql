PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    state_version TEXT NOT NULL,
    node_name TEXT NOT NULL,
    state_json TEXT NOT NULL CHECK (length(state_json) <= 65536),
    action_proposal_id TEXT,
    idempotency_key TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'pending_confirmation', 'approved', 'rejected', 'expired',
        'cancelled', 'completed', 'failed_recovery'
    )),
    public_event_cursor INTEGER,
    terminal_receipt_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_thread_created
ON agent_checkpoints(thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_run_created
ON agent_checkpoints(run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_status_expires
ON agent_checkpoints(status, expires_at);

CREATE TABLE IF NOT EXISTS agent_checkpoint_decisions (
    decision_id TEXT PRIMARY KEY,
    checkpoint_id TEXT NOT NULL REFERENCES agent_checkpoints(checkpoint_id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected', 'expired')),
    policy_version TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    UNIQUE(checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_checkpoint_decisions_checkpoint
ON agent_checkpoint_decisions(checkpoint_id);
