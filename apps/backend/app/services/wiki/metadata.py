from .common import *


class WikiMetadataWorkflowMixin:

    def plan_lint(self, request: WikiLintRequest | None = None) -> WikiLintProposal:
        lint_request = request or WikiLintRequest()
        date = utc_now_iso()[:10]
        target_path = f"Wiki/Reports/Lint-{date}.md" if lint_request.write_report else None
        markdown = "\n".join(
            [
                "## Wiki Lint Proposal",
                "",
                f"- write_report: `{str(lint_request.write_report).lower()}`",
                f"- target_path: `{target_path or ''}`",
                "",
                "This proposal does not run a Markdown write. Confirm the lint action before writing a report.",
            ]
        ).strip()
        return WikiLintProposal(
            write_report=lint_request.write_report,
            target_path=target_path,
            markdown_preview=markdown,
        )

