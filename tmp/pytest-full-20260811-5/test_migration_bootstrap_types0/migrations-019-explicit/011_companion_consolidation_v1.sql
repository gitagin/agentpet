PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companion_consolidation_runs (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    window_started_at TEXT,
    window_ended_at TEXT,
    source_count INTEGER NOT NULL DEFAULT 0,
    output_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    budget_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (vault_id, window_started_at, window_ended_at)
);

CREATE TABLE IF NOT EXISTS companion_consolidation_run_sources (
    run_id TEXT NOT NULL REFERENCES companion_consolidation_runs(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    occurred_at TEXT,
    source_scope TEXT NOT NULL,
    PRIMARY KEY (run_id, source_type, source_id)
);

CREATE TABLE IF NOT EXISTS companion_consolidation_run_outputs (
    run_id TEXT NOT NULL REFERENCES companion_consolidation_runs(id) ON DELETE CASCADE,
    fact_id TEXT NOT NULL REFERENCES memory_graph_facts(id) ON DELETE CASCADE,
    output_type TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    PRIMARY KEY (run_id, fact_id)
);

CREATE TABLE IF NOT EXISTS companion_retrieval_reports (
    id TEXT PRIMARY KEY,
    agent_run_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    candidate_count INTEGER NOT NULL,
    selected_count INTEGER NOT NULL,
    duplicate_drop_count INTEGER NOT NULL,
    per_scope_drop_count INTEGER NOT NULL,
    budget_drop_count INTEGER NOT NULL,
    item_budget INTEGER NOT NULL,
    per_scope_limit INTEGER NOT NULL,
    char_budget INTEGER NOT NULL,
    used_chars INTEGER NOT NULL,
    source_counts_json TEXT NOT NULL DEFAULT '{}',
    selected_scopes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_companion_consolidation_runs_vault_created
ON companion_consolidation_runs(vault_id, created_at);

CREATE INDEX IF NOT EXISTS idx_companion_retrieval_reports_agent_run
ON companion_retrieval_reports(agent_run_id, created_at);
