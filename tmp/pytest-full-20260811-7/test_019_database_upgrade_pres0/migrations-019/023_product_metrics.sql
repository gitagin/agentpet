PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS product_metric_events (
    id TEXT PRIMARY KEY,
    event_version TEXT NOT NULL,
    event_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    subject_hash TEXT,
    value REAL NOT NULL DEFAULT 1 CHECK (value >= 0),
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_product_metric_events_type_time
ON product_metric_events(event_type, created_at);

CREATE INDEX IF NOT EXISTS idx_product_metric_events_subject
ON product_metric_events(subject_hash, event_type, created_at);
