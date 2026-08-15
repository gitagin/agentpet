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
    if isinstance(exc, RuntimeError):
        raw_code = str(exc)
        code = raw_code.removeprefix("action_lifecycle_").strip()
        if code in {"markdown_write_failed", "policy_denied"}:
            return AppError(
                "markdown_write_failed",
                "记忆目标文件路径或写入策略不允许，未把不确定结果显示为成功。",
                status.HTTP_400_BAD_REQUEST,
            )
        if code == "memory_write_conflict":
            return AppError(
                "memory_write_conflict",
                "记忆目标在提案预览后已发生变化。",
                status.HTTP_409_CONFLICT,
            )
        if code in {"proposal_not_found", "proposal_state_conflict"}:
            return AppError(code, "记忆提案状态已变化，请重新加载后再操作。", status.HTTP_409_CONFLICT)
    return AppError("memory_service_error", "记忆服务处理失败。", status.HTTP_500_INTERNAL_SERVER_ERROR)


def map_task_error(exc: Exception) -> AppError:
    if isinstance(exc, TaskNotFoundError):
        return AppError("task_not_found", "未找到任务。", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, TimezoneParseError):
        return AppError("invalid_timezone", str(exc), status.HTTP_400_BAD_REQUEST)
    return AppError("task_service_error", "任务服务处理失败。", status.HTTP_500_INTERNAL_SERVER_ERROR)
