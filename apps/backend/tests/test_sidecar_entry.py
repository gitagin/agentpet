from __future__ import annotations

import json
import socket

from app.sidecar_entry import (
    ERROR_LINE_PREFIX,
    RUNTIME_LINE_PREFIX,
    bind_available_socket,
    build_parser,
    control_line,
)


def test_sidecar_socket_selection_keeps_selected_port_reserved() -> None:
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    preferred_port = int(occupied.getsockname()[1])

    listener = None
    try:
        listener, selected_port = bind_available_socket("127.0.0.1", preferred_port, 20)
        assert selected_port > preferred_port

        competing = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            competing.bind(("127.0.0.1", selected_port))
        except OSError:
            pass
        else:  # pragma: no cover - the selected listener must retain ownership
            raise AssertionError("selected sidecar port was not retained atomically")
        finally:
            competing.close()
    finally:
        occupied.close()
        if listener is not None:
            listener.close()


def test_sidecar_runtime_line_is_machine_parseable() -> None:
    payload = {"host": "127.0.0.1", "port": 8765, "pid": 42}
    line = control_line(RUNTIME_LINE_PREFIX, payload)
    assert json.loads(line.removeprefix(RUNTIME_LINE_PREFIX)) == payload


def test_sidecar_error_line_is_machine_parseable() -> None:
    payload = {"code": "PORT_IN_USE", "message": "no available port"}
    line = control_line(ERROR_LINE_PREFIX, payload)
    assert json.loads(line.removeprefix(ERROR_LINE_PREFIX)) == payload


def test_sidecar_socket_selection_reports_exhausted_range() -> None:
    occupied: list[socket.socket] = []
    first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    first.bind(("127.0.0.1", 0))
    first.listen(1)
    occupied.append(first)
    preferred_port = int(first.getsockname()[1])

    second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        second.bind(("127.0.0.1", preferred_port + 1))
    except OSError:
        second.close()
    else:
        second.listen(1)
        occupied.append(second)

    try:
        try:
            listener, _ = bind_available_socket("127.0.0.1", preferred_port, len(occupied) - 1)
        except OSError as exc:
            assert "no available sidecar port" in str(exc)
        else:  # pragma: no cover - every port in the tested range is occupied
            listener.close()
            raise AssertionError("sidecar unexpectedly bound an occupied port range")
    finally:
        for listener in occupied:
            listener.close()


def test_sidecar_cli_uses_bounded_explicit_port_settings() -> None:
    args = build_parser().parse_args(
        ["--host", "127.0.0.1", "--port", "9000", "--port-search-range", "8"]
    )
    assert (args.host, args.port, args.port_search_range) == ("127.0.0.1", 9000, 8)
