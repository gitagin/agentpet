from __future__ import annotations

from fastapi import status

from app.errors import AppError
from app.services.memory import (
    MarkdownWriteError,
    MemoryConflictError,
    MemoryProposalNotFoundError,
    MemoryProposalStateError,
)
from app.services.tasks import TaskNotFoundError, TimezoneParseError


def map_memory_error(exc: Exception) -> AppError:
    if isinstance(exc, MemoryProposalNotFoundError):
        return AppError("proposal_not_found", "未找到记忆提案。", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, MemoryProposalStateError):
        return AppError("proposal_state_conflict", str(exc), status.HTTP_409_CONFLICT)
    if isinstance(exc, MemoryConflictError):
        return AppError("memory_write_conflict", str(exc), status.HTTP_409_CONFLICT)
    if isinstance(exc, MarkdownWriteError):
        return AppError("markdown_write_failed", str(exc), status.HTTP_400_BAD_REQUEST)
    return AppError("memory_service_error", "记忆服务处理失败。", status.HTTP_500_INTERNAL_SERVER_ERROR)


def map_task_error(exc: Exception) -> AppError:
    if isinstance(exc, TaskNotFoundError):
        return AppError("task_not_found", "未找到任务。", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, TimezoneParseError):
        return AppError("invalid_timezone", str(exc), status.HTTP_400_BAD_REQUEST)
    return AppError("task_service_error", "任务服务处理失败。", status.HTTP_500_INTERNAL_SERVER_ERROR)
