from __future__ import annotations

from pydantic import Field

from app.models.wiki import WikiLintIssue
from .compiler import (Citation, CompilerError, StrictOutput, assert_snapshots_current,
                       read_snapshot, structured_call)


class SemanticFinding(StrictOutput):
    kind: str
    explanation: str = Field(min_length=1)
    evidence: list[Citation] = Field(min_length=2)


class SemanticReview(StrictOutput):
    findings: list[SemanticFinding] = Field(default_factory=list, max_length=100)


async def semantic_issues(wiki, model) -> tuple[list[WikiLintIssue], int]:
    paths = [page.relative_path for page in wiki.list_pages()
             if not page.relative_path.startswith("Wiki/Reports/")]
    if not paths:
        return [], 0
    snapshots = {path: read_snapshot(wiki, path) for path in paths}
    review = await structured_call(model, SemanticReview,
        task="Compare the supplied wiki pages. Identify factual contradictions, stale claims, "
             "or missing semantic cross-links, including cross-domain relationships. Distinguish "
             "different dates and scopes from genuine conflict. Do not rewrite pages or resolve "
             "conflicts automatically. Each finding needs exact quotes from at least two different "
             "supplied pages. kind must be contradiction, stale_claim or missing_link.",
        payload={"task": "semantic_lint", "pages": [{"path": s.path, "text": s.text} for s in snapshots.values()]})
    issues = []
    for finding in review.findings:
        if finding.kind not in {"contradiction", "stale_claim", "missing_link"}:
            raise CompilerError("wiki_semantic_lint_invalid_kind")
        if len({e.path for e in finding.evidence}) < 2:
            raise CompilerError("wiki_semantic_lint_requires_two_pages")
        for citation in finding.evidence:
            if citation.path not in snapshots or citation.quote not in snapshots[citation.path].text:
                raise CompilerError("wiki_semantic_lint_invalid_citation")
        evidence = "\n".join(f"{e.path}: {e.quote}" for e in finding.evidence)
        issues.append(WikiLintIssue(severity="warning", code=f"semantic_{finding.kind}",
            message=finding.explanation + "\n" + evidence,
            path=finding.evidence[0].path, target=finding.evidence[1].path))
    assert_snapshots_current(wiki, {p: s.content_hash for p, s in snapshots.items()})
    return issues, len(snapshots)
