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


def test_negotiation_stats_returns_aggregates(client: TestClient) -> None:
    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO agent_actions(
                id, action_type, risk_tier, decision, status, title, summary,
                metadata_json, reversible, created_at, updated_at, completed_at,
                negotiation_rounds, total_tokens, total_latency_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "negotiation-stats-1",
                "agent.negotiation",
                "low",
                "auto",
                "completed",
                "协商 1",
                "",
                '{"fallback":true,"agents_invoked":["memory_retrieval_agent","wiki_manager_agent"]}',
                0,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                2,
                0,
                120,
            ),
        )
        conn.execute(
            """
            INSERT INTO agent_actions(
                id, action_type, risk_tier, decision, status, title, summary,
                metadata_json, reversible, created_at, updated_at, completed_at,
                negotiation_rounds, total_tokens, total_latency_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "negotiation-stats-2",
                "agent.negotiation",
                "low",
                "auto",
                "completed",
                "协商 2",
                "",
                '{"fallback":false,"agents_invoked":["memory_retrieval_agent"]}',
                0,
                "2026-01-01T00:00:01Z",
                "2026-01-01T00:00:01Z",
                "2026-01-01T00:00:01Z",
                4,
                0,
                180,
            ),
        )
        conn.commit()

    response = client.get("/api/diagnostics/negotiation-stats", headers=auth())

    assert response.status_code == 200
    assert response.json() == {
        "avg_rounds": 3.0,
        "avg_latency_ms": 150.0,
        "fallback_rate": 0.5,
        "top_agents_invoked": ["retrieval_agent", "action_agent"],
        "top_outcomes_supported": ["cited answer", "local action"],
        "outcome_support_counts": {"cited answer": 2, "local action": 1},
    }


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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
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
