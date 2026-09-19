ALTER TABLE wiki_generations ADD COLUMN workflow_run_id TEXT REFERENCES wiki_workflow_runs(id);
CREATE UNIQUE INDEX idx_wiki_generation_workflow ON wiki_generations(workflow_run_id)
WHERE workflow_run_id IS NOT NULL;

CREATE TABLE wiki_generation_dependencies (
    vault_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    dependency_json TEXT NOT NULL,
    PRIMARY KEY(vault_id, generation, relative_path),
    FOREIGN KEY(vault_id, generation, relative_path)
        REFERENCES wiki_generation_pages(vault_id, generation, relative_path) ON DELETE CASCADE
);
