PRAGMA foreign_keys = ON;

ALTER TABLE agent_actions ADD COLUMN negotiation_rounds INTEGER DEFAULT 0;
ALTER TABLE agent_actions ADD COLUMN total_tokens INTEGER DEFAULT 0;
ALTER TABLE agent_actions ADD COLUMN total_latency_ms INTEGER DEFAULT 0;
