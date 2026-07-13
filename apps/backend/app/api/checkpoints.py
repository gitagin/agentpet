from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from ..agents.checkpointer import (
    CheckpointConflictError,
    CheckpointError,
    CheckpointExpiredError,
    CheckpointNotFoundError,
    SQLiteCheckpointStore,
)
from ..errors import AppError
from .services.adapters import agent_runtime
from .services.factory import database

router = APIRouter(prefix="/checkpoints", tags=["checkpoints"])


class CheckpointDecisionRequest(BaseModel):
    decision_id: str = Field(min_length=16, max_length=128)
    decision: Literal["approved", "rejected"]
    policy_version: str = Field(min_length=1, max_length=64)


class CheckpointSummary(BaseModel):
    checkpoint_id: str
    thread_id: str
    run_id: str
    node_name: str
    status: str
    action_proposal_id: str | None
    public_event_cursor: int | None
    created_at: str
    updated_at: str
    expires_at: str
    decision_id: str
    decision_expires_at: str
    action_label: str
    safe_target_summary: str
    risk_tier: str
    reversible: bool


class CheckpointDecisionResponse(BaseModel):
    checkpoint_id: str
    status: str
    effect_applied: bool


def _store(request: Request) -> SQLiteCheckpointStore:
    return SQLiteCheckpointStore(database(request))


def _summary(record: Any) -> CheckpointSummary:
    return CheckpointSummary(
        checkpoint_id=record.checkpoint_id,
        thread_id=record.thread_id,
        run_id=record.run_id,
        node_name=record.node_name,
        status=record.status,
        action_proposal_id=record.action_proposal_id,
        public_event_cursor=record.public_event_cursor,
        created_at=record.created_at,
        updated_at=record.updated_at,
        expires_at=record.expires_at,
        decision_id=str(record.state.get("decision_id") or ""),
        decision_expires_at=str(record.state.get("decision_expires_at") or ""),
        action_label=str(record.state.get("action_label") or ""),
        safe_target_summary=str(record.state.get("safe_target_summary") or ""),
        risk_tier=str(record.state.get("risk_tier") or "high"),
        reversible=bool(record.state.get("reversible")),
    )


@router.get("/pending", response_model=list[CheckpointSummary])
async def list_pending_checkpoints(
    request: Request,
    thread_id: str | None = None,
) -> list[CheckpointSummary]:
    return [_summary(record) for record in _store(request).list_pending(thread_id=thread_id)]


@router.get("/{checkpoint_id}", response_model=CheckpointSummary)
async def get_checkpoint(checkpoint_id: str, request: Request) -> CheckpointSummary:
    try:
        return _summary(_store(request).get(checkpoint_id))
    except CheckpointNotFoundError as exc:
        raise AppError(
            code="checkpoint_not_found",
            message="待确认项不存在。",
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc


@router.post("/{checkpoint_id}/decision", response_model=CheckpointDecisionResponse)
async def decide_checkpoint(
    checkpoint_id: str,
    body: CheckpointDecisionRequest,
    request: Request,
) -> CheckpointDecisionResponse:
    try:
        result = await agent_runtime(request).resume_checkpoint(
            checkpoint_id,
            decision_id=body.decision_id,
            decision=body.decision,
            policy_version=body.policy_version,
        )
        return CheckpointDecisionResponse(**result)
    except CheckpointNotFoundError as exc:
        raise AppError(
            code="checkpoint_not_found",
            message="待确认项不存在。",
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc
    except CheckpointExpiredError as exc:
        raise AppError(
            code="checkpoint_expired",
            message="待确认项已过期。",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    except (CheckpointConflictError, CheckpointError) as exc:
        raise AppError(
            code="checkpoint_decision_rejected",
            message="确认请求未通过安全校验。",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
