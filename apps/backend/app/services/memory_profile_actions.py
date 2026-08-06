from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus

from app.models.enums import MemoryFactStatus
from app.services.memory_lifecycle import MemoryLifecycleService, MemoryLifecycleTransitionError
from app.services.memory_profile_projection import MemoryProfileProjectionService
from app.storage.database import Database


@dataclass(frozen=True, slots=True)
class MemoryProfileActionSpec:
    feedback_operation: str
    feedback_text: str
    agent_summary: str
    user_message: str


@dataclass(frozen=True, slots=True)
class MemoryProfileActionResult:
    item_id: str
    action: str
    user_message: str
    agent_summary: str
    category_label: str
    status_label: str
    feedback_event_id: str | None


class MemoryProfileActionError(ValueError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code


_PROFILE_ACTION_SPECS: dict[str, MemoryProfileActionSpec] = {
    "forget": MemoryProfileActionSpec(
        feedback_operation="forget",
        feedback_text="用户从画像详情中撤回",
        agent_summary="已撤回一条画像记忆",
        user_message="已撤回这条记忆，我不会再把它作为当前画像使用。",
    ),
    "mark_inaccurate": MemoryProfileActionSpec(
        feedback_operation="reject_candidate",
        feedback_text="用户从画像详情中标记不准确",
        agent_summary="已标记一条画像记忆不准确",
        user_message="已标记为不准确，我不会再把它作为当前画像使用。",
    ),
    "keep": MemoryProfileActionSpec(
        feedback_operation="keep",
        feedback_text="用户从画像详情中确认记住",
        agent_summary="已确认一条画像记忆",
        user_message="已确认记住，之后我会在合适时参考它。",
    ),
    "make_temporary": MemoryProfileActionSpec(
        feedback_operation="make_temporary",
        feedback_text="用户从画像详情中设为临时",
        agent_summary="已将一条画像记忆设为临时",
        user_message="已改为暂时保留，我只会在近期参考它。",
    ),
    "mark_stale": MemoryProfileActionSpec(
        feedback_operation="mark_stale",
        feedback_text="用户从画像详情中标记过期",
        agent_summary="已标记一条画像记忆可能过期",
        user_message="已标记为可能过时，我会减少使用并等待你再次确认。",
    ),
}


class MemoryProfileActionService:
    def __init__(self, database: Database, lifecycle: MemoryLifecycleService) -> None:
        self.database = database
        self.lifecycle = lifecycle

    def apply(
        self,
        *,
        item_id: str,
        action: str,
        confirmed: bool,
        expires_at: str | None,
    ) -> MemoryProfileActionResult:
        self._require_confirmation(confirmed)
        with self.database.session() as conn:
            projection = MemoryProfileProjectionService(conn)
            target = projection.resolve_target(item_id)
            detail = projection.get_detail(item_id)

        if target is None or detail is None or target.target_id is None:
            raise MemoryProfileActionError(
                code="memory_profile_item_not_found",
                message="这条记忆已经不可操作，请刷新后重试。",
                status_code=HTTPStatus.NOT_FOUND,
            )

        available_actions = {available.action for available in detail.available_actions}
        if action not in available_actions:
            raise MemoryProfileActionError(
                code="memory_profile_action_not_available",
                message="这条记忆当前不能执行这个操作。",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )

        spec = self._action_spec(action)
        validated_expiry = self._validate_expiry(action=action, expires_at=expires_at)
        feedback_event_id = self._transition(
            target_type=target.target_type,
            target_id=target.target_id,
            action=action,
            spec=spec,
            expires_at=validated_expiry,
        )
        return MemoryProfileActionResult(
            item_id=item_id,
            action=action,
            user_message=spec.user_message,
            agent_summary=spec.agent_summary,
            category_label=detail.category_label,
            status_label=detail.status_label,
            feedback_event_id=feedback_event_id,
        )

    def link_feedback_event_to_action(self, *, feedback_event_id: str, action_id: str) -> None:
        with self.database.session() as conn:
            conn.execute(
                "UPDATE memory_feedback_events SET agent_action_id = ? WHERE id = ?",
                (action_id, feedback_event_id),
            )

    @staticmethod
    def _require_confirmation(confirmed: bool) -> None:
        if confirmed is not True:
            raise MemoryProfileActionError(
                code="memory_profile_action_confirmation_required",
                message="需要你确认后，才会改动这条记忆。",
                status_code=HTTPStatus.BAD_REQUEST,
            )

    @staticmethod
    def _action_spec(action: str) -> MemoryProfileActionSpec:
        spec = _PROFILE_ACTION_SPECS.get(action)
        if spec is None:
            raise MemoryProfileActionError(
                code="memory_profile_action_unknown",
                message="这条记忆当前不能执行这个操作。",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        return spec

    @staticmethod
    def _validate_expiry(*, action: str, expires_at: str | None) -> str | None:
        if action != "make_temporary":
            return None
        value = (expires_at or "").strip()
        if not value:
            raise MemoryProfileActionError(
                code="memory_profile_action_expiry_required",
                message="暂时保留需要设置一个有效的到期时间。",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MemoryProfileActionError(
                code="memory_profile_action_expiry_invalid",
                message="暂时保留的到期时间格式不正确。",
                status_code=HTTPStatus.BAD_REQUEST,
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed <= datetime.now(timezone.utc):
            raise MemoryProfileActionError(
                code="memory_profile_action_expiry_in_past",
                message="暂时保留的到期时间需要晚于现在。",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        return value

    def _transition(
        self,
        *,
        target_type: str,
        target_id: str,
        action: str,
        spec: MemoryProfileActionSpec,
        expires_at: str | None,
    ) -> str | None:
        try:
            if target_type == "fact" and action == "mark_inaccurate":
                self.lifecycle.transition(
                    target_type="fact",
                    target_id=target_id,
                    to_status=MemoryFactStatus.WRONG,
                    reason="user_marked_wrong",
                )
                return None
            result = self.lifecycle.apply_feedback(
                target_type=target_type,  # type: ignore[arg-type]
                target_id=target_id,
                operation=spec.feedback_operation,  # type: ignore[arg-type]
                feedback_text=spec.feedback_text,
                expires_at=expires_at,
            )
            return result.feedback_event_id
        except (KeyError, MemoryLifecycleTransitionError, ValueError) as exc:
            raise MemoryProfileActionError(
                code="memory_profile_action_failed",
                message="这次没有改动记忆，请稍后重试。",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            ) from exc
