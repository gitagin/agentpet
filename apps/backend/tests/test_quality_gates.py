from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _require_module(name: str) -> None:
    if importlib.util.find_spec(name) is None:
        pytest.skip(f"{name} is available only in the backend dev extra")


def test_mypy_gate_rejects_a_new_type_error(tmp_path: Path) -> None:
    _require_module("mypy")
    probe = tmp_path / "new_module_type_probe.py"
    probe.write_text(
        "def answer() -> int:\n"
        "    return 'not-an-int'\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--config-file", "pyproject.toml", str(probe)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Incompatible return value type" in result.stdout


def test_ruff_gate_rejects_new_builtin_shadowing(tmp_path: Path) -> None:
    _require_module("ruff")
    probe = tmp_path / "new_module_lint_probe.py"
    probe.write_text("list = []\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--config", "pyproject.toml", str(probe)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "A001" in result.stdout
