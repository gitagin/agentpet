from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


# 注意：此文件的 PAGE_TYPE_CONTRACTS 是 resources/wiki/AGENTS.md「页面类型」一节的
# 代码化镜像，用于确定性校验（validate_page_type）。AGENTS.md 是唯一规则来源，
# LLM 审查会读取它（wiki/review.py）。修改页面类型 / 证据门槛 / 必需章节时，
# 必须同时更新 AGENTS.md 与下表，否则一致性测试会失败。


@dataclass(frozen=True, slots=True)
class WikiPageTypeContract:
    required_sections: tuple[str, ...]
    optional_sections: tuple[str, ...] = ()
    minimum_evidence: int = 1
    requires_user_decision: bool = False


PAGE_TYPE_CONTRACTS: dict[str, WikiPageTypeContract] = {
    "source": WikiPageTypeContract(
        required_sections=("来源摘要",),
        optional_sections=("不可变摘录", "可验证主张", "关联实体", "来源"),
    ),
    "entity": WikiPageTypeContract(
        required_sections=("实体定义", "已确认事实", "来源"),
        optional_sections=("关系", "冲突与过期", "更新日志"),
    ),
    "concept": WikiPageTypeContract(
        required_sections=("定义", "来源"),
        optional_sections=("核心要点", "案例", "误区", "关系", "更新日志"),
    ),
    "synthesis": WikiPageTypeContract(
        required_sections=("问题", "结论", "支持证据", "来源"),
        optional_sections=("反证与不确定性", "影响", "更新日志"),
        minimum_evidence=2,
    ),
    "comparison": WikiPageTypeContract(
        required_sections=("比较对象", "共同证据", "差异", "来源"),
        optional_sections=("限制", "更新日志"),
        minimum_evidence=2,
    ),
    "decision": WikiPageTypeContract(
        required_sections=("用户决定", "背景", "依据", "来源"),
        optional_sections=("替代方案", "风险", "后续检查", "未解决问题", "更新日志"),
        minimum_evidence=1,
        requires_user_decision=True,
    ),
    "report": WikiPageTypeContract(
        required_sections=("范围", "结果", "证据"),
        optional_sections=("失败项", "后续动作", "生成信息", "来源", "更新日志"),
        minimum_evidence=1,
    ),
}

PAGE_TYPE_ROOTS: dict[str, str] = {
    "source": "Wiki/Sources/",
    "entity": "Wiki/Entities/",
    "concept": "Wiki/Concepts/",
    "synthesis": "Wiki/Syntheses/",
    "comparison": "Wiki/Comparisons/",
    "decision": "Wiki/Decisions/",
    "report": "Wiki/Reports/",
}


def page_type_for_path(relative_path: str, default: str = "page") -> str:
    normalized = relative_path.replace("\\", "/")
    for page_type, prefix in PAGE_TYPE_ROOTS.items():
        if normalized.startswith(prefix):
            return page_type
    if normalized.startswith("Wiki/Companion/Summaries/"):
        return "source"
    if normalized.startswith("Wiki/Companion/Reports/"):
        return "report"
    return default


def unique_evidence(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip().replace("\\", "/")
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


def evidence_count(*, sources: Iterable[str], evidence_ids: Iterable[str]) -> int:
    source_count = len(unique_evidence(sources))
    evidence_count_value = len(unique_evidence(evidence_ids))
    return max(source_count, evidence_count_value)


def validate_page_type(
    page_type: str,
    *,
    sources: Iterable[str],
    evidence_ids: Iterable[str] = (),
    user_decision: str | None = None,
    inference: bool = False,
    enforce_minimum_evidence: bool = True,
) -> None:
    contract = PAGE_TYPE_CONTRACTS.get(page_type)
    if contract is None:
        return
    normalized_sources = unique_evidence(sources)
    if not normalized_sources:
        raise ValueError(f"{page_type}_requires_source_reference")
    count = evidence_count(sources=normalized_sources, evidence_ids=evidence_ids)
    if enforce_minimum_evidence and count < contract.minimum_evidence:
        raise ValueError(f"{page_type}_requires_{contract.minimum_evidence}_independent_evidence")
    if contract.requires_user_decision and not (user_decision or "").strip():
        raise ValueError("decision_requires_explicit_user_decision")
    if page_type == "decision" and inference:
        raise ValueError("decision_cannot_be_model_inference")


def path_matches_page_type(relative_path: str, page_type: str) -> bool:
    expected = page_type_for_path(relative_path, default=page_type)
    if page_type == "source" and relative_path.startswith("Wiki/Companion/Summaries/"):
        return True
    return expected == page_type


def slug_for_page_type(page_type: str) -> str:
    return PAGE_TYPE_ROOTS.get(page_type, "Wiki/")
