from .common import *
from .contracts import slug_for_page_type, validate_page_type
from .utility import _unique

from .markdown import _synthesis_markdown
from .memory_closure import (
    WikiMemoryClosureError,
    finalize_wiki_synthesis_authority,
    prepare_wiki_synthesis_authority,
)

class WikiSynthesisWorkflowMixin:

    def plan_synthesis(self, request: WikiSynthesizeRequest) -> WikiSynthesisProposal:
        _validate_synthesis_request(request)
        target_path = request.target_path or f"{slug_for_page_type(request.page_type)}{slugify_wiki_title(request.title)}.md"
        return WikiSynthesisProposal(
            title=request.title,
            target_path=target_path,
            tags=_unique([request.page_type, *request.tags]),
            links=_unique([*request.links, *request.source_paths]),
            source_paths=_unique(request.source_paths),
            markdown_preview=_synthesis_markdown(request),
        )

    def synthesize(
        self,
        request: WikiSynthesizeRequest,
        *,
        action_marker: str | None = None,
    ) -> WikiSynthesizeResponse:
        _validate_synthesis_request(request, enforce_declared_evidence_count=False)
        target_path = request.target_path or f"{slug_for_page_type(request.page_type)}{slugify_wiki_title(request.title)}.md"
        try:
            with self.database.session() as conn:
                authority = prepare_wiki_synthesis_authority(
                    conn,
                    vault_root=self.wiki.writer.vault_root,
                    target_path=target_path,
                    page_type=request.page_type,
                    title=request.title,
                    source_paths=request.source_paths,
                    requested_entity_ids=request.entity_ids,
                    requested_fact_ids=request.fact_ids,
                    requested_evidence_ids=request.evidence_ids,
                )
        except WikiMemoryClosureError as exc:
            raise WikiWorkflowError(exc.reason) from exc
        grounded_request = request.model_copy(
            update={
                "source_paths": list(authority.source_paths),
                **authority.page_metadata(),
            }
        )
        content = _synthesis_markdown(grounded_request)
        if action_marker:
            content = f"{action_marker}\n{content}"
        page = self.wiki.write_page(
            WikiPageWriteRequest(
                title=request.title,
                content=content,
                operation="replace_section",
                target_path=target_path,
                section="页面内容",
                page_type=request.page_type,
                tags=_unique([request.page_type, *request.tags]),
                links=_unique([*request.links, *request.source_paths]),
                sources=list(authority.source_paths),
                **authority.page_metadata(),
                inference=request.page_type != "decision",
            ),
            action_marker=action_marker,
        )
        try:
            with self.database.session() as conn:
                finalize_wiki_synthesis_authority(
                    conn,
                    authority=authority,
                    vault_root=self.wiki.writer.vault_root,
                )
        except WikiMemoryClosureError as exc:
            raise WikiWorkflowError(exc.reason) from exc
        self.wiki.refresh_index()
        self.wiki.append_log(
            "synthesize",
            request.title,
            f"- 页面：`{page.relative_path}`\n- 来源路径：{len(request.source_paths)}",
            dedupe_marker=action_marker,
        )
        return WikiSynthesizeResponse(page=page, index_updated=True, log_appended=True)


def _validate_synthesis_request(
    request: WikiSynthesizeRequest,
    *,
    enforce_declared_evidence_count: bool = True,
) -> None:
    try:
        validate_page_type(
            request.page_type,
            sources=request.source_paths,
            evidence_ids=request.evidence_ids,
            user_decision=request.user_decision,
            inference=request.page_type != "decision",
            enforce_minimum_evidence=enforce_declared_evidence_count,
        )
    except ValueError as exc:
        raise WikiWorkflowError(str(exc)) from exc
