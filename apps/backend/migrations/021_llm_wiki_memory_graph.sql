PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS graph_source_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO graph_source_state (id, revision, updated_at)
VALUES (1, 0, datetime('now'));

CREATE TABLE IF NOT EXISTS memory_entities (
    id TEXT PRIMARY KEY,
    entity_key TEXT NOT NULL UNIQUE,
    lookup_fingerprint TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'self', 'person', 'project', 'preference', 'boundary', 'goal',
        'event', 'concept', 'source', 'wiki_page', 'decision'
    )),
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    risk_tier TEXT NOT NULL DEFAULT 'low' CHECK (risk_tier IN ('low', 'medium', 'high')),
    confidence REAL NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_entities_lookup
ON memory_entities(entity_type, lookup_fingerprint, status);

CREATE UNIQUE INDEX IF NOT EXISTS ux_memory_entities_self
ON memory_entities(entity_type)
WHERE entity_type = 'self';

CREATE TABLE IF NOT EXISTS memory_entity_aliases (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'active', 'rejected')),
    created_at TEXT NOT NULL,
    UNIQUE(entity_id, normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_memory_entity_aliases_lookup
ON memory_entity_aliases(normalized_alias, status);

CREATE TABLE IF NOT EXISTS memory_entity_evidence (
    entity_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES memory_evidence(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('names', 'describes', 'supports', 'contradicts')),
    created_at TEXT NOT NULL,
    PRIMARY KEY(entity_id, evidence_id, role)
);

CREATE TABLE IF NOT EXISTS wiki_page_bindings (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    page_entity_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    wiki_relative_path TEXT NOT NULL,
    content_hash TEXT,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'stale', 'quarantined', 'forgotten')),
    updated_at TEXT NOT NULL,
    UNIQUE(vault_id, page_entity_id),
    UNIQUE(vault_id, wiki_relative_path)
);

CREATE INDEX IF NOT EXISTS idx_wiki_page_bindings_path
ON wiki_page_bindings(vault_id, wiki_relative_path, status);

CREATE TABLE IF NOT EXISTS memory_fact_artifact_bindings (
    id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES memory_graph_facts(id) ON DELETE CASCADE,
    vault_id TEXT,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('source', 'wiki_page', 'fts_chunk')),
    artifact_ref TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'quarantined')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(fact_id, vault_id, artifact_type, artifact_ref)
);

CREATE INDEX IF NOT EXISTS idx_memory_fact_artifacts_active
ON memory_fact_artifact_bindings(fact_id, status, vault_id);

CREATE TABLE IF NOT EXISTS graph_projection_generations (
    id TEXT PRIMARY KEY,
    backend TEXT NOT NULL CHECK (backend = 'kuzu'),
    schema_version TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision >= 0),
    status TEXT NOT NULL CHECK (status IN ('building', 'active', 'stale', 'failed')),
    built_at TEXT,
    error_code TEXT
);

ALTER TABLE memory_graph_facts ADD COLUMN statement_kind TEXT;
ALTER TABLE memory_graph_facts ADD COLUMN subject_entity_id TEXT REFERENCES memory_entities(id);
ALTER TABLE memory_graph_facts ADD COLUMN subject_fact_id TEXT REFERENCES memory_graph_facts(id);
ALTER TABLE memory_graph_facts ADD COLUMN object_entity_id TEXT REFERENCES memory_entities(id);
ALTER TABLE memory_graph_facts ADD COLUMN object_fact_id TEXT REFERENCES memory_graph_facts(id);
ALTER TABLE memory_graph_facts ADD COLUMN relation_type TEXT;

CREATE INDEX IF NOT EXISTS idx_memory_graph_facts_statement_kind
ON memory_graph_facts(statement_kind, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_memory_graph_facts_relation_subject
ON memory_graph_facts(subject_entity_id, relation_type, status);

CREATE INDEX IF NOT EXISTS idx_memory_graph_facts_relation_object
ON memory_graph_facts(object_entity_id, relation_type, status);

CREATE UNIQUE INDEX IF NOT EXISTS ux_memory_graph_active_supersedes
ON memory_graph_facts(object_fact_id, relation_type)
WHERE statement_kind = 'relation'
  AND relation_type = 'supersedes'
  AND status = 'active'
  AND object_fact_id IS NOT NULL;
