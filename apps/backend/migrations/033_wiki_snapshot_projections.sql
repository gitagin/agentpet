CREATE TABLE wiki_body_projection (
    vault_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    links_json TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    PRIMARY KEY(vault_id, content_hash),
    FOREIGN KEY(vault_id, content_hash) REFERENCES wiki_page_bodies(vault_id, content_hash)
);

CREATE VIRTUAL TABLE wiki_body_fts USING fts5(
    vault_id UNINDEXED,
    content_hash UNINDEXED,
    chunk_index UNINDEXED,
    title,
    heading,
    content,
    tokenize = 'unicode61'
);

CREATE TABLE wiki_generation_links (
    vault_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    PRIMARY KEY(vault_id, generation, source_path, target_path),
    FOREIGN KEY(vault_id, generation, source_path)
        REFERENCES wiki_generation_pages(vault_id, generation, relative_path) ON DELETE CASCADE,
    FOREIGN KEY(vault_id, generation, target_path)
        REFERENCES wiki_generation_pages(vault_id, generation, relative_path) ON DELETE CASCADE
);

CREATE INDEX idx_wiki_generation_backlinks
ON wiki_generation_links(vault_id, generation, target_path);

CREATE TABLE wiki_generation_projection (
    vault_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    link_count INTEGER NOT NULL,
    PRIMARY KEY(vault_id, generation),
    FOREIGN KEY(vault_id, generation) REFERENCES wiki_generations(vault_id, id)
);
