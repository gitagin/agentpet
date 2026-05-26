from .common import *
from .utility import _unique

from .markdown import _synthesis_markdown

class WikiSynthesisWorkflowMixin:

    def plan_synthesis(self, request: WikiSynthesizeRequest) -> WikiSynthesisProposal:
        target_path = request.target_path or f"Wiki/Syntheses/{slugify_wiki_title(request.title)}.md"
        return WikiSynthesisProposal(
            title=request.title,
            target_path=target_path,
            tags=_unique(["synthesis", *request.tags]),
            links=_unique([*request.links, *request.source_paths]),
            source_paths=_unique(request.source_paths),
            markdown_preview=_synthesis_markdown(request),
        )

    def synthesize(self, request: WikiSynthesizeRequest) -> WikiSynthesizeResponse:
        target_path = request.target_path or f"Wiki/Syntheses/{slugify_wiki_title(request.title)}.md"
        content = _synthesis_markdown(request)
        page = self.wiki.write_page(
            WikiPageWriteRequest(
                title=request.title,
                content=content,
                operation="replace_section",
                target_path=target_path,
                section="综合整理",
                tags=_unique(["synthesis", *request.tags]),
                links=_unique([*request.links, *request.source_paths]),
            )
        )
        self.wiki.refresh_index()
        self.wiki.append_log(
            "synthesize",
            request.title,
            f"- 页面：`{page.relative_path}`\n- 来源路径：{len(request.source_paths)}",
        )
        return WikiSynthesizeResponse(page=page, index_updated=True, log_appended=True)
