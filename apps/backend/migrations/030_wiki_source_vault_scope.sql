ALTER TABLE wiki_sources ADD COLUMN vault_id TEXT REFERENCES vaults(id);

CREATE INDEX IF NOT EXISTS idx_wiki_sources_vault
ON wiki_sources(vault_id);
