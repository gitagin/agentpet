from pathlib import Path, PureWindowsPath

# [internal] /vaults/bind 当前无桌面端 UI 调用方（UI 走 /vaults/init）；保留供脚本/测试。
from fastapi import APIRouter, Request, status

from ..errors import AppError
from ..models.enums import NoteStatus
from ..models.api import VaultBindRequest, VaultBindResponse, VaultIndexResponse, VaultStatusResponse
from ..repositories.storage import VaultRepository
from .wiring import (
    active_vault_id,
    audit_reason,
    database,
    ensure_vault_path,
    record_audit,
    retrieval_service,
    set_active_vault_id,
)

router = APIRouter(prefix="/vaults", tags=["vaults"])


def _safe_root_path_label(root_path: str) -> str:
    root = Path(root_path)
    name = root.name or str(root)
    windows_path = PureWindowsPath(root_path)
    if windows_path.drive:
        return f"{windows_path.drive}\\...\\{name}"
    return f".../{name}"


def _read_vault_summary(conn, vault_id: str) -> dict[str, int | str | None]:
    active_note_status = NoteStatus.DELETED.value
    counts = conn.execute(
        """
        SELECT
            COUNT(*) AS markdown_count,
            SUM(CASE WHEN relative_path LIKE 'Wiki/%' THEN 1 ELSE 0 END) AS wiki_page_count,
            SUM(CASE WHEN relative_path LIKE 'Memories/Daily/%' THEN 1 ELSE 0 END) AS diary_page_count,
            MAX(indexed_at) AS latest_note_indexed_at
        FROM notes
        WHERE vault_id = ? AND status != ?
        """,
        (vault_id, active_note_status),
    ).fetchone()
    latest_job = conn.execute(
        """
        SELECT MAX(updated_at) AS latest_job_indexed_at
        FROM index_jobs
        WHERE vault_id = ?
        """,
        (vault_id,),
    ).fetchone()
    latest_indexed_at = (latest_job and latest_job["latest_job_indexed_at"]) or (
        counts and counts["latest_note_indexed_at"]
    )
    return {
        "latest_indexed_at": latest_indexed_at,
        "markdown_count": int(counts["markdown_count"] or 0) if counts else 0,
        "wiki_page_count": int(counts["wiki_page_count"] or 0) if counts else 0,
        "diary_page_count": int(counts["diary_page_count"] or 0) if counts else 0,
    }


@router.get("/status", response_model=VaultStatusResponse)
async def get_vault_status(request: Request) -> VaultStatusResponse:
    try:
        vault_id = active_vault_id(request)
    except AppError as exc:
        if exc.code == "vault_not_configured":
            return VaultStatusResponse(configured=False)
        raise
    with database(request).session() as conn:
        vault = VaultRepository(conn).get(vault_id)
        summary = _read_vault_summary(conn, vault_id)
    root_path = str(vault["root_path"])
    return VaultStatusResponse(
        configured=True,
        active_vault_id=vault_id,
        root_path=root_path,
        root_path_label=_safe_root_path_label(root_path),
        name=str(vault["name"]),
        **summary,
    )


@router.post("/init", response_model=VaultBindResponse)
async def init_vault(bind_request: VaultBindRequest, request: Request) -> VaultBindResponse:
    if not bind_request.confirmed:
        record_audit(
            request,
            action="vault.bind",
            result="denied",
            target_path=bind_request.path,
            reason=audit_reason(request, code="vault_bind_confirmation_required"),
        )
        raise AppError(
            code="vault_bind_confirmation_required",
            message="绑定知识库目录前需要显式确认。",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"path": bind_request.path},
        )
    try:
        root = ensure_vault_path(bind_request.path, create_if_missing=bind_request.create_if_missing)
    except AppError as exc:
        record_audit(
            request,
            action="vault.bind",
            result="denied",
            target_path=bind_request.path,
            reason=audit_reason(request, code=exc.code),
        )
        raise
    try:
        vault_id = retrieval_service(request).bind_vault(str(root))
    except Exception as exc:
        record_audit(
            request,
            action="vault.bind",
            result="failed",
            target_path=str(root),
            reason=audit_reason(request, code=exc.__class__.__name__),
        )
        raise AppError(
            code="vault_bind_failed",
            message="知识库绑定失败。",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"path": str(root), "error": str(exc)},
        ) from exc
    set_active_vault_id(request, vault_id)
    record_audit(
        request,
        action="vault.bind",
        result="success",
        target_path=str(root),
        reason=audit_reason(request, vault_id=vault_id),
    )
    with database(request).session() as conn:
        vault = VaultRepository(conn).get(vault_id)
    return VaultBindResponse(
        vault_id=vault_id,
        status="bound",
        root_path=str(vault["root_path"]),
        name=str(vault["name"]),
    )


@router.post("/bind", response_model=VaultBindResponse)
async def bind_vault(bind_request: VaultBindRequest, request: Request) -> VaultBindResponse:
    return await init_vault(bind_request, request)


@router.post("/{vault_id}/index", response_model=VaultIndexResponse)
async def rebuild_vault_index(vault_id: str, request: Request) -> VaultIndexResponse:
    try:
        result = retrieval_service(request).rebuild_index(vault_id)
    except KeyError as exc:
        raise AppError(
            code="vault_not_found",
            message="未找到知识库。",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"vault_id": vault_id},
        ) from exc
    return VaultIndexResponse(
        index_job_id=result.index_job_id,
        status=result.status,
        files_seen=result.files_seen,
        files_indexed=result.files_indexed,
    )
