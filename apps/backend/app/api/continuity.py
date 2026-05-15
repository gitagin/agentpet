from fastapi import APIRouter, Depends, Request, status

from ..errors import AppError
from ..models.api import (
    ContinuityProposalActionResponse,
    ContinuityProposalListResponse,
    ContinuityProposalResponse,
    ContinuityStateItem,
    ContinuityStateResponse,
    RejectProposalRequest,
)
from ..services.continuity import (
    ContinuityProposalNotFoundError,
    ContinuityProposalStateError,
    ContinuityService,
)
from .wiring import audit_reason, continuity_service_dependency, record_audit

router = APIRouter(prefix="/continuity", tags=["continuity"])


@router.get("/state", response_model=ContinuityStateResponse)
async def get_continuity_state(
    request: Request,
    service: ContinuityService = Depends(continuity_service_dependency),
) -> ContinuityStateResponse:
    items = service.get_state_items()
    record_audit(
        request,
        action="continuity.state.read",
        result="success",
        reason=audit_reason(request, item_count=str(len(items))),
    )
    return _state_response(items)


@router.get("/proposals", response_model=ContinuityProposalListResponse)
async def list_continuity_proposals(
    request: Request,
    service: ContinuityService = Depends(continuity_service_dependency),
) -> ContinuityProposalListResponse:
    proposals = service.list_pending()
    record_audit(
        request,
        action="continuity.proposal.list",
        result="success",
        reason=audit_reason(request, proposal_count=str(len(proposals))),
    )
    return ContinuityProposalListResponse(
        proposals=[_proposal_response(proposal) for proposal in proposals]
    )


@router.post("/proposals/{proposal_id}/confirm", response_model=ContinuityProposalActionResponse)
async def confirm_continuity_proposal(
    proposal_id: str,
    request: Request,
    service: ContinuityService = Depends(continuity_service_dependency),
) -> ContinuityProposalActionResponse:
    try:
        proposal = service.confirm_proposal(proposal_id)
    except Exception as exc:
        record_audit(
            request,
            action="continuity.proposal.confirm",
            result="failed",
            reason=audit_reason(request, proposal_id=proposal_id, code=exc.__class__.__name__),
        )
        raise _map_continuity_error(exc) from exc
    record_audit(
        request,
        action="continuity.proposal.confirm",
        result="success",
        reason=audit_reason(request, proposal_id=proposal.id, kind=proposal.kind),
    )
    return ContinuityProposalActionResponse(proposal_id=proposal.id, status=proposal.status)


@router.post("/proposals/{proposal_id}/reject", response_model=ContinuityProposalActionResponse)
async def reject_continuity_proposal(
    proposal_id: str,
    reject_request: RejectProposalRequest,
    request: Request,
    service: ContinuityService = Depends(continuity_service_dependency),
) -> ContinuityProposalActionResponse:
    try:
        proposal = service.reject_proposal(proposal_id, reject_request.reason)
    except Exception as exc:
        record_audit(
            request,
            action="continuity.proposal.reject",
            result="failed",
            reason=audit_reason(request, proposal_id=proposal_id, code=exc.__class__.__name__),
        )
        raise _map_continuity_error(exc) from exc
    record_audit(
        request,
        action="continuity.proposal.reject",
        result="success",
        reason=audit_reason(request, proposal_id=proposal.id, kind=proposal.kind),
    )
    return ContinuityProposalActionResponse(proposal_id=proposal.id, status=proposal.status)


def _proposal_response(proposal) -> ContinuityProposalResponse:
    return ContinuityProposalResponse(
        proposal_id=proposal.id,
        kind=proposal.kind,
        summary=proposal.summary,
        evidence=proposal.evidence,
        confidence=proposal.confidence,
        source_conversation_id=proposal.source_conversation_id,
        source_message_id=proposal.source_message_id,
        agent_run_id=proposal.agent_run_id,
        status=proposal.status,
        rejected_reason=proposal.rejected_reason,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


def _state_response(items) -> ContinuityStateResponse:
    by_key = {item.state_key: item for item in items}
    updated_at = max((item.updated_at for item in items), default=None)
    return ContinuityStateResponse(
        identity_traits=_value(by_key, "identity_traits"),
        relationship_summary=_value(by_key, "relationship_summary"),
        current_mood=_value(by_key, "current_mood"),
        mood_momentum=_value(by_key, "mood_momentum"),
        energy_level=_value(by_key, "energy_level"),
        unresolved_threads=_value(by_key, "unresolved_threads"),
        recent_emotional_signals=_value(by_key, "recent_emotional_signals"),
        updated_at=updated_at,
        items=[
            ContinuityStateItem(
                state_key=item.state_key,
                value=item.value,
                confidence=item.confidence,
                source_proposal_id=item.source_proposal_id,
                source_conversation_id=item.source_conversation_id,
                source_message_id=item.source_message_id,
                agent_run_id=item.agent_run_id,
                updated_at=item.updated_at,
            )
            for item in items
        ],
    )


def _value(items: dict, key: str) -> str | None:
    item = items.get(key)
    return item.value if item is not None else None


def _map_continuity_error(exc: Exception) -> AppError:
    if isinstance(exc, ContinuityProposalNotFoundError):
        return AppError(
            "continuity_proposal_not_found",
            "未找到连续性提案。",
            status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exc, ContinuityProposalStateError):
        return AppError(
            "continuity_proposal_state_conflict",
            str(exc),
            status.HTTP_409_CONFLICT,
        )
    return AppError(
        "continuity_service_error",
        "连续性服务处理失败。",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
