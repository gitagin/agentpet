PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS wiki_query_archives (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    answer_preview TEXT NOT NULL,
    answer TEXT NOT NULL,
    title TEXT NOT NULL,
    target_path TEXT NOT NULL,
    section TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    citations_json TEXT NOT NULL DEFAULT '[]',
    citation_count INTEGER NOT NULL DEFAULT 0,
    agent_run_id TEXT,
    source_message_id TEXT,
    page_title TEXT NOT NULL,
    page_operation TEXT NOT NULL,
    page_status TEXT NOT NULL,
    index_job_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_wiki_query_archives_created
ON wiki_query_archives(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_wiki_query_archives_target
ON wiki_query_archives(target_path);
