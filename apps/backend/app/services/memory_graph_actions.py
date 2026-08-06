from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.models.enums import MemoryFactStatus
from app.services.memory_lifecycle import MemoryLifecycleService


class MemoryGraphFactAction(str, Enum):
    CONFIRM = "confirm"
    REJECT = "reject"
    WRONG = "wrong"
    SENSITIVE_BLOCK = "sensitive-block"
    ARCHIVE = "archive"


@dataclass(frozen=True, slots=True)
class MemoryGraphFactActionSpec:
    status: MemoryFactStatus
    reason: str
    audit_action: str


@dataclass(frozen=True, slots=True)
class MemoryGraphFactActionResult:
    fact_id: str
    status: MemoryFactStatus
    audit_action: str


MEMORY_GRAPH_FACT_ACTIONS: dict[MemoryGraphFactAction, MemoryGraphFactActionSpec] = {
    MemoryGraphFactAction.CONFIRM: MemoryGraphFactActionSpec(
        MemoryFactStatus.ACTIVE,
        "user_confirmed",
        "memory.graph.confirm",
    ),
    MemoryGraphFactAction.REJECT: MemoryGraphFactActionSpec(
        MemoryFactStatus.REJECTED,
        "user_rejected",
        "memory.graph.reject",
    ),
    MemoryGraphFactAction.WRONG: MemoryGraphFactActionSpec(
        MemoryFactStatus.WRONG,
        "user_marked_wrong",
        "memory.graph.wrong",
    ),
    MemoryGraphFactAction.SENSITIVE_BLOCK: MemoryGraphFactActionSpec(
        MemoryFactStatus.SENSITIVE_BLOCKED,
        "user_sensitive_blocked",
        "memory.graph.sensitive_block",
    ),
    MemoryGraphFactAction.ARCHIVE: MemoryGraphFactActionSpec(
        MemoryFactStatus.ARCHIVED,
        "user_archived",
        "memory.graph.archive",
    ),
}


class MemoryGraphFactActionService:
    def __init__(self, lifecycle: MemoryLifecycleService) -> None:
        self._lifecycle = lifecycle

    def close(self) -> None:
        self._lifecycle.close()

    def apply(
        self,
        fact_id: str,
        action: MemoryGraphFactAction | str,
    ) -> MemoryGraphFactActionResult:
        normalized_action = MemoryGraphFactAction(action)
        spec = MEMORY_GRAPH_FACT_ACTIONS[normalized_action]
        self._lifecycle.transition(
            target_type="fact",
            target_id=fact_id,
            to_status=spec.status,
            reason=spec.reason,
        )
        fact = self._lifecycle.graph.get(fact_id)
        return MemoryGraphFactActionResult(
            fact_id=fact.id,
            status=fact.status,
            audit_action=spec.audit_action,
        )
