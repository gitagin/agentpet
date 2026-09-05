"""长期记忆候选（proposal）端点。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from ...errors import AppError
from ...models.api import (
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    MemoryProposalListResponse,
    MemoryProposalResponse,
    RejectProposalRequest,
)
from ...services.memory import MemoryService
from ...services.memory_policy import evaluate_memory_content
from ..services.adapters import RuntimeMemoryAdapter
from ..services.factory import memory_service
from ..wiring import (
    audit_reason,
    map_memory_error,
    memory_service_dependency,
    production_action_lifecycle,
    record_audit,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/proposals", response_model=MemoryProposalResponse)
async def create_memory_proposal(
    proposal_request: MemoryProposalCreateRequest,
    request: Request,
) -> MemoryProposalResponse:
    policy = evaluate_memory_content(proposal_request.content)
    if not policy.allowed:
        record_audit(
            request,
            action="memory.proposal.create",
            result="denied",
            target_path=proposal_request.target_path,
            reason=audit_reason(request, code="sensitive_memory_rejected", policy=policy.reason),
        )
        raise AppError(
            code="sensitive_memory_rejected",
            message="疑似密钥或凭据的敏感内容不能保存为长期记忆。",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"reason": policy.reason or "sensitive_content"},
        )
    # Validate the target before creating a lifecycle claim.  Invalid input
    # has no business effect and should retain the writer's precise, actionable
    # error instead of becoming a generic policy-denied receipt.
    service = memory_service(request)
    try:
        service.writer.resolve_markdown_path(proposal_request.target_path)
    except Exception as exc:
        record_audit(
            request,
            action="memory.proposal.create",
            result="denied",
            target_path=proposal_request.target_path,
            reason=audit_reason(request, code=exc.__class__.__name__),
        )
        raise map_memory_error(exc) from exc
    finally:
        service.close()
    try:
        action = await RuntimeMemoryAdapter(
            request,
            production_action_lifecycle(request),
        ).create_proposal(proposal_request)
    except Exception as exc:
        record_audit(
            request,
            action="memory.proposal.create",
            result="failed",
            target_path=proposal_request.target_path,
            reason=audit_reason(request, code=exc.__class__.__name__),
        )
        raise map_memory_error(exc) from exc
    record_audit(
        request,
        action="memory.proposal.create",
        result="success",
        target_path=proposal_request.target_path,
        reason=audit_reason(request, proposal_id=action.proposal_id),
    )
    target_content_hash: str | None = None
    service = memory_service(request)
    try:
        target_content_hash = service.store.get(action.proposal_id).target_content_hash
    except Exception:
        target_content_hash = None
    finally:
        service.close()
    return MemoryProposalResponse(
        proposal_id=action.proposal_id,
        status=action.status,
        preview_markdown=proposal_request.content,
        target_path=proposal_request.target_path,
        type=proposal_request.type,
        content=proposal_request.content,
        target_content_hash=target_content_hash,
    )


@router.get("/proposals", response_model=MemoryProposalListResponse)
async def list_memory_proposals(
    service: MemoryService = Depends(memory_service_dependency),
) -> MemoryProposalListResponse:
    proposals = service.list_pending()
    return MemoryProposalListResponse(
        proposals=[
            MemoryProposalResponse(
                proposal_id=proposal.id,
                status=proposal.status.value,
                preview_markdown=proposal.content,
                target_path=proposal.target_path,
                type=proposal.type,
                content=proposal.content,
            )
            for proposal in proposals
        ]
    )


@router.post("/proposals/{proposal_id}/confirm", response_model=MemoryProposalActionResponse)
async def confirm_memory_proposal(
    proposal_id: str,
    request: Request,
) -> MemoryProposalActionResponse:
    try:
        action = await RuntimeMemoryAdapter(
            request,
            production_action_lifecycle(request),
        ).confirm_proposal(proposal_id)
    except Exception as exc:
        record_audit(
            request,
            action="memory.proposal.confirm",
            result="failed",
            reason=audit_reason(request, proposal_id=proposal_id, code=exc.__class__.__name__),
        )
        raise map_memory_error(exc) from exc
    record_audit(
        request,
        action="memory.proposal.confirm",
        result="success",
        target_path=action.written_path,
        reason=audit_reason(request, proposal_id=action.proposal_id, index_job_id=action.index_job_id),
    )
    return action


@router.post("/proposals/{proposal_id}/reject", response_model=MemoryProposalActionResponse)
async def reject_memory_proposal(
    proposal_id: str,
    reject_request: RejectProposalRequest,
    request: Request,
) -> MemoryProposalActionResponse:
    try:
        action = await RuntimeMemoryAdapter(
            request,
            production_action_lifecycle(request),
        ).reject_proposal(proposal_id, reject_request.reason)
    except Exception as exc:
        record_audit(
            request,
            action="memory.proposal.reject",
            result="failed",
            reason=audit_reason(request, proposal_id=proposal_id, code=exc.__class__.__name__),
        )
        raise map_memory_error(exc) from exc
    record_audit(
        request,
        action="memory.proposal.reject",
        result="success",
        reason=audit_reason(request, proposal_id=action.proposal_id),
    )
    return action
