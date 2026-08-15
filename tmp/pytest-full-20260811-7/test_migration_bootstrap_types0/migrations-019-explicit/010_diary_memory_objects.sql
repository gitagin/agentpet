PRAGMA foreign_keys = ON;

ALTER TABLE memory_graph_facts ADD COLUMN memory_type TEXT;
ALTER TABLE memory_graph_facts ADD COLUMN entity_type TEXT;
ALTER TABLE memory_graph_facts ADD COLUMN occurred_at TEXT;
ALTER TABLE memory_graph_facts ADD COLUMN expires_at TEXT;
ALTER TABLE memory_graph_facts ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE memory_graph_facts ADD COLUMN importance REAL NOT NULL DEFAULT 0.5;

CREATE TABLE IF NOT EXISTS diary_memory_objects (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    topic TEXT,
    emotion TEXT,
    people_json TEXT NOT NULL DEFAULT '[]',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    importance REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    occurred_at TEXT NOT NULL,
    timezone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    object_hash TEXT NOT NULL UNIQUE,
    extraction_model TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_diary_memory_objects_vault_time
ON diary_memory_objects(vault_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_diary_memory_objects_vault_type
ON diary_memory_objects(vault_id, type);

CREATE INDEX IF NOT EXISTS idx_diary_memory_objects_vault_topic
ON diary_memory_objects(vault_id, topic);

CREATE INDEX IF NOT EXISTS idx_diary_memory_objects_vault_emotion
ON diary_memory_objects(vault_id, emotion);

CREATE INDEX IF NOT EXISTS idx_diary_memory_objects_status_updated
ON diary_memory_objects(status, updated_at);

CREATE TABLE IF NOT EXISTS diary_memory_object_sources (
    object_id TEXT NOT NULL REFERENCES diary_memory_objects(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    conversation_id TEXT,
    user_message_id TEXT,
    assistant_message_id TEXT,
    agent_run_id TEXT,
    markdown_path TEXT,
    note_id TEXT,
    chunk_id TEXT,
    PRIMARY KEY (object_id, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_diary_memory_object_sources_agent_run
ON diary_memory_object_sources(agent_run_id);

CREATE VIRTUAL TABLE IF NOT EXISTS diary_memory_object_fts USING fts5(
    object_id UNINDEXED,
    type,
    summary,
    topic,
    emotion,
    people,
    keywords,
    tokenize = 'unicode61'
);
