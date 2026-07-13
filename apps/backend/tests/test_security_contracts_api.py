import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.events import NegotiationStepEvent, public_agent_error, sse_encode
from app.models.event_payloads import (
    AgentTraceAgentId,
    AgentTracePhase,
    AgentTraceReasonCode,
    AgentTraceStatus,
)
from tests.conftest import FORBIDDEN_HEALTH_KEYS, assert_error_shape, auth_headers, iter_keys


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory() as test_client:
        yield test_client


def test_health_endpoint_is_unauthenticated_and_does_not_leak_vault_state(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert FORBIDDEN_HEALTH_KEYS.isdisjoint({key.lower() for key in iter_keys(payload)})


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/vaults/status"),
        ("POST", "/api/vaults/init"),
        ("POST", "/api/chat"),
        ("GET", "/api/chat/runs/test-run-id/events"),
        ("GET", "/api/today/snapshot"),
        ("POST", "/api/memory/search"),
        ("POST", "/api/memory/feedback"),
        ("POST", "/api/memory/proposals"),
        ("POST", "/api/tasks"),
        ("PUT", "/api/settings/model-key"),
        ("PUT", "/api/settings/model-config"),
        ("GET", "/api/settings/tts"),
        ("PUT", "/api/settings/tts"),
        ("PUT", "/api/settings/tts-key"),
        ("POST", "/api/tts/synthesize"),
        ("DELETE", "/api/tts/cache"),
        ("POST", "/api/settings/model-test"),
    ],
)
def test_non_health_endpoints_require_authorization(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    response = client.request(method, path, json={})

    assert response.status_code == 401
    assert_error_shape(response.json())


@pytest.mark.parametrize(
    "authorization",
    [
        "",
        "Bearer",
        "Basic abc123",
        "Bearer invalid-session-token",
    ],
)
def test_invalid_authorization_is_rejected_with_error_shape(
    client: TestClient,
    authorization: str,
) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    response = client.get("/api/vaults/status", headers=headers)

    assert response.status_code == 401
    assert_error_shape(response.json())


@pytest.mark.parametrize("path", ["/api/vaults/init", "/api/vaults/bind"])
def test_vault_bind_requires_explicit_confirmation(client: TestClient, tmp_path: Path, path: str) -> None:
    vault = tmp_path / "Vault"
    response = client.post(
        path,
        headers=auth_headers(),
        json={"path": str(vault), "create_if_missing": True},
    )

    assert response.status_code == 400
    payload = response.json()
    assert_error_shape(payload)
    assert payload["error"]["code"] == "vault_bind_confirmation_required"


@pytest.mark.parametrize("path", ["/api/vaults/init", "/api/vaults/bind"])
def test_vault_bind_accepts_confirmed_safe_path(client: TestClient, tmp_path: Path, path: str) -> None:
    vault = tmp_path / f"Vault-{path.rsplit('/', 1)[-1]}"
    response = client.post(
        path,
        headers=auth_headers(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "bound"
    assert payload["root_path"] == str(vault)


@pytest.mark.parametrize("path", ["/api/vaults/init", "/api/vaults/bind"])
def test_vault_bind_rejects_invalid_path_even_when_confirmed(
    client: TestClient,
    tmp_path: Path,
    path: str,
) -> None:
    invalid_vault_path = tmp_path / f"not-a-vault-{path.rsplit('/', 1)[-1]}.md"
    invalid_vault_path.write_text("not a directory", encoding="utf-8")

    response = client.post(
        path,
        headers=auth_headers(),
        json={"path": str(invalid_vault_path), "create_if_missing": True, "confirmed": True},
    )

    assert response.status_code == 400
    payload = response.json()
    assert_error_shape(payload)
    assert payload["error"]["code"] != "vault_bind_confirmation_required"


def _safe_trace_event_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": "run-security-1",
        "agent_id": AgentTraceAgentId.ORCHESTRATOR,
        "phase": AgentTracePhase.SYNTHESIZING,
        "status": AgentTraceStatus.RUNNING,
        "round": 1,
        "sequence": 1,
        "reason_code": AgentTraceReasonCode.EVIDENCE_READY,
    }
    payload.update(overrides)
    return payload


def test_public_trace_model_and_sse_use_an_exact_allowlist() -> None:
    credential = "s" + "k-" + "security-contract-secret"
    unsafe_summary = " | ".join(
        [
            "private-security-sentinel",
            "Authorization: " + "Bearer " + credential,
            r"C:\Users\Alice\Vault\Secret.md",
            "/home/alice/vault/Secret.md",
            "raw_prompt=hidden",
            "tool_arguments={'query': 'hidden'}",
            "Traceback (most recent call last):",
        ]
    )
    event = NegotiationStepEvent(**_safe_trace_event_payload(safe_summary=unsafe_summary))
    serialized = sse_encode(event)
    payload = json.loads(serialized.split("data: ", 1)[1])
    expected_fields = {
        "contract_version",
        "run_id",
        "branch_id",
        "stage_id",
        "agent_id",
        "phase",
        "status",
        "round",
        "sequence",
        "duration_ms",
        "reason_code",
        "safe_summary",
        "counts",
        "source_scope",
    }

    assert "reasoning" not in NegotiationStepEvent.model_fields
    assert set(payload) == expected_fields
    assert payload["safe_summary"] == "已有信息足够，正在合成回复。"
    assert unsafe_summary not in serialized
    forbidden_patterns = (
        re.compile(r"authorization\s*:\s*bearer", re.IGNORECASE),
        re.compile(r"\bsk-[A-Za-z0-9_-]+", re.IGNORECASE),
        re.compile(r"\b[A-Za-z]:[\\/]"),
        re.compile(r"/(?:home|users)/", re.IGNORECASE),
        re.compile(r"raw_prompt|tool_arguments|traceback|stack trace", re.IGNORECASE),
    )
    assert all(pattern.search(serialized) is None for pattern in forbidden_patterns)


@pytest.mark.parametrize(
    "unsafe_field",
    ["reasoning", "raw_prompt", "tool_arguments", "stack", "absolute_path"],
)
def test_public_trace_model_rejects_non_contract_fields(unsafe_field: str) -> None:
    payload = _safe_trace_event_payload()
    payload[unsafe_field] = "private detail"

    with pytest.raises(ValidationError):
        NegotiationStepEvent(**payload)


def test_unknown_public_error_is_reduced_to_fixed_internal_error() -> None:
    code, message = public_agent_error(r"C:\Users\Alice\Vault\Secret.md Traceback raw_prompt")

    assert code == "internal_error"
    assert message == "回复处理失败，请稍后重试。"
