PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_actions (
    id TEXT PRIMARY KEY,
    source_agent_run_id TEXT,
    source_conversation_id TEXT,
    source_message_id TEXT,
    action_type TEXT NOT NULL,
    risk_tier TEXT NOT NULL CHECK (risk_tier IN ('low', 'medium', 'high')),
    decision TEXT NOT NULL CHECK (decision IN ('auto', 'notify', 'ask')),
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    target_paths_json TEXT NOT NULL DEFAULT '[]',
    before_snapshot_json TEXT NOT NULL DEFAULT '{}',
    after_snapshot_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    reversible INTEGER NOT NULL DEFAULT 0,
    reverted_by TEXT REFERENCES agent_actions(id),
    reverts_action_id TEXT REFERENCES agent_actions(id),
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_actions_created
ON agent_actions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_actions_source_run
ON agent_actions(source_agent_run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS automation_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    auto_chat_diary INTEGER NOT NULL DEFAULT 0,
    auto_structured_memory INTEGER NOT NULL DEFAULT 0,
    auto_long_term_memory INTEGER NOT NULL DEFAULT 0,
    auto_wiki_organize INTEGER NOT NULL DEFAULT 0,
    high_risk_confirmation_required INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
