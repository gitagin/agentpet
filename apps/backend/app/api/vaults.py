from fastapi import APIRouter, Request, status

from ..errors import AppError
from ..models.api import VaultBindRequest, VaultBindResponse, VaultIndexResponse, VaultStatusResponse
from ..repositories.storage import VaultRepository
from .wiring import (
    active_vault_id,
    audit_reason,
    database,
    ensure_default_vault_content,
    ensure_vault_path,
    record_audit,
    retrieval_service,
    set_active_vault_id,
)

router = APIRouter(prefix="/vaults", tags=["vaults"])


@router.get("/status", response_model=VaultStatusResponse)
async def get_vault_status(request: Request) -> VaultStatusResponse:
    try:
        vault_id = active_vault_id(request)
    except AppError as exc:
        if exc.code == "vault_not_configured":
            return VaultStatusResponse(configured=False)
        raise
    with database(request).connect() as conn:
        vault = VaultRepository(conn).get(vault_id)
    return VaultStatusResponse(
        configured=True,
        active_vault_id=vault_id,
        root_path=str(vault["root_path"]),
        name=str(vault["name"]),
    )


@router.post("/init", response_model=VaultBindResponse)
async def init_vault(bind_request: VaultBindRequest, request: Request) -> VaultBindResponse:
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
    if bind_request.create_if_missing:
        ensure_default_vault_content(root)
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
    with database(request).connect() as conn:
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
