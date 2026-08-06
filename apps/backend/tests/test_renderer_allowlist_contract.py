"""Drift guard for the OpenAPI-derived Electron renderer proxy routes.

``apps/backend/openapi.json`` is the route source of truth. The desktop
generator turns it into a versioned JSON artifact consumed by ``proxy.js``;
routes intentionally unavailable to the renderer live in a separate,
justified exemption document. These tests keep all three in lockstep.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ROOT = Path(__file__).resolve().parents[2] / "desktop"
OPENAPI_PATH = BACKEND_ROOT / "openapi.json"
PROXY_ROUTES_PATH = DESKTOP_ROOT / "electron" / "proxy-routes.generated.json"
EXEMPTIONS_PATH = DESKTOP_ROOT / "electron" / "proxy-route-exemptions.json"

ARTIFACT_SCHEMA_VERSION = 1
EXEMPTIONS_SCHEMA_VERSION = 1
OPENAPI_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)
Route = tuple[str, str]


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain a JSON object"
    return value


def collect_openapi_routes(document: dict[str, Any]) -> set[Route]:
    paths = document.get("paths")
    assert isinstance(paths, dict), "openapi.json must contain a paths object"
    return {
        (method.upper(), path)
        for path, path_item in paths.items()
        if path.startswith("/api/") and isinstance(path_item, dict)
        for method in path_item
        if method.lower() in OPENAPI_METHODS
    }


def collect_generated_routes(document: dict[str, Any]) -> set[Route]:
    routes = document.get("routes")
    assert isinstance(routes, list), "generated proxy routes must be an array"
    expanded: set[Route] = set()
    for route in routes:
        assert isinstance(route, dict)
        path = route.get("path")
        methods = route.get("methods")
        assert isinstance(path, str) and path.startswith("/api/")
        assert isinstance(methods, list) and methods
        for method in methods:
            assert isinstance(method, str)
            key = (method, path)
            assert key not in expanded, f"duplicate generated proxy route: {key}"
            expanded.add(key)
    return expanded


def collect_exemptions(document: dict[str, Any]) -> set[Route]:
    routes = document.get("routes")
    assert isinstance(routes, list), "proxy route exemptions must be an array"
    exemptions: set[Route] = set()
    for route in routes:
        assert isinstance(route, dict)
        method = route.get("method")
        path = route.get("path")
        reason = route.get("reason")
        assert isinstance(method, str)
        assert isinstance(path, str) and path.startswith("/api/")
        assert isinstance(reason, str) and reason.strip(), (
            f"renderer proxy exemption {method} {path} needs a justification"
        )
        key = (method, path)
        assert key not in exemptions, f"duplicate renderer proxy exemption: {key}"
        exemptions.add(key)
    return exemptions


def route_contract_drift(
    declared: set[Route], allowed: set[Route], exempt: set[Route]
) -> tuple[set[Route], set[Route], set[Route]]:
    covered = allowed | exempt
    return declared - covered, covered - declared, allowed & exempt


def test_generated_proxy_artifact_tracks_openapi_snapshot() -> None:
    openapi_text = OPENAPI_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    openapi = json.loads(openapi_text)
    artifact = load_json(PROXY_ROUTES_PATH)

    assert artifact.get("schemaVersion") == ARTIFACT_SCHEMA_VERSION
    source = artifact.get("source")
    assert isinstance(source, dict)
    assert source.get("openapiVersion") == openapi.get("openapi")
    assert source.get("apiVersion") == openapi.get("info", {}).get("version")
    assert source.get("sha256") == hashlib.sha256(openapi_text.encode()).hexdigest(), (
        "proxy-routes.generated.json is stale; run `npm run generate:api-contracts` "
        "from apps/desktop"
    )


def test_every_openapi_route_is_generated_or_explicitly_exempt() -> None:
    declared = collect_openapi_routes(load_json(OPENAPI_PATH))
    allowed = collect_generated_routes(load_json(PROXY_ROUTES_PATH))
    exemptions_document = load_json(EXEMPTIONS_PATH)
    assert exemptions_document.get("schemaVersion") == EXEMPTIONS_SCHEMA_VERSION
    exempt = collect_exemptions(exemptions_document)

    missing, stale, overlap = route_contract_drift(declared, allowed, exempt)
    assert not missing, (
        "Backend routes missing from generated renderer routes or exemptions:\n  "
        + "\n  ".join(f"{method} {path}" for method, path in sorted(missing))
    )
    assert not stale, (
        "Generated renderer routes or exemptions no longer exist in OpenAPI:\n  "
        + "\n  ".join(f"{method} {path}" for method, path in sorted(stale))
    )
    assert not overlap, (
        "Routes cannot be both renderer-allowed and exempt:\n  "
        + "\n  ".join(f"{method} {path}" for method, path in sorted(overlap))
    )


def test_contract_drift_check_rejects_new_missing_and_stale_routes() -> None:
    declared = {("GET", "/api/existing"), ("POST", "/api/new")}
    allowed = {("GET", "/api/existing"), ("DELETE", "/api/removed")}
    missing, stale, overlap = route_contract_drift(declared, allowed, set())

    assert missing == {("POST", "/api/new")}
    assert stale == {("DELETE", "/api/removed")}
    assert overlap == set()
