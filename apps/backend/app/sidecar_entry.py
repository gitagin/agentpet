from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sys
from collections.abc import Sequence
from pathlib import Path


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
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Load packaged native/local-vector dependencies and run a read-only inference smoke test.",
    )
    return parser


def _bundle_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(str(frozen_root))
    return Path(__file__).resolve().parents[1]


def _self_test() -> int:
    """Exercise the same imports and native runtimes used by retrieval.

    This deliberately does not open the database, bind a port, or write files.
    A frozen distribution can therefore be checked immediately after build and
    before it is launched by Electron.
    """
    try:
        import langchain_qdrant  # noqa: F401
        import numpy as np
        import onnxruntime  # noqa: F401
        import qdrant_client  # noqa: F401
        import tokenizers  # noqa: F401
        from app.services.embeddings import LocalOnnxEmbeddings
        from app.services.retrieval_fusion import FusedCandidate
        from app.services.reranking_local import LocalCrossEncoderReranker
    except Exception as exc:
        print(
            control_line(
                ERROR_LINE_PREFIX,
                {"code": "SELF_TEST_IMPORT_FAILED", "message": str(exc)},
            ),
            file=sys.stderr,
            flush=True,
        )
        return 3

    root = _bundle_root()
    embedding_dir = root / "models" / "embedding"
    reranker_dir = root / "models" / "reranker"
    require_models = os.environ.get("AGENT_PET_REQUIRE_LOCAL_VECTOR", "") == "1"
    try:
        if not embedding_dir.is_dir() or not reranker_dir.is_dir():
            if require_models:
                raise RuntimeError("packaged local-vector model directories are missing")
            print(
                control_line(
                    RUNTIME_LINE_PREFIX,
                    {"self_test": "ok", "local_vector": "skipped_models_missing"},
                ),
                flush=True,
            )
            return 0

        embedder = LocalOnnxEmbeddings(embedding_dir)
        vector = embedder.embed_query("sidecar self-test")
        if len(vector) != 512 or not all(math.isfinite(float(value)) for value in vector):
            raise RuntimeError("local embedding returned an invalid vector")

        reranker = LocalCrossEncoderReranker(model_dir=reranker_dir)
        candidate = FusedCandidate(
            stable_id="self-test",
            content_hash="self-test",
            source_scope="personal_memory",
            payload={"title": "self-test", "content": "local reranker"},
            score=0.0,
            best_rank=1,
            contributions=(),
        )
        response = reranker.rerank(
            query="sidecar self-test",
            candidates=(candidate,),
            timeout_seconds=10.0,
        )
        if response.ordered_ids != ("self-test",):
            raise RuntimeError("local reranker returned an invalid ordering")
    except Exception as exc:
        print(
            control_line(
                ERROR_LINE_PREFIX,
                {"code": "SELF_TEST_RUNTIME_FAILED", "message": str(exc)},
            ),
            file=sys.stderr,
            flush=True,
        )
        return 4

    print(
        control_line(
            RUNTIME_LINE_PREFIX,
            {"self_test": "ok", "local_vector": "ready", "embedding_dimensions": len(vector)},
        ),
        flush=True,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()
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
