-- 修复迁移漂移:部分旧安装的 002 版本没有创建 app_state,
-- 但 schema_migrations 已把 002 记为已应用,新代码会跳过建表,
-- 启动期 ensure_bigram_fts 随即报 "no such table: app_state"。
-- 此迁移幂等,对正常安装无副作用。
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
