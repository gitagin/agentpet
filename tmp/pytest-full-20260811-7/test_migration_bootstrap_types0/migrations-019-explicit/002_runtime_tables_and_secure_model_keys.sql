PRAGMA foreign_keys = ON;
PRAGMA secure_delete = ON;

CREATE TABLE IF NOT EXISTS model_keys_secure (
    provider TEXT PRIMARY KEY,
    masked TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_keys (
    provider TEXT PRIMARY KEY,
    api_key TEXT NOT NULL,
    masked TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO model_keys_secure (provider, masked, credential_ref, created_at, updated_at)
SELECT
    provider,
    masked,
    'migrated-unavailable:' || provider,
    created_at,
    updated_at
FROM model_keys
WHERE EXISTS (
    SELECT 1
    FROM pragma_table_info('model_keys')
    WHERE name = 'api_key'
);

DROP TABLE IF EXISTS model_keys;
ALTER TABLE model_keys_secure RENAME TO model_keys;

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    assistant_message_id TEXT,
    status TEXT NOT NULL,
    intent TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_proposals (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    target_path TEXT NOT NULL,
    target_content_hash TEXT,
    source_message_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rejected_reason TEXT,
    written_path TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    due_at_utc TEXT,
    status TEXT NOT NULL,
    source_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    remind_at_utc TEXT NOT NULL,
    time_parse_timezone TEXT NOT NULL,
    status TEXT NOT NULL,
    scheduler_job_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation ON agent_runs(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_proposals_status ON memory_proposals(status, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_at_utc, created_at);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status, remind_at_utc);

VACUUM;
