from __future__ import annotations

from .common import *
from .common import _StoredIngestRun, _StoredPagePlan
from .utility import _preview_text, _unique

def _deterministic_review_response(
    run: _StoredIngestRun,
    *,
    reviewer_agent_id: str,
    status: str,
    model_error: str | None = None,
    summary: str | None = None,
) -> WikiIngestReviewResponse:
    targets = [plan.target_path for plan in run.page_plans]
    findings = [
        WikiIngestReviewFinding(
            severity="info",
            code="source_claims_extracted",
            message=f"Source has {_non_empty_line_count(run.raw_content)} non-empty lines and {len(run.page_plans)} planned page updates.",
            target_path=targets[0] if targets else None,
        )
    ]
    missing_link_targets = _missing_link_targets(run.page_plans)
    findings.extend(
        WikiIngestReviewFinding(
            severity="warning",
            code="missing_link_review_needed",
            message=f"Planned content references [[{target}]]. Confirm whether this page should exist or be created.",
            target_path=None,
        )
        for target in missing_link_targets[:5]
    )
    if not run.page_plans:
        findings.append(
            WikiIngestReviewFinding(
                severity="error",
                code="no_page_plans",
                message="No page plans were generated for this ingest run.",
            )
        )
    return WikiIngestReviewResponse(
        review_id=new_id(),
        run_id=run.id,
        status=status,  # type: ignore[arg-type]
        summary=summary
        or f"确定性审查为来源 '{run.source_title}' 准备了 {len(run.page_plans)} 个页面计划。",
        findings=findings,
        recommended_targets=targets,
        reviewer_agent_id=reviewer_agent_id,
        model_error=model_error,
    )


def _parse_model_review(
    text: str,
    run: _StoredIngestRun,
    *,
    reviewer_agent_id: str,
) -> WikiIngestReviewResponse:
    data = _json_object_from_text(text)
    if data is None:
        base = _deterministic_review_response(
            run,
            reviewer_agent_id=reviewer_agent_id,
            status="failed",
            model_error="invalid_review_json",
            summary=_plain_text_summary(text) or "模型审查返回的不是有效 JSON。已保留确定性审查。",
        )
        return base

    findings = _model_findings(data.get("findings"))
    recommended = _valid_review_targets(data.get("recommended_targets"), run)
    if not recommended:
        recommended = [plan.target_path for plan in run.page_plans]
    summary = str(data.get("summary") or "").strip() or _plain_text_summary(text)
    return WikiIngestReviewResponse(
        review_id=new_id(),
        run_id=run.id,
        status="reviewed",
        summary=summary or f"模型审查准备了 {len(recommended)} 个推荐目标。",
        findings=findings,
        recommended_targets=recommended,
        reviewer_agent_id=reviewer_agent_id,
    )


async def _complete_model(model: WikiReviewModelProtocol, *, user_message: str, system_prompt: str) -> str:
    result = model.complete(user_message=user_message, system_prompt=system_prompt)
    if inspect.isawaitable(result):
        result = await result
    return str(result).strip()


def _review_system_prompt() -> str:
    return (
        "你正在审查本地优先的 LLM Wiki 导入计划。"
        "只返回 JSON，包含 summary, findings, recommended_targets 键。"
        "findings 是对象数组，含 severity(info|warning|error)、code、message、target_path。"
        "不要要求写文件，不要包含密钥。"
    )


def _review_user_message(run: _StoredIngestRun) -> str:
    plans = [
        {
            "title": plan.title,
            "target_path": plan.target_path,
            "operation": plan.operation,
            "section": plan.section,
            "tags": plan.tags,
            "links": plan.links,
            "content_preview": _preview_text(plan.content, 700),
        }
        for plan in run.page_plans
    ]
    payload = {
        "run_id": run.id,
        "source": {
            "id": run.source_id,
            "title": run.source_title,
            "type": run.source_type,
            "uri": run.source_uri,
            "content_preview": _preview_text(run.raw_content, 6000),
        },
        "page_plans": plans,
    }
    return json.dumps(payload, ensure_ascii=False)


def _json_object_from_text(text: str) -> dict[str, object] | None:
    stripped = text.strip()
    candidates = [stripped]
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _model_findings(value) -> list[WikiIngestReviewFinding]:
    if not isinstance(value, list):
        return []
    findings: list[WikiIngestReviewFinding] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "info").strip()
        if severity not in {"info", "warning", "error"}:
            severity = "info"
        code = str(item.get("code") or "model_review_note").strip()[:80] or "model_review_note"
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        target_path = item.get("target_path")
        findings.append(
            WikiIngestReviewFinding(
                severity=severity,  # type: ignore[arg-type]
                code=code,
                message=message[:1000],
                target_path=str(target_path).strip() if target_path else None,
            )
        )
    return findings


def _valid_review_targets(value, run: _StoredIngestRun) -> list[str]:
    valid = {plan.target_path for plan in run.page_plans}
    if not isinstance(value, list):
        return []
    return _unique(str(item) for item in value if str(item) in valid)


def _missing_link_targets(plans: list[_StoredPagePlan]) -> list[str]:
    plan_titles = {plan.title.casefold() for plan in plans}
    plan_paths = {Path(plan.target_path).stem.replace("-", " ").casefold() for plan in plans}
    linked: list[str] = []
    for plan in plans:
        linked.extend(plan.links)
        linked.extend(re.findall(r"\[\[([^\]]+)\]\]", plan.content))
    return [
        link
        for link in _unique(link.split("|", 1)[0].strip() for link in linked)
        if link.casefold() not in plan_titles and link.replace("-", " ").casefold() not in plan_paths
    ]


def _plain_text_summary(text: str, limit: int = 600) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit].rstrip()


def _non_empty_line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())
