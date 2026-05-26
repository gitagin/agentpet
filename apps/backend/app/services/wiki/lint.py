from .common import *
from .markdown import _query_archive_markdown
from .utility import _dedupe_citations

def _lint_query_archive(request: QueryArchiveRequest) -> QueryArchiveLintResponse:
    errors: list[str] = []
    warnings: list[str] = []
    normalized = _dedupe_citations(request.citations)
    knowledge = [citation for citation in normalized if citation.source_scope == "knowledge_base"]
    non_knowledge = [citation for citation in normalized if citation.source_scope != "knowledge_base"]
    if not normalized:
        errors.append("archive_requires_at_least_one_citation")
    if not knowledge:
        errors.append("archive_requires_knowledge_base_citation")
    if non_knowledge and not request.allow_mixed_sources:
        errors.append("archive_contains_non_knowledge_citation")
    elif non_knowledge:
        warnings.append("archive_contains_mixed_source_citations")
    markdown = _query_archive_markdown(request, normalized)
    return QueryArchiveLintResponse(
        passed=not errors,
        errors=errors,
        warnings=warnings,
        normalized_citations=normalized,
        markdown_preview=markdown,
    )
