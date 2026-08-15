CREATE TABLE model_keys_without_masks (
    provider TEXT PRIMARY KEY,
    masked TEXT,
    credential_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO model_keys_without_masks (provider, masked, credential_ref, created_at, updated_at)
SELECT provider, NULL, credential_ref, created_at, updated_at
FROM model_keys;

DROP TABLE model_keys;
ALTER TABLE model_keys_without_masks RENAME TO model_keys;

CREATE TABLE embedding_keys_without_masks (
    provider TEXT PRIMARY KEY,
    masked TEXT,
    credential_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO embedding_keys_without_masks (provider, masked, credential_ref, created_at, updated_at)
SELECT provider, NULL, credential_ref, created_at, updated_at
FROM embedding_keys;

DROP TABLE embedding_keys;
ALTER TABLE embedding_keys_without_masks RENAME TO embedding_keys;

UPDATE agent_model_configs SET masked = NULL;
