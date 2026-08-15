PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_model_configs (
    agent_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    masked TEXT,
    credential_ref TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO agent_model_configs (
    agent_id,
    provider,
    base_url,
    model,
    masked,
    credential_ref,
    enabled,
    created_at,
    updated_at
)
SELECT
    'knowledge_retrieval_agent',
    provider,
    base_url,
    model,
    masked,
    credential_ref,
    enabled,
    created_at,
    updated_at
FROM agent_model_configs
WHERE agent_id = 'knowledge_agent'
  AND NOT EXISTS (
      SELECT 1
      FROM agent_model_configs
      WHERE agent_id = 'knowledge_retrieval_agent'
  );

INSERT INTO agent_model_configs (
    agent_id,
    provider,
    base_url,
    model,
    masked,
    credential_ref,
    enabled,
    created_at,
    updated_at
)
SELECT
    'memory_retrieval_agent',
    provider,
    base_url,
    model,
    masked,
    credential_ref,
    enabled,
    created_at,
    updated_at
FROM agent_model_configs
WHERE agent_id = 'context_retrieval_agent'
  AND NOT EXISTS (
      SELECT 1
      FROM agent_model_configs
      WHERE agent_id = 'memory_retrieval_agent'
  );

INSERT INTO agent_model_configs (
    agent_id,
    provider,
    base_url,
    model,
    masked,
    credential_ref,
    enabled,
    created_at,
    updated_at
)
SELECT
    'knowledge_retrieval_agent',
    provider,
    base_url,
    model,
    masked,
    credential_ref,
    enabled,
    created_at,
    updated_at
FROM agent_model_configs
WHERE agent_id = 'context_retrieval_agent'
  AND NOT EXISTS (
      SELECT 1
      FROM agent_model_configs
      WHERE agent_id = 'knowledge_retrieval_agent'
  );

DELETE FROM agent_model_configs
WHERE agent_id IN ('context_retrieval_agent', 'knowledge_agent');
