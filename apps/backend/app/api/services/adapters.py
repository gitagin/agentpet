from __future__ import annotations

from typing import Any

from fastapi import Request

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.models.api import (
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    MemorySearchResponse,
    MemorySearchResult,
    QueryArchiveLintResponse,
    QueryArchiveRequest,
    QueryArchiveResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    WikiIngestApplyRequest,
    WikiIngestApplyResponse,
    WikiIngestConfirmRequest,
    WikiIngestPreviewRequest,
    WikiIngestPreviewResponse,
    WikiIngestReviewRequest,
    WikiIngestReviewResponse,
    WikiLintReportResponse,
    WikiLintRequest,
    WikiPageResponse,
    WikiPageWriteRequest,
    WikiSynthesizeRequest,
    WikiSynthesizeResponse,
)
from app.models.enums import MemoryFactStatus
from app.services.agent_actions import AgentActionCreate, markdown_snapshot
from app.services.diary_memory import DiaryMemorySearch, diary_records_to_search_results
from app.services.memory_activation import (
    MemoryActivationContext,
    MemoryActivationDecision,
    MemoryActivationService,
    activation_item_from_graph_fact,
    rank_activation_decisions,
)
from app.services.memory_graph import MemoryGraphFact
from app.services.memory_permissions import result_with_activation_permissions
from app.services.tasks import display_timezone_name
from app.services.wiki import resolve_wiki_path

from .factory import (
    active_vault_id,
    agent_model_registry,
    chat_model_client,
    companion_retrieval_report_store,
    continuity_service,
    diary_memory_service,
    memory_activation_recorder,
    memory_graph_store,
    memory_service,
    record_agent_action,
    retrieval_service,
    settings_store,
    task_service,
    wiki_lint_service,
    wiki_service,
    wiki_workflow_service,
)


class RuntimeRetrievalAdapter:
    def __init__(self, request: Request):
        self.request = request

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> Any:
        if source_scope == "diary_objects":
            service = diary_memory_service(self.request)
            try:
                records = service.search(DiaryMemorySearch(query=query, top_k=top_k))
                return MemorySearchResponse(
                    results=diary_records_to_search_results(records),
                    metadata={"semantic_available": False, "retrieval_mode": "diary_object"},
                )
            finally:
                service.close()
        response = retrieval_service(self.request).search(
            vault_id=active_vault_id(self.request),
            query=query,
            top_k=top_k,
            source_scope=source_scope,
            mode=mode,
        )
        if source_scope in {"personal_memory", "all"}:
            response = prepend_graph_memory_results(self.request, response, query=query, top_k=top_k)
        if source_scope == "all":
            response = _prepend_diary_memory_results(self.request, response, query=query, top_k=top_k)
        return response


def prepend_graph_memory_results(
    request: Request,
    response: MemorySearchResponse,
    *,
    query: str,
    top_k: int,
) -> MemorySearchResponse:
    store = memory_graph_store(request)
    try:
        inactive_facts = _graph_fact_candidates(store, query=query, limit=200)
        decisions = _activated_graph_facts(inactive_facts, query=query, top_k=top_k)
    finally:
        store.close()
    inactive_signatures = _inactive_long_term_signatures(inactive_facts)
    graph_results = [
        result_with_activation_permissions(
            MemorySearchResult(
                note_id=fact.id,
                chunk_id=fact.id,
                relative_path="MemoryGraph/LongTerm",
                title="Structured Long-Term Memory",
                heading=fact.subject,
                snippet=_graph_result_snippet(fact),
                score=decision.activation_score,
                source_scope="personal_memory",
                retrieval_mode="graph_activation",
            ),
            decision,
            query=query,
            fact_id=fact.id,
        )
        for fact, decision in decisions
    ]
    seen = {(result.relative_path, result.heading or "", result.snippet) for result in graph_results}
    merged = [*graph_results]
    for result in response.results:
        if _matches_inactive_long_term_fact(result, inactive_signatures):
            continue
        key = (result.relative_path, result.heading or "", result.snippet)
        if key in seen:
            continue
        seen.add(key)
        merged.append(result)
    return response.model_copy(update={"results": merged[:top_k]})


def _inactive_long_term_signatures(facts: list[MemoryGraphFact]) -> set[tuple[str, str]]:
    inactive_statuses = {
        MemoryFactStatus.ARCHIVED,
        MemoryFactStatus.FORGOTTEN,
        MemoryFactStatus.REJECTED,
        MemoryFactStatus.SUPERSEDED,
        MemoryFactStatus.WRONG,
        MemoryFactStatus.SENSITIVE_BLOCKED,
    }
    return {
        (fact.subject.casefold(), fact.object.casefold())
        for fact in facts
        if fact.status in inactive_statuses
    }


def _matches_inactive_long_term_fact(result: MemorySearchResult, signatures: set[tuple[str, str]]) -> bool:
    if not signatures:
        return False
    normalized_path = result.relative_path.replace("\\", "/")
    if not normalized_path.startswith("Memories/LongTerm/"):
        return False
    haystack = " ".join([result.title, result.heading or "", result.snippet]).casefold()
    return any(subject in haystack and object_value in haystack for subject, object_value in signatures)


def _graph_fact_candidates(store, *, query: str, limit: int) -> list[MemoryGraphFact]:
    candidate_limit = max(1, min(limit, 200))
    facts = _dedupe_graph_facts(store.list_facts(query=query.strip() or None, limit=candidate_limit))
    for term in _significant_terms(query):
        if len(facts) >= candidate_limit:
            break
        facts = _dedupe_graph_facts(
            (
                *facts,
                *store.list_facts(query=term, limit=candidate_limit),
            )
        )
    return facts[:candidate_limit]


def _activated_graph_facts(
    facts: list[MemoryGraphFact],
    *,
    query: str,
    top_k: int,
) -> list[tuple[MemoryGraphFact, MemoryActivationDecision]]:
    service = MemoryActivationService()
    context = MemoryActivationContext(query=query, route_scopes=("graph_facts", "personal_memory"))
    decisions = [
        service.score(activation_item_from_graph_fact(fact), context)
        for fact in facts
    ]
    ranked = rank_activation_decisions(decisions, limit=top_k, require_answer_context=False)
    facts_by_id = {fact.id: fact for fact in facts}
    return [
        (facts_by_id[decision.item.memory_id], decision)
        for decision in ranked
        if decision.item.memory_id in facts_by_id
    ]


def _graph_result_snippet(fact: MemoryGraphFact) -> str:
    status_part = "" if fact.status is MemoryFactStatus.ACTIVE else f" (status={fact.status.value})"
    return f"{fact.subject} {fact.predicate} {fact.object}{status_part}"


def _significant_terms(query: str) -> tuple[str, ...]:
    stop_words = {
        "about",
        "does",
        "what",
        "when",
        "where",
        "which",
    }
    terms = []
    for raw in query.replace("?", " ").replace(",", " ").split():
        term = raw.strip().casefold()
        if len(term) < 3 or term in stop_words:
            continue
        terms.append(term)
    return tuple(dict.fromkeys(terms))


def _dedupe_graph_facts(facts):
    seen: set[str] = set()
    deduped = []
    for fact in facts:
        if fact.id in seen:
            continue
        seen.add(fact.id)
        deduped.append(fact)
    return deduped


def _prepend_diary_memory_results(
    request: Request,
    response: MemorySearchResponse,
    *,
    query: str,
    top_k: int,
) -> MemorySearchResponse:
    service = diary_memory_service(request)
    try:
        diary_results = diary_records_to_search_results(
            service.search(DiaryMemorySearch(query=query, top_k=top_k))
        )
    finally:
        service.close()
    seen = {(result.relative_path, result.heading or "", result.snippet) for result in diary_results}
    merged = [*diary_results]
    for result in response.results:
        key = (result.relative_path, result.heading or "", result.snippet)
        if key in seen:
            continue
        seen.add(key)
        merged.append(result)
    return response.model_copy(update={"results": merged[:top_k]})


class RuntimeMemoryAdapter:
    def __init__(self, request: Request):
        self.request = request

    async def create_proposal(
        self,
        create_request: MemoryProposalCreateRequest,
    ) -> MemoryProposalActionResponse:
        service = memory_service(self.request)
        try:
            proposal = service.create_proposal(
                type=create_request.type,
                content=create_request.content,
                target_path=create_request.target_path,
                source_message_id=create_request.source_message_id,
            )
        finally:
            service.close()
        return MemoryProposalActionResponse(
            proposal_id=proposal.id,
            status=proposal.status.value,
        )


class RuntimeTaskAdapter:
    def __init__(self, request: Request):
        self.request = request

    async def create(self, create_request: TaskCreateRequest) -> TaskCreateResponse:
        service = task_service(self.request)
        try:
            result = service.create(
                title=create_request.title,
                description=create_request.description,
                due_at=create_request.due_at,
                remind_at=create_request.remind_at,
                timezone=create_request.timezone,
                source_text=create_request.source_text,
            )
        finally:
            service.close()
        return TaskCreateResponse(
            task_id=result.task.id,
            reminder_id=result.reminder.id if result.reminder else None,
            status=result.task.status.value,
            metadata={
                **result.metadata,
                "title": result.task.title,
                "reminder_status": result.reminder.status.value if result.reminder else "",
                "remind_at": result.reminder.remind_at_utc if result.reminder else "",
                "timezone": result.reminder.time_parse_timezone if result.reminder else result.metadata.get("timezone", ""),
                "timezone_label": display_timezone_name(result.reminder.time_parse_timezone) if result.reminder else result.metadata.get("timezone_label", ""),
            },
        )


class RuntimeContinuityAdapter:
    def __init__(self, request: Request):
        self.request = request

    def context_block(self) -> str:
        service = continuity_service(self.request)
        try:
            return service.context_block()
        finally:
            service.close()

    def presence_context_block(self) -> str:
        service = continuity_service(self.request)
        try:
            return service.presence_context_block()
        finally:
            service.close()

    def presence_signal(self):
        service = continuity_service(self.request)
        try:
            return service.presence_signal()
        finally:
            service.close()


class RuntimeWikiAdapter:
    def __init__(self, request: Request):
        self.request = request

    async def manage_page(self, write_request: WikiPageWriteRequest) -> WikiPageResponse:
        service = wiki_service(self.request)
        target_path = resolve_wiki_path(write_request.title, write_request.target_path)
        before = markdown_snapshot(service.writer, [target_path])
        response = service.write_page(write_request)
        after = markdown_snapshot(service.writer, [response.relative_path])
        action = record_agent_action(
            self.request,
            AgentActionCreate(
                action_type="wiki.page.write",
                title=f"已整理 Wiki 页面：{response.title}",
                summary=f"{response.operation} -> {response.relative_path}",
                source_message_id=write_request.source_message_id,
                risk_tier="low",
                decision="auto",
                status="completed",
                target_paths=(response.relative_path,),
                before_snapshot=before,
                after_snapshot=after,
                metadata={"operation": response.operation, "index_job_id": response.index_job_id},
                reversible=True,
            ),
        )
        return response.model_copy(update={"action_id": action.action_id})


class RuntimeWikiWorkflowAdapter:
    def __init__(self, request: Request):
        self.request = request

    async def preview_ingest(self, ingest_request: WikiIngestPreviewRequest) -> WikiIngestPreviewResponse:
        return wiki_workflow_service(self.request).preview_ingest(ingest_request)

    async def confirm_ingest(self, confirm_request: WikiIngestConfirmRequest) -> WikiIngestPreviewResponse:
        return wiki_workflow_service(self.request).confirm_ingest(confirm_request)

    async def review_ingest(self, review_request: WikiIngestReviewRequest) -> WikiIngestReviewResponse:
        return await wiki_workflow_service(self.request).review_ingest(review_request)

    async def lint_query_archive(self, archive_request: QueryArchiveRequest) -> QueryArchiveLintResponse:
        return wiki_workflow_service(self.request).lint_query_archive(archive_request)

    async def archive_query(self, archive_request: QueryArchiveRequest) -> QueryArchiveResponse:
        service = wiki_workflow_service(self.request)
        plan = service.plan_query_archive(archive_request)
        before = markdown_snapshot(service.wiki.writer, [plan.target_path])
        response = service.archive_query(archive_request)
        after = markdown_snapshot(service.wiki.writer, [response.page.relative_path])
        action = record_agent_action(
            self.request,
            AgentActionCreate(
                action_type="wiki.query_archive.write",
                title=f"已归档查询：{plan.title}",
                summary=f"写入 {response.page.relative_path}",
                source_agent_run_id=archive_request.agent_run_id,
                source_message_id=archive_request.source_message_id,
                risk_tier="low",
                decision="auto",
                status="completed",
                target_paths=(response.page.relative_path,),
                before_snapshot=before,
                after_snapshot=after,
                metadata={"archive_id": response.archive_id, "index_job_id": response.page.index_job_id},
                reversible=True,
            ),
        )
        return response.model_copy(
            update={
                "action_id": action.action_id,
                "page": response.page.model_copy(update={"action_id": action.action_id}),
            }
        )

    async def plan_query_archive(self, archive_request: QueryArchiveRequest):
        return wiki_workflow_service(self.request).plan_query_archive(archive_request)

    async def synthesize(self, synthesize_request: WikiSynthesizeRequest) -> WikiSynthesizeResponse:
        service = wiki_workflow_service(self.request)
        plan = service.plan_synthesis(synthesize_request)
        before = markdown_snapshot(service.wiki.writer, [plan.target_path])
        response = service.synthesize(synthesize_request)
        after = markdown_snapshot(service.wiki.writer, [response.page.relative_path])
        action = record_agent_action(
            self.request,
            AgentActionCreate(
                action_type="wiki.synthesize.write",
                title=f"已综合整理：{synthesize_request.title}",
                summary=f"写入 {response.page.relative_path}",
                source_message_id=None,
                risk_tier="low",
                decision="auto",
                status="completed",
                target_paths=(response.page.relative_path,),
                before_snapshot=before,
                after_snapshot=after,
                metadata={"source_paths": synthesize_request.source_paths, "index_job_id": response.page.index_job_id},
                reversible=True,
            ),
        )
        return response.model_copy(
            update={
                "action_id": action.action_id,
                "page": response.page.model_copy(update={"action_id": action.action_id}),
            }
        )

    async def plan_synthesis(self, synthesize_request):
        return wiki_workflow_service(self.request).plan_synthesis(synthesize_request)

    async def run_lint(self, lint_request: WikiLintRequest) -> WikiLintReportResponse:
        plan = wiki_workflow_service(self.request).plan_lint(lint_request)
        lint_service = wiki_lint_service(self.request)
        try:
            before = markdown_snapshot(lint_service.wiki.writer, [plan.target_path]) if plan.target_path and lint_service.wiki else {}
            response = lint_service.run(lint_request)
            if response.report_page is None:
                return response
            after = markdown_snapshot(lint_service.wiki.writer, [response.report_page.relative_path]) if lint_service.wiki else {}
            action = record_agent_action(
                self.request,
                AgentActionCreate(
                    action_type="wiki.lint.report",
                    title="已生成 Wiki 体检报告",
                    summary=f"写入 {response.report_page.relative_path}",
                    risk_tier="low",
                    decision="auto",
                    status="completed",
                    target_paths=(response.report_page.relative_path,),
                    before_snapshot=before,
                    after_snapshot=after,
                    metadata={"summary": response.summary},
                    reversible=True,
                ),
            )
            return response.model_copy(
                update={
                    "action_id": action.action_id,
                    "report_page": response.report_page.model_copy(update={"action_id": action.action_id}),
                }
            )
        finally:
            lint_service.close()

    async def plan_lint(self, lint_request):
        return wiki_workflow_service(self.request).plan_lint(lint_request)

    async def apply_ingest(self, apply_request: WikiIngestApplyRequest) -> WikiIngestApplyResponse:
        response = wiki_workflow_service(self.request).apply_ingest(apply_request)
        target_paths = tuple(result.relative_path for result in response.page_results if result.status in {"created", "updated"})
        if target_paths:
            record_agent_action(
                self.request,
                AgentActionCreate(
                    action_type="wiki.ingest.apply",
                    title="已应用 Wiki 导入计划",
                    summary=f"写入 {response.pages_written} 个页面。",
                    risk_tier="medium",
                    decision="ask",
                    status="completed",
                    target_paths=target_paths,
                    metadata={"run_id": response.run_id, "lint_summary": response.lint_summary},
                    reversible=False,
                ),
            )
        return response


def agent_runtime(request: Request) -> LangGraphAgentRuntime:
    registry = agent_model_registry(request)
    store = settings_store(request)
    try:
        automation = store.get_automation_settings()
    finally:
        store.close()
    return LangGraphAgentRuntime(
        AgentRuntimeServices(
            retrieval=RuntimeRetrievalAdapter(request),
            memory=RuntimeMemoryAdapter(request),
            tasks=RuntimeTaskAdapter(request),
            continuity=RuntimeContinuityAdapter(request),
            wiki=RuntimeWikiAdapter(request),
            wiki_workflow=RuntimeWikiWorkflowAdapter(request),
            companion_retrieval_reports=companion_retrieval_report_store(request),
            model_registry=registry if registry.clients else None,
            automation_settings=automation,
            agent_action_recorder=lambda action: record_agent_action(request, action),
            memory_activation_recorder=memory_activation_recorder(request),
        )
    )
