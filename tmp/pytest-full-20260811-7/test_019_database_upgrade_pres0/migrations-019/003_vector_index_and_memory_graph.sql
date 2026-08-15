PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS vector_chunks (
    vector_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL,
    note_id TEXT NOT NULL,
    vault_id TEXT NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    collection_name TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vector_chunks_vault_path
ON vector_chunks(vault_id, relative_path);

CREATE TABLE IF NOT EXISTS embedding_keys (
    provider TEXT PRIMARY KEY,
    masked TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_graph_facts (
    id TEXT PRIMARY KEY,
    fact_key TEXT NOT NULL UNIQUE,
    conflict_key TEXT NOT NULL,
    category TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_text TEXT NOT NULL,
    source_type TEXT NOT NULL,
    conversation_id TEXT,
    user_message_id TEXT,
    agent_run_id TEXT,
    support_count INTEGER NOT NULL DEFAULT 1,
    conflicts_with TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_graph_facts_status
ON memory_graph_facts(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_memory_graph_facts_conflict
ON memory_graph_facts(conflict_key, status);

CREATE TABLE IF NOT EXISTS memory_graph_events (
    id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES memory_graph_facts(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);
