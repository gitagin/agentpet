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
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso


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


class ContinuityService:
    """Review-gated runtime continuity store.

    This service writes only compact SQLite state and audit rows. It does not
    write Markdown, touch the Vault index, or promote pending proposals into
    prompt context.
    """

    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
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
        for candidate in candidates:
            normalized = _normalize_candidate(candidate)
            if normalized is None:
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
            ("identity_traits", "identity traits"),
            ("relationship_summary", "relationship summary"),
            ("current_mood", "current mood"),
            ("mood_momentum", "mood momentum"),
            ("energy_level", "energy level"),
            ("unresolved_threads", "unresolved threads"),
            ("recent_emotional_signals", "recent emotional signals"),
        )
        lines = ["Confirmed continuity context (user-reviewed; compact runtime state):"]
        for key, label in labels:
            item = state.get(key)
            if item is None or not item.value.strip():
                continue
            lines.append(f"- {label}: {_truncate(item.value, 220)}")
        if len(lines) == 1:
            return ""
        lines.append("Use this only when relevant; never treat pending continuity proposals as confirmed memory.")
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
            "Companion presence behavior:",
            "- Carry confirmed continuity with high presence, but keep it natural and brief.",
            "- You may gently reference confirmed mood, energy, relationship, identity, or unresolved threads when relevant.",
            "- Do not claim pending or rejected proposals are memory.",
            "- Do not say anything was written to Vault, Markdown, tasks, or reminders unless a tool event confirms it.",
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
            return ContinuitySignal(
                kind="open_thread",
                title="有个话题还没收好",
                summary=f"我还记着这个未完话题：{_truncate(unresolved, 180)}",
                intensity="high",
                display_hint="可以在这次对话里自然接上，不需要创建提醒或写入 Vault。",
                source_state_keys=("unresolved_threads",),
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
            return proposal
        if proposal.status != PENDING:
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
            self.conn.execute(
                """
                INSERT INTO continuity_events (id, proposal_id, action, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id(), proposal_id, REJECTED, compact_reason, now),
            )
        return self._map_proposal(self._proposal_row(proposal_id))

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
                    "You are continuity_agent. Return only compact JSON proposals for "
                    "review-gated companion continuity. Do not include secrets. Do not "
                    "claim anything is confirmed."
                ),
            )
            payload = json.loads(_extract_json_object(str(text)))
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

    mood_markers = {
        "tired": "User sounds tired or depleted.",
        "exhausted": "User sounds exhausted.",
        "sad": "User signaled sadness.",
        "lonely": "User signaled loneliness.",
        "stressed": "User signaled stress.",
        "anxious": "User signaled anxiety.",
        "worried": "User signaled worry.",
        "happy": "User signaled positive mood.",
        "excited": "User signaled excitement.",
        "angry": "User signaled anger.",
        "overwhelmed": "User signaled overwhelm.",
    }
    for marker, summary in mood_markers.items():
        if marker in normalized:
            candidates.append(_candidate("mood", summary, evidence, 0.56))
            break

    if any(marker in normalized for marker in ("tired", "exhausted", "sleepy", "low energy", "burned out")):
        candidates.append(_candidate("energy", "User appears to be in a low-energy state.", evidence, 0.53))
    elif any(marker in normalized for marker in ("energized", "high energy", "motivated")):
        candidates.append(_candidate("energy", "User appears to be in a higher-energy state.", evidence, 0.5))

    if any(marker in normalized for marker in ("continue this", "continue tomorrow", "tomorrow", "next time", "later", "pick this up", "unfinished")):
        candidates.append(_candidate("open_thread", "There is an unresolved thread to continue later.", evidence, 0.52))

    if any(marker in normalized for marker in ("thank you", "thanks", "you helped", "i trust you", "companion", "stay with me")):
        candidates.append(_candidate("relationship", "User expressed trust or appreciation toward the companion.", evidence, 0.5))

    identity_match = re.search(r"\byour name is ([A-Za-z0-9 _-]{2,40})", normalized)
    if identity_match:
        name = identity_match.group(1).strip()
        candidates.append(_candidate("identity", f"Companion identity name signal: {name}.", evidence, 0.54))

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
    raw = "\n".join(
        [
            kind,
            summary.casefold().strip(),
            evidence.casefold().strip(),
            conversation_id or "",
            source_message_id or "",
            agent_run_id or "",
        ]
    )
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
        "Review the exchange and propose only continuity updates that should be shown to the user for confirmation.\n"
        "Return JSON: {\"proposals\":[{\"kind\":\"identity|relationship|mood|energy|open_thread\","
        "\"summary\":\"compact statement\",\"evidence\":\"short source excerpt\",\"confidence\":0.0}]}\n"
        "Avoid ordinary facts, secrets, and long diary text. Pending proposals are not active memory.\n\n"
        f"User message:\n{_truncate(user_message, 1600)}\n\nAssistant answer:\n{_truncate(assistant_answer, 1600)}"
    )


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("continuity_json_missing")
    return text[start : end + 1]


def _evidence_excerpt(text: str) -> str:
    compact = " ".join(text.split())
    return _truncate(compact, 240) or "chat exchange"


def _truncate(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."
