from __future__ import annotations

from fastapi import APIRouter, Query, Request, status

from ..errors import AppError
from ..models.api import AgentActionListResponse, AgentActionRevertResponse
from ..services.agent_actions import AgentActionNotFoundError, AgentActionRevertError
from .wiring import agent_action_service

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/actions", response_model=AgentActionListResponse)
async def list_agent_actions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    agent_run_id: str | None = Query(default=None),
) -> AgentActionListResponse:
    service = agent_action_service(request)
    try:
        return AgentActionListResponse(actions=service.list_recent(limit=limit, source_agent_run_id=agent_run_id))
    finally:
        service.close()


@router.post("/actions/{action_id}/revert", response_model=AgentActionRevertResponse)
async def revert_agent_action(action_id: str, request: Request) -> AgentActionRevertResponse:
    service = agent_action_service(request)
    try:
        action, reverted = service.revert(action_id)
    except AgentActionNotFoundError as exc:
        raise AppError(
            code="agent_action_not_found",
            message="未找到自动整理活动。",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"action_id": action_id},
        ) from exc
    except AgentActionRevertError as exc:
        raise AppError(
            code="agent_action_revert_failed",
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
            details={"action_id": action_id},
        ) from exc
    finally:
        service.close()
    return AgentActionRevertResponse(action=action, reverted=reverted)
