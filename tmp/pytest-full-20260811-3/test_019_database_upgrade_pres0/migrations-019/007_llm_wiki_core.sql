PRAGMA foreign_keys = ON;

ALTER TABLE wiki_sources ADD COLUMN raw_content TEXT;

CREATE TABLE IF NOT EXISTS wiki_log_events (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_wiki_log_events_created
ON wiki_log_events(created_at DESC);
