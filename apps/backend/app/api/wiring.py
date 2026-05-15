from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Request, status

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.config import get_settings
from app.errors import AppError
from app.models.api import (
    MemorySearchResponse,
    MemorySearchResult,
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    QueryArchiveLintResponse,
    QueryArchiveRequest,
    TaskCreateRequest,
    TaskCreateResponse,
    WikiIngestPreviewRequest,
    WikiIngestPreviewResponse,
    WikiIngestReviewRequest,
    WikiIngestReviewResponse,
    WikiPageResponse,
    WikiPageWriteRequest,
)
from app.models.enums import AgentId
from app.repositories.storage import VaultRepository
from app.services.memory import (
    MarkdownWriteError,
    MemoryConflictError,
    MemoryProposalNotFoundError,
    MemoryProposalStateError,
    MemoryProposalStore,
    MemoryService,
    SafeMarkdownWriter,
)
from app.services.audit import AuditLogService
from app.services.chat_auto_memory import ChatAutoMemoryService, ChatAutoMemoryStore
from app.services.continuity import ContinuityService
from app.services.diary_memory import (
    DiaryMemorySearch,
    DiaryMemoryService,
    DiaryMemoryStore,
    diary_records_to_search_results,
)
from app.services.diary_memory_extractor import DiaryMemoryExtractor
from app.services.long_term_memory import LongTermMemoryService
from app.services.memory_graph import MemoryGraphStore
from app.services.retrieval import RetrievalService
from app.services.retrieval_factory import build_vector_index
from app.services.chat_model import AGENT_IDS, AgentModelRegistry, LangChainGraphChatClient
from app.services.settings import SettingsStore
from app.services.tasks import (
    TaskNotFoundError,
    TaskService,
    TaskStore,
    TimezoneParseError,
    display_timezone_name,
)
from app.services.wiki import WikiService
from app.services.wiki_lint import WikiLintService
from app.services.wiki_workflows import WikiWorkflowService
from app.storage.database import Database


_index_refresh_timers: dict[str, Any] = {}


def database(request: Request) -> Database:
    return request.app.state.database


def retrieval_service(request: Request) -> RetrievalService:
    return request.app.state.retrieval_service


def refresh_retrieval_vector_index(request: Request) -> None:
    settings = get_settings()
    request.app.state.retrieval_service.vector_index = build_vector_index(database(request).path, settings)


def audit_log_service(request: Request) -> AuditLogService:
    return AuditLogService(database(request).path)


def record_audit(
    request: Request,
    *,
    actor: str = "local-api",
    action: str,
    result: str,
    target_path: str | None = None,
    reason: str | None = None,
) -> None:
    service = audit_log_service(request)
    try:
        service.record(
            actor=actor,
            action=action,
            target_path=target_path,
            result=result,
            reason=reason,
        )
    finally:
        service.close()


def audit_reason(request: Request, **values: str | None) -> str:
    request_id = getattr(getattr(request, "state", None), "request_id", None)
    pairs = [("request_id", request_id)]
    pairs.extend((key, value) for key, value in values.items())
    return ";".join(f"{key}={value}" for key, value in pairs if value)


def set_active_vault_id(request: Request, vault_id: str) -> None:
    request.app.state.active_vault_id = vault_id
    with database(request).connect() as conn:
        with conn:
            VaultRepository(conn).set_active(vault_id)


def active_vault_id(request: Request) -> str:
    current = getattr(request.app.state, "active_vault_id", None)
    if current:
        return str(current)
    with database(request).connect() as conn:
        row = VaultRepository(conn).get_active()
    if row is None:
        raise AppError(
            code="vault_not_configured",
            message="尚未配置当前知识库。",
            status_code=status.HTTP_409_CONFLICT,
        )
    set_active_vault_id(request, str(row["id"]))
    return str(row["id"])


def active_vault_root(request: Request) -> str:
    vault_id = active_vault_id(request)
    with database(request).connect() as conn:
        try:
            return str(VaultRepository(conn).get(vault_id)["root_path"])
        except KeyError as exc:
            request.app.state.active_vault_id = None
            raise AppError(
                code="vault_not_found",
                message="未找到当前知识库。",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"vault_id": vault_id},
            ) from exc


def ensure_vault_path(path: str, *, create_if_missing: bool) -> Path:
    root = Path(path).expanduser().resolve(strict=False)
    if root.exists() and not root.is_dir():
        raise AppError(
            code="invalid_vault_path",
            message="知识库路径必须是目录。",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"path": str(root)},
        )
    if not root.exists():
        if not create_if_missing:
            raise AppError(
                code="vault_path_not_found",
                message="知识库路径不存在。",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"path": str(root)},
            )
        root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_default_vault_content(root: Path) -> None:
    inbox = root / "Inbox"
    memories = root / "Memories"
    inbox.mkdir(parents=True, exist_ok=True)
    memories.mkdir(parents=True, exist_ok=True)
    pending = inbox / "Pending Memories.md"
    if not pending.exists():
        pending.write_text("# Pending Memories\n\n", encoding="utf-8")


def memory_service(request: Request) -> MemoryService:
    root = active_vault_root(request)
    vault_id = active_vault_id(request)
    retrieval = retrieval_service(request)
    store = MemoryProposalStore(database(request).path)
    writer = SafeMarkdownWriter(root)
    return MemoryService(
        store,
        writer,
        index_refresh=lambda _relative_path: schedule_index_refresh(request, vault_id),
    )


def chat_auto_memory_service(request: Request) -> ChatAutoMemoryService:
    root = active_vault_root(request)
    vault_id = active_vault_id(request)
    retrieval = retrieval_service(request)
    store = ChatAutoMemoryStore(database(request).path)
    writer = SafeMarkdownWriter(root)
    return ChatAutoMemoryService(
        store,
        writer,
        index_refresh=lambda _relative_path: schedule_index_refresh(request, vault_id),
    )


def diary_memory_service(request: Request) -> DiaryMemoryService:
    vault_id = active_vault_id(request)
    extractor_agent = chat_model_client(request, AgentId.DIARY_MEMORY_EXTRACTOR_AGENT.value)
    extraction_model = AgentId.DIARY_MEMORY_EXTRACTOR_AGENT.value if extractor_agent is not None else None
    model = extractor_agent
    if model is None:
        model = chat_model_client(request, AgentId.SEMANTIC_ANALYSIS_AGENT.value)
        extraction_model = AgentId.SEMANTIC_ANALYSIS_AGENT.value if model is not None else None
    if model is None:
        model = chat_model_client(request, AgentId.CHAT_AGENT.value)
        extraction_model = AgentId.CHAT_AGENT.value if model is not None else None
    return DiaryMemoryService(
        DiaryMemoryStore(database(request).path),
        vault_id=vault_id,
        extractor=DiaryMemoryExtractor(model),
        extraction_model=extraction_model,
    )


def long_term_memory_service(request: Request) -> LongTermMemoryService:
    root = active_vault_root(request)
    vault_id = active_vault_id(request)
    writer = SafeMarkdownWriter(root)
    extraction_model = chat_model_client(request, AgentId.DIARY_MEMORY_EXTRACTOR_AGENT.value)
    extraction_model_name = AgentId.DIARY_MEMORY_EXTRACTOR_AGENT.value if extraction_model is not None else None
    if extraction_model is None:
        extraction_model = chat_model_client(request, AgentId.SEMANTIC_ANALYSIS_AGENT.value)
        extraction_model_name = AgentId.SEMANTIC_ANALYSIS_AGENT.value if extraction_model is not None else None
    return LongTermMemoryService(
        writer,
        index_refresh=lambda _relative_path: schedule_index_refresh(request, vault_id),
        graph_store=MemoryGraphStore(
            database(request).path,
            graph_root=get_settings().data_dir / "memory-graph",
        ),
        extraction_model=extraction_model,
        extraction_model_name=extraction_model_name,
    )


def continuity_service(request: Request) -> ContinuityService:
    return ContinuityService(database(request).path)


async def continuity_service_dependency(request: Request) -> AsyncIterator[ContinuityService]:
    service = continuity_service(request)
    try:
        yield service
    finally:
        service.close()


def wiki_service(request: Request) -> WikiService:
    root = active_vault_root(request)
    vault_id = active_vault_id(request)
    return WikiService(
        SafeMarkdownWriter(root),
        index_refresh=lambda _relative_path: schedule_index_refresh(request, vault_id),
    )


async def wiki_service_dependency(request: Request) -> AsyncIterator[WikiService]:
    yield wiki_service(request)


def wiki_workflow_service(request: Request) -> WikiWorkflowService:
    return WikiWorkflowService(
        database(request),
        wiki_service(request),
        review_agent_id="wiki_manager_agent",
        review_model_resolver=lambda agent_id: chat_model_client(request, agent_id.value),
    )


async def wiki_workflow_service_dependency(request: Request) -> AsyncIterator[WikiWorkflowService]:
    yield wiki_workflow_service(request)


def wiki_lint_service(request: Request) -> WikiLintService:
    return WikiLintService(
        database(request).path,
        vault_id=active_vault_id(request),
        vault_root=active_vault_root(request),
        wiki=wiki_service(request),
    )


async def wiki_lint_service_dependency(request: Request) -> AsyncIterator[WikiLintService]:
    service = wiki_lint_service(request)
    try:
        yield service
    finally:
        service.close()


def memory_graph_store(request: Request) -> MemoryGraphStore:
    return MemoryGraphStore(
        database(request).path,
        graph_root=get_settings().data_dir / "memory-graph",
    )


def schedule_index_refresh(request: Request, vault_id: str, *, delay_seconds: float = 0.5) -> str:
    import threading

    app = request.app
    job_id = f"scheduled:{vault_id}"
    previous = _index_refresh_timers.get(vault_id)
    if previous is not None:
        previous.cancel()

    def rebuild() -> None:
        try:
            retrieval_service(_AppRequest(app)).rebuild_index(vault_id)
        finally:
            _index_refresh_timers.pop(vault_id, None)

    timer = threading.Timer(delay_seconds, rebuild)
    timer.daemon = True
    _index_refresh_timers[vault_id] = timer
    timer.start()
    return job_id


class _AppRequest:
    def __init__(self, app) -> None:
        self.app = app


async def memory_service_dependency(request: Request) -> AsyncIterator[MemoryService]:
    service = memory_service(request)
    try:
        yield service
    finally:
        service.close()


def task_service(request: Request) -> TaskService:
    return TaskService(
        TaskStore(database(request).path),
        scheduler=getattr(request.app.state, "reminder_scheduler", None),
    )


async def task_service_dependency(request: Request) -> AsyncIterator[TaskService]:
    service = task_service(request)
    try:
        yield service
    finally:
        service.close()


def settings_store(request: Request) -> SettingsStore:
    return SettingsStore(database(request).path)


async def settings_store_dependency(request: Request) -> AsyncIterator[SettingsStore]:
    store = settings_store(request)
    try:
        yield store
    finally:
        store.close()


class RuntimeRetrievalAdapter:
    def __init__(self, request: Request):
        self.request = request

    def search(
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
            response = _prepend_graph_memory_results(self.request, response, query=query, top_k=top_k)
        if source_scope == "all":
            response = _prepend_diary_memory_results(self.request, response, query=query, top_k=top_k)
        return response


def _prepend_graph_memory_results(
    request: Request,
    response: MemorySearchResponse,
    *,
    query: str,
    top_k: int,
) -> MemorySearchResponse:
    store = memory_graph_store(request)
    try:
        facts = store.search_active(query, limit=top_k)
    finally:
        store.close()
    graph_results = [
        MemorySearchResult(
            note_id=fact.id,
            chunk_id=fact.id,
            relative_path="MemoryGraph/LongTerm",
            title="Structured Long-Term Memory",
            heading=fact.subject,
            snippet=f"{fact.subject} {fact.predicate} {fact.object}",
            score=fact.confidence + min(fact.support_count, 10) / 100,
            source_scope="personal_memory",
            retrieval_mode="graph",
        )
        for fact in facts
    ]
    seen = {(result.relative_path, result.heading or "", result.snippet) for result in graph_results}
    merged = [*graph_results]
    for result in response.results:
        key = (result.relative_path, result.heading or "", result.snippet)
        if key in seen:
            continue
        seen.add(key)
        merged.append(result)
    return response.model_copy(update={"results": merged[:top_k]})


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

    def create_proposal(
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

    def create(self, create_request: TaskCreateRequest) -> TaskCreateResponse:
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

    def manage_page(self, write_request: WikiPageWriteRequest) -> WikiPageResponse:
        return wiki_service(self.request).write_page(write_request)


class RuntimeWikiWorkflowAdapter:
    def __init__(self, request: Request):
        self.request = request

    def preview_ingest(self, ingest_request: WikiIngestPreviewRequest) -> WikiIngestPreviewResponse:
        return wiki_workflow_service(self.request).preview_ingest(ingest_request)

    async def review_ingest(self, review_request: WikiIngestReviewRequest) -> WikiIngestReviewResponse:
        return await wiki_workflow_service(self.request).review_ingest(review_request)

    def lint_query_archive(self, archive_request: QueryArchiveRequest) -> QueryArchiveLintResponse:
        return wiki_workflow_service(self.request).lint_query_archive(archive_request)

    def plan_query_archive(self, archive_request: QueryArchiveRequest):
        return wiki_workflow_service(self.request).plan_query_archive(archive_request)

    def plan_synthesis(self, synthesize_request):
        return wiki_workflow_service(self.request).plan_synthesis(synthesize_request)

    def plan_lint(self, lint_request):
        return wiki_workflow_service(self.request).plan_lint(lint_request)


def agent_runtime(request: Request) -> LangGraphAgentRuntime:
    registry = agent_model_registry(request)
    return LangGraphAgentRuntime(
        AgentRuntimeServices(
            retrieval=RuntimeRetrievalAdapter(request),
            memory=RuntimeMemoryAdapter(request),
            tasks=RuntimeTaskAdapter(request),
            continuity=RuntimeContinuityAdapter(request),
            wiki=RuntimeWikiAdapter(request),
            wiki_workflow=RuntimeWikiWorkflowAdapter(request),
            model_registry=registry if registry.clients else None,
        )
    )


def agent_model_registry(request: Request) -> AgentModelRegistry:
    return AgentModelRegistry(
        clients={
            agent_id: client
            for agent_id in AGENT_IDS
            if (client := chat_model_client(request, agent_id.value)) is not None
        }
    )


def chat_model_client(
    request: Request,
    agent_id: str | None = None,
) -> LangChainGraphChatClient | None:
    settings = get_settings()
    store = settings_store(request)
    try:
        if agent_id is None:
            status_value = store.get_model_key_status()
            model_config = store.get_model_config(
                default_provider=status_value.provider or "openai-compatible",
                default_base_url=settings.model_base_url,
                default_model=settings.chat_model,
            )
        else:
            status_value = store.get_agent_model_key_status(agent_id)
            model_config = store.get_agent_model_config(
                agent_id,
                default_provider=status_value.provider or "openai-compatible",
                default_base_url=settings.model_base_url,
                default_model=settings.chat_model,
            )
            if model_config is None:
                return None
            provider_status = store.get_agent_model_key_status(
                agent_id,
                provider=model_config.provider,
            )
            if provider_status.configured:
                status_value = provider_status
        if not status_value.configured:
            return None
        provider = model_config.provider.strip().lower()
        if provider not in {"openai", "openai-compatible", "openai_compatible"}:
            return None
        if agent_id is None:
            api_key = store.get_model_key(model_config.provider)
            if not api_key and status_value.provider:
                api_key = store.get_model_key(status_value.provider)
        else:
            api_key = store.get_agent_model_key(
                agent_id=agent_id,
                provider=model_config.provider,
            )
            if not api_key and status_value.provider:
                api_key = store.get_agent_model_key(
                    agent_id=agent_id,
                    provider=status_value.provider,
                )
        if not api_key:
            return None
        return LangChainGraphChatClient(
            api_key=api_key,
            base_url=model_config.base_url,
            model=model_config.model,
            timeout_seconds=settings.model_timeout_seconds,
        )
    finally:
        store.close()


def map_memory_error(exc: Exception) -> AppError:
    if isinstance(exc, MemoryProposalNotFoundError):
        return AppError("proposal_not_found", "未找到记忆提案。", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, MemoryProposalStateError):
        return AppError("proposal_state_conflict", str(exc), status.HTTP_409_CONFLICT)
    if isinstance(exc, MemoryConflictError):
        return AppError("memory_write_conflict", str(exc), status.HTTP_409_CONFLICT)
    if isinstance(exc, MarkdownWriteError):
        return AppError("markdown_write_failed", str(exc), status.HTTP_400_BAD_REQUEST)
    return AppError("memory_service_error", "记忆服务处理失败。", status.HTTP_500_INTERNAL_SERVER_ERROR)


def map_task_error(exc: Exception) -> AppError:
    if isinstance(exc, TaskNotFoundError):
        return AppError("task_not_found", "未找到任务。", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, TimezoneParseError):
        return AppError("invalid_timezone", str(exc), status.HTTP_400_BAD_REQUEST)
    return AppError("task_service_error", "任务服务处理失败。", status.HTTP_500_INTERNAL_SERVER_ERROR)
