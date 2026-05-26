from __future__ import annotations

import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request, status

from app.config import get_settings
from app.errors import AppError
from app.models.enums import AgentId
from app.repositories.storage import VaultRepository
from app.services.agent_actions import AgentActionCreate, AgentActionService, AgentActionStore
from app.services.audit import AuditLogService
from app.services.chat_auto_memory import ChatAutoMemoryService, ChatAutoMemoryStore
from app.scheduler import ReminderSchedulerProtocol
from app.services.chat_model import AGENT_IDS, AgentModelRegistry, LangChainGraphChatClient
from app.services.companion_consolidation import CompanionConsolidationService
from app.services.companion_retrieval import CompanionRetrievalReportStore
from app.services.continuity import ContinuityService
from app.services.diary_memory import DiaryMemoryService, DiaryMemoryStore
from app.services.diary_memory_extractor import DiaryMemoryExtractor
from app.services.health import component_health_from_vector_index
from app.services.long_term_memory import LongTermMemoryService
from app.services.memory import MemoryProposalStore, MemoryService, SafeMarkdownWriter
from app.services.memory_graph import MemoryGraphStore
from app.services.retrieval import RetrievalService
from app.services.retrieval_factory import build_vector_index
from app.services.settings import SettingsStore
from app.services.tasks import TaskService, TaskStore
from app.services.wiki import WikiService
from app.services.wiki_lint import WikiDiagnosticsQueueService, WikiLintService
from app.services.wiki_workflows import WikiWorkflowService
from app.storage.database import Database
from app.agents.state import AgentState


logger = logging.getLogger(__name__)

_CHAT_RUN_TTL_SECONDS = 900


@dataclass(frozen=True, slots=True)
class AppContext:
    # Background work only keeps app-scoped services and request id, not the raw HTTP Request.
    app: FastAPI
    request_id: str | None = None


def app_context(request: Request) -> AppContext:
    return AppContext(
        app=request.app,
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )


def database(request: Request | AppContext) -> Database:
    return request.app.state.database


def retrieval_service(request: Request | AppContext) -> RetrievalService:
    service = getattr(request.app.state, "retrieval_service", None)
    if service is None:
        from app.main import ensure_app_services

        ensure_app_services(request.app)
        service = request.app.state.retrieval_service
    return service


def refresh_retrieval_vector_index(request: Request) -> None:
    settings = get_settings()
    vector_index = build_vector_index(database(request).path, settings)
    request.app.state.retrieval_service.vector_index = vector_index
    request.app.state.component_health["vector_index"] = component_health_from_vector_index(vector_index)


def _chat_runs_lock(request: Request) -> threading.Lock:
    lock = getattr(request.app.state, "chat_runs_lock", None)
    if lock is None:
        lock = threading.Lock()
        request.app.state.chat_runs_lock = lock
    return lock


def chat_runs(request: Request) -> dict[str, AgentState]:
    return request.app.state.chat_runs


def add_chat_run(request: Request, state: AgentState) -> None:
    with _chat_runs_lock(request):
        request.app.state.chat_runs[state.agent_run_id] = state
        request.app.state.chat_runs_expires_at[state.agent_run_id] = time.monotonic() + _CHAT_RUN_TTL_SECONDS


def get_chat_run(request: Request, agent_run_id: str) -> AgentState | None:
    with _chat_runs_lock(request):
        expires_at = request.app.state.chat_runs_expires_at.get(agent_run_id)
        if expires_at is not None and expires_at <= time.monotonic():
            request.app.state.chat_runs.pop(agent_run_id, None)
            request.app.state.chat_runs_expires_at.pop(agent_run_id, None)
            return None
        return request.app.state.chat_runs.get(agent_run_id)


def pop_chat_run(request: Request, agent_run_id: str) -> None:
    with _chat_runs_lock(request):
        request.app.state.chat_runs.pop(agent_run_id, None)
        request.app.state.chat_runs_expires_at.pop(agent_run_id, None)


def reset_chat_runs(request: Request) -> None:
    with _chat_runs_lock(request):
        request.app.state.chat_runs = {}
        request.app.state.chat_runs_expires_at = {}


def reminder_scheduler(request: Request) -> ReminderSchedulerProtocol:
    return request.app.state.reminder_scheduler


def cached_active_vault_id(request: Request) -> str | None:
    value = getattr(request.app.state, "active_vault_id", None)
    return str(value) if value else None


def clear_cached_active_vault_id(request: Request) -> None:
    request.app.state.active_vault_id = None


def audit_log_service(request: Request | AppContext) -> AuditLogService:
    return AuditLogService(database(request).path)


def agent_action_store(request: Request | AppContext) -> AgentActionStore:
    return AgentActionStore(database(request).path)


def agent_action_service(request: Request | AppContext) -> AgentActionService:
    services = vault_services(request)
    writer = services.optional_writer()
    return AgentActionService(
        agent_action_store(request),
        writer=writer,
        index_refresh=lambda relative_path: schedule_index_refresh(request, services.vault_id) if writer is not None else None,
    )


def record_audit(
    request: Request | AppContext,
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


def record_agent_action(request: Request | AppContext, action: AgentActionCreate):
    service = agent_action_service(request)
    try:
        return service.record(action)
    finally:
        service.close()


def audit_reason(request: Request | AppContext, **values: str | None) -> str:
    request_id = getattr(request, "request_id", None) or getattr(getattr(request, "state", None), "request_id", None)
    pairs = [("request_id", request_id)]
    pairs.extend((key, value) for key, value in values.items())
    return ";".join(f"{key}={value}" for key, value in pairs if value)


def set_active_vault_id(request: Request | AppContext, vault_id: str) -> None:
    request.app.state.active_vault_id = vault_id
    with database(request).connect() as conn:
        with conn:
            VaultRepository(conn).set_active(vault_id)


def active_vault_id(request: Request | AppContext) -> str:
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


def active_vault_root(request: Request | AppContext) -> str:
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


class VaultServiceContainer:
    def __init__(self, request: Request | AppContext):
        self.request = request

    @property
    def db(self) -> Database:
        return database(self.request)

    @property
    def vault_id(self) -> str:
        return active_vault_id(self.request)

    @property
    def vault_root(self) -> str:
        return active_vault_root(self.request)

    def writer(self) -> SafeMarkdownWriter:
        return SafeMarkdownWriter(self.vault_root)

    def index_refresh(self, vault_id: str | None = None):
        resolved_vault_id = vault_id or self.vault_id
        return lambda _relative_path: schedule_index_refresh(self.request, resolved_vault_id)

    def memory_service(self) -> MemoryService:
        return MemoryService(
            MemoryProposalStore(self.db.path),
            self.writer(),
            index_refresh=self.index_refresh(),
        )

    def chat_auto_memory_service(self) -> ChatAutoMemoryService:
        return ChatAutoMemoryService(
            ChatAutoMemoryStore(self.db.path),
            self.writer(),
            index_refresh=self.index_refresh(),
        )

    def long_term_memory_service(self) -> LongTermMemoryService:
        extraction_model = chat_model_client(self.request, AgentId.DIARY_MEMORY_EXTRACTOR_AGENT.value)
        extraction_model_name = AgentId.DIARY_MEMORY_EXTRACTOR_AGENT.value if extraction_model is not None else None
        if extraction_model is None:
            extraction_model = chat_model_client(self.request, AgentId.SEMANTIC_ANALYSIS_AGENT.value)
            extraction_model_name = AgentId.SEMANTIC_ANALYSIS_AGENT.value if extraction_model is not None else None
        return LongTermMemoryService(
            self.writer(),
            index_refresh=self.index_refresh(),
            graph_store=MemoryGraphStore(
                self.db.path,
                graph_root=get_settings().data_dir / "memory-graph",
            ),
            extraction_model=extraction_model,
            extraction_model_name=extraction_model_name,
        )

    def wiki_service(self) -> WikiService:
        return WikiService(
            self.writer(),
            index_refresh=self.index_refresh(),
        )

    def optional_writer(self) -> SafeMarkdownWriter | None:
        try:
            return self.writer()
        except Exception:
            logger.warning("Optional markdown writer creation failed; continuing without writer", exc_info=True)
            return None


def vault_services(request: Request | AppContext) -> VaultServiceContainer:
    return VaultServiceContainer(request)


def memory_service(request: Request | AppContext) -> MemoryService:
    return vault_services(request).memory_service()


def chat_auto_memory_service(request: Request | AppContext) -> ChatAutoMemoryService:
    return vault_services(request).chat_auto_memory_service()


def diary_memory_service(request: Request | AppContext) -> DiaryMemoryService:
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


def long_term_memory_service(request: Request | AppContext) -> LongTermMemoryService:
    return vault_services(request).long_term_memory_service()


def continuity_service(request: Request | AppContext) -> ContinuityService:
    return ContinuityService(database(request).path)


async def continuity_service_dependency(request: Request) -> AsyncIterator[ContinuityService]:
    service = continuity_service(request)
    try:
        yield service
    finally:
        service.close()


def wiki_service(request: Request | AppContext) -> WikiService:
    return vault_services(request).wiki_service()


async def wiki_service_dependency(request: Request) -> AsyncIterator[WikiService]:
    yield wiki_service(request)


def wiki_workflow_service(request: Request | AppContext) -> WikiWorkflowService:
    return WikiWorkflowService(
        database(request),
        wiki_service(request),
        review_agent_id="wiki_manager_agent",
        review_model_resolver=lambda agent_id: chat_model_client(request, agent_id.value),
    )


async def wiki_workflow_service_dependency(request: Request) -> AsyncIterator[WikiWorkflowService]:
    yield wiki_workflow_service(request)


def wiki_lint_service(request: Request | AppContext) -> WikiLintService:
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


def wiki_diagnostics_queue_service(request: Request | AppContext) -> WikiDiagnosticsQueueService:
    return WikiDiagnosticsQueueService(
        database(request).path,
        vault_id=active_vault_id(request),
        vault_root=active_vault_root(request),
        wiki=None,
    )


async def wiki_diagnostics_queue_service_dependency(request: Request) -> AsyncIterator[WikiDiagnosticsQueueService]:
    service = wiki_diagnostics_queue_service(request)
    try:
        yield service
    finally:
        service.close()


def memory_graph_store(request: Request | AppContext) -> MemoryGraphStore:
    return MemoryGraphStore(
        database(request).path,
        graph_root=get_settings().data_dir / "memory-graph",
    )


def companion_consolidation_service(request: Request | AppContext) -> CompanionConsolidationService:
    return CompanionConsolidationService(
        database(request).path,
        vault_id=active_vault_id(request),
        graph_store=memory_graph_store(request),
    )


def companion_retrieval_report_store(request: Request | AppContext) -> CompanionRetrievalReportStore:
    return CompanionRetrievalReportStore(database(request).path)


def schedule_index_refresh(request: Request | AppContext, vault_id: str, *, delay_seconds: float = 0.5) -> str:
    import threading

    context = request if isinstance(request, AppContext) else app_context(request)
    timers = context.app.state.index_refresh_timers
    job_id = f"scheduled:{vault_id}"
    previous = timers.get(vault_id)
    if previous is not None:
        previous.cancel()

    def rebuild() -> None:
        try:
            retrieval_service(context).rebuild_index(vault_id)
        finally:
            timers.pop(vault_id, None)

    timer = threading.Timer(delay_seconds, rebuild)
    timer.daemon = True
    timers[vault_id] = timer
    timer.start()
    return job_id


async def memory_service_dependency(request: Request) -> AsyncIterator[MemoryService]:
    service = memory_service(request)
    try:
        yield service
    finally:
        service.close()


def task_service(request: Request | AppContext) -> TaskService:
    return TaskService(
        TaskStore(database(request).path),
        scheduler=request.app.state.reminder_scheduler,
    )


async def task_service_dependency(request: Request) -> AsyncIterator[TaskService]:
    service = task_service(request)
    try:
        yield service
    finally:
        service.close()


def settings_store(request: Request | AppContext) -> SettingsStore:
    return SettingsStore(database(request).path)


async def settings_store_dependency(request: Request) -> AsyncIterator[SettingsStore]:
    store = settings_store(request)
    try:
        yield store
    finally:
        store.close()


def agent_model_registry(request: Request | AppContext) -> AgentModelRegistry:
    return AgentModelRegistry(
        clients={
            agent_id: client
            for agent_id in AGENT_IDS
            if (client := chat_model_client(request, agent_id.value)) is not None
        }
    )


def chat_model_client(
    request: Request | AppContext,
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
