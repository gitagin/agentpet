from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = ROOT / "docs" / "runbook.md"
SCRIPTS = ROOT / "scripts"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_runbook_documents_local_trial_commands_and_environment() -> None:
    content = read_text(RUNBOOK)

    required_terms = [
        "scripts\\check-trial-processes.ps1",
        "scripts\\dev-backend.ps1",
        "scripts\\dev-frontend.ps1",
        "scripts\\runbook-smoke.ps1",
        "scripts\\smoke-backend.ps1",
        "AGENT_PET_SESSION_TOKEN",
        "AGENT_PET_DATA_DIR",
        "AGENT_PET_SQLITE_PATH",
        "/api/health",
        "/api/vaults/init",
        "/api/memory/search",
        "/api/tasks",
        "/api/chat",
        "/api/diagnostics/export",
        "Authorization: Bearer",
        "uvicorn app.main:app",
        "leftover uvicorn/Electron",
    ]

    for term in required_terms:
        assert term in content


def test_backend_smoke_script_covers_core_mvp_endpoints() -> None:
    content = read_text(SCRIPTS / "smoke-backend.ps1")

    required_fragments = [
        "/api/health",
        "/api/vaults/status",
        "/api/vaults/init",
        "/api/vaults/$($vault.vault_id)/index",
        "/api/memory/search",
        "/api/memory/proposals",
        "/api/tasks",
        "/api/chat",
        "/api/diagnostics/export",
        "ok diagnostics export",
        "Authorization",
        "event:",
    ]

    for fragment in required_fragments:
        assert fragment in content


def test_runbook_smoke_script_starts_isolated_backend_and_delegates_smoke() -> None:
    content = read_text(SCRIPTS / "runbook-smoke.ps1")

    required_fragments = [
        "AGENT_PET_SESSION_TOKEN",
        "AGENT_PET_SQLITE_PATH",
        "uvicorn",
        "app.main:app",
        "/api/health",
        "smoke-backend.ps1",
        "ProcessStartInfo",
        "Stop-Process",
        "WaitForExit",
        "did not stop",
        "still healthy",
        "KeepBackend",
        ".tmp\\runbook-smoke",
    ]

    for fragment in required_fragments:
        assert fragment in content


def test_preflight_runs_trial_process_residue_checker() -> None:
    content = read_text(SCRIPTS / "preflight-windows.ps1")

    required_fragments = [
        "check-trial-processes.ps1",
        "SkipPortChecks",
        "Leftover trial process check failed",
        "No leftover uvicorn/Electron trial processes detected",
    ]

    for fragment in required_fragments:
        assert fragment in content


def test_trial_process_checker_detects_uvicorn_electron_and_ports() -> None:
    content = read_text(SCRIPTS / "check-trial-processes.ps1")

    required_fragments = [
        "Get-CimInstance Win32_Process",
        "Get-NetTCPConnection",
        "uvicorn",
        "app\\.main:app",
        "electron",
        "apps\\desktop",
        "Leftover FastAPI sidecar process detected",
        "Leftover Electron trial process detected",
        "listener remains",
        "exit 1",
    ]

    for fragment in required_fragments:
        assert fragment in content


def test_dev_scripts_define_stable_local_ports_and_tokens() -> None:
    backend = read_text(SCRIPTS / "dev-backend.ps1")
    frontend = read_text(SCRIPTS / "dev-frontend.ps1")

    assert "127.0.0.1" in backend
    assert "8765" in backend
    assert "AGENT_PET_SESSION_TOKEN" in backend
    assert "uvicorn app.main:app" in backend

    assert "127.0.0.1" in frontend
    assert "5173" in frontend
    assert "npm run dev" in frontend
    assert "node_modules" in frontend
