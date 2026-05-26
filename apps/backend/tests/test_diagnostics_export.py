from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, iter_keys


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory(session_token="diagnostics-token") as test_client:
        yield test_client


def auth() -> dict[str, str]:
    return auth_headers("diagnostics-token")


def test_diagnostics_export_requires_authorization(client: TestClient) -> None:
    response = client.get("/api/diagnostics/export")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_authorization"


def test_diagnostics_export_returns_redacted_runtime_summary(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Private Vault"
    secret = "sk-diagnostics-secret-1234567890"
    bearer = "Bearer diagnostics-leak-token"
    client.put(
        "/api/settings/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": secret},
    )
    bind = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )
    assert bind.status_code == 200
    vault_id = bind.json()["vault_id"]

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO index_jobs(id, vault_id, type, status, files_seen, files_indexed, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-redaction-check",
                vault_id,
                "full",
                "failed",
                2,
                1,
                f"failed at {vault}\\Secrets.md with api_key={secret} and {bearer}",
            ),
        )
        conn.execute(
            """
            INSERT INTO audit_logs(id, actor, action, target_path, result, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "audit-redaction-check",
                "Authorization: Bearer audit-secret-token",
                "write",
                str(vault / "Secrets.md"),
                "denied",
                f"token={secret}",
            ),
        )
        conn.commit()

    response = client.get("/api/diagnostics/export", headers=auth())

    assert response.status_code == 200
    payload = response.json()
    body = response.text
    assert payload["app"]["version"] == "0.2.0"
    assert payload["database"]["reachable"] is True
    assert payload["database"]["quick_check"] == "ok"
    assert payload["vault"]["configured"] is True
    assert payload["vault"]["active_vault_id"].startswith("id:")
    assert vault_id not in response.text
    assert payload["model_configured"] is True
    assert payload["recent_index_jobs"][0]["id"] == "job-redaction-check"
    assert any(row["id"] == "audit-redaction-check" for row in payload["recent_audit_logs"])
    assert any(row["target_path_present"] is True for row in payload["recent_audit_logs"])

    forbidden_keys = {"api_key", "token", "authorization", "credential_ref", "root_path"}
    assert forbidden_keys.isdisjoint({key.lower() for key in iter_keys(payload)})
    assert secret not in body
    assert "diagnostics-leak-token" not in body
    assert "audit-secret-token" not in body
    assert str(vault) not in body
    assert str(vault / "Secrets.md") not in body
