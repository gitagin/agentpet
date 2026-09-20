-- 035_source_identity.sql —— Source Identity 迁移(设计 docs/source-identity-migration-design.md §1/§2.8/§3)
-- 目标:把 source_hash 从「全局唯一身份」降级为「内容指纹」(非唯一索引),
-- 确立 id 为稳定 source_id,新增 source_version/verification_status 等列与版本账本表,
-- 为仅含 source_hash 的 evidence/candidate/graph metadata 幂等回填 source_id+source_version
--
-- 执行机制:本迁移以 PRAGMA foreign_keys = OFF 开头,MigrationRunner 会在 BEGIN 之前
-- 关闭外键、提交/回滚后恢复(事务内切换外键是静默空操作,SQLite 不允许),
-- 12 步重建表(DROP + RENAME)依赖此机制,重建末尾用 pragma_foreign_key_check 做整体
-- 完整性对账,任何违反行 → CHECK 中止 → 单事务整体回滚。注释内不使用 ASCII 分号
-- (迁移语句切分器按分号切分,注释中的分号会把注释切成孤立语句)
PRAGMA foreign_keys = OFF;

-- 防御:迁移期 source_hash 必须仍唯一(历史 UNIQUE 保证),出现重复则中止整体回滚
CREATE TEMP TABLE _m035_duphash (dup INTEGER CHECK (dup = 0));
INSERT INTO _m035_duphash(dup)
SELECT CASE WHEN EXISTS (SELECT 1 FROM wiki_sources GROUP BY source_hash HAVING COUNT(*) > 1)
THEN 1 ELSE 0 END;
DROP TABLE _m035_duphash;

-- 12 步重建:新表(去 UNIQUE,加版本/验证列)
CREATE TABLE wiki_sources_new (
    id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT,
    content_preview TEXT NOT NULL,
    raw_content TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    links_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    source_version INTEGER NOT NULL DEFAULT 1,
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    verified_at TEXT,
    verified_by TEXT,
    expires_at TEXT,
    revoked_at TEXT,
    revoked_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    vault_id TEXT REFERENCES vaults(id)
);

INSERT INTO wiki_sources_new (
    id, source_hash, title, source_type, source_uri, content_preview, raw_content,
    tags_json, links_json, metadata_json, created_at, updated_at, vault_id
) SELECT
    id, source_hash, title, source_type, source_uri, content_preview, raw_content,
    tags_json, links_json, metadata_json, created_at, updated_at, vault_id
FROM wiki_sources;

-- 对账:重建前后行数必须一致,不一致则中止(单事务 → 整体回滚)
CREATE TEMP TABLE _m035_reconcile (ok INTEGER CHECK (ok = 1));
INSERT INTO _m035_reconcile(ok)
SELECT CASE WHEN (SELECT COUNT(*) FROM wiki_sources_new) = (SELECT COUNT(*) FROM wiki_sources)
THEN 1 ELSE 0 END;
DROP TABLE _m035_reconcile;

DROP TABLE wiki_sources;
ALTER TABLE wiki_sources_new RENAME TO wiki_sources;

-- 索引:source_hash 降级为非唯一索引(保持查询性能),vault 索引重建(030 随旧表删除)
CREATE INDEX idx_wiki_sources_hash ON wiki_sources(source_hash);
CREATE INDEX idx_wiki_sources_vault ON wiki_sources(vault_id);

-- 版本账本(仅来源自身内容历史,非第二套证据库,设计 §1.3)
CREATE TABLE wiki_source_version_history (
    source_id TEXT NOT NULL REFERENCES wiki_sources(id),
    source_version INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    content_preview TEXT,
    raw_content TEXT,
    reason TEXT,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (source_id, source_version)
);

-- 回填(设计 §3):仅当 metadata.source_id 缺失且 source_hash 能唯一命中 wiki_sources 时写入,
-- 幂等(条件 json_extract IS NULL),hash 不在 wiki_sources(如 diary/companion 第三套 hash)的行不动
UPDATE memory_evidence
SET metadata_json = json_set(metadata_json, '$.source_id',
    (SELECT w.id FROM wiki_sources w WHERE w.source_hash = json_extract(memory_evidence.metadata_json, '$.source_hash')),
    '$.source_version', 1)
WHERE json_extract(metadata_json, '$.source_id') IS NULL
  AND EXISTS (SELECT 1 FROM wiki_sources w WHERE w.source_hash = json_extract(memory_evidence.metadata_json, '$.source_hash'));

UPDATE memory_candidates
SET metadata_json = json_set(metadata_json, '$.source_id',
    (SELECT w.id FROM wiki_sources w WHERE w.source_hash = json_extract(memory_candidates.metadata_json, '$.source_hash')),
    '$.source_version', 1)
WHERE json_extract(metadata_json, '$.source_id') IS NULL
  AND EXISTS (SELECT 1 FROM wiki_sources w WHERE w.source_hash = json_extract(memory_candidates.metadata_json, '$.source_hash'));

UPDATE memory_graph_facts
SET metadata_json = json_set(metadata_json, '$.source_id',
    (SELECT w.id FROM wiki_sources w WHERE w.source_hash = json_extract(memory_graph_facts.metadata_json, '$.source_hash')),
    '$.source_version', 1)
WHERE json_extract(metadata_json, '$.source_id') IS NULL
  AND EXISTS (SELECT 1 FROM wiki_sources w WHERE w.source_hash = json_extract(memory_graph_facts.metadata_json, '$.source_hash'));

-- 整体完整性对账:重建后外键引用必须无违反行,否则中止(单事务 → 整体回滚)
CREATE TEMP TABLE _m035_fkviolation AS SELECT * FROM pragma_foreign_key_check;
CREATE TEMP TABLE _m035_fkguard (ok INTEGER CHECK (ok = 1));
INSERT INTO _m035_fkguard(ok)
SELECT CASE WHEN (SELECT COUNT(*) FROM _m035_fkviolation) = 0 THEN 1 ELSE 0 END;
DROP TABLE _m035_fkguard;
DROP TABLE _m035_fkviolation;
