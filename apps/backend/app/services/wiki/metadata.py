from .common import *


class WikiMetadataWorkflowMixin:

    def plan_lint(self, request: WikiLintRequest | None = None) -> WikiLintProposal:
        lint_request = request or WikiLintRequest()
        date = utc_now_iso()[:10]
        target_path = f"Wiki/Reports/Lint-{date}.md" if lint_request.write_report else None
        markdown = "\n".join(
            [
                "## Wiki Lint 提案",
                "",
                f"- write_report: `{str(lint_request.write_report).lower()}`",
                f"- target_path: `{target_path or ''}`",
                "",
                "此提案不会立即执行 Markdown 写入。写入报告前请先确认 lint 操作。",
            ]
        ).strip()
        return WikiLintProposal(
            write_report=lint_request.write_report,
            target_path=target_path,
            markdown_preview=markdown,
        )

