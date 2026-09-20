# T13 测试脚手架预研:wiki_sources 测试夹具与约定

> 只读预研,为 T4 失败测试(source identity 迁移验收用例)提供脚手架事实。不写业务代码。
> 依据:apps/backend/tests/ 下 conftest.py、_schema.py、test_wiki_source_scope.py、test_wiki_ingest_source_identity.py、test_wiki_workflows.py、test_wiki_compilation.py、test_wiki_provenance.py、test_wiki_synthesis_roots.py、test_llmwiki_memory_closure.py、wiki_fixtures.py。

## 1. wiki_sources 行的构造方式(四种)

| 方式 | 位置 | 说明 |
|---|---|---|
| 全链路 ingest(推荐) | test_wiki_ingest_source_identity.py:19-24 confirm(service, preview)=preview_ingest→confirm_ingest | 服务端 hash-first 生成 source_id/source_hash,行由业务代码写入,最接近真实 |
| 直接 SQL INSERT | test_wiki_source_scope.py:296-303 | 仅用于 legacy/迁移场景:INSERT INTO wiki_sources(id, source_hash, title, source_type, content_preview, raw_content)+wiki_workflow_runs |
| 编译流 | test_wiki_compilation.py:15-65 CompilerModel(脚本化 review model)+ compile_preview/apply_preview | 生成 Wiki/Sources/{title}-{hash12}.md 与概念页,source_metadata[compilation_status]==compiled |
| 纯文件+索引 | tests/wiki_fixtures.py:13-42 indexed_citation(database, vault_root, relative_path) | 直接写 markdown、note_chunks、wiki binding,供检索/引用/scope 分类断言;不写 wiki_sources 行 |

## 2. 测试库初始化方式

- 主流模式:临时文件 SQLite。每个测试文件自带 function-scope fixture:
  - test_wiki_ingest_source_identity.py:34-36 service(tmp_path) = _workflow_service(Database(tmp_path/state.sqlite3), tmp_path/Vault)
  - test_wiki_source_scope.py:29-35 services(tmp_path) = 同一个 Database + 双 vault(FirstVault/OtherVault),跨 vault 场景专用
- _workflow_service(test_wiki_workflows.py:1665-1675):内部 MigrationRunner(database).apply() 跑全量迁移 + WikiService(SafeMarkdownWriter(vault_root), index_refresh=lambda _: job_id);可选 review_model/review_model_resolver 注入脚本模型
- tests/_schema.py:独立小工具——migrate_db(path)、migrate_db_with_vault(path, vault_id=vault-1)(临时文件+插 vaults 行)、migrated_connection()(in-memory+逐迁移 executescript,PRAGMA foreign_keys=ON)
- legacy 库构造:test_wiki_source_scope.py:288-294 复制名称 < 030 的迁移到临时目录再 apply(迁移基线场景)
- conftest.py:无共享 DB fixture。client_factory(env 隔离 AGENT_PET_SQLITE_PATH/AGENT_PET_DATA_DIR + TestClient,API 层用)、auth_headers()、autouse clear_settings_cache

## 3. 现有断言模式(供 T4 复用)

- 计数断言:SELECT COUNT(*) FROM wiki_sources / wiki_workflow_runs / wiki_workflow_page_updates / memory_entities(identity/provenance 测试)
- 行快照不可变:source_record(service, id) → dict(row) 全列对比(test_wiki_ingest_source_identity.py:27-31、64)
- 冲突/拒绝错误:pytest.raises(WikiWorkflowError, match=source_identity_conflict|source_scope_unverified|source_);apply 被拒时断言页面不落盘(_assert_apply_rejected_without_writes + _vault_file 不存在)
- synthesis 证据:prepare_wiki_synthesis_authority(conn, vault_root, target_path, page_type, title, source_paths) 返回 authority;断言 resolved.source_hashes/source_entity_ids/evidence_ids 非空且数量正确(test_wiki_synthesis_roots.py:20-48)
- graph 关系:MemoryEntityGraphStore(conn) + bind_authoritative_wiki_page(graph, vault_id, relative_path, parsed=read_markdown(path));查询 graph.get_wiki_binding(...);篡改 entity metadata_json 的 source_hash 后断言 source_hash_not_authoritative(test_wiki_synthesis_roots.py:64-85)
- 页面内容:read_markdown(path) 断言 frontmatter(如 sources 数组、disputed、aliases、tags)与 body 内容(test_wiki_compilation.py:97-109)
- 候选状态流转:MemoryCandidateStore(conn).transition(candidate_id, to_status) 后断言 synthesis 被拒(source_candidate_not_activatable,test_wiki_synthesis_roots.py:51-61)

## 4. T4 失败测试落点与复用清单

- 落点建议:source identity 语义最贴近 tests/test_wiki_ingest_source_identity.py(直接追加或新建 test_wiki_source_identity_migration.py);涉及跨 vault/scope 的用例用 test_wiki_source_scope.py 的 services 双 vault 模式;涉及编译产物路径语义(dual-track 命名)的用例参考 test_wiki_compilation.py + test_wiki_synthesis_roots.py
- 可复用夹具/helper 清单:
  1. service fixture 模式 + confirm/source_record(test_wiki_ingest_source_identity.py)
  2. _workflow_service/_confirm_ingest/_ingest_source_page/_assert_apply_rejected_without_writes(test_wiki_workflows.py)
  3. _schema.migrate_db/migrate_db_with_vault/migrated_connection
  4. CompilerModel + compile_preview/apply_preview/service_for(test_wiki_compilation.py)
  5. compiled_sources fixture + authority()(test_wiki_synthesis_roots.py)
  6. indexed_citation(tests/wiki_fixtures.py)
  7. client_factory + auth_headers(conftest.py,API 层用例)
