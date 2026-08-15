PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS memory_candidates (
    id TEXT PRIMARY KEY,
    candidate_hash TEXT NOT NULL UNIQUE,
    memory_kind TEXT NOT NULL CHECK (memory_kind IN (
        'fact', 'preference', 'recent_state', 'boundary',
        'project_context', 'historical', 'inference'
    )),
    memory_scope TEXT NOT NULL CHECK (memory_scope IN (
        'global', 'project', 'topic', 'relationship', 'temporary', 'sensitive'
    )),
    summary TEXT NOT NULL,
    normalized_value TEXT NOT NULL DEFAULT '',
    source_text TEXT NOT NULL,
    source_text_hash TEXT NOT NULL,
    source_track TEXT NOT NULL CHECK (source_track IN (
        'immediate', 'slow_consolidation', 'explicit_user',
        'model_extracted', 'diary', 'continuity'
    )),
    risk_tier TEXT NOT NULL CHECK (risk_tier IN ('low', 'medium', 'high')),
    confidence REAL NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    importance REAL NOT NULL DEFAULT 0 CHECK (importance >= 0 AND importance <= 1),
    evidence_count INTEGER NOT NULL DEFAULT 1 CHECK (evidence_count >= 0),
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN (
        'candidate', 'active', 'stale', 'archived',
        'forgotten', 'rejected', 'superseded'
    )),
    expires_at TEXT,
    last_confirmed_at TEXT,
    superseded_by TEXT REFERENCES memory_candidates(id) ON DELETE SET NULL,
    fact_id TEXT REFERENCES memory_graph_facts(id) ON DELETE SET NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_status_kind
ON memory_candidates(status, memory_kind, updated_at);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_scope_risk
ON memory_candidates(memory_scope, risk_tier, updated_at);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_fact
ON memory_candidates(fact_id);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_expires
ON memory_candidates(expires_at)
WHERE expires_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS memory_evidence (
    id TEXT PRIMARY KEY,
    candidate_id TEXT REFERENCES memory_candidates(id) ON DELETE CASCADE,
    fact_id TEXT REFERENCES memory_graph_facts(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_text_hash TEXT NOT NULL,
    source_excerpt TEXT NOT NULL DEFAULT '',
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    diary_object_id TEXT REFERENCES diary_memory_objects(id) ON DELETE SET NULL,
    confidence REAL NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    CHECK (candidate_id IS NOT NULL OR fact_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_memory_evidence_candidate
ON memory_evidence(candidate_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_evidence_fact
ON memory_evidence(fact_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_evidence_agent_run
ON memory_evidence(agent_run_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_evidence_diary_object
ON memory_evidence(diary_object_id, created_at);

CREATE TABLE IF NOT EXISTS memory_lifecycle_events (
    id TEXT PRIMARY KEY,
    candidate_id TEXT REFERENCES memory_candidates(id) ON DELETE CASCADE,
    fact_id TEXT REFERENCES memory_graph_facts(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL CHECK (to_status IN (
        'candidate', 'active', 'stale', 'archived',
        'forgotten', 'rejected', 'superseded'
    )),
    reason TEXT NOT NULL DEFAULT '',
    source_agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    source_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    agent_action_id TEXT REFERENCES agent_actions(id) ON DELETE SET NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    CHECK (candidate_id IS NOT NULL OR fact_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_memory_lifecycle_events_candidate
ON memory_lifecycle_events(candidate_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_lifecycle_events_fact
ON memory_lifecycle_events(fact_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_lifecycle_events_action
ON memory_lifecycle_events(agent_action_id, created_at);

CREATE TABLE IF NOT EXISTS memory_activation_events (
    id TEXT PRIMARY KEY,
    candidate_id TEXT REFERENCES memory_candidates(id) ON DELETE SET NULL,
    fact_id TEXT REFERENCES memory_graph_facts(id) ON DELETE SET NULL,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    activation_score REAL NOT NULL DEFAULT 0 CHECK (activation_score >= 0 AND activation_score <= 1),
    permissions_json TEXT NOT NULL DEFAULT '{}',
    score_breakdown_json TEXT NOT NULL DEFAULT '{}',
    used_for_style INTEGER NOT NULL DEFAULT 0 CHECK (used_for_style IN (0, 1)),
    used_for_answer_context INTEGER NOT NULL DEFAULT 0 CHECK (used_for_answer_context IN (0, 1)),
    used_for_proactive_mention INTEGER NOT NULL DEFAULT 0 CHECK (used_for_proactive_mention IN (0, 1)),
    used_for_action_suggestion INTEGER NOT NULL DEFAULT 0 CHECK (used_for_action_suggestion IN (0, 1)),
    filtered_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_activation_events_run
ON memory_activation_events(agent_run_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_activation_events_candidate
ON memory_activation_events(candidate_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_activation_events_fact
ON memory_activation_events(fact_id, created_at);

CREATE TABLE IF NOT EXISTS memory_feedback_events (
    id TEXT PRIMARY KEY,
    candidate_id TEXT REFERENCES memory_candidates(id) ON DELETE SET NULL,
    fact_id TEXT REFERENCES memory_graph_facts(id) ON DELETE SET NULL,
    feedback_type TEXT NOT NULL CHECK (feedback_type IN (
        'correction', 'keep', 'forget', 'rewrite',
        'make_temporary', 'mark_completed', 'mark_stale',
        'reject_candidate'
    )),
    feedback_text TEXT NOT NULL DEFAULT '',
    requested_status TEXT CHECK (requested_status IN (
        'candidate', 'active', 'stale', 'archived',
        'forgotten', 'rejected', 'superseded'
    )),
    replacement_candidate_id TEXT REFERENCES memory_candidates(id) ON DELETE SET NULL,
    source_conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    source_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    source_agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    agent_action_id TEXT REFERENCES agent_actions(id) ON DELETE SET NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    CHECK (candidate_id IS NOT NULL OR fact_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_memory_feedback_events_candidate
ON memory_feedback_events(candidate_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_feedback_events_fact
ON memory_feedback_events(fact_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_feedback_events_type
ON memory_feedback_events(feedback_type, created_at);

