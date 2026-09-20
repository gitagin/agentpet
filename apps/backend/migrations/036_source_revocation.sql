-- 036_source_revocation.sql —— 版本化权限:generation/binding 级撤销时间列
-- 设计:docs/draft-first-publication-design.md §4.2(D3)/§6、事实:t11 §3.3、t18 §1
-- 目标:以可空时间列表达「撤销」状态事件,不扩展状态枚举、不重建表、不改 CHECK——
--   generation 级撤销(置 revoked_at)→ 读路径 _scope 增加 revoked_at IS NULL,该版本整体不可读;
--   binding 级撤销(置 binding.revoked_at)→ 读路径 authorize 拒绝(与 status='active' 同点判定);
--   正文与审计保留:不删行、不删 body、不写 dependency stamp。
-- 执行机制:纯 ADD COLUMN(可空、默认 NULL),SQLite 3.37 无需 12 步重建、无需关外键,
--   单事务执行(035 模式)+ 列数/存量 NULL 对账,失败整体回滚。
-- 注释内不使用 ASCII 分号(迁移语句切分器按分号切分)

ALTER TABLE wiki_generations ADD COLUMN revoked_at TEXT;
ALTER TABLE wiki_generations ADD COLUMN revoked_reason TEXT;

ALTER TABLE wiki_page_bindings ADD COLUMN revoked_at TEXT;
ALTER TABLE wiki_page_bindings ADD COLUMN revoked_reason TEXT;

-- 对账:四列全部落地,且存量行新列均为 NULL(纯增量、无数据迁移)
CREATE TEMP TABLE _m036_reconcile (ok INTEGER CHECK (ok = 1));
INSERT INTO _m036_reconcile(ok)
SELECT CASE WHEN
  (SELECT COUNT(*) FROM pragma_table_info('wiki_generations')
    WHERE name IN ('revoked_at','revoked_reason')) = 2
  AND (SELECT COUNT(*) FROM pragma_table_info('wiki_page_bindings')
    WHERE name IN ('revoked_at','revoked_reason')) = 2
  AND (SELECT COUNT(*) FROM wiki_generations
    WHERE revoked_at IS NOT NULL OR revoked_reason IS NOT NULL) = 0
  AND (SELECT COUNT(*) FROM wiki_page_bindings
    WHERE revoked_at IS NOT NULL OR revoked_reason IS NOT NULL) = 0
THEN 1 ELSE 0 END;
DROP TABLE _m036_reconcile;
