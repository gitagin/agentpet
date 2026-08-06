from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from collections.abc import Sequence


RUNTIME_LINE_PREFIX = "AGENT_PET_SIDECAR_RUNTIME "
ERROR_LINE_PREFIX = "AGENT_PET_SIDECAR_ERROR "


def control_line(prefix: str, payload: dict[str, object]) -> str:
    return prefix + json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def bind_available_socket(host: str, preferred_port: int, search_range: int) -> tuple[socket.socket, int]:
    last_error: OSError | None = None
    for port in range(preferred_port, preferred_port + max(0, search_range) + 1):
        candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            candidate.bind((host, port))
            candidate.listen(socket.SOMAXCONN)
            return candidate, port
        except OSError as exc:
            last_error = exc
            candidate.close()
    detail = f": {last_error}" if last_error is not None else ""
    raise OSError(
        f"no available sidecar port in {preferred_port}-{preferred_port + max(0, search_range)}{detail}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Agent Pet backend sidecar")
    parser.add_argument("--host", default=os.environ.get("AGENT_PET_BACKEND_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AGENT_PET_BACKEND_PORT", "8765")),
    )
    parser.add_argument("--port-search-range", type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        listener, selected_port = bind_available_socket(
            args.host,
            max(1, min(args.port, 65_535)),
            max(0, min(args.port_search_range, 100)),
        )
    except OSError as exc:
        message = f"Agent Pet sidecar failed to bind: {exc}"
        print(
            control_line(ERROR_LINE_PREFIX, {"code": "PORT_IN_USE", "message": message}),
            file=sys.stderr,
            flush=True,
        )
        return 2

    os.environ["AGENT_PET_BACKEND_HOST"] = args.host
    os.environ["AGENT_PET_BACKEND_PORT"] = str(selected_port)
    print(
        control_line(
            RUNTIME_LINE_PREFIX,
            {"host": args.host, "port": selected_port, "pid": os.getpid()},
        ),
        flush=True,
    )

    try:
        try:
            import uvicorn

            from app.main import app

            uvicorn.Server(
                uvicorn.Config(
                    app,
                    host=args.host,
                    port=selected_port,
                    log_level="info",
                    access_log=False,
                )
            ).run(sockets=[listener])
        except Exception as exc:
            print(
                control_line(
                    ERROR_LINE_PREFIX,
                    {
                        "code": "STARTUP_FAILED",
                        "message": f"Agent Pet sidecar startup failed: {exc}",
                    },
                ),
                file=sys.stderr,
                flush=True,
            )
            raise
        return 0
    finally:
        listener.close()


if __name__ == "__main__":
    raise SystemExit(main())
