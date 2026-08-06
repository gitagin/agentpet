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
from ...services.agent_actions import AgentActionCreate
from ...services.memory import MemoryService
from ...services.memory_policy import evaluate_memory_content
from ..wiring import (
    audit_reason,
    map_memory_error,
    memory_service_dependency,
    record_agent_action,
    record_audit,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/proposals", response_model=MemoryProposalResponse)
async def create_memory_proposal(
    proposal_request: MemoryProposalCreateRequest,
    request: Request,
    service: MemoryService = Depends(memory_service_dependency),
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
    try:
        proposal = service.create_proposal(
            type=proposal_request.type,
            content=proposal_request.content,
            target_path=proposal_request.target_path,
            source_message_id=proposal_request.source_message_id,
        )
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
        target_path=proposal.target_path,
        reason=audit_reason(request, proposal_id=proposal.id),
    )
    record_agent_action(
        request,
        AgentActionCreate(
            action_type="memory.proposal.ask",
            title="需要确认长期记忆",
            summary=proposal.content[:180],
            source_message_id=proposal.source_message_id,
            risk_tier="medium",
            decision="ask",
            status="pending",
            target_paths=(proposal.target_path,),
            metadata={"proposal_id": proposal.id, "proposal_type": proposal.type.value},
            reversible=False,
        ),
    )
    return MemoryProposalResponse(
        proposal_id=proposal.id,
        status=proposal.status.value,
        preview_markdown=proposal.content,
        target_path=proposal.target_path,
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
            )
            for proposal in proposals
        ]
    )


@router.post("/proposals/{proposal_id}/confirm", response_model=MemoryProposalActionResponse)
async def confirm_memory_proposal(
    proposal_id: str,
    request: Request,
    service: MemoryService = Depends(memory_service_dependency),
) -> MemoryProposalActionResponse:
    try:
        result = service.confirm_proposal(proposal_id)
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
        target_path=result.written_path,
        reason=audit_reason(request, proposal_id=result.proposal_id, index_job_id=result.index_job_id),
    )
    action = record_agent_action(
        request,
        AgentActionCreate(
            action_type="memory.proposal.confirm",
            title="已写入长期记忆",
            summary=result.written_path or "",
            risk_tier="medium",
            decision="ask",
            status="completed",
            target_paths=tuple([result.written_path] if result.written_path else []),
            metadata={"proposal_id": result.proposal_id, "index_job_id": result.index_job_id},
            reversible=False,
        ),
    )
    return MemoryProposalActionResponse(
        proposal_id=result.proposal_id,
        status=result.status.value,
        written_path=result.written_path,
        index_job_id=result.index_job_id,
        action_id=action.action_id,
    )


@router.post("/proposals/{proposal_id}/reject", response_model=MemoryProposalActionResponse)
async def reject_memory_proposal(
    proposal_id: str,
    reject_request: RejectProposalRequest,
    request: Request,
    service: MemoryService = Depends(memory_service_dependency),
) -> MemoryProposalActionResponse:
    try:
        proposal = service.reject_proposal(proposal_id, reject_request.reason)
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
        target_path=proposal.target_path,
        reason=audit_reason(request, proposal_id=proposal.id),
    )
    action = record_agent_action(
        request,
        AgentActionCreate(
            action_type="memory.proposal.reject",
            title="已取消长期记忆候选",
            summary=proposal.rejected_reason or "",
            risk_tier="low",
            decision="auto",
            status="completed",
            target_paths=(proposal.target_path,),
            metadata={"proposal_id": proposal.id},
            reversible=False,
        ),
    )
    return MemoryProposalActionResponse(
        proposal_id=proposal.id,
        status=proposal.status.value,
        action_id=action.action_id,
    )
