from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.services.vector_index import LangChainQdrantVectorIndex


@dataclass
class ComponentHealth:
    name: str
    status: Literal["ok", "degraded", "unavailable"]
    reason: str | None = None
    last_checked: datetime | None = None


def component_health_from_vector_index(vector_index: LangChainQdrantVectorIndex) -> ComponentHealth:
    reason = vector_index.config.unavailable_reason
    if vector_index.available:
        return ComponentHealth(
            name="vector_index",
            status="ok",
            last_checked=datetime.now(timezone.utc),
        )
    if reason in {None, "embedding_api_key_missing"}:
        return ComponentHealth(
            name="vector_index",
            status="ok",
            reason=reason,
            last_checked=datetime.now(timezone.utc),
        )
    return ComponentHealth(
        name="vector_index",
        status="unavailable",
        reason=f"初始化失败: {reason}",
        last_checked=datetime.now(timezone.utc),
    )
