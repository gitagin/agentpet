from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Mapping

from app.services.vector_index import LangChainQdrantVectorIndex


_BENIGN_VECTOR_REASONS = {
    "active_generation_missing",
    "embedding_api_key_missing",
    "embedding_not_configured",
    "index_not_built",
    "local_embedding_unavailable",
    "local_privacy_mode",
    "local_privacy_remote_blocked",
    "vector_disabled",
}
_SAFE_VECTOR_REASONS = _BENIGN_VECTOR_REASONS | {
    "credential_store_unavailable",
    "embedding_dimension_mismatch",
    "embedding_dimensions_unknown",
    "embedding_configuration_unavailable",
    "embedding_initialization_failed",
    "embedding_provider_unavailable",
    "embedding_provider_unsupported",
    "index_corrupt",
    "index_drift",
    "qdrant_unavailable",
    "sensitive_content_blocked",
    "sync_failed",
    "vector_health_unavailable",
    "vector_index_unavailable",
}


@dataclass
class ComponentHealth:
    name: str
    status: Literal["ok", "degraded", "unavailable"]
    reason: str | None = None
    last_checked: datetime | None = None


def component_health_from_vector_index(vector_index: LangChainQdrantVectorIndex) -> ComponentHealth:
    checked_at = datetime.now(timezone.utc)
    config_reason = _safe_reason(getattr(getattr(vector_index, "config", None), "unavailable_reason", None))
    health_method = getattr(vector_index, "health", None)
    if callable(health_method):
        try:
            projection = health_method()
        except Exception:
            return ComponentHealth(
                name="vector_index",
                status="unavailable",
                reason="vector_health_unavailable",
                last_checked=checked_at,
            )
        if isinstance(projection, Mapping):
            reason = config_reason or _safe_reason(projection.get("unavailability_reason"))
            vector_available = projection.get("vector_available") is True
            sync_status = str(projection.get("last_sync_status") or "").strip().casefold()
            if vector_available:
                return ComponentHealth(name="vector_index", status="ok", last_checked=checked_at)
            if reason is None and sync_status in {"idle", "not_built", "unavailable"}:
                reason = "index_not_built" if sync_status == "not_built" else "embedding_not_configured"
            component_reason = _legacy_component_reason(vector_index, reason or "vector_index_unavailable")
            return ComponentHealth(
                name="vector_index",
                status="ok" if reason in _BENIGN_VECTOR_REASONS else "unavailable",
                reason=component_reason,
                last_checked=checked_at,
            )

    try:
        available = bool(vector_index.available)
    except Exception:
        available = False
    if available:
        return ComponentHealth(name="vector_index", status="ok", last_checked=checked_at)
    reason = config_reason or "embedding_not_configured"
    return ComponentHealth(
        name="vector_index",
        status="ok" if reason in _BENIGN_VECTOR_REASONS else "unavailable",
        reason=reason,
        last_checked=checked_at,
    )


def _safe_reason(reason: object) -> str | None:
    if reason is None:
        return None
    normalized = str(reason).strip().casefold()
    return normalized if normalized in _SAFE_VECTOR_REASONS else "vector_index_unavailable"


def _legacy_component_reason(vector_index: object, reason: str) -> str:
    if reason != "embedding_initialization_failed":
        return reason
    error_type = str(getattr(vector_index, "_legacy_initialization_error_type", "")).strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", error_type):
        return reason
    return f"{reason}:{error_type}"
