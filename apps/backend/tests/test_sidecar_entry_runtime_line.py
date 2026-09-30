from __future__ import annotations

import json

from app.sidecar_entry import NONCE_ENV_VAR, RUNTIME_LINE_PREFIX, control_line, runtime_payload


def _decode(line: str) -> dict[str, object]:
    assert line.startswith(RUNTIME_LINE_PREFIX)
    return json.loads(line[len(RUNTIME_LINE_PREFIX) :])


def test_runtime_line_echoes_the_launch_nonce() -> None:
    line = control_line(RUNTIME_LINE_PREFIX, runtime_payload("127.0.0.1", 8765, 4056, "3f2a5c1d"))

    assert _decode(line) == {
        "host": "127.0.0.1",
        "port": 8765,
        "pid": 4056,
        "nonce": "3f2a5c1d",
    }


def test_runtime_line_omits_an_absent_nonce() -> None:
    line = control_line(RUNTIME_LINE_PREFIX, runtime_payload("127.0.0.1", 8765, 4056, None))

    assert _decode(line) == {"host": "127.0.0.1", "port": 8765, "pid": 4056}


def test_runtime_line_omits_an_empty_nonce() -> None:
    assert "nonce" not in runtime_payload("127.0.0.1", 8765, 4056, "")


def test_nonce_environment_variable_name_is_part_of_the_launcher_contract() -> None:
    assert NONCE_ENV_VAR == "AGENT_PET_SIDECAR_NONCE"
