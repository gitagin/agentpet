CREATE TABLE wiki_generations (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL REFERENCES vaults(id),
    base_generation TEXT,
    status TEXT NOT NULL CHECK (status IN ('staged', 'published')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    published_at TEXT,
    UNIQUE(vault_id, id),
    FOREIGN KEY(vault_id, base_generation) REFERENCES wiki_generations(vault_id, id)
);

CREATE TABLE wiki_generation_heads (
    vault_id TEXT PRIMARY KEY REFERENCES vaults(id),
    active_generation TEXT,
    FOREIGN KEY(vault_id, active_generation) REFERENCES wiki_generations(vault_id, id)
);

CREATE TABLE wiki_page_bodies (
    vault_id TEXT NOT NULL REFERENCES vaults(id),
    content_hash TEXT NOT NULL,
    body BLOB NOT NULL,
    PRIMARY KEY(vault_id, content_hash)
);

CREATE TABLE wiki_generation_pages (
    vault_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY(vault_id, generation, relative_path),
    FOREIGN KEY(vault_id, generation) REFERENCES wiki_generations(vault_id, id),
    FOREIGN KEY(vault_id, content_hash) REFERENCES wiki_page_bodies(vault_id, content_hash)
);
