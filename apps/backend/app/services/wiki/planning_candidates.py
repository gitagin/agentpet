from __future__ import annotations

from dataclasses import dataclass

from .common import *
from .utility import _unique


@dataclass(frozen=True)
class _EntityCandidate:
    title: str
    kind: str
    evidence: str = ""


def _entity_candidates(request: WikiIngestPreviewRequest, parsed) -> list[_EntityCandidate]:
    candidates: list[_EntityCandidate] = []
    for tag in _unique([*request.tags, *parsed.tags]):
        candidate = _entity_candidate_from_tag(tag)
        if candidate is not None:
            candidates.append(candidate)

    for key, value in parsed.frontmatter.items():
        kind = _entity_kind_from_key(str(key))
        if kind is None:
            continue
        for title in _candidate_values(value):
            candidates.append(_EntityCandidate(title=title, kind=kind, evidence=f"frontmatter:{key}"))

    for match in re.finditer(
        r"(?im)^\s*(?:[-*]\s*)?(entity|entities|person|people|company|organization|project|paper)\s*:\s*(.+)$",
        parsed.body,
    ):
        kind = _entity_kind_from_key(match.group(1)) or "entity"
        for title in _candidate_values(match.group(2)):
            candidates.append(_EntityCandidate(title=title, kind=kind, evidence=match.group(0).strip()))

    for chunk in parsed.chunks:
        kind = _entity_kind_from_heading(chunk.heading or "")
        if kind is None:
            continue
        for title in _bullet_values(chunk.content):
            candidates.append(_EntityCandidate(title=title, kind=kind, evidence=chunk.heading or "heading"))

    return _unique_entity_candidates(candidates)


def _entity_candidate_from_tag(tag: str) -> _EntityCandidate | None:
    marker, _, raw_title = tag.partition("/")
    kind = _entity_kind_from_key(marker)
    title = _clean_title_candidate(raw_title.replace("-", " ").replace("_", " ")) if raw_title else ""
    if kind is None or not title:
        return None
    return _EntityCandidate(title=title, kind=kind, evidence=f"tag:{tag}")


def _entity_kind_from_key(value: str) -> str | None:
    normalized = value.strip().casefold().replace("-", "_")
    return {
        "entity": "entity",
        "entities": "entity",
        "person": "person",
        "people": "person",
        "author": "person",
        "authors": "person",
        "company": "organization",
        "companies": "organization",
        "organization": "organization",
        "organizations": "organization",
        "org": "organization",
        "project": "project",
        "projects": "project",
        "paper": "paper",
        "papers": "paper",
    }.get(normalized)


def _entity_kind_from_heading(heading: str) -> str | None:
    normalized = heading.casefold()
    if any(marker in normalized for marker in ("people", "person", "authors")):
        return "person"
    if any(marker in normalized for marker in ("companies", "company", "organizations", "organization")):
        return "organization"
    if "projects" in normalized or "project" in normalized:
        return "project"
    if "papers" in normalized or "paper" in normalized:
        return "paper"
    if "entities" in normalized or "entity" in normalized:
        return "entity"
    return None


def _candidate_values(value) -> list[str]:
    raw_values = value if isinstance(value, list) else re.split(r"[,;]", str(value))
    return [
        cleaned
        for raw in raw_values
        if (cleaned := _clean_title_candidate(str(raw)))
    ]


def _bullet_values(content: str) -> list[str]:
    values: list[str] = []
    for line in content.splitlines():
        match = re.match(r"\s*(?:[-*]|\d+[.)])\s+(.+)$", line)
        if match:
            values.extend(_candidate_values(match.group(1)))
    return values


def _unique_entity_candidates(candidates: list[_EntityCandidate]) -> list[_EntityCandidate]:
    by_title: dict[str, _EntityCandidate] = {}
    for candidate in candidates:
        key = candidate.title.casefold()
        if key not in by_title:
            by_title[key] = candidate
    return list(by_title.values())


def _should_plan_maintenance(content: str, parsed) -> bool:
    text = " ".join([content, *(chunk.heading or "" for chunk in parsed.chunks)]).casefold()
    return any(
        marker in text
        for marker in (
            "conflict",
            "contradict",
            "inconsistent",
            "stale",
            "duplicate",
            "drift",
            "todo",
            "follow-up",
            "open question",
            "unclear",
            "disagreement",
        )
    )


def _clean_title_candidate(value: str) -> str:
    text = re.sub(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", r"\1", value)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.split(r"\s+-\s+|\s+--\s+|\s+\|\s+|\s+\(", text, maxsplit=1)[0]
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n#`'\".,;:")
    if not text or text.casefold() in {"entity", "entities", "people", "projects", "papers"}:
        return ""
    if text.casefold().startswith(("http://", "https://")):
        return ""
    return text[:80].rstrip()
