from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.models.config import AutomationSettingsRequest
from app.services.health import component_health_from_vector_index
from app.services.retrieval_factory import build_vector_index
from app.services.settings import CredentialStoreError, InMemoryCredentialStore, SettingsStore
from app.storage.database import Database, MigrationRunner
from tests.conftest import auth_headers


@pytest.fixture()
def client(client_factory, tmp_path: Path) -> Iterator[TestClient]:
    with client_factory(data_dir=tmp_path / "data") as test_client:
        yield test_client


def auth() -> dict[str, str]:
    return auth_headers()


def test_embedding_settings_are_persisted_separately_from_chat_model(client: TestClient) -> None:
    config = client.put(
        "/api/settings/embedding-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://embed.example.test/v1/",
            "model": "text-embedding-3-small",
            "dimensions": 128,
        },
    )
    key = client.put(
        "/api/settings/embedding-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "embedding-test-secret"},
    )
    status = client.get("/api/settings", headers=auth())

    assert config.status_code == 200
    assert config.json()["status"] == "missing_key"
    assert key.status_code == 200
    assert key.json()["configured"] is True
    assert key.json()["masked"] == "****cret"
    payload = status.json()
    assert payload["embedding_base_url"] == "https://embed.example.test/v1"
    assert payload["embedding_model"] == "text-embedding-3-small"
    assert payload["embedding_dimensions"] == 128
    assert payload["embedding_configured"] is True
    assert "embedding-test-secret" not in status.text


def test_embedding_test_reports_missing_key(client: TestClient) -> None:
    response = client.post("/api/settings/embedding-test", headers=auth())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "not_configured"


def test_embedding_test_is_blocked_without_constructing_client_in_local_privacy_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "local-privacy-embedding-test-secret"
    private_path_marker = "private-path-marker"
    config = client.put(
        "/api/settings/embedding-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": f"https://embed.example.test/v1/{private_path_marker}",
            "model": "privacy-sentinel-model",
            "dimensions": 64,
        },
    )
    key = client.put(
        "/api/settings/embedding-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": secret},
    )
    privacy = client.put(
        "/api/settings/automation",
        headers=auth(),
        json={"local_privacy_mode": True},
    )
    constructed: list[object] = []

    class ForbiddenEmbeddingClient:
        def __init__(self, *args, **kwargs) -> None:
            constructed.append((args, kwargs))
            raise AssertionError("embedding client must not be constructed in local privacy mode")

    monkeypatch.setattr("app.api.settings.LangChainEmbeddingClient", ForbiddenEmbeddingClient)

    response = client.post("/api/settings/embedding-test", headers=auth())

    assert config.status_code == 200
    assert key.status_code == 200
    assert privacy.status_code == 200
    assert constructed == []
    assert response.status_code == 200
    assert response.json() == {
        "status": "blocked",
        "provider": None,
        "base_url": None,
        "model": None,
        "dimensions": None,
        "latency_ms": None,
        "message": "本地隐私模式已开启，Embedding 试连已阻止。",
        "error_code": "local_privacy_mode",
        "error_detail": None,
    }
    assert secret not in response.text
    assert private_path_marker not in response.text
    assert "embedding connection test" not in response.text


def test_automation_refreshes_vector_index_only_when_local_privacy_mode_changes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_calls: list[object] = []
    close_calls: list[str] = []

    class ClosableVectorIndex:
        def close(self) -> None:
            close_calls.append("closed")

    client.app.state.retrieval_service.vector_index = ClosableVectorIndex()
    monkeypatch.setattr(
        "app.api.settings.refresh_retrieval_vector_index",
        lambda request: refresh_calls.append(request),
    )

    enabled = client.put(
        "/api/settings/automation",
        headers=auth(),
        json={"local_privacy_mode": True},
    )
    unchanged = client.put(
        "/api/settings/automation",
        headers=auth(),
        json={"local_privacy_mode": True},
    )
    disabled = client.put(
        "/api/settings/automation",
        headers=auth(),
        json={"local_privacy_mode": False},
    )

    assert enabled.status_code == 200
    assert enabled.json()["local_privacy_mode"] is True
    assert unchanged.status_code == 200
    assert disabled.status_code == 200
    assert disabled.json()["local_privacy_mode"] is False
    assert len(refresh_calls) == 2
    assert close_calls == ["closed", "closed"]


def test_enabling_embeddings_backfills_existing_fts_snapshot(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "backfill-vault"
    vault.mkdir()
    (vault / "Existing.md").write_text("# Existing\n\nbackfill-sentinel", encoding="utf-8")
    retrieval = client.app.state.retrieval_service
    vault_id = retrieval.bind_vault(str(vault))
    assert retrieval.rebuild_index(vault_id).status == "success"

    class RecordingVectorIndex:
        available = True
        config = SimpleNamespace(unavailable_reason=None)

        def __init__(self) -> None:
            self.reconcile_calls: list[tuple[str, int, bool]] = []
            self.ready = False

        def health(self, vault_id: str | None = None) -> dict[str, object]:
            return {
                "semantic_available": self.ready,
                "vector_available": self.ready,
                "embedding_configured": True,
                "index_version": "vector-index.v1",
                "active_generation": "generation-1" if self.ready else None,
                "last_sync_status": "success" if self.ready else "not_built",
                "unavailability_reason": None if self.ready else "index_not_built",
            }

        def reconcile(self, conn, vault_id: str, *, local_privacy: bool = False):
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM note_chunks WHERE vault_id = ?",
                    (vault_id,),
                ).fetchone()[0]
            )
            self.reconcile_calls.append((vault_id, count, local_privacy))
            self.ready = True
            return SimpleNamespace(status="success")

    vector_index = RecordingVectorIndex()
    monkeypatch.setattr(
        "app.api.services.factory.build_vector_index",
        lambda db_path, settings: vector_index,
    )

    response = client.put(
        "/api/settings/embedding-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "embedding-key-sentinel"},
    )

    assert response.status_code == 200
    assert vector_index.reconcile_calls == [(vault_id, 1, False)]
    component = client.app.state.component_health["vector_index"]
    assert component.status == "ok"
    assert component.reason is None


def test_vector_factory_local_privacy_never_constructs_remote_embeddings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _prepare_vector_factory_store(tmp_path, monkeypatch, local_privacy=True)
    constructed: list[object] = []

    class ForbiddenEmbeddingClient:
        def __init__(self, *args, **kwargs) -> None:
            constructed.append((args, kwargs))
            raise AssertionError("remote embedding construction is forbidden")

    monkeypatch.setattr("app.services.retrieval_factory.LangChainEmbeddingClient", ForbiddenEmbeddingClient)

    vector_index = build_vector_index(db_path, _vector_factory_settings(tmp_path))

    assert constructed == []
    assert vector_index.available is False
    assert vector_index.config.unavailable_reason == "local_privacy_mode"
    assert vector_index.config.embedding_configured is True
    assert vector_index.config.embeddings is None
    assert component_health_from_vector_index(vector_index).status == "ok"


def test_vector_factory_propagates_locked_generation_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _prepare_vector_factory_store(tmp_path, monkeypatch)
    embeddings = object()

    class FakeEmbeddingClient:
        def __init__(self, **kwargs) -> None:
            assert kwargs == {
                "api_key": "factory-secret-sentinel",
                "base_url": "https://embedding.invalid/v1",
                "model": "fixture-embedding-model",
                "dimensions": 48,
                "timeout_seconds": 30.0,
            }

        def create_embeddings(self):
            return embeddings

    monkeypatch.setattr("app.services.retrieval_factory.LangChainEmbeddingClient", FakeEmbeddingClient)

    vector_index = build_vector_index(db_path, _vector_factory_settings(tmp_path))
    config = vector_index.config

    assert vector_index.available is True
    assert config.embedding_provider == "openai-compatible"
    assert config.embedding_model == "fixture-embedding-model"
    assert config.embedding_dimensions == 48
    assert config.normalization == "l2"
    assert config.chunker_version == "markdown-chunker.v1"
    assert config.index_version == "vector-index.v1"
    assert config.privacy_policy_version == "embedding-privacy.v1"
    assert config.transport_class == "remote-approved"
    assert config.embedding_configured is True
    assert config.qdrant_client is None


@pytest.mark.parametrize(
    ("provider", "with_key", "expected_reason", "expected_status"),
    [
        ("openai-compatible", False, "embedding_api_key_missing", "ok"),
        ("unsupported-provider", True, "embedding_provider_unsupported", "unavailable"),
    ],
)
def test_vector_factory_configuration_failures_are_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    with_key: bool,
    expected_reason: str,
    expected_status: str,
) -> None:
    db_path = _prepare_vector_factory_store(
        tmp_path,
        monkeypatch,
        provider=provider,
        with_key=with_key,
    )

    vector_index = build_vector_index(db_path, _vector_factory_settings(tmp_path))
    health = component_health_from_vector_index(vector_index)

    assert vector_index.available is False
    assert vector_index.config.unavailable_reason == expected_reason
    assert health.status == expected_status
    assert health.reason == expected_reason


def test_vector_factory_credential_read_failure_preserves_fts_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _prepare_vector_factory_store(tmp_path, monkeypatch)

    def fail_credential_read(self, provider: str):
        raise CredentialStoreError("credential read failed")

    monkeypatch.setattr(
        SettingsStore,
        "get_embedding_key",
        fail_credential_read,
    )

    vector_index = build_vector_index(db_path, _vector_factory_settings(tmp_path))

    assert vector_index.available is False
    assert vector_index.config.unavailable_reason == "credential_store_unavailable"
    assert vector_index.health()["unavailability_reason"] == "credential_store_unavailable"


def test_vector_factory_initialization_failure_keeps_safe_config_and_legacy_health_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db_path = _prepare_vector_factory_store(tmp_path, monkeypatch)

    class BrokenEmbeddingClient:
        def __init__(self, **kwargs) -> None:
            pass

        def create_embeddings(self):
            raise RuntimeError("factory-secret-sentinel C:\\private\\embedding")

    monkeypatch.setattr("app.services.retrieval_factory.LangChainEmbeddingClient", BrokenEmbeddingClient)

    vector_index = build_vector_index(db_path, _vector_factory_settings(tmp_path))
    projection = vector_index.health()
    health = component_health_from_vector_index(vector_index)

    assert vector_index.config.unavailable_reason == "embedding_initialization_failed"
    assert projection["unavailability_reason"] == "embedding_initialization_failed"
    assert health.status == "unavailable"
    assert health.reason == "embedding_initialization_failed:RuntimeError"
    assert "factory-secret-sentinel" not in caplog.text
    assert "C:\\private\\embedding" not in caplog.text


@pytest.mark.parametrize(
    "reason",
    ["embedding_api_key_missing", "local_privacy_mode", "index_not_built", "active_generation_missing"],
)
def test_vector_component_health_keeps_optional_unavailability_core_healthy(reason: str) -> None:
    vector_index = _ProjectionVectorIndex(reason=reason, sync_status="not_built")

    health = component_health_from_vector_index(vector_index)

    assert health.status == "ok"
    assert health.reason == reason


def test_vector_component_health_bounds_unknown_projection_reason() -> None:
    vector_index = _ProjectionVectorIndex(
        reason="secret path C:\\private\\index",
        sync_status="failed",
    )

    health = component_health_from_vector_index(vector_index)

    assert health.status == "unavailable"
    assert health.reason == "vector_index_unavailable"
    assert "private" not in health.reason


def _vector_factory_settings(tmp_path: Path) -> Settings:
    return Settings(
        AGENT_PET_SESSION_TOKEN="factory-test-token",
        AGENT_PET_DATA_DIR=tmp_path / "data",
        AGENT_PET_SQLITE_PATH=tmp_path / "state.sqlite3",
    )


def _prepare_vector_factory_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str = "openai-compatible",
    with_key: bool = True,
    local_privacy: bool = False,
) -> Path:
    db_path = tmp_path / "state.sqlite3"
    database = Database(db_path)
    MigrationRunner(database).apply()
    credentials = InMemoryCredentialStore()
    monkeypatch.setattr(
        "app.services.settings.LocalCredentialStore.for_database",
        classmethod(lambda cls, path: credentials),
    )
    store = SettingsStore(db_path, credential_store=credentials)
    try:
        store.set_embedding_config(
            provider=provider,
            base_url="https://embedding.invalid/v1",
            model="fixture-embedding-model",
            dimensions=48,
        )
        if with_key:
            store.set_embedding_key(provider, "factory-secret-sentinel")
        if local_privacy:
            store.set_automation_settings(AutomationSettingsRequest(local_privacy_mode=True))
    finally:
        store.close()
    return db_path


class _ProjectionVectorIndex:
    def __init__(self, *, reason: str, sync_status: str) -> None:
        self.reason = reason
        self.sync_status = sync_status
        self.config = SimpleNamespace(unavailable_reason=None)

    def health(self) -> dict[str, object]:
        return {
            "semantic_available": False,
            "vector_available": False,
            "embedding_configured": self.reason not in {"embedding_api_key_missing", "local_privacy_mode"},
            "index_version": "vector-index.v1",
            "active_generation": None,
            "last_sync_status": self.sync_status,
            "unavailability_reason": self.reason,
        }
