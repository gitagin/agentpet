from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.conftest import auth_headers


AUTH_HEADERS = auth_headers()
INGEST_ACTION_TYPES = (
    "wiki.ingest.confirm",
    "wiki.ingest.review",
    "wiki.ingest.apply",
)


def _enable_source_identity_v2(client) -> None:
    # v2 语义:跨 vault 同正文、同正文不同身份均各自新建(legacy 下分别被
    # scope_unverified/identity_conflict 拒绝)。仅对本用例开启,不影响同文件
    # 其他锁定 legacy 复用行为的用例。
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute(
            "INSERT INTO app_state(key, value) VALUES ('source_identity_v2', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(True),),
        )


def test_repeated_complete_ingest_reuses_workflow_and_receipts(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, tmp_path / "Vault")
        first_request = _ingest_request(
            source_metadata={
                "origin": "explicit_user",
                "extraction": {"schema_version": "fixture.v1", "enabled": True},
            }
        )
        first = _complete_ingest(client, first_request)
        before = _durable_ingest_state(client.app.state.database.path)

        repeated_request = _ingest_request(
            source_metadata={
                "extraction": {"enabled": True, "schema_version": "fixture.v1"},
                "origin": "explicit_user",
            }
        )
        repeated = _complete_ingest(client, repeated_request)
        after = _durable_ingest_state(client.app.state.database.path)

    assert repeated["preview"]["preview_token"] != first["preview"]["preview_token"]
    assert repeated["preview"]["run_id"] != first["preview"]["run_id"]
    assert repeated["confirm"] == first["confirm"]
    assert repeated["review"] == first["review"]
    assert repeated["apply"] == first["apply"]
    assert before == after
    serialized_actions = json.dumps(after["actions"], ensure_ascii=True, sort_keys=True)
    assert first["preview"]["preview_token"] not in serialized_actions
    assert repeated["preview"]["preview_token"] not in serialized_actions


def test_same_ingest_in_different_vaults_has_distinct_effect_identity(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        _enable_source_identity_v2(client)
        first_vault = tmp_path / "First Vault"
        second_vault = tmp_path / "Second Vault"
        request_body = _ingest_request(source_metadata={"origin": "explicit_user"})

        _bind_vault(client, first_vault)
        first = _complete_ingest(client, request_body)
        _bind_vault(client, second_vault)
        second = _complete_ingest(client, request_body)

        with sqlite3.connect(client.app.state.database.path) as conn:
            workflow_count = conn.execute(
                "SELECT COUNT(*) FROM wiki_workflow_runs WHERE workflow_type = 'ingest'"
            ).fetchone()[0]
            action_count = conn.execute(
                "SELECT COUNT(*) FROM agent_actions WHERE action_type LIKE 'wiki.ingest.%'"
            ).fetchone()[0]

    # v2 语义:两个 vault 的来源身份独立,来源页各自使用本 vault 的 source_id 后缀,
    # 因此路径不同但都真实落盘。
    first_relative_path = str(first["apply"]["page_results"][0]["relative_path"])
    second_relative_path = str(second["apply"]["page_results"][0]["relative_path"])
    assert first["confirm"]["run_id"] != second["confirm"]["run_id"]
    assert workflow_count == 2
    assert action_count == 6
    assert first_vault.joinpath(*first_relative_path.split("/")).is_file()
    assert second_vault.joinpath(*second_relative_path.split("/")).is_file()
    assert first_relative_path != second_relative_path


@pytest.mark.parametrize(
    "change",
    [
        {"content": "# Stable import\n\nA different authoritative statement."},
        {"source_type": "file"},
        {"title": "Stable import alternate target"},
        {"source_metadata": {"origin": "external_file"}},
    ],
    ids=("content", "import-mode", "target", "effective-metadata"),
)
def test_distinct_ingest_intents_create_distinct_workflows(
    client_factory,
    tmp_path: Path,
    change: dict[str, object],
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        _enable_source_identity_v2(client)
        _bind_vault(client, tmp_path / "Vault")
        base_request = _ingest_request(source_metadata={"origin": "explicit_user"})
        first = _preview_and_confirm(client, base_request)
        changed_request = {**base_request, **change}
        second = _preview_and_confirm(client, changed_request)

        with sqlite3.connect(client.app.state.database.path) as conn:
            workflow_count = conn.execute(
                "SELECT COUNT(*) FROM wiki_workflow_runs WHERE workflow_type = 'ingest'"
            ).fetchone()[0]
            action_count = conn.execute(
                "SELECT COUNT(*) FROM agent_actions WHERE action_type = 'wiki.ingest.confirm'"
            ).fetchone()[0]

    assert second["run_id"] != first["run_id"]
    assert workflow_count == 2
    assert action_count == 2


def _bind_vault(client, vault_root: Path) -> None:
    response = client.post(
        "/api/vaults/init",
        headers=AUTH_HEADERS,
        json={"path": str(vault_root), "create_if_missing": True, "confirmed": True},
    )
    assert response.status_code == 200


def _ingest_request(*, source_metadata: dict[str, object]) -> dict[str, object]:
    return {
        "title": "Stable import",
        "content": "# Stable import\n\nOne authoritative statement.",
        "source_type": "user_message",
        "source_uri": "conversation://stable-import",
        "tags": ["project/Atlas", "reliability"],
        "links": [],
        "max_pages": 1,
        "source_metadata": source_metadata,
    }


def _preview_and_confirm(client, request_body: dict[str, object]) -> dict[str, object]:
    preview = client.post(
        "/api/wiki/ingest/preview",
        headers=AUTH_HEADERS,
        json=request_body,
    )
    assert preview.status_code == 200
    preview_payload = preview.json()
    confirm = client.post(
        "/api/wiki/ingest/confirm",
        headers=AUTH_HEADERS,
        json={"preview_token": preview_payload["preview_token"], "user_confirmed": True},
    )
    assert confirm.status_code == 200
    return confirm.json()


def _complete_ingest(client, request_body: dict[str, object]) -> dict[str, dict[str, object]]:
    preview = client.post(
        "/api/wiki/ingest/preview",
        headers=AUTH_HEADERS,
        json=request_body,
    )
    assert preview.status_code == 200
    preview_payload = preview.json()
    confirm = client.post(
        "/api/wiki/ingest/confirm",
        headers=AUTH_HEADERS,
        json={"preview_token": preview_payload["preview_token"], "user_confirmed": True},
    )
    assert confirm.status_code == 200
    confirm_payload = confirm.json()
    review = client.post(
        "/api/wiki/ingest/review",
        headers=AUTH_HEADERS,
        json={"run_id": confirm_payload["run_id"]},
    )
    assert review.status_code == 200
    review_payload = review.json()
    apply = client.post(
        "/api/wiki/ingest/apply",
        headers=AUTH_HEADERS,
        json={
            "run_id": confirm_payload["run_id"],
            "approved_targets": [confirm_payload["page_plans"][0]["target_path"]],
            "review_id": review_payload["review_id"],
            "review_acknowledged": True,
        },
    )
    assert apply.status_code == 200, apply.text
    return {
        "preview": preview_payload,
        "confirm": confirm_payload,
        "review": review_payload,
        "apply": apply.json(),
    }


def test_ingest_apply_stops_when_target_appears_after_confirmation(
    client_factory,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, vault)
        preview = client.post(
            "/api/wiki/ingest/preview",
            headers=AUTH_HEADERS,
            json=_ingest_request(source_metadata={"origin": "explicit_user"}),
        )
        assert preview.status_code == 200
        confirm = client.post(
            "/api/wiki/ingest/confirm",
            headers=AUTH_HEADERS,
            json={"preview_token": preview.json()["preview_token"], "user_confirmed": True},
        )
        assert confirm.status_code == 200
        confirm_payload = confirm.json()
        target_path = confirm_payload["page_plans"][0]["target_path"]

        target = vault / target_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("external edit after preview\n", encoding="utf-8")

        review = client.post(
            "/api/wiki/ingest/review",
            headers=AUTH_HEADERS,
            json={"run_id": confirm_payload["run_id"]},
        )
        assert review.status_code == 200
        apply = client.post(
            "/api/wiki/ingest/apply",
            headers=AUTH_HEADERS,
            json={
                "run_id": confirm_payload["run_id"],
                "approved_targets": [target_path],
                "review_id": review.json()["review_id"],
                "review_acknowledged": True,
            },
        )

    assert apply.status_code == 200
    payload = apply.json()
    assert payload["status"] == "failed"
    assert payload["pages_written"] == 0
    assert payload["page_results"][0]["status"] == "failed"
    assert "预览后已被外部修改" in str(payload["page_results"][0]["error"])
    assert target.read_text(encoding="utf-8") == "external edit after preview\n"


def _durable_ingest_state(database_path: Path) -> dict[str, object]:
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        counts = {
            "workflows": conn.execute(
                "SELECT COUNT(*) FROM wiki_workflow_runs WHERE workflow_type = 'ingest'"
            ).fetchone()[0],
            "reviews": conn.execute("SELECT COUNT(*) FROM wiki_ingest_reviews").fetchone()[0],
            "page_updates": conn.execute("SELECT COUNT(*) FROM wiki_workflow_page_updates").fetchone()[0],
        }
        placeholders = ",".join("?" for _ in INGEST_ACTION_TYPES)
        rows = conn.execute(
            f"""
            SELECT id, action_type, idempotency_key, metadata_json
            FROM agent_actions
            WHERE action_type IN ({placeholders})
            ORDER BY action_type, id
            """,
            INGEST_ACTION_TYPES,
        ).fetchall()
    actions = [
        {
            "id": str(row["id"]),
            "action_type": str(row["action_type"]),
            "idempotency_key": str(row["idempotency_key"]),
            "metadata": json.loads(str(row["metadata_json"])),
        }
        for row in rows
    ]
    return {**counts, "actions": actions}
