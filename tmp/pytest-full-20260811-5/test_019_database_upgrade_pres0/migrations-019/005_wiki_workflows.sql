PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS wiki_sources (
    id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT,
    content_preview TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    links_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wiki_workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_type TEXT NOT NULL,
    source_id TEXT REFERENCES wiki_sources(id),
    status TEXT NOT NULL,
    request_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wiki_workflow_page_updates (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES wiki_workflow_runs(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    target_path TEXT NOT NULL,
    operation TEXT NOT NULL,
    section TEXT,
    content TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    links_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    index_job_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_wiki_workflow_runs_type_status
ON wiki_workflow_runs(workflow_type, status, created_at);

CREATE INDEX IF NOT EXISTS idx_wiki_workflow_page_updates_run
ON wiki_workflow_page_updates(run_id, status);
