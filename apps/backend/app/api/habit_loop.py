from __future__ import annotations

from fastapi import APIRouter, Request

from ..models.api import HabitLoopTriggerRequest, HabitLoopTriggerResponse
from ..services.habit_loop import HabitLoopTriggerService
from .wiring import database

router = APIRouter(prefix="/habit-loop", tags=["habit-loop"])


@router.post("/trigger", response_model=HabitLoopTriggerResponse)
async def trigger_habit_loop(
    trigger_request: HabitLoopTriggerRequest,
    request: Request,
) -> HabitLoopTriggerResponse:
    with database(request).connect() as conn:
        return HabitLoopTriggerService(conn).trigger(timezone_name=trigger_request.timezone)
