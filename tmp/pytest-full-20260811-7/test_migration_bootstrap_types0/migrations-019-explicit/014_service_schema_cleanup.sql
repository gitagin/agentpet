PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS daily_chat_memory_entries (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL,
    assistant_message_id TEXT NOT NULL,
    agent_run_id TEXT NOT NULL UNIQUE,
    entry_hash TEXT NOT NULL UNIQUE,
    memory_date TEXT NOT NULL,
    memory_time TEXT NOT NULL,
    timezone TEXT NOT NULL,
    markdown_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_chat_memory_entries_date
ON daily_chat_memory_entries(memory_date, created_at);

CREATE TABLE IF NOT EXISTS companion_retrieval_events (
    id TEXT PRIMARY KEY,
    query_hash TEXT NOT NULL,
    route_scopes_json TEXT NOT NULL DEFAULT '[]',
    result_ids_json TEXT NOT NULL DEFAULT '[]',
    result_hashes_json TEXT NOT NULL DEFAULT '[]',
    budget_json TEXT NOT NULL DEFAULT '{}',
    counts_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_companion_retrieval_events_created
ON companion_retrieval_events(created_at);

CREATE TABLE IF NOT EXISTS model_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS agent_model_config AS
SELECT agent_id, provider, base_url, model, created_at, updated_at
FROM agent_model_configs;

CREATE VIEW IF NOT EXISTS agent_model_keys AS
SELECT agent_id, provider, masked, credential_ref, created_at, updated_at
FROM agent_model_configs
WHERE masked IS NOT NULL;

ALTER TABLE reminders ADD COLUMN triggered_at TEXT;
ALTER TABLE wiki_sources ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';
