from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.common import new_id
from app.services.memory_policy import evaluate_memory_content
from app.storage.database import open_database_connection
from app.utils.hash import sha256_hex
from app.utils.text import is_greeting_only
from app.utils.time import utc_now_iso

from app.utils.sqlite import extract_json_object


CONTINUITY_STATE_KEYS = (
    "identity_traits",
    "relationship_summary",
    "current_mood",
    "mood_momentum",
    "energy_level",
    "unresolved_threads",
    "recent_emotional_signals",
)
CONTINUITY_PROPOSAL_KINDS = {"identity", "relationship", "mood", "energy", "open_thread"}

# 同话题判定:双门槛,均在真实数据上测得——
# ① Dice ≥ 0.14:同一话题不同措辞 ≈0.20,不同话题 ≤0.09;
# ② 共享 bigram ≥ 4:纯靠比例会把短文本误判为同话题(差一字的两个
#    短摘要 Dice 0.5 但只共享 2 个 bigram,学日语/学英语共享 3),
#    而真变体共享 8 个、短文本真同话题共享 6 个。
# 变体措辞若不按此归并,用户拒绝一条后其余变体会继续每轮注入。
#
# 这两个门槛只适用于模型自己写的句子。确定性模板句(下面的 *_TEMPLATE 常量)
# 走模板身份,理由是实测:十一种情绪模板两两共享 4 个 bigram、Dice 0.47-0.5,
# 整句相似度会把"用户表达了难过"和"用户表达了兴奋"判成同一话题,于是用户
# 拒绝一条之后整个类别的建议被永久静默抑制——被判定的其实是模板前缀。
SAME_TOPIC_DICE_THRESHOLD = 0.14
SAME_TOPIC_MIN_SHARED_BIGRAMS = 4

MOOD_TEMPLATES = (
    ("tired", "用户听起来有些疲惫或消耗。", "mood_tired"),
    ("exhausted", "用户听起来很疲惫。", "mood_exhausted"),
    ("sad", "用户表达了难过情绪。", "mood_sad"),
    ("lonely", "用户表达了孤独感。", "mood_lonely"),
    ("stressed", "用户表达了压力。", "mood_stressed"),
    ("anxious", "用户表达了焦虑。", "mood_anxious"),
    ("worried", "用户表达了担心。", "mood_worried"),
    ("happy", "用户表达了积极情绪。", "mood_happy"),
    ("excited", "用户表达了兴奋。", "mood_excited"),
    ("angry", "用户表达了生气。", "mood_angry"),
    ("overwhelmed", "用户表达了不堪重负的感受。", "mood_overwhelmed"),
)
ENERGY_TEMPLATES = (
    (
        ("tired", "exhausted", "sleepy", "low energy", "burned out"),
        "用户看起来处于低能量状态。",
        "energy_low",
        0.53,
    ),
    (
        ("energized", "high energy", "motivated"),
        "用户看起来处于较高能量状态。",
        "energy_high",
        0.5,
    ),
)
OPEN_THREAD_MARKERS = (
    "continue this",
    "continue tomorrow",
    "tomorrow",
    "next time",
    "later",
    "pick this up",
    "unfinished",
)
OPEN_THREAD_TEMPLATE = ("有一个未完话题适合之后继续。", "open_thread_continue")
RELATIONSHIP_MARKERS = ("thank you", "thanks", "you helped", "i trust you", "companion", "stay with me")
RELATIONSHIP_TEMPLATE = ("用户表达了对陪伴助手的信任或感谢。", "relationship_trust")
IDENTITY_TEMPLATE_PREFIX = "陪伴助手的名称线索："
IDENTITY_TEMPLATE_SUFFIX = "。"
# 名字是变量,但"要不要记录助手名字"是同一个话题:拒绝过一次就不该换个名字再来。
IDENTITY_TEMPLATE_KEY = "identity_name"

_TEMPLATE_TOPIC_KEYS = {
    **{summary: key for _, summary, key in MOOD_TEMPLATES},
    **{summary: key for _, summary, key, _confidence in ENERGY_TEMPLATES},
    OPEN_THREAD_TEMPLATE[0]: OPEN_THREAD_TEMPLATE[1],
    RELATIONSHIP_TEMPLATE[0]: RELATIONSHIP_TEMPLATE[1],
}


def _template_topic_key(summary: str) -> str | None:
    """Identity of a deterministic template sentence, or None for free text."""
    normalized = " ".join(summary.split())
    key = _TEMPLATE_TOPIC_KEYS.get(normalized)
    if key is not None:
        return key
    if normalized.startswith(IDENTITY_TEMPLATE_PREFIX):
        return IDENTITY_TEMPLATE_KEY
    return None


def _normalized_summary(summary: str) -> str:
    """Identity of a free-text summary: whitespace-collapsed, case-folded text."""
    return " ".join(summary.split()).casefold()


def _char_bigrams(text: str) -> set[str]:
    compact = "".join(char for char in text if not char.isspace())
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def _is_same_topic(left: str, right: str) -> bool:
    """Are these two summaries the same topic for suppression purposes?

    Templates are compared by template identity and never by sentence
    similarity: a template's shared prefix is not topic content, and treating it
    as such makes one rejection silence every sibling suggestion.
    """
    left_key = _template_topic_key(left)
    right_key = _template_topic_key(right)
    if left_key is not None or right_key is not None:
        return left_key is not None and left_key == right_key

    if left.strip().casefold() == right.strip().casefold():
        return True
    left_grams = _char_bigrams(left)
    right_grams = _char_bigrams(right)
    if not left_grams or not right_grams:
        return False
    shared = len(left_grams & right_grams)
    if shared < SAME_TOPIC_MIN_SHARED_BIGRAMS:
        return False
    return 2 * shared / (len(left_grams) + len(right_grams)) >= SAME_TOPIC_DICE_THRESHOLD


def _carries_thread_topic(user_message: str) -> bool:
    """一条消息是否承载"未完话题"的实质内容。

    纯问候(嗨/你好/晚安…)与仅有符号、单字的输入不构成待接续话题:
    放行它们只会每轮生成“用户以简短问候开场”这类噪音话题。
    """
    compact = " ".join(user_message.split())
    if is_greeting_only(compact):
        return False
    meaningful = [char for char in compact if char.isalnum()]
    return len(meaningful) >= 4

logger = logging.getLogger(__name__)

PENDING = "pending"
CONFIRMED = "confirmed"
REJECTED = "rejected"


class ContinuityProposalNotFoundError(Exception):
    pass


class ContinuityProposalStateError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ContinuityProposal:
    id: str
    kind: str
    summary: str
    evidence: str
    confidence: float
    source_conversation_id: str | None
    source_message_id: str | None
    agent_run_id: str | None
    status: str
    rejected_reason: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ContinuityStateItem:
    state_key: str
    value: str
    confidence: float
    source_proposal_id: str | None
    source_conversation_id: str | None
    source_message_id: str | None
    agent_run_id: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class ContinuitySignal:
    kind: str
    title: str
    summary: str
    intensity: str
    display_hint: str
    source_state_keys: tuple[str, ...]
    source_proposal_id: str | None = None


class ContinuityService:
    """Review-gated runtime continuity store.

    This service writes only compact SQLite state and audit rows. It does not
    write Markdown, touch the Vault index, or promote pending proposals into
    prompt context.
    """

    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    async def create_proposals_from_exchange(
        self,
        *,
        user_message: str,
        assistant_answer: str,
        conversation_id: str | None,
        source_message_id: str | None,
        agent_run_id: str | None,
        model_client: Any | None = None,
    ) -> list[ContinuityProposal]:
        source_text = f"{user_message}\n\n{assistant_answer}".strip()
        if not source_text:
            return []
        policy = evaluate_memory_content(source_text)
        if not policy.allowed:
            return []

        candidates = await self._model_candidates(
            user_message=user_message,
            assistant_answer=assistant_answer,
            model_client=model_client,
        )
        if not candidates:
            candidates = _deterministic_candidates(user_message, assistant_answer)

        proposals: list[ContinuityProposal] = []
        carries_topic = _carries_thread_topic(user_message)
        for candidate in candidates:
            normalized = _normalize_candidate(candidate)
            if normalized is None:
                continue
            if normalized["kind"] == "open_thread" and not carries_topic:
                # 纯问候/无实质内容的输入不形成未完话题。
                continue
            proposal = self._insert_candidate(
                normalized,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                agent_run_id=agent_run_id,
            )
            if proposal is not None and proposal.status == PENDING:
                proposals.append(proposal)
        return proposals

    def list_pending(self) -> list[ContinuityProposal]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM continuity_proposals
            WHERE status = ?
            ORDER BY created_at ASC, id ASC
            """,
            (PENDING,),
        ).fetchall()
        return [self._map_proposal(row) for row in rows]

    def get_proposal(self, proposal_id: str) -> ContinuityProposal:
        row = self._proposal_row(proposal_id)
        if row is None:
            raise ContinuityProposalNotFoundError(proposal_id)
        return self._map_proposal(row)

    def get_state_items(self) -> list[ContinuityStateItem]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM continuity_state
            ORDER BY updated_at DESC, state_key ASC
            """
        ).fetchall()
        return [self._map_state(row) for row in rows]

    def get_state(self) -> dict[str, ContinuityStateItem]:
        return {item.state_key: item for item in self.get_state_items()}

    def context_block(self) -> str:
        state = self.get_state()
        if not state:
            return ""
        labels = (
            ("identity_traits", "身份特质"),
            ("relationship_summary", "关系摘要"),
            ("current_mood", "当前情绪"),
            ("mood_momentum", "情绪惯性"),
            ("energy_level", "能量水平"),
            ("unresolved_threads", "未完话题"),
            ("recent_emotional_signals", "近期情绪信号"),
        )
        lines = ["已确认的连续性上下文（用户已审阅；紧凑运行时状态）："]
        for key, label in labels:
            item = state.get(key)
            if item is None or not item.value.strip():
                continue
            value = item.value
            if key == "unresolved_threads":
                # 在场提示只带最近两条未完话题,避免历史线程每轮都注入
                # 污染新话题;完整列表仍保留在状态里供记忆页查看。
                recent = [part.strip() for part in value.split(" | ") if part.strip()][-2:]
                if not recent:
                    continue
                value = " | ".join(recent)
            lines.append(f"- {label}: {_truncate(value, 220)}")
        if len(lines) == 1:
            return ""
        lines.append("仅在相关时使用；永远不要把待处理的连续性提案当作已确认的记忆。")
        return "\n".join(lines)

    def presence_context_block(self) -> str:
        state = self.get_state()
        if not state:
            return ""
        context = self.context_block()
        if not context:
            return ""
        lines = [
            context,
            "陪伴在场行为：",
            "- 以高在场感承载已确认的连续性，但保持自然和简洁。",
            "- 在相关时可以温和地引用已确认的情绪、能量、关系、身份或未完话题。",
            "- 不要声称待处理或已拒绝的提案是记忆。",
            "- 除非工具事件确认，否则不要说任何内容已写入 Vault、Markdown、任务或提醒。",
        ]
        return "\n".join(lines)

    def presence_signal(self) -> ContinuitySignal | None:
        state = self.get_state()
        if not state:
            return None
        unresolved = _state_text(state, "unresolved_threads")
        mood = _state_text(state, "current_mood")
        energy = _state_text(state, "energy_level")
        relationship = _state_text(state, "relationship_summary")
        identity = _state_text(state, "identity_traits")

        if unresolved:
            # 在场提示只承载最近一条未完话题,并与按钮落点严格一致:按钮一次只
            # 静音一个话题;若提示同时展示多条而按钮只命中其中一条,用户会判定
            # "按钮没反应"。历史线程的完整列表仍留在 continuity_state 供状态页查看。
            threads = [part.strip() for part in unresolved.split(" | ") if part.strip()]
            newest = threads[-1] if threads else unresolved
            owner = self._live_thread_owner([newest])
            summary = f"我还记着这个未完话题：{_truncate(newest, 180)}"
            if len(threads) > 1:
                summary = f"{summary}（另有 {len(threads) - 1} 条待接续话题）"
            return ContinuitySignal(
                kind="open_thread",
                title="有个话题还没收好",
                summary=summary,
                intensity="high",
                display_hint="可以在这次对话里自然接上，不需要创建提醒或写入 Vault。",
                source_state_keys=("unresolved_threads",),
                # 落点从状态"派生"而不是直接读 source_proposal_id:那一列记录的是
                # 最后一次写入者,话题被拒绝后它仍指向已拒绝的提案,前端于是拿一个
                # 已拒绝的 id 去调拒绝接口 —— 服务层按幂等直接返回,按钮从此变成
                # 静默空操作。派生出的 id 必定是仍存活的已确认提案。
                source_proposal_id=owner.id if owner is not None else None,
            )
        if mood or energy:
            parts = []
            keys = []
            if mood:
                parts.append(f"情绪：{_truncate(mood, 140)}")
                keys.append("current_mood")
            if energy:
                parts.append(f"能量：{_truncate(energy, 140)}")
                keys.append("energy_level")
            return ContinuitySignal(
                kind="mood_energy",
                title="我会带着刚确认的状态陪你",
                summary="；".join(parts),
                intensity="high",
                display_hint="对话语气和桌宠待机状态会更明显地承接这条连续性。",
                source_state_keys=tuple(keys),
            )
        if relationship or identity:
            summary = relationship or identity or ""
            key = "relationship_summary" if relationship else "identity_traits"
            return ContinuitySignal(
                kind="relationship",
                title="关系连续性已在场",
                summary=_truncate(summary, 180),
                intensity="medium",
                display_hint="会影响陪伴语气，但不会展开成长期记忆写入。",
                source_state_keys=(key,),
            )
        return None

    def confirm_proposal(self, proposal_id: str) -> ContinuityProposal:
        row = self._proposal_row(proposal_id)
        if row is None:
            raise ContinuityProposalNotFoundError(proposal_id)
        proposal = self._map_proposal(row)
        if proposal.status == CONFIRMED:
            return proposal
        if proposal.status != PENDING:
            raise ContinuityProposalStateError(f"proposal {proposal_id} is {proposal.status}")

        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                UPDATE continuity_proposals
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (CONFIRMED, now, proposal_id),
            )
            self._apply_confirmed_state(proposal, updated_at=now)
            self.conn.execute(
                """
                INSERT INTO continuity_events (id, proposal_id, action, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id(), proposal_id, CONFIRMED, None, now),
            )
        return self._map_proposal(self._proposal_row(proposal_id))

    def reject_proposal(self, proposal_id: str, reason: str) -> ContinuityProposal:
        row = self._proposal_row(proposal_id)
        if row is None:
            raise ContinuityProposalNotFoundError(proposal_id)
        proposal = self._map_proposal(row)
        if proposal.status == REJECTED:
            # 幂等返回,但"已拒绝"并不等于"状态已经清干净":话题可能以未被相似度
            # 规则覆盖的措辞留在未完话题里,或者历史状态里的来源指针还停在死提案
            # 上。此时直接返回会让接口报 success、前端弹「已忽略」,而状态纹丝不动,
            # 按钮看起来毫无作用。补一次撤销,重复点击才会真正收敛。
            if proposal.kind == "open_thread":
                with self.conn:
                    self._retract_unresolved_thread(proposal.summary)
            return self._map_proposal(self._proposal_row(proposal_id))
        # 「下次接着聊」的 open_thread 会在回复后被自动确认(见 api/chat.py),
        # 用户没有可拒绝的 pending 提案;拒绝一个已确认的线程 = 撤销接续:
        # 从在场状态中移除该话题,后续对话不再注入。
        retract_confirmed_thread = proposal.status == CONFIRMED and proposal.kind == "open_thread"
        if proposal.status != PENDING and not retract_confirmed_thread:
            raise ContinuityProposalStateError(f"proposal {proposal_id} is {proposal.status}")

        compact_reason = _truncate(reason.strip() or "user_rejected", 500)
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                UPDATE continuity_proposals
                SET status = ?, rejected_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (REJECTED, compact_reason, now, proposal_id),
            )
            if retract_confirmed_thread:
                self._retract_unresolved_thread(proposal.summary)
            self.conn.execute(
                """
                INSERT INTO continuity_events (id, proposal_id, action, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id(), proposal_id, REJECTED, compact_reason, now),
            )
        return self._map_proposal(self._proposal_row(proposal_id))

    def _retract_unresolved_thread(self, summary: str) -> None:
        current = self._state_value("unresolved_threads")
        if not current:
            return
        # 只撤下被拒绝的那一条(以及同文的重复项)。这里刻意不用相似度:未完话题是
        # 用户确认过的在场状态,而相似度会把"只是措辞相近"的其他话题一起删掉——
        # 一次拒绝造成多条已确认话题静默消失。换措辞的变体交给提案侧的抑制规则,
        # 用户看到变体时再拒绝一次(重复拒绝是幂等的,会复查在场状态)。
        target = _normalized_summary(summary)
        remaining = [
            item.strip()
            for item in current.split(" | ")
            if item.strip() and _normalized_summary(item) != target
        ]
        now = utc_now_iso()
        if not remaining:
            self.conn.execute(
                "DELETE FROM continuity_state WHERE state_key = ?",
                ("unresolved_threads",),
            )
            return
        # 撤下一条后必须把来源列改判给仍然存活的话题:该列是"合并列表"的单一
        # 归属指针,继续指向刚被拒绝的提案会让状态页与在场提示指向一个死提案。
        owner = self._live_thread_owner(remaining)
        self.conn.execute(
            """
            UPDATE continuity_state
            SET value = ?, confidence = ?, source_proposal_id = ?,
                source_conversation_id = ?, source_message_id = ?, agent_run_id = ?,
                updated_at = ?
            WHERE state_key = ?
            """,
            (
                " | ".join(remaining),
                owner.confidence if owner is not None else 0.0,
                owner.id if owner is not None else None,
                owner.source_conversation_id if owner is not None else None,
                owner.source_message_id if owner is not None else None,
                owner.agent_run_id if owner is not None else None,
                now,
                "unresolved_threads",
            ),
        )

    def _live_thread_owner(self, threads: list[str]) -> ContinuityProposal | None:
        """在给定话题里找出"仍存活"的最新已确认提案。

        未完成话题是一个合并文本列表,而 continuity_state 只存得下一个来源提案。
        要判断某条话题还能不能被静音,必须回到 continuity_proposals 里查它是否
        仍有 status=confirmed 的提案;否则按钮会落到已拒绝的提案上,调用方按幂等
        返回成功,用户看到的却是话题纹丝不动。
        """
        if not threads:
            return None
        rows = self.conn.execute(
            """
            SELECT *
            FROM continuity_proposals
            WHERE kind = ? AND status = ?
            ORDER BY created_at DESC, id DESC
            """,
            ("open_thread", CONFIRMED),
        ).fetchall()
        for row in rows:
            proposal = self._map_proposal(row)
            if any(_is_same_topic(thread, proposal.summary) for thread in threads):
                return proposal
        return None

    async def _model_candidates(
        self,
        *,
        user_message: str,
        assistant_answer: str,
        model_client: Any | None,
    ) -> list[dict[str, Any]]:
        if model_client is None:
            return []
        try:
            text = await model_client.complete(
                user_message=_continuity_model_prompt(user_message, assistant_answer),
                system_prompt=(
                    "你是 reflection_agent。仅返回紧凑的中文 JSON 提案，用于审阅把关的陪伴连续性。"
                    "摘要与证据使用简体中文。不要包含密钥。不要声称任何内容已确认。"
                ),
            )
            payload = json.loads(extract_json_object(str(text), error_code="continuity_json_missing"))
        except Exception:
            logger.warning(
                "Continuity model extraction failed; falling back to deterministic candidates",
                exc_info=True,
                extra={"user_message_length": len(user_message), "assistant_answer_length": len(assistant_answer)},
            )
            return []
        proposals = payload.get("proposals") if isinstance(payload, dict) else payload
        if not isinstance(proposals, list):
            return []
        return [item for item in proposals if isinstance(item, dict)]

    def _is_rejected_topic(self, *, kind: str, summary: str) -> bool:
        rows = self.conn.execute(
            "SELECT summary FROM continuity_proposals WHERE kind = ? AND status = ?",
            (kind, REJECTED),
        ).fetchall()
        return any(_is_same_topic(str(row["summary"]), summary) for row in rows)

    def _insert_candidate(
        self,
        candidate: dict[str, Any],
        *,
        conversation_id: str | None,
        source_message_id: str | None,
        agent_run_id: str | None,
    ) -> ContinuityProposal | None:
        kind = str(candidate["kind"])
        summary = str(candidate["summary"])
        evidence = str(candidate["evidence"])
        confidence = float(candidate["confidence"])
        proposal_hash = _proposal_hash(
            kind=kind,
            summary=summary,
            evidence=evidence,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            agent_run_id=agent_run_id,
        )
        existing = self.conn.execute(
            "SELECT * FROM continuity_proposals WHERE proposal_hash = ?",
            (proposal_hash,),
        ).fetchone()
        if existing is not None:
            proposal = self._map_proposal(existing)
            return proposal if proposal.status == PENDING else None
        if self._is_rejected_topic(kind=kind, summary=summary):
            # 用户拒绝过的话题:即使措辞变了也是同一个话题,不再提案。
            return None

        now = utc_now_iso()
        proposal_id = new_id()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO continuity_proposals (
                    id, proposal_hash, kind, summary, evidence, confidence,
                    source_conversation_id, source_message_id, agent_run_id,
                    status, rejected_reason, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    proposal_hash,
                    kind,
                    summary,
                    evidence,
                    confidence,
                    conversation_id,
                    source_message_id,
                    agent_run_id,
                    PENDING,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO continuity_events (id, proposal_id, action, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id(), proposal_id, "created", None, now),
            )
        return self._map_proposal(self._proposal_row(proposal_id))

    def _apply_confirmed_state(self, proposal: ContinuityProposal, *, updated_at: str) -> None:
        if proposal.kind == "identity":
            self._upsert_state(
                "identity_traits",
                _merge_compact_list(self._state_value("identity_traits"), proposal.summary, limit=6),
                proposal,
                updated_at=updated_at,
            )
        elif proposal.kind == "relationship":
            self._upsert_state("relationship_summary", proposal.summary, proposal, updated_at=updated_at)
        elif proposal.kind == "mood":
            self._upsert_state("current_mood", proposal.summary, proposal, updated_at=updated_at)
            self._upsert_state(
                "mood_momentum",
                f"Latest confirmed mood signal: {proposal.summary}",
                proposal,
                updated_at=updated_at,
            )
            self._upsert_state(
                "recent_emotional_signals",
                _merge_compact_list(self._state_value("recent_emotional_signals"), proposal.summary, limit=4),
                proposal,
                updated_at=updated_at,
            )
        elif proposal.kind == "energy":
            self._upsert_state("energy_level", proposal.summary, proposal, updated_at=updated_at)
        elif proposal.kind == "open_thread":
            self._upsert_state(
                "unresolved_threads",
                _merge_compact_list(self._state_value("unresolved_threads"), proposal.summary, limit=6),
                proposal,
                updated_at=updated_at,
            )

    def _upsert_state(
        self,
        key: str,
        value: str,
        proposal: ContinuityProposal,
        *,
        updated_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO continuity_state (
                state_key, value, confidence, source_proposal_id,
                source_conversation_id, source_message_id, agent_run_id, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                source_proposal_id = excluded.source_proposal_id,
                source_conversation_id = excluded.source_conversation_id,
                source_message_id = excluded.source_message_id,
                agent_run_id = excluded.agent_run_id,
                updated_at = excluded.updated_at
            """,
            (
                key,
                _truncate(value, 800),
                proposal.confidence,
                proposal.id,
                proposal.source_conversation_id,
                proposal.source_message_id,
                proposal.agent_run_id,
                updated_at,
            ),
        )

    def _state_value(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM continuity_state WHERE state_key = ?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row is not None else None

    def _proposal_row(self, proposal_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM continuity_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()

    @staticmethod
    def _map_proposal(row: sqlite3.Row) -> ContinuityProposal:
        return ContinuityProposal(
            id=str(row["id"]),
            kind=str(row["kind"]),
            summary=str(row["summary"]),
            evidence=str(row["evidence"]),
            confidence=float(row["confidence"]),
            source_conversation_id=str(row["source_conversation_id"]) if row["source_conversation_id"] is not None else None,
            source_message_id=str(row["source_message_id"]) if row["source_message_id"] is not None else None,
            agent_run_id=str(row["agent_run_id"]) if row["agent_run_id"] is not None else None,
            status=str(row["status"]),
            rejected_reason=str(row["rejected_reason"]) if row["rejected_reason"] is not None else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _map_state(row: sqlite3.Row) -> ContinuityStateItem:
        return ContinuityStateItem(
            state_key=str(row["state_key"]),
            value=str(row["value"]),
            confidence=float(row["confidence"]),
            source_proposal_id=str(row["source_proposal_id"]) if row["source_proposal_id"] is not None else None,
            source_conversation_id=str(row["source_conversation_id"]) if row["source_conversation_id"] is not None else None,
            source_message_id=str(row["source_message_id"]) if row["source_message_id"] is not None else None,
            agent_run_id=str(row["agent_run_id"]) if row["agent_run_id"] is not None else None,
            updated_at=str(row["updated_at"]),
        )


def _deterministic_candidates(user_message: str, assistant_answer: str) -> list[dict[str, Any]]:
    text = f"{user_message}\n{assistant_answer}"
    normalized = text.casefold()
    candidates: list[dict[str, Any]] = []
    evidence = _evidence_excerpt(user_message)

    for marker, summary, _key in MOOD_TEMPLATES:
        if marker in normalized:
            candidates.append(_candidate("mood", summary, evidence, 0.56))
            break

    for markers, summary, _key, confidence in ENERGY_TEMPLATES:
        if any(marker in normalized for marker in markers):
            candidates.append(_candidate("energy", summary, evidence, confidence))
            break

    if any(marker in normalized for marker in OPEN_THREAD_MARKERS):
        candidates.append(_candidate("open_thread", OPEN_THREAD_TEMPLATE[0], evidence, 0.52))

    if any(marker in normalized for marker in RELATIONSHIP_MARKERS):
        candidates.append(_candidate("relationship", RELATIONSHIP_TEMPLATE[0], evidence, 0.5))

    identity_match = re.search(r"\byour name is ([A-Za-z0-9 _-]{2,40})", normalized)
    if identity_match:
        name = identity_match.group(1).strip()
        candidates.append(
            _candidate(
                "identity",
                f"{IDENTITY_TEMPLATE_PREFIX}{name}{IDENTITY_TEMPLATE_SUFFIX}",
                evidence,
                0.54,
            )
        )

    return candidates[:4]


def _candidate(kind: str, summary: str, evidence: str, confidence: float) -> dict[str, Any]:
    return {
        "kind": kind,
        "summary": summary,
        "evidence": evidence,
        "confidence": confidence,
    }


def _normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(candidate.get("kind", "")).strip()
    if kind not in CONTINUITY_PROPOSAL_KINDS:
        return None
    summary = _truncate(str(candidate.get("summary", "")).strip(), 500)
    evidence = _truncate(str(candidate.get("evidence", "")).strip(), 500)
    if not summary or not evidence:
        return None
    try:
        confidence = float(candidate.get("confidence", 0.45))
    except (TypeError, ValueError):
        confidence = 0.45
    confidence = min(max(confidence, 0.0), 1.0)
    if confidence <= 0:
        return None
    return {
        "kind": kind,
        "summary": summary,
        "evidence": evidence,
        "confidence": confidence,
    }


def _proposal_hash(
    *,
    kind: str,
    summary: str,
    evidence: str,
    conversation_id: str | None,
    source_message_id: str | None,
    agent_run_id: str | None,
) -> str:
    """Content-derived identity for one continuity proposal.

    Identity is (kind, normalized summary) only. Per-turn identifiers
    (message/run/conversation) and the turn's evidence wording are volatile:
    including them makes the same thread a brand-new proposal on every turn,
    so a user rejection could never persist and the topic resurfaced forever
    (see dev.to "why LLM extraction pipelines create duplicate records on
    retry" and llm-message-hash's rule to drop per-call id noise). Evidence
    stays in the row for display; it is not part of the identity.
    """
    del evidence, conversation_id, source_message_id, agent_run_id
    raw = "\n".join([kind.casefold().strip(), " ".join(summary.split()).casefold()])
    return sha256_hex(raw)


def _merge_compact_list(existing: str | None, incoming: str, *, limit: int) -> str:
    items: list[str] = []
    for value in [*(existing or "").split(" | "), incoming]:
        compact = value.strip()
        if not compact:
            continue
        if compact.casefold() in {item.casefold() for item in items}:
            continue
        items.append(compact)
    return " | ".join(items[-limit:])


def _state_text(state: dict[str, ContinuityStateItem], key: str) -> str:
    item = state.get(key)
    return item.value.strip() if item is not None else ""


def _continuity_model_prompt(user_message: str, assistant_answer: str) -> str:
    return (
        "审查本轮对话，仅提议需要展示给用户确认的连续性更新。\n"
        "返回 JSON：{\"proposals\":[{\"kind\":\"identity|relationship|mood|energy|open_thread\","
        "\"summary\":\"简短中文陈述\",\"evidence\":\"简短中文证据摘录\",\"confidence\":0.0}]}\n"
        "摘要与证据使用简体中文。避免普通事实、密钥和长篇日记文字。待处理提案不是活跃记忆。\n\n"
        f"用户消息：\n{_truncate(user_message, 1600)}\n\n助手回复：\n{_truncate(assistant_answer, 1600)}"
    )




def _evidence_excerpt(text: str) -> str:
    compact = " ".join(text.split())
    return _truncate(compact, 240) or "聊天片段"


def _truncate(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."
