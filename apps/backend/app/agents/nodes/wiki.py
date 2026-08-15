from __future__ import annotations


def _wiki_proposal_kind(message: str) -> str:
    normalized = message.casefold()
    if any(
        marker in normalized
        for marker in (
            "query archive",
            "archive query",
            "archive answer",
            "归档回答",
            "归档查询",
            "查询归档",
        )
    ):
        return "query_archive"
    if any(
        marker in normalized
        for marker in (
            "synthesize",
            "synthesis",
            "综合整理",
            "综合成",
            "整合成",
            "整理综合",
        )
    ):
        return "synthesize"
    if any(
        marker in normalized
        for marker in (
            "wiki lint",
            "lint report",
            "lint wiki",
            "wiki health",
            "检查 wiki",
            "wiki 检查",
            "wiki 体检",
            "质量报告",
        )
    ):
        return "lint"
    return "ingest"
