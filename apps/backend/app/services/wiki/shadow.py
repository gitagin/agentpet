"""Opt-in query evaluation; never runs the chat, archive or action graph."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.agents.memory_router import explicit_memory_read_scopes
from app.agents.nodes.wiki_retrieval import wiki_knowledge_retrieval_node
from app.agents.services import AgentRuntimeServices, WikiFallbackServiceProtocol
from app.agents.state import AgentState
from app.models.enums import AgentId
from app.models.config import WikiShadowSummary


_STATE_KEY = "wiki_shadow_metrics_v1"


class ShadowMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["reserved", "completed", "failed", "interrupted"] = "reserved"
    old_citation_count: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    page_read_count: int = Field(default=0, ge=0)
    note_read_count: int = Field(default=0, ge=0)
    evidence_chars: int = Field(default=0, ge=0)
    assessment_calls: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    authority: Literal["not_checked", "passed", "denied"] = "not_checked"
    freshness: Literal["unknown"] = "unknown"
    coverage: Literal["not_assessed", "partial", "model_assessed_complete"] = "not_assessed"
    conflict: Literal["not_assessed", "disputed", "none_detected_by_model"] = "not_assessed"
    budget_exhausted: bool = False
    correctness: Literal["unknown"] = "unknown"
    # complete() does not expose provider usage; character counts are not tokens.
    token_count: None = None


class ShadowMetricStore:
    """Small bounded local records in the existing app_state store."""

    def __init__(self, database):
        self.database = database

    def _load(self, conn, now):
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (_STATE_KEY,)).fetchone()
        records = json.loads(row["value"]) if row else []
        cutoff = (now - timedelta(days=7)).isoformat()
        return [item for item in records if item["created_at"] > cutoff]

    def _save(self, conn, records, now):
        conn.execute(
            "INSERT INTO app_state(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (_STATE_KEY, json.dumps(records), now.isoformat()),
        )

    def reserve(self, *, now=None):
        now = now or datetime.now(timezone.utc)
        with self.database.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            records = self._load(conn, now)
            today = now.date().isoformat()
            if sum(item["created_at"][:10] == today for item in records) >= 20:
                self._save(conn, records, now)
                return None
            sample_id = str(uuid4())
            records.append({
                "id": sample_id, "created_at": now.isoformat(),
                "metrics": ShadowMetrics().model_dump(mode="json"),
            })
            self._save(conn, records, now)
            return sample_id

    def finish(self, sample_id, metrics: ShadowMetrics, *, now=None):
        # Validate again at the storage boundary, including model_construct callers.
        metrics = ShadowMetrics.model_validate(metrics.model_dump(mode="json"))
        now = now or datetime.now(timezone.utc)
        with self.database.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            records = self._load(conn, now)
            for item in records:
                if item["id"] == sample_id:
                    item["metrics"] = metrics.model_dump(mode="json")
                    break
            self._save(conn, records, now)

    def prune(self, *, now=None):
        now = now or datetime.now(timezone.utc)
        with self.database.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._save(conn, self._load(conn, now), now)

    def summary(self, *, now=None) -> WikiShadowSummary:
        now = now or datetime.now(timezone.utc)
        result = WikiShadowSummary()
        try:
            with self.database.session(read_only=True) as conn:
                row = conn.execute("SELECT value FROM app_state WHERE key = ?", (_STATE_KEY,)).fetchone()
            raw = row["value"] if row else "[]"
            if len(raw) > 1_000_000:
                return WikiShadowSummary(available=False)
            records = json.loads(raw)
            if not isinstance(records, list):
                return WikiShadowSummary(available=False)
        except Exception:
            return WikiShadowSummary(available=False)
        latencies = []
        for record in records:
            try:
                created = datetime.fromisoformat(record["created_at"])
                if created.tzinfo is None:
                    raise ValueError("shadow_timestamp_timezone_missing")
                if not now - timedelta(days=7) < created <= now:
                    continue
                metrics = ShadowMetrics.model_validate(record["metrics"])
            except (TypeError, ValueError, KeyError):
                result.invalid_records += 1
                continue
            result.samples += 1
            result.today_samples += int(created.astimezone(timezone.utc).date() == now.date())
            if metrics.status == "reserved":
                result.unfinished += 1
            elif metrics.status == "failed":
                result.failed += 1
            elif metrics.status == "interrupted":
                result.interrupted += 1
            else:
                result.completed += 1
                result.wiki_hits += int(metrics.page_read_count > 0)
                result.note_fallbacks += int(metrics.note_read_count > 0)
                result.authority_denied += int(metrics.authority == "denied")
                result.coverage_complete += int(metrics.coverage == "model_assessed_complete")
                result.disputed += int(metrics.conflict == "disputed")
                result.budget_exhausted += int(metrics.budget_exhausted)
                result.assessment_calls += metrics.assessment_calls
                result.evidence_chars += metrics.evidence_chars
                latencies.append(metrics.latency_ms)
        result.mean_latency_ms = round(sum(latencies) / len(latencies)) if latencies else None
        return result


def shadow_eligible(state: AgentState, *, enabled: bool = False) -> bool:
    semantic = state.semantic_analysis
    explicit = explicit_memory_read_scopes(state.user_message)
    return (
        enabled is True
        and not state.local_privacy_mode
        and not state.suppress_post_reply_automation
        and not state.action_plan
        and not state.action_plans
        and semantic is not None
        and semantic.needs_context
        and semantic.source_scope == "knowledge_base"
        and (not explicit or "knowledge_base" in explicit)
        and bool(state.agent_run_id)
        and int(hashlib.sha256(state.agent_run_id.encode()).hexdigest()[:8], 16) % 10 == 0
    )


class _ReadOnlyServices:
    """Expose only the query node's read capabilities and approved model."""

    def __init__(self, services, model, permitted):
        self._services = services
        self._model = model
        self._permitted = permitted
        self.wiki_reader = self
        self.model_registry = self
        self.retrieval = self if isinstance(services.retrieval, WikiFallbackServiceProtocol) else None

    def _check(self):
        if self._permitted() is not True:
            raise PermissionError("shadow_no_longer_allowed")

    async def _call(self, method, *args, **kwargs):
        self._check()
        result = await method(*args, **kwargs)
        self._check()
        return result

    async def search_pages(self, *args, **kwargs):
        return await self._call(self._services.wiki_reader.search_pages, *args, **kwargs)

    async def read_page(self, *args, **kwargs):
        return await self._call(self._services.wiki_reader.read_page, *args, **kwargs)

    async def check_source_watermark(self, *args, **kwargs):
        return await self._call(self._services.wiki_reader.check_source_watermark, *args, **kwargs)

    async def search_vault_notes(self, *args, **kwargs):
        return await self._call(self._services.retrieval.search_vault_notes, *args, **kwargs)

    async def restore_vault_notes(self, *args, **kwargs):
        return await self._call(self._services.retrieval.restore_vault_notes, *args, **kwargs)

    def get(self, agent_id):
        self._check()
        if agent_id != AgentId.RETRIEVAL_AGENT:
            raise PermissionError("shadow_model_not_allowed")
        return self

    async def complete(self, **kwargs):
        return await self._call(self._model.complete, **kwargs)


class WikiShadowEvaluator:
    """One instance per app; busy evaluations are skipped, never queued."""

    def __init__(self, store: ShadowMetricStore):
        self.store = store
        self._busy = False

    async def evaluate(self, state, services: AgentRuntimeServices, *, permitted, old_citation_count=None):
        # The caller must include live opt-in, privacy and foreground-idle checks.
        if self._busy or not shadow_eligible(state, enabled=permitted()):
            return "skipped"
        if services.wiki_reader is None or services.model_registry is None:
            return "skipped"
        self._busy = True
        sample_id = None
        started = time.monotonic()
        baseline_count = len(state.citations) if old_citation_count is None else max(0, int(old_citation_count))
        metrics = ShadowMetrics(status="failed", old_citation_count=baseline_count)
        try:
            model = services.model_registry.get(AgentId.RETRIEVAL_AGENT)
            if model is None:
                return "skipped"
            sample_id = self.store.reserve()
            if sample_id is None:
                return "quota_exhausted"
            # Do not clone foreground answers, personal context, actions or events.
            isolated = AgentState(
                conversation_id="shadow", message_id="shadow", agent_run_id="shadow",
                user_message=state.user_message,
                semantic_analysis=state.semantic_analysis.model_copy(deep=True),
            )
            graph = {"agent_state": isolated, "events": []}
            readonly = _ReadOnlyServices(services, model, permitted)
            await asyncio.wait_for(wiki_knowledge_retrieval_node(graph, readonly), timeout=35)
            readonly._check()
            report = graph.get("wiki_reading", {})
            gate = isolated.wiki_evidence_gate
            metrics = ShadowMetrics(
                status="completed", old_citation_count=baseline_count,
                candidate_count=len(report.get("retrieved", [])),
                page_read_count=len(report.get("read", [])),
                note_read_count=len(report.get("fallback_read", [])),
                evidence_chars=report.get("used_chars", 0),
                assessment_calls=report.get("assessment_calls", 0),
                authority=gate.authority if gate else "not_checked",
                freshness=gate.freshness if gate else "unknown",
                coverage=gate.coverage if gate else "not_assessed",
                conflict=gate.conflict if gate else "not_assessed",
                budget_exhausted=gate.budget_exhausted if gate else False,
            )
            return "completed"
        except asyncio.CancelledError:
            metrics.status = "interrupted"
            raise
        except Exception:
            # Exception text can contain queries, paths or provider response bodies.
            return "failed"
        finally:
            try:
                if sample_id:
                    metrics.latency_ms = max(0, int((time.monotonic() - started) * 1000))
                    self.store.finish(sample_id, metrics)
            finally:
                self._busy = False
