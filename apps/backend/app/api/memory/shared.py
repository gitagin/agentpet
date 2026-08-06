"""记忆 API 各子路由共享的纯函数与常量。

放这里的只有无副作用的转换/脱敏工具；任何依赖 Request 的逻辑都留在各自模块。
"""

from __future__ import annotations

import json

from ...models.enums import MemoryFactStatus
from ...services.memory_policy import evaluate_memory_content

RAW_EVIDENCE_REDACTION_NOTE = (
    "原始来源证据已从此预览中省略。文件导出必须通过已确认的安全路径处理。"
)


def graph_lifecycle_status(fact_status: str) -> str | None:
    if fact_status == MemoryFactStatus.QUARANTINED.value:
        return "candidate"
    if fact_status in {MemoryFactStatus.WRONG.value, MemoryFactStatus.SENSITIVE_BLOCKED.value}:
        return "rejected"
    if fact_status in {
        MemoryFactStatus.CANDIDATE.value,
        MemoryFactStatus.ACTIVE.value,
        MemoryFactStatus.STALE.value,
        MemoryFactStatus.ARCHIVED.value,
        MemoryFactStatus.FORGOTTEN.value,
        MemoryFactStatus.REJECTED.value,
        MemoryFactStatus.SUPERSEDED.value,
    }:
        return fact_status
    return None


def safe_export_value(value: str) -> str:
    policy = evaluate_memory_content(value)
    if not policy.allowed:
        return "[redacted sensitive content]"
    return value


def safe_export_optional(value: str | None) -> str | None:
    return safe_export_value(value) if value is not None else None


def safe_export_object(value) -> object:
    if isinstance(value, str):
        return safe_export_value(value)
    if isinstance(value, dict):
        return {
            safe_export_value(str(key)): safe_export_object(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [safe_export_object(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return safe_export_value(str(value))


def safe_export_metadata(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        safe_export_value(str(key)): safe_export_object(value)
        for key, value in parsed.items()
    }
