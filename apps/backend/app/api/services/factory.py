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
from app.models.common import new_id
from app.models.enums import AgentId, AgentRunStatus, MessageRole, MessageStatus
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
from app.services.memory_candidates import MemoryCandidateStore
from app.services.memory_consolidation import MemoryConsolidationService
from app.services.memory_graph import MemoryGraphStore
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_permissions import MemoryActivationEventRecorder
from app.services.prompt_profile_provider import PromptProfileProvider
from app.services.retrieval import RetrievalService
from app.services.retrieval_factory import build_vector_index
from app.services.retrospectives import RetrospectiveService
from app.services.settings import SettingsStore
from app.services.tasks import TaskService, TaskStore
from app.services.wiki import WikiService
from app.services.wiki_lint import WikiDiagnosticsQueueService, WikiLintService
from app.services.wiki_workflows import WikiWorkflowService
from app.storage.database import Database
from app.agents.state import AgentState
from app.utils.time import utc_now_iso


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


def _chat_runs_lock(request: Request | AppContext) -> threading.Lock:
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
    expired_state = None
    with _chat_runs_lock(request):
        expires_at = request.app.state.chat_runs_expires_at.get(agent_run_id)
        if expires_at is not None and expires_at <= time.monotonic():
            expired_state = request.app.state.chat_runs.pop(agent_run_id, None)
            request.app.state.chat_runs_expires_at.pop(agent_run_id, None)
        else:
            return request.app.state.chat_runs.get(agent_run_id)
    if expired_state is not None:
        finalize_unstreamed_chat_run(request, expired_state)
    return None


def claim_chat_run(request: Request, state: AgentState) -> bool:
    with _chat_runs_lock(request):
        current = request.app.state.chat_runs.get(state.agent_run_id)
        if current is not state:
            return False
        request.app.state.chat_runs.pop(state.agent_run_id, None)
        request.app.state.chat_runs_expires_at.pop(state.agent_run_id, None)
        return True


def expire_chat_runs(request: Request | AppContext, *, force: bool = False) -> int:
    expired_states: list[AgentState] = []
    now = time.monotonic()
    with _chat_runs_lock(request):
        runs = request.app.state.chat_runs
        expires_at = request.app.state.chat_runs_expires_at
        for agent_run_id, state in list(runs.items()):
            expiry = expires_at.get(agent_run_id)
            if not force and (expiry is None or expiry > now):
                continue
            expired_states.append(state)
            runs.pop(agent_run_id, None)
            expires_at.pop(agent_run_id, None)
    error_code = "stream_not_started_or_shutdown" if force else "stream_not_started_or_expired"
    for state in expired_states:
        finalize_unstreamed_chat_run(request, state, error_code=error_code)
    return len(expired_states)


def finalize_unstreamed_chat_run(
    request: Request | AppContext,
    state: AgentState,
    *,
    error_code: str = "stream_not_started_or_expired",
) -> bool:
    now = utc_now_iso()
    with database(request).session() as conn:
        with conn:
            row = conn.execute(
                "SELECT status, assistant_message_id FROM agent_runs WHERE id = ?",
                (state.agent_run_id,),
            ).fetchone()
            if row is None or row["status"] != AgentRunStatus.RUNNING.value:
                return False
            assistant_message_id = row["assistant_message_id"] or new_id()
            if row["assistant_message_id"]:
                conn.execute(
                    "UPDATE messages SET status = ?, updated_at = ? WHERE id = ?",
                    (MessageStatus.CANCELLED.value, now, assistant_message_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assistant_message_id,
                        state.conversation_id,
                        MessageRole.ASSISTANT.value,
                        "",
                        MessageStatus.CANCELLED.value,
                        now,
                        now,
                    ),
                )
            conn.execute(
                """
                UPDATE agent_runs
                SET assistant_message_id = ?, status = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    assistant_message_id,
                    AgentRunStatus.CANCELLED.value,
                    error_code,
                    "回复流未在有效期内启动，运行已安全取消。",
                    now,
                    state.agent_run_id,
                    AgentRunStatus.RUNNING.value,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, state.conversation_id),
            )
    return True


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
    with database(request).session() as conn:
        with conn:
            VaultRepository(conn).set_active(vault_id)


def active_vault_id(request: Request | AppContext) -> str:
    current = getattr(request.app.state, "active_vault_id", None)
    if current:
        return str(current)
    with database(request).session() as conn:
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
    with database(request).session() as conn:
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
    """已废弃：默认目录改为按需创建，不再在绑定 vault 时预建。

    历史行为会在 vault 根目录预建 Inbox/、Memories/ 与 Inbox/Pending Memories.md，
    用户删除后重新绑定又会被重建。SafeMarkdownWriter.write 写入时会自动创建
    父目录，因此这些目录/文件只会在真正需要时出现，删除后不会被自动重建。
    """
    del root  # 保留签名兼容调用方，语义已废弃


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
        extraction_model = chat_model_client(self.request, AgentId.REFLECTION_AGENT.value)
        extraction_model_name = AgentId.REFLECTION_AGENT.value if extraction_model is not None else None
        if extraction_model is None:
            extraction_model = chat_model_client(self.request, AgentId.SEMANTIC_ANALYSIS_AGENT.value)
            extraction_model_name = AgentId.SEMANTIC_ANALYSIS_AGENT.value if extraction_model is not None else None
        return LongTermMemoryService(
            self.writer(),
            index_refresh=self.index_refresh(),
            graph_store=MemoryEntityGraphStore(
                self.db.path,
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
        except AppError as error:
            if error.code == "vault_not_configured":
                logger.info("Optional markdown writer unavailable because no active vault is configured.")
                return None
            logger.warning("Optional markdown writer creation failed; continuing without writer", exc_info=True)
            return None
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
    extractor_agent = chat_model_client(request, AgentId.REFLECTION_AGENT.value)
    extraction_model = AgentId.REFLECTION_AGENT.value if extractor_agent is not None else None
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


def memory_consolidation_service(request: Request | AppContext) -> MemoryConsolidationService:
    store = MemoryCandidateStore(database(request).path)
    return MemoryConsolidationService(
        store,
        entity_graph=MemoryEntityGraphStore(store.conn),
    )


def memory_activation_recorder(request: Request | AppContext) -> MemoryActivationEventRecorder:
    return MemoryActivationEventRecorder(database(request).path)


def prompt_profile_provider(request: Request | AppContext) -> PromptProfileProvider:
    return PromptProfileProvider(database(request).path)


def memory_lifecycle_service(request: Request | AppContext) -> MemoryLifecycleService:
    return MemoryLifecycleService(database(request).path)


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
        review_agent_id=AgentId.ACTION_AGENT,
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
    return MemoryGraphStore(database(request).path)


def memory_entity_graph_store(request: Request | AppContext) -> MemoryEntityGraphStore:
    return MemoryEntityGraphStore(database(request).path)


def companion_consolidation_service(request: Request | AppContext) -> CompanionConsolidationService:
    return CompanionConsolidationService(
        database(request).path,
        vault_id=active_vault_id(request),
        graph_store=memory_entity_graph_store(request),
    )


def companion_retrieval_report_store(request: Request | AppContext) -> CompanionRetrievalReportStore:
    return CompanionRetrievalReportStore(database(request).path)


def retrospective_service(request: Request | AppContext) -> RetrospectiveService:
    services = vault_services(request)
    writer = services.optional_writer()
    return RetrospectiveService(
        database(request).path,
        vault_id=services.vault_id,
        writer=writer,
        index_refresh=services.index_refresh() if writer is not None else None,
    )


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
    return SettingsStore(database(request))


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
        use_agent_config = agent_id is not None and store.is_agent_model_enabled(agent_id)
        if use_agent_config:
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
        else:
            status_value = store.get_model_key_status()
            model_config = store.get_model_config(
                default_provider=status_value.provider or "openai-compatible",
                default_base_url=settings.model_base_url,
                default_model=settings.chat_model,
            )
        if not status_value.configured:
            return None
        provider = model_config.provider.strip().lower()
        if provider not in {"openai", "openai-compatible", "openai_compatible"}:
            return None
        if use_agent_config:
            api_key = store.get_agent_model_key(
                agent_id=agent_id,
                provider=model_config.provider,
            )
            if not api_key and status_value.provider:
                api_key = store.get_agent_model_key(
                    agent_id=agent_id,
                    provider=status_value.provider,
                )
        else:
            api_key = store.get_model_key(model_config.provider)
            if not api_key and status_value.provider:
                api_key = store.get_model_key(status_value.provider)
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
