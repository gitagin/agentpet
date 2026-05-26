PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS automation_settings_new (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    auto_chat_diary INTEGER NOT NULL DEFAULT 0,
    auto_structured_memory INTEGER NOT NULL DEFAULT 0,
    auto_long_term_memory INTEGER NOT NULL DEFAULT 0,
    auto_wiki_organize INTEGER NOT NULL DEFAULT 0,
    high_risk_confirmation_required INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT OR REPLACE INTO automation_settings_new (
    id,
    auto_chat_diary,
    auto_structured_memory,
    auto_long_term_memory,
    auto_wiki_organize,
    high_risk_confirmation_required,
    created_at,
    updated_at
)
SELECT
    id,
    auto_chat_diary,
    auto_structured_memory,
    auto_long_term_memory,
    auto_wiki_organize,
    high_risk_confirmation_required,
    created_at,
    updated_at
FROM automation_settings;

DROP TABLE automation_settings;
ALTER TABLE automation_settings_new RENAME TO automation_settings;
