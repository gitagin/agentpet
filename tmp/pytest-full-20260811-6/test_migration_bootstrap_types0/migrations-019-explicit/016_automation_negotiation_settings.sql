PRAGMA foreign_keys = ON;

ALTER TABLE automation_settings ADD COLUMN use_negotiation INTEGER NOT NULL DEFAULT 1;
ALTER TABLE automation_settings ADD COLUMN max_rounds INTEGER NOT NULL DEFAULT 5;
