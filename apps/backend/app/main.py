from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .api.health import router as health_router
from .config import get_settings
from .errors import register_error_handlers
from .scheduler import InMemoryReminderScheduler
from .services.audit import AuditLogService
from .services.retrieval import RetrievalService
from .services.retrieval_factory import build_vector_index
from .services.tasks import TaskService, TaskStore
from .storage.database import Database


def create_app() -> FastAPI:
    settings = get_settings()
    database = Database(settings.sqlite_path)
    retrieval_service = RetrievalService(database, vector_index=build_vector_index(database.path, settings))
    retrieval_service.initialize()

    def mark_reminder_triggered(reminder_id: str) -> None:
        store = TaskStore(database.path)
        try:
            TaskService(store).mark_reminder_triggered(reminder_id)
            _record_scheduler_audit(database.path, "reminder.triggered", "success", reminder_id)
        finally:
            store.close()

    def mark_reminder_failed(reminder_id: str, exc: Exception) -> None:
        store = TaskStore(database.path)
        try:
            TaskService(store).mark_reminder_failed(reminder_id, str(exc) or "提醒触发失败")
            _record_scheduler_audit(
                database.path,
                "reminder.failed",
                "failed",
                reminder_id,
                code=exc.__class__.__name__,
            )
        finally:
            store.close()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = TaskStore(database.path)
        try:
            TaskService(
                store,
                scheduler=app.state.reminder_scheduler,
            ).recover_reminders()
        finally:
            store.close()
        try:
            yield
        finally:
            scheduler = getattr(app.state, "reminder_scheduler", None)
            if hasattr(scheduler, "shutdown"):
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
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
    )
    app.state.database = database
    app.state.retrieval_service = retrieval_service
    app.state.reminder_scheduler = InMemoryReminderScheduler(
        on_trigger=mark_reminder_triggered,
        on_error=mark_reminder_failed,
    )
    app.state.active_vault_id = None
    app.state.chat_runs = {}

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    register_error_handlers(app)
    app.include_router(health_router, prefix="/api")
    app.include_router(api_router)
    return app


def _record_scheduler_audit(
    db_path,
    action: str,
    result: str,
    reminder_id: str,
    *,
    code: str | None = None,
) -> None:
    audit = AuditLogService(db_path)
    try:
        reason = f"reminder_id={reminder_id}"
        if code:
            reason = f"{reason};code={code}"
        audit.record(
            actor="scheduler",
            action=action,
            result=result,
            reason=reason,
        )
    finally:
        audit.close()


app = create_app()
