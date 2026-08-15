ALTER TABLE agent_actions ADD COLUMN idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_actions_idempotency_key
ON agent_actions(idempotency_key)
WHERE idempotency_key IS NOT NULL;
