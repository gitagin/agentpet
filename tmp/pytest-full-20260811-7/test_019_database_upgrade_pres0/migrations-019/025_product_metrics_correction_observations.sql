PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS product_metric_correction_observations (
    correction_event_id TEXT PRIMARY KEY
        REFERENCES product_metric_events(id) ON DELETE CASCADE,
    old_subject_hash TEXT NOT NULL,
    replacement_subject_hash TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'verified', 'failed')),
    query_count INTEGER NOT NULL DEFAULT 0 CHECK (query_count >= 0),
    observed_at TEXT,
    updated_at TEXT NOT NULL,
    CHECK (
        status = 'pending'
        OR observed_at IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_product_metric_correction_status_time
ON product_metric_correction_observations(status, observed_at, updated_at);

CREATE INDEX IF NOT EXISTS idx_product_metric_correction_subjects
ON product_metric_correction_observations(old_subject_hash, replacement_subject_hash);
