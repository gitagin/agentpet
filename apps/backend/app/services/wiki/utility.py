from __future__ import annotations

from .common import *

def _source_hash(content: str) -> str:
    return sha256_hex(content)


def _resolve_import_path(import_root: str | None, source_path: str | None) -> Path:
    if not import_root:
        raise WikiSourceImportRejectedError("import_root_required")
    if not source_path:
        raise WikiSourceImportRejectedError("source_path_required")
    root = Path(import_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise WikiSourceImportRejectedError("import_root_not_found")
    raw_path = Path(source_path).expanduser()
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WikiSourceImportRejectedError("source_path_outside_import_root") from exc
    return resolved


def _read_text_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WikiSourceImportRejectedError("source_file_not_utf8") from exc
    if not text.strip():
        raise WikiSourceImportRejectedError("source_file_empty")
    return text


def _is_binary_asset(path: Path) -> bool:
    return path.suffix.casefold() in {
        ".apng",
        ".avif",
        ".bmp",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".webp",
        ".pdf",
        ".zip",
    }


def _is_hidden_relative(root: Path, path: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _supplied_web_content(request: WikiSourceImportPreviewRequest) -> str:
    if request.text and request.text.strip():
        return request.text.strip()
    if request.html and request.html.strip():
        return _html_to_text(request.html)
    return ""


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|article|h[1-6]|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [re.sub(r"\s+", " ", html.unescape(line)).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _title_from_url(url: str) -> str:
    cleaned = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", url).strip("/")
    tail = cleaned.rsplit("/", 1)[-1] or cleaned
    title = re.sub(r"[-_]+", " ", tail).strip()
    return title.title() if title else "Imported URL"


def _asset_markdown(path: Path | None, *, title: str) -> str:
    lines = [
        f"# {title}",
        "",
        "Asset import preview.",
    ]
    if path is not None:
        lines.extend(
            [
                "",
                f"- File name: `{path.name}`",
                f"- File size bytes: `{path.stat().st_size}`",
                f"- Extension: `{path.suffix.casefold()}`",
            ]
        )
    return "\n".join(lines).strip()


def _base_import_metadata(request: WikiSourceImportPreviewRequest, *, source_uri: str | None) -> dict[str, object]:
    return {
        "importer": "wiki_source_import",
        "source_kind": request.source_kind,
        "source_uri": source_uri,
    }


def _preview_text(content: str, limit: int = 2000) -> str:
    return content[:limit]


def _answer_preview(answer: str, limit: int = 320) -> str:
    compact = re.sub(r"\s+", " ", answer).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip()


def _json_list(values: list[str]) -> str:
    return json.dumps(_unique(values), ensure_ascii=True)


def _json_object(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_citations(citations: list[MemorySearchResult]) -> str:
    return json.dumps([citation.model_dump() for citation in citations], ensure_ascii=True)


def _load_json_list(value) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data if str(item).strip()] if isinstance(data, list) else []


def _load_citations(value) -> list[MemorySearchResult]:
    if not value:
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    citations: list[MemorySearchResult] = []
    for item in data:
        try:
            citations.append(MemorySearchResult.model_validate(item))
        except (TypeError, ValueError):
            continue
    return _dedupe_citations(citations)


def _dedupe_citations(citations: list[MemorySearchResult]) -> list[MemorySearchResult]:
    seen: set[tuple[str, str, str]] = set()
    normalized: list[MemorySearchResult] = []
    for citation in citations:
        key = (
            citation.chunk_id or citation.relative_path,
            citation.heading or "",
            citation.snippet.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(citation)
    return normalized


def _load_review_findings(value) -> list[WikiIngestReviewFinding]:
    if not value:
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    findings: list[WikiIngestReviewFinding] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            findings.append(WikiIngestReviewFinding.model_validate(item))
        except (TypeError, ValueError):
            continue
    return findings


def _history_limit(limit: int) -> int:
    return min(max(int(limit), 1), 100)


def _unique(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result



def _table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
