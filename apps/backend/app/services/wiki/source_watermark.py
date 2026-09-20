"""Database observation watermark, never a semantic freshness certificate."""

import hashlib
import json


def source_watermark(conn, vault_id):
    from app.services.retrieval import _fusion_source_scope

    digest = hashlib.sha256()
    queries = (
        ("sources", """SELECT id, source_hash, source_type, updated_at
                       FROM wiki_sources WHERE vault_id = ? ORDER BY id"""),
        ("notes", """SELECT id, relative_path, content_hash, status
                     FROM notes WHERE vault_id = ? ORDER BY id"""),
        # 版本化权限维度(设计 §4.2-4):binding 状态与撤销随摘要变化,
        # source_observation 可感知遗忘与撤销
        ("bindings", """SELECT wiki_relative_path, status, content_hash,
                               COALESCE(revoked_at, ''), COALESCE(revoked_reason, '')
                        FROM wiki_page_bindings WHERE vault_id = ? ORDER BY wiki_relative_path"""),
    )
    for kind, sql in queries:
        digest.update(kind.encode("ascii"))
        for row in conn.execute(sql, (vault_id,)):
            if kind == "notes" and _fusion_source_scope(row["relative_path"]) != "vault_note":
                continue
            digest.update(json.dumps(dict(row), sort_keys=True, ensure_ascii=True).encode("ascii"))
            digest.update(b"\n")
    return {"version": 1, "digest": digest.hexdigest()}
