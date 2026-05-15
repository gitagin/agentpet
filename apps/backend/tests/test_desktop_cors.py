from fastapi.testclient import TestClient
import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGENT_PET_SQLITE_PATH", str(tmp_path / "desktop-cors.sqlite3"))
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    return TestClient(create_app())


def test_vite_desktop_origin_can_read_health(client: TestClient) -> None:

    response = client.get(
        "/api/health",
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_vite_desktop_origin_can_preflight_authorized_api(client: TestClient) -> None:
    response = client.options(
        "/api/vaults/status",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "Authorization" in response.headers["access-control-allow-headers"]
