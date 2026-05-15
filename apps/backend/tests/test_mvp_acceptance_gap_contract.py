from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "docs" / "mvp-acceptance-coverage.md"
BACKEND = ROOT / "apps" / "backend"
DESKTOP = ROOT / "apps" / "desktop"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def desktop_text() -> str:
    parts: list[str] = []
    text_suffixes = {".cjs", ".css", ".html", ".js", ".json", ".mjs", ".ts", ".tsx"}
    for path in DESKTOP.rglob("*"):
        if not path.is_file():
            continue
        normalized = path.as_posix()
        if (
            "/node_modules/" in normalized
            or "/dist/" in normalized
            or "/public/live2d/" in normalized
            or "/scripts/" in normalized
        ):
            continue
        if path.suffix not in text_suffixes:
            continue
        parts.append(read_text(path))
    return "\n".join(parts)


def assert_matrix_row_status(content: str, row_id: str, status: str) -> None:
    pattern = rf"\|\s*{re.escape(row_id)}\s*\|[^\n]*{re.escape(status)}[^\n]*\|"
    assert re.search(pattern, content, flags=re.IGNORECASE), f"{row_id} must be marked {status}"


def test_mvp_acceptance_matrix_tracks_all_mvp_rows_and_known_gaps() -> None:
    content = read_text(MATRIX)

    for number in range(1, 19):
        assert f"MVP-{number:02d}" in content

    assert_matrix_row_status(content, "MVP-14", "Covered")
    assert_matrix_row_status(content, "MVP-15", "Partial")
    assert_matrix_row_status(content, "MVP-18", "Covered")
    assert_matrix_row_status(content, "Full Live2D", "Partial / Gap")
    assert_matrix_row_status(content, "Actual signed auto-update", "Out of scope / Gap")

    required_gap_text = [
        "Manual Electron validation on 2026-05-15 confirmed near-term reminder triggered and emitted one OS notification",
        "Full natural-language date parsing is not implemented",
        "structured audit/application logging implementation",
        "lacks lip sync, complex motion sequencing, multi-character resource management",
        "no `publish`, signing, or `autoUpdater` contract",
    ]
    for text in required_gap_text:
        assert text in content


def test_reminder_runtime_is_still_documented_as_in_memory_gap() -> None:
    scheduler = read_text(BACKEND / "app" / "scheduler" / "reminders.py")
    main = read_text(DESKTOP / "electron" / "main.cjs")
    task_tests = read_text(BACKEND / "tests" / "test_tasks_services.py")

    assert "class InMemoryReminderScheduler" in scheduler
    assert not re.search(r"APScheduler|BackgroundScheduler|AsyncIOScheduler", scheduler)
    assert re.search(r"\bNotification\b|new\s+Notification\s*\(", main)
    assert "agent-pet:show-reminder-notification" in main
    assert "test_scheduler_failure_keeps_task_and_marks_reminder_unscheduled" in task_tests
    assert "test_create_task_converts_local_times_to_utc_and_schedules_reminder" in task_tests
    assert "test_create_task_parses_chinese_absolute_reminder_time" in task_tests
    assert "test_scheduler_trigger_marks_reminder_triggered" in task_tests


def test_desktop_gaps_for_live2d_and_signed_update_remain_explicit() -> None:
    text = desktop_text()
    main = read_text(DESKTOP / "electron" / "main.cjs")
    package_json = read_text(DESKTOP / "package.json")

    assert "桌宠模型" in text
    assert "ugofficial.model3.json" in text
    assert "Live2D Cubism WebGL 渲染器已挂载" in text
    assert not re.search(r"(@live2d|pixi-live2d)", package_json, flags=re.IGNORECASE)
    assert "validate-cubism-sdk.mjs" in package_json
    assert re.search(r"\bTray\b|new\s+Tray\s*\(", main)
    assert not re.search(r"autoUpdater|electron-updater", main)
    assert "\"electron-builder\"" in package_json
    assert "\"publish\"" not in package_json
