from contextlib import asynccontextmanager
import asyncio
import logging
import threading
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .api.health import router as health_router
from .api.chat import recover_interrupted_chat_runs, recover_post_reply_memory_jobs, shutdown_post_reply_tasks
from .api.services.adapters import RuntimeReminderDeliveryAdapter, production_action_lifecycle
from .api.services.factory import AppContext, expire_chat_runs
from .config import get_settings
from .errors import register_error_handlers
from .scheduler import APSchedulerReminderScheduler, ReminderSchedulerProtocol
from .services.health import component_health_from_vector_index
from .services.retrieval import RetrievalService
from .services.retrieval_factory import build_vector_index
from .services.reminder_delivery import ReminderDeliveryService
from .services.settings import initialize_settings_store
from .agents.reflection_graph import ReflectionJobManager
from .services.tasks import TaskService, TaskStore
from .services.wiki_reconciler import reconcile_all_vaults
from .storage.database import Database, MigrationRunner


_CHAT_RUN_CLEANUP_INTERVAL_SECONDS = 60
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    schema_lock = threading.Lock()
    schema_ready = False

    def ensure_schema(db: Database) -> None:
        nonlocal schema_ready
        if schema_ready:
            return
        with schema_lock:
            if schema_ready:
                return
            MigrationRunner(db).apply()
            schema_ready = True

    database = Database(settings.sqlite_path, on_path_access=ensure_schema)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ensure_app_services(app)
        app.state.reflection_jobs.recover_orphans()
        recovered_post_reply_jobs = recover_post_reply_memory_jobs(app)
        if recovered_post_reply_jobs:
            logger.info("Scheduled %s durable post-reply jobs during startup", recovered_post_reply_jobs)
        cleanup_task = asyncio.create_task(_cleanup_expired_chat_runs(app))
        scheduler = app.state.reminder_scheduler
        if isinstance(scheduler, ReminderSchedulerProtocol):
            scheduler.start(paused=True)
        store = TaskStore(database.path)
        try:
            delivery = ReminderDeliveryService(database.path)
            try:
                has_reserved_delivery = bool(delivery.list_reserved())
            finally:
                delivery.close()
            if has_reserved_delivery:
                startup_context = AppContext(app, request_id=f"sidecar-startup-{uuid4()}")
                await RuntimeReminderDeliveryAdapter(
                    startup_context,
                    production_action_lifecycle(startup_context),
                ).recover(
                    recovery_run_id=startup_context.request_id or "sidecar-startup",
                    reason="sidecar_startup",
                )
            TaskService(
                store,
                scheduler=scheduler,
            ).recover_reminders()
        finally:
            store.close()
        if isinstance(scheduler, ReminderSchedulerProtocol):
            scheduler.resume()
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            await shutdown_post_reply_tasks()
            await app.state.reflection_jobs.shutdown()
            expire_chat_runs(AppContext(app), force=True)
            if isinstance(scheduler, ReminderSchedulerProtocol):
                scheduler.shutdown()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "file://",
        ],
        allow_origin_regex=r"^file://.*$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "Idempotency-Key"],
    )
    app.state.database = database
    app.state.ensure_schema = ensure_schema
    app.state.retrieval_service = None
    app.state.component_health = {}
    app.state.index_refresh_timers = {}
    app.state.services_initialized = False
    app.state.services_lock = threading.Lock()
    app.state.reminder_scheduler = APSchedulerReminderScheduler(database.path)
    app.state.active_vault_id = None
    app.state.chat_runs = {}
    app.state.chat_runs_expires_at = {}
    app.state.chat_runs_lock = threading.Lock()
    app.state.reflection_jobs = ReflectionJobManager()

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        ensure_app_services(request.app)
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    register_error_handlers(app)
    app.include_router(health_router, prefix="/api")
    app.include_router(api_router)
    return app


async def _cleanup_expired_chat_runs(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(_CHAT_RUN_CLEANUP_INTERVAL_SECONDS)
        expire_chat_runs(AppContext(app))


def ensure_app_services(app: FastAPI) -> None:
    if getattr(app.state, "services_initialized", False):
        return
    lock = getattr(app.state, "services_lock", None)
    if lock is None:
        lock = threading.Lock()
        app.state.services_lock = lock
    with lock:
        if getattr(app.state, "services_initialized", False):
            return
        settings = get_settings()
        database = app.state.database
        ensure_schema = getattr(app.state, "ensure_schema", None)
        if ensure_schema is None:
            MigrationRunner(database).apply()
        else:
            ensure_schema(database)
        initialize_settings_store(database)
        try:
            app.state.wiki_reconcile_reports = reconcile_all_vaults(database.path)
        except Exception:
            logger.warning("Wiki binding reconciliation failed; derived graph reads stay on SQLite", exc_info=True)
            app.state.wiki_reconcile_reports = ()
        recover_interrupted_chat_runs(database)
        vector_index = build_vector_index(database.path, settings)
        retrieval_service = RetrievalService(database, vector_index=vector_index)
        app.state.retrieval_service = retrieval_service
        app.state.component_health["vector_index"] = component_health_from_vector_index(vector_index)
        app.state.services_initialized = True


app = create_app()
