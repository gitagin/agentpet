from fastapi import APIRouter, Query, Request, status

from ..errors import AppError
from ..models.api import (
    ReflectionProposalActionResponse,
    ReflectionProposalListResponse,
    ReflectionProposalResponse,
    RejectProposalRequest,
)
from ..services.reflection_proposals import (
    ATTENTION_STATUSES,
    ReflectionProposalNotFoundError,
    ReflectionProposalRecord,
    ReflectionProposalStateError,
)
from .services.adapters import RuntimeReflectionAdapter
from .wiring import audit_reason, production_action_lifecycle, record_audit

router = APIRouter(prefix="/reflection", tags=["reflection"])

_QUEUE_FILTER = "attention"
_ALL_STATUSES_FILTER = "all"


def _status_filter(status: str | None) -> tuple[str, ...] | None:
    """Translate the queue's query value into the status set to return.

    ``attention`` is the review queue as the user meets it: proposals still
    awaiting a decision, plus the ones the system failed to apply and can still
    retry.  Anything else is an exact status, and ``all`` means no filter.
    """
    if status == _ALL_STATUSES_FILTER:
        return None
    if status in (None, _QUEUE_FILTER):
        return ATTENTION_STATUSES
    return (status,)


@router.get("/proposals", response_model=ReflectionProposalListResponse)
async def list_reflection_proposals(
    request: Request,
    status_filter: str | None = Query(default="pending", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> ReflectionProposalListResponse:
    proposals = RuntimeReflectionAdapter(request).list_proposals(
        statuses=_status_filter(status_filter),
        limit=limit,
    )
    record_audit(
        request,
        action="reflection.proposal.list",
        result="success",
        reason=audit_reason(request, proposal_count=str(len(proposals))),
    )
    return ReflectionProposalListResponse(
        proposals=[_proposal_response(proposal) for proposal in proposals]
    )


@router.post("/proposals/{proposal_id}/confirm", response_model=ReflectionProposalActionResponse)
async def confirm_reflection_proposal(
    proposal_id: str,
    request: Request,
) -> ReflectionProposalActionResponse:
    try:
        action = await RuntimeReflectionAdapter(
            request,
            production_action_lifecycle(request),
        ).confirm_proposal(proposal_id)
    except Exception as exc:
        record_audit(
            request,
            action="reflection.proposal.confirm",
            result="failed",
            reason=audit_reason(request, proposal_id=proposal_id, code=exc.__class__.__name__),
        )
        raise _map_reflection_error(exc) from exc
    record_audit(
        request,
        action="reflection.proposal.confirm",
        result="success",
        reason=audit_reason(request, proposal_id=action.proposal_id),
    )
    return action


@router.post("/proposals/{proposal_id}/reject", response_model=ReflectionProposalActionResponse)
async def reject_reflection_proposal(
    proposal_id: str,
    reject_request: RejectProposalRequest,
    request: Request,
) -> ReflectionProposalActionResponse:
    try:
        action = await RuntimeReflectionAdapter(
            request,
            production_action_lifecycle(request),
        ).reject_proposal(proposal_id, reject_request.reason)
    except Exception as exc:
        record_audit(
            request,
            action="reflection.proposal.reject",
            result="failed",
            reason=audit_reason(request, proposal_id=proposal_id, code=exc.__class__.__name__),
        )
        raise _map_reflection_error(exc) from exc
    record_audit(
        request,
        action="reflection.proposal.reject",
        result="success",
        reason=audit_reason(request, proposal_id=action.proposal_id),
    )
    return action


def _proposal_response(proposal: ReflectionProposalRecord) -> ReflectionProposalResponse:
    return ReflectionProposalResponse(
        proposal_id=proposal.id,
        proposal_kind=proposal.proposal_kind,
        action_type=proposal.action_type,
        content=proposal.content,
        confidence=proposal.confidence,
        reversible=proposal.reversible,
        status=proposal.status,
        target_ref=proposal.target_ref,
        rejected_reason=proposal.rejected_reason,
        error=proposal.error,
        applied_ref=proposal.applied_ref,
        source_conversation_id=proposal.source_conversation_id,
        source_message_id=proposal.source_message_id,
        agent_run_id=proposal.agent_run_id,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


def _map_reflection_error(exc: Exception) -> AppError:
    if isinstance(exc, ReflectionProposalNotFoundError):
        return AppError(
            "reflection_proposal_not_found",
            "未找到反思建议。",
            status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exc, ReflectionProposalStateError):
        return AppError(
            "reflection_proposal_state_conflict",
            str(exc),
            status.HTTP_409_CONFLICT,
        )
    return AppError(
        "reflection_service_error",
        "反思建议处理失败。",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
