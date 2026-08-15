from .common import *
from .markdown import _concept_update_markdown, _entity_update_markdown, _maintenance_markdown, _related_titles, _source_summary_markdown
from .planning_candidates import _EntityCandidate, _entity_candidates, _should_plan_maintenance
from .utility import _unique

def _build_ingest_page_plans(request: WikiIngestPreviewRequest, source_hash: str) -> list[WikiIngestPagePlan]:
    parsed = parse_markdown(request.content, fallback_title=request.title)
    source_path = f"Wiki/Sources/{slugify_wiki_title(request.title)}.md"
    source_links = _unique([*request.links, *parsed.links])
    plans: list[WikiIngestPagePlan] = []
    _append_ingest_plan(
        plans,
        _source_page_plan(request, source_hash=source_hash, source_path=source_path, source_links=source_links),
        max_pages=request.max_pages,
    )

    related_titles = _related_titles(request, parsed.links, parsed.tags)
    entity_candidates = _entity_candidates(request, parsed)
    concept_plans = [
        _concept_page_plan(title, request=request, source_path=source_path)
        for title in related_titles
    ]
    entity_plans = [
        _entity_page_plan(candidate, request=request, source_path=source_path, related_titles=related_titles)
        for candidate in entity_candidates
    ]
    seed_plans: list[WikiIngestPagePlan] = []
    if concept_plans:
        seed_plans.append(concept_plans[0])
    if entity_plans:
        seed_plans.append(entity_plans[0])
    if _should_plan_maintenance(request.content, parsed):
        seed_plans.append(
            _maintenance_page_plan(
                request,
                source_path=source_path,
                related_titles=related_titles,
            )
        )

    for plan in [
        *seed_plans,
        *concept_plans[1:],
        *entity_plans[1:],
    ]:
        _append_ingest_plan(plans, plan, max_pages=request.max_pages)
        if len(plans) >= request.max_pages:
            break
    return plans

def _build_basic_ingest_page_plans(request: WikiIngestPreviewRequest, source_hash: str) -> list[WikiIngestPagePlan]:
    parsed = parse_markdown(request.content, fallback_title=request.title)
    source_slug = slugify_wiki_title(request.title)
    source_path = f"Wiki/Sources/{source_slug}.md"
    source_links = _unique([*request.links, *parsed.links])
    tags = _unique([*request.tags, *parsed.tags, "source"])
    plans = [
        WikiIngestPagePlan(
            title=request.title,
            target_path=source_path,
            operation="replace_section",
            section="来源摘要",
            content=_source_summary_markdown(request, source_hash, source_links),
            tags=tags,
            links=source_links,
        )
    ]
    related_titles = _related_titles(request, parsed.links)
    for title in related_titles[: max(0, request.max_pages - 1)]:
        plans.append(
            WikiIngestPagePlan(
                title=title,
                target_path=f"Wiki/Concepts/{slugify_wiki_title(title)}.md",
                operation="replace_section",
                section="定义",
                content=_concept_update_markdown(title, request, source_path),
                tags=_unique([*request.tags, "concept"]),
                links=[source_path, request.title],
            )
        )
    return plans[: request.max_pages]

def _source_page_plan(
    request: WikiIngestPreviewRequest,
    *,
    source_hash: str,
    source_path: str,
    source_links: list[str],
) -> WikiIngestPagePlan:
    return WikiIngestPagePlan(
        title=request.title,
        target_path=source_path,
        operation="replace_section",
        section="来源摘要",
        content=_source_summary_markdown(request, source_hash, source_links),
        tags=_unique([*request.tags, *parse_markdown(request.content, fallback_title=request.title).tags, "source"]),
        links=source_links,
    )


def _concept_page_plan(
    title: str,
    *,
    request: WikiIngestPreviewRequest,
    source_path: str,
) -> WikiIngestPagePlan:
    return WikiIngestPagePlan(
        title=title,
        target_path=f"Wiki/Concepts/{slugify_wiki_title(title)}.md",
        operation="replace_section",
        section="定义",
        content=_concept_update_markdown(title, request, source_path),
        tags=_unique([*request.tags, "concept"]),
        links=[request.title],
    )


def _entity_page_plan(
    candidate: _EntityCandidate,
    *,
    request: WikiIngestPreviewRequest,
    source_path: str,
    related_titles: list[str],
) -> WikiIngestPagePlan:
    return WikiIngestPagePlan(
        title=candidate.title,
        target_path=f"Wiki/Entities/{slugify_wiki_title(candidate.title)}.md",
        operation="replace_section",
        section="实体定义",
        content=_entity_update_markdown(candidate, request, source_path),
        tags=_unique([*request.tags, "entity", candidate.kind]),
        links=_unique([request.title, source_path, *related_titles]),
    )


def _maintenance_page_plan(
    request: WikiIngestPreviewRequest,
    *,
    source_path: str,
    related_titles: list[str],
) -> WikiIngestPagePlan:
    title = f"{request.title} Maintenance"
    return WikiIngestPagePlan(
        title=title,
        target_path=f"Wiki/Reports/{slugify_wiki_title(title)}.md",
        operation="replace_section",
        section=f"Maintenance: {request.title}",
        content=_maintenance_markdown(request, source_path=source_path),
        tags=_unique([*request.tags, "maintenance", "conflict-review"]),
        links=_unique([request.title, source_path, *related_titles]),
    )


def _append_ingest_plan(
    plans: list[WikiIngestPagePlan],
    plan: WikiIngestPagePlan,
    *,
    max_pages: int,
) -> None:
    if len(plans) >= max_pages:
        return
    existing_paths = {item.target_path.casefold() for item in plans}
    if plan.target_path.casefold() in existing_paths:
        return
    plans.append(plan)

