from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.models.common import new_id
from app.services.agent_actions import AutomationPolicy
from app.utils.time import utc_now_iso

logger = logging.getLogger(__name__)


PostReplyStageKey = Literal["daily_diary", "structured_diary", "slow_consolidation", "entity_relation", "wiki_summary"]
PostReplyStageStatus = Literal["skipped", "succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class PostReplyStageResult:
    key: PostReplyStageKey
    status: PostReplyStageStatus
    action_ids: tuple[str, ...] = ()
    safe_summary: str = ""
    duration_ms: int = 0
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class PostReplyMemoryJobResult:
    job_id: str
    agent_run_id: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    stages: tuple[PostReplyStageResult, ...]
    started_at: str
    completed_at: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class PostReplyMemoryJobInput:
    context: Any
    state: AgentState
    assistant_message_id: str
    assistant_answer: str
    job_id: str = field(default_factory=new_id)
    automation: Any | None = None
    policy: AutomationPolicy | None = None


@dataclass(frozen=True, slots=True)
class PostReplyMemoryJobRun:
    result: PostReplyMemoryJobResult
    action_events: tuple[AgentActionEvent, ...] = field(default_factory=tuple, repr=False, compare=False)


_StageCallable = Callable[..., Any | Awaitable[Any]]
_AutomationProvider = Callable[[Any], Any]


class PostReplyMemoryJobRunner:
    def __init__(
        self,
        *,
        automation_provider: _AutomationProvider | None = None,
        daily_diary_stage: _StageCallable | None = None,
        structured_diary_stage: _StageCallable | None = None,
        slow_consolidation_stage: _StageCallable | None = None,
        entity_relation_stage: _StageCallable | None = None,
        wiki_summary_stage: _StageCallable | None = None,
    ) -> None:
        self._automation_provider = automation_provider
        self._daily_diary_stage = daily_diary_stage
        self._structured_diary_stage = structured_diary_stage
        self._slow_consolidation_stage = slow_consolidation_stage
        self._entity_relation_extraction_stage = entity_relation_stage
        self._wiki_summary_stage = wiki_summary_stage

    async def run(self, payload: PostReplyMemoryJobInput) -> PostReplyMemoryJobResult:
        return (await self.run_with_actions(payload)).result

    async def run_with_actions(self, payload: PostReplyMemoryJobInput) -> PostReplyMemoryJobRun:
        started_at = utc_now_iso()
        started = time.perf_counter()
        stages: list[PostReplyStageResult] = []
        actions: list[AgentActionEvent] = []
        daily_result: Any | None = None
        diary_object_ids: tuple[str, ...] = ()

        try:
            automation = payload.automation if payload.automation is not None else self._load_automation(payload.context)
        except Exception:
            logger.warning(
                "Post-reply memory job skipped because automation settings failed for agent_run_id=%s",
                payload.state.agent_run_id,
                exc_info=True,
            )
            stages.extend(
                self._failed_stage(key, started=time.perf_counter(), error_code="automation_settings_failed")
                for key in ("daily_diary", "structured_diary", "slow_consolidation", "entity_relation", "wiki_summary")
            )
            return self._finish(payload, stages=stages, actions=actions, started_at=started_at, started=started)

        policy = payload.policy or AutomationPolicy()

        if not getattr(automation, "auto_chat_diary", False):
            stages.append(self._skipped_stage("daily_diary", started=time.perf_counter(), reason="disabled"))
        else:
            stage_started = time.perf_counter()
            try:
                daily_result, daily_actions = await self._call_stage(
                    self._daily_stage(),
                    context=payload.context,
                    state=payload.state,
                    assistant_message_id=payload.assistant_message_id,
                    assistant_answer=payload.assistant_answer,
                    automation=automation,
                    policy=policy,
                    raise_errors=True,
                )
                daily_actions = tuple(daily_actions or ())
                actions.extend(daily_actions)
                stages.append(
                    self._stage_result(
                        "daily_diary",
                        started=stage_started,
                        actions=daily_actions,
                        succeeded=daily_result is not None,
                    )
                )
            except Exception:
                logger.warning(
                    "Post-reply memory stage daily_diary failed for agent_run_id=%s",
                    payload.state.agent_run_id,
                    exc_info=True,
                )
                stages.append(self._failed_stage("daily_diary", started=stage_started, error_code="daily_diary_failed"))
                daily_result = None

        if not getattr(automation, "auto_structured_memory", False):
            stages.append(self._skipped_stage("structured_diary", started=time.perf_counter(), reason="disabled"))
        else:
            stage_started = time.perf_counter()
            try:
                diary_object_ids, diary_actions = await self._call_stage(
                    self._structured_stage(),
                    context=payload.context,
                    state=payload.state,
                    assistant_message_id=payload.assistant_message_id,
                    assistant_answer=payload.assistant_answer,
                    daily_result=daily_result,
                    automation=automation,
                    policy=policy,
                    raise_errors=True,
                )
                diary_object_ids = tuple(diary_object_ids or ())
                diary_actions = tuple(diary_actions or ())
                actions.extend(diary_actions)
                stages.append(
                    self._stage_result(
                        "structured_diary",
                        started=stage_started,
                        actions=diary_actions,
                        succeeded=bool(diary_object_ids),
                    )
                )
            except Exception:
                logger.warning(
                    "Post-reply memory stage structured_diary failed for agent_run_id=%s",
                    payload.state.agent_run_id,
                    exc_info=True,
                )
                stages.append(
                    self._failed_stage(
                        "structured_diary",
                        started=stage_started,
                        error_code="structured_diary_failed",
                    )
                )
                diary_object_ids = ()

        if not getattr(automation, "auto_long_term_memory", False):
            stages.append(self._skipped_stage("slow_consolidation", started=time.perf_counter(), reason="disabled"))
        else:
            stage_started = time.perf_counter()
            try:
                consolidation_actions = await self._call_stage(
                    self._slow_stage(),
                    context=payload.context,
                    state=payload.state,
                    assistant_message_id=payload.assistant_message_id,
                    assistant_answer=payload.assistant_answer,
                    daily_result=daily_result,
                    diary_object_ids=diary_object_ids,
                    automation=automation,
                    policy=policy,
                    raise_errors=True,
                )
                consolidation_actions = tuple(consolidation_actions or ())
                actions.extend(consolidation_actions)
                stages.append(
                    self._stage_result(
                        "slow_consolidation",
                        started=stage_started,
                        actions=consolidation_actions,
                        succeeded=bool(consolidation_actions),
                    )
                )
            except Exception:
                logger.warning(
                    "Post-reply memory stage slow_consolidation failed for agent_run_id=%s",
                    payload.state.agent_run_id,
                    exc_info=True,
                )
                stages.append(
                    self._failed_stage(
                        "slow_consolidation",
                        started=stage_started,
                        error_code="slow_consolidation_failed",
                    )
                )

        if not getattr(automation, "auto_long_term_memory", False):
            stages.append(self._skipped_stage("entity_relation", started=time.perf_counter(), reason="disabled"))
        else:
            stage_started = time.perf_counter()
            try:
                entity_actions = await self._call_stage(
                    self._entity_relation_stage(),
                    context=payload.context,
                    state=payload.state,
                    assistant_message_id=payload.assistant_message_id,
                    assistant_answer=payload.assistant_answer,
                    daily_result=daily_result,
                    diary_object_ids=diary_object_ids,
                    automation=automation,
                    policy=policy,
                    raise_errors=True,
                )
                entity_actions = tuple(entity_actions or ())
                actions.extend(entity_actions)
                stages.append(
                    self._stage_result(
                        "entity_relation",
                        started=stage_started,
                        actions=entity_actions,
                        succeeded=bool(entity_actions),
                    )
                )
            except Exception:
                logger.warning(
                    "Post-reply memory stage entity_relation failed for agent_run_id=%s",
                    payload.state.agent_run_id,
                    exc_info=True,
                )
                stages.append(
                    self._failed_stage(
                        "entity_relation",
                        started=stage_started,
                        error_code="entity_relation_failed",
                    )
                )

        if not getattr(automation, "auto_wiki_organize", False) or daily_result is None:
            stages.append(self._skipped_stage("wiki_summary", started=time.perf_counter(), reason="disabled"))
        else:
            stage_started = time.perf_counter()
            try:
                wiki_actions = await self._call_stage(
                    self._wiki_stage(),
                    context=payload.context,
                    state=payload.state,
                    assistant_message_id=payload.assistant_message_id,
                    assistant_answer=payload.assistant_answer,
                    daily_result=daily_result,
                    diary_object_ids=diary_object_ids,
                    automation=automation,
                    policy=policy,
                    raise_errors=True,
                )
                wiki_actions = tuple(wiki_actions or ())
                actions.extend(wiki_actions)
                stages.append(
                    self._stage_result(
                        "wiki_summary",
                        started=stage_started,
                        actions=wiki_actions,
                        succeeded=bool(wiki_actions),
                    )
                )
            except Exception:
                logger.warning(
                    "Post-reply memory stage wiki_summary failed for agent_run_id=%s",
                    payload.state.agent_run_id,
                    exc_info=True,
                )
                stages.append(self._failed_stage("wiki_summary", started=stage_started, error_code="wiki_summary_failed"))

        return self._finish(payload, stages=stages, actions=actions, started_at=started_at, started=started)

    def _finish(
        self,
        payload: PostReplyMemoryJobInput,
        *,
        stages: list[PostReplyStageResult],
        actions: list[AgentActionEvent],
        started_at: str,
        started: float,
    ) -> PostReplyMemoryJobRun:
        completed_at = utc_now_iso()
        result = PostReplyMemoryJobResult(
            job_id=payload.job_id,
            agent_run_id=payload.state.agent_run_id,
            conversation_id=payload.state.conversation_id,
            user_message_id=payload.state.message_id,
            assistant_message_id=payload.assistant_message_id,
            stages=tuple(stages),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=_elapsed_ms(started),
        )
        return PostReplyMemoryJobRun(result=result, action_events=tuple(actions))

    def _load_automation(self, context: Any) -> Any:
        if self._automation_provider is not None:
            return self._automation_provider(context)
        from app.services.chat_pipeline import automation_settings

        return automation_settings(context)

    def _daily_stage(self) -> _StageCallable:
        if self._daily_diary_stage is not None:
            return self._daily_diary_stage
        from app.services.chat_pipeline.diary import archive_daily_diary

        return archive_daily_diary

    def _structured_stage(self) -> _StageCallable:
        if self._structured_diary_stage is not None:
            return self._structured_diary_stage
        from app.services.chat_pipeline.diary_memory import archive_structured_diary_memory

        return archive_structured_diary_memory

    def _slow_stage(self) -> _StageCallable:
        if self._slow_consolidation_stage is not None:
            return self._slow_consolidation_stage
        from app.services.chat_pipeline.consolidation import consolidate_slow_memory

        return consolidate_slow_memory

    def _entity_relation_stage(self) -> _StageCallable:
        if self._entity_relation_extraction_stage is not None:
            return self._entity_relation_extraction_stage
        from app.services.chat_pipeline.entity_relation import archive_entity_relations

        return archive_entity_relations

    def _wiki_stage(self) -> _StageCallable:
        if self._wiki_summary_stage is not None:
            return self._wiki_summary_stage
        from app.services.chat_pipeline.wiki_summary import archive_wiki_answer_summary

        return archive_wiki_answer_summary

    async def _call_stage(self, func: _StageCallable, **kwargs: Any) -> Any:
        result = func(**_compatible_kwargs(func, kwargs))
        if inspect.isawaitable(result):
            return await result
        return result

    def _stage_result(
        self,
        key: PostReplyStageKey,
        *,
        started: float,
        actions: tuple[AgentActionEvent, ...],
        succeeded: bool,
    ) -> PostReplyStageResult:
        if actions and any(action.status == "failed" for action in actions):
            return PostReplyStageResult(
                key=key,
                status="failed",
                action_ids=tuple(action.action_id for action in actions),
                safe_summary="Stage failed safely.",
                duration_ms=_elapsed_ms(started),
                error_code=f"{key}_failed",
            )
        if actions and any(action.status != "skipped" for action in actions):
            status: PostReplyStageStatus = "succeeded"
            summary = "Stage completed."
        elif succeeded:
            status = "succeeded"
            summary = "Stage completed."
        else:
            status = "skipped"
            summary = "Stage skipped."
        return PostReplyStageResult(
            key=key,
            status=status,
            action_ids=tuple(action.action_id for action in actions),
            safe_summary=summary,
            duration_ms=_elapsed_ms(started),
        )

    def _skipped_stage(self, key: PostReplyStageKey, *, started: float, reason: str) -> PostReplyStageResult:
        return PostReplyStageResult(
            key=key,
            status="skipped",
            safe_summary=f"Stage skipped: {reason}.",
            duration_ms=_elapsed_ms(started),
        )

    def _failed_stage(self, key: PostReplyStageKey, *, started: float, error_code: str) -> PostReplyStageResult:
        return PostReplyStageResult(
            key=key,
            status="failed",
            safe_summary="Stage failed safely.",
            duration_ms=_elapsed_ms(started),
            error_code=error_code,
        )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _compatible_kwargs(func: _StageCallable, kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return kwargs
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in signature.parameters}
