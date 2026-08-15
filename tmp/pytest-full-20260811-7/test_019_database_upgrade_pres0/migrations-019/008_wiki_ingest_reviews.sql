PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS wiki_ingest_reviews (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES wiki_workflow_runs(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES wiki_sources(id),
    reviewer_agent_id TEXT,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    findings_json TEXT NOT NULL DEFAULT '[]',
    recommended_targets_json TEXT NOT NULL DEFAULT '[]',
    model_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_wiki_ingest_reviews_run
ON wiki_ingest_reviews(run_id, created_at DESC);
