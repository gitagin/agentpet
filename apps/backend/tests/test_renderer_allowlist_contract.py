"""Contract test: every backend API route is reachable through the Electron
renderer proxy allowlist, and the allowlist carries no dead entries.

Why this exists
---------------
The renderer can only reach the backend through the hand-maintained regex
allowlist in ``apps/desktop/electron/proxy.js``. That list has drifted twice
in project history (the checkpoint-decision incident recorded in
``docs/portfolio/case-study.md``, then a 27-route gap found in the 2026-07
review, including ``graph/facts/{id}/reject`` while its four sibling actions
were allowed). Each drift shows up at runtime as
``renderer_api_route_not_allowed`` long after the backend work shipped.

This test turns the relationship into a build-time contract:

1. every route declared by a FastAPI ``@router.<method>`` decorator must be
   matched by at least one allowlist entry (unless explicitly exempted), and
2. every allowlist entry must match at least one backend route, so stale
   patterns (e.g. the historical ``(config|key)`` group that no longer
   matched the real ``model-config``/``model-key`` paths) are flagged
   instead of silently rotting.

The long-term fix is generating both sides from ``/openapi.json`` (fix
backlog item #9); until then this test is the drift guard.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"
PROXY_JS_PATH = Path(__file__).resolve().parents[2] / "desktop" / "electron" / "proxy.js"

# Routes that intentionally must NOT be reachable from the renderer.
# Add entries as ("METHOD", "/api/full/path/{param}") template strings.
RENDERER_EXEMPT_ROUTES: frozenset[tuple[str, str]] = frozenset()

_ROUTER_PREFIX_RE = re.compile(r'APIRouter\(\s*prefix="([^"]*)"')
_ROUTE_DECORATOR_RE = re.compile(
    r'@router\.(get|post|put|patch|delete)\(\s*\n?\s*"([^"]*)"', re.MULTILINE
)
_ALLOWLIST_ENTRY_RE = re.compile(
    r"\{\s*methods:\s*\[([^\]]+)\],\s*pattern:\s*/(.+?)/\s*\}"
)
_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def collect_backend_routes() -> list[tuple[str, str, str]]:
    """Return (source_file, METHOD, /api/... template) for every route."""
    routes: list[tuple[str, str, str]] = []
    for source in sorted(BACKEND_API_DIR.glob("*.py")):
        text = source.read_text(encoding="utf-8")
        prefix_match = _ROUTER_PREFIX_RE.search(text)
        prefix = prefix_match.group(1) if prefix_match else ""
        for match in _ROUTE_DECORATOR_RE.finditer(text):
            method = match.group(1).upper()
            routes.append((source.name, method, f"/api{prefix}{match.group(2)}"))
    return routes


def collect_allowlist_entries() -> list[tuple[str, frozenset[str], re.Pattern[str]]]:
    """Return (raw_pattern, methods, compiled_pattern) from proxy.js."""
    text = PROXY_JS_PATH.read_text(encoding="utf-8")
    entries = []
    for match in _ALLOWLIST_ENTRY_RE.finditer(text):
        methods = frozenset(
            part.strip().strip('"') for part in match.group(1).split(",")
        )
        entries.append((match.group(2), methods, re.compile(match.group(2))))
    return entries


def sample_concrete_path(template: str) -> str:
    """Substitute path params with values compatible with allowlist regexes."""

    def replace(match: re.Match[str]) -> str:
        if "profile-projection" in template:
            # The allowlist intentionally restricts these ids to profile_*.
            return "profile_abc123"
        return "sample-id-123"

    return _PATH_PARAM_RE.sub(replace, template)


def test_every_backend_route_is_allowlisted_or_exempt() -> None:
    routes = collect_backend_routes()
    entries = collect_allowlist_entries()
    assert routes, "route extraction found nothing — parser or layout changed"
    assert entries, "allowlist extraction found nothing — proxy.js format changed"

    missing: list[str] = []
    for source, method, template in routes:
        if (method, template) in RENDERER_EXEMPT_ROUTES:
            continue
        concrete = sample_concrete_path(template)
        allowed = any(
            method in methods and pattern.fullmatch(concrete)
            for _raw, methods, pattern in entries
        )
        if not allowed:
            missing.append(f"{method} {template}  (declared in {source})")

    assert not missing, (
        "Backend routes missing from the renderer proxy allowlist "
        "(add them to apps/desktop/electron/proxy.js or to "
        "RENDERER_EXEMPT_ROUTES with a justification):\n  "
        + "\n  ".join(missing)
    )


def test_allowlist_has_no_dead_entries() -> None:
    routes = collect_backend_routes()
    entries = collect_allowlist_entries()

    concrete_routes = [
        (method, sample_concrete_path(template)) for _s, method, template in routes
    ]
    dead: list[str] = []
    for raw, methods, pattern in entries:
        matches_any = any(
            method in methods and pattern.fullmatch(concrete)
            for method, concrete in concrete_routes
        )
        if not matches_any:
            dead.append(f"[{', '.join(sorted(methods))}] /{raw}/")

    assert not dead, (
        "Allowlist entries that match no backend route (stale pattern or "
        "removed endpoint — fix or delete them):\n  " + "\n  ".join(dead)
    )


def test_exemption_list_stays_honest() -> None:
    """Every exemption must still correspond to a real backend route."""
    declared = {(method, template) for _s, method, template in collect_backend_routes()}
    stale = [
        f"{method} {template}"
        for method, template in sorted(RENDERER_EXEMPT_ROUTES)
        if (method, template) not in declared
    ]
    assert not stale, (
        "RENDERER_EXEMPT_ROUTES entries no longer exist in the backend "
        "(remove them):\n  " + "\n  ".join(stale)
    )
