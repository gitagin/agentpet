from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Protocol

from app.agents.memory_router import MemoryRoute, route_memory
from app.models.api import MemorySearchResponse, MemorySearchResult
from app.models.common import new_id
from app.models.enums import MemoryFactStatus
from app.models.event_payloads import ContextBudgetData
from app.services.diary_memory import DiaryMemorySearch, DiaryMemoryStore, diary_records_to_search_results
from app.services.memory_graph import MemoryGraphStore, facts_to_context_lines
from app.services.memory_policy import evaluate_memory_content
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso


COMPANION_RETRIEVAL_SCOPES = {
    "personal_memory",
    "diary_objects",
    "daily_chat",
    "knowledge_base",
    "graph_facts",
}


class VaultRetrievalService(Protocol):
    def search(
        self,
        *,
        vault_id: str,
        query: str,
        top_k: int = 8,
        source_scope: str = "all",
        mode: str = "hybrid",
    ) -> MemorySearchResponse:
        ...


@dataclass(frozen=True, slots=True)
class CompanionRetrievalBudget:
    max_items: int = 8
    max_context_chars: int = 1400
    max_item_chars: int = 280
    max_graph_facts: int = 4
    max_diary_objects: int = 4
    max_vault_results_per_scope: int = 4


@dataclass(frozen=True, slots=True)
class CompanionRetrievedItem:
    item_id: str
    source_scope: str
    source_id: str
    source_hash: str
    title: str
    text: str
    score: float
    retrieval_mode: str


@dataclass(frozen=True, slots=True)
class CompanionRetrievalTelemetry:
    event_id: str
    query_hash: str
    route_scopes: tuple[str, ...]
    result_ids: tuple[str, ...]
    result_hashes: tuple[str, ...]
    budget: dict[str, int]
    counts: dict[str, int]
    created_at: str


@dataclass(frozen=True, slots=True)
class CompanionRetrievalResult:
    event_id: str
    route: MemoryRoute
    items: tuple[CompanionRetrievedItem, ...]
    context_block: str
    telemetry: CompanionRetrievalTelemetry


class CompanionRetrievalService:
    """Higher-level retrieval draft with reranking, compression, and safe telemetry."""

    def __init__(
        self,
        *,
        vault_retrieval: VaultRetrievalService | None = None,
        diary_store: DiaryMemoryStore | None = None,
        graph_store: MemoryGraphStore | None = None,
        telemetry_db: str | Path | sqlite3.Connection | None = None,
    ):
        self.vault_retrieval = vault_retrieval
        self.diary_store = diary_store
        self.graph_store = graph_store
        if telemetry_db is None and graph_store is not None:
            telemetry_db = graph_store.conn
        self._owns_connection = not isinstance(telemetry_db, sqlite3.Connection)
        self.conn = sqlite3.connect(telemetry_db or ":memory:") if self._owns_connection else telemetry_db
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def retrieve(
        self,
        *,
        vault_id: str,
        query: str,
        route: MemoryRoute | None = None,
        budget: CompanionRetrievalBudget | None = None,
    ) -> CompanionRetrievalResult:
        active_budget = budget or CompanionRetrievalBudget()
        active_route = route or route_memory(query)
        scopes = _normalize_scopes(active_route.all_scopes)
        raw_items: list[CompanionRetrievedItem] = []
        skipped_sensitive = 0

        if "graph_facts" in scopes or "personal_memory" in scopes or "diary_objects" in scopes:
            graph_items, skipped = self._graph_items(query, budget=active_budget)
            raw_items.extend(graph_items)
            skipped_sensitive += skipped
        if "diary_objects" in scopes:
            diary_items, skipped = self._diary_items(vault_id, query, budget=active_budget)
            raw_items.extend(diary_items)
            skipped_sensitive += skipped
        for scope in ("personal_memory", "daily_chat", "knowledge_base"):
            if scope not in scopes:
                continue
            vault_items, skipped = self._vault_items(vault_id, query, scope=scope, budget=active_budget)
            raw_items.extend(vault_items)
            skipped_sensitive += skipped

        items = tuple(_rerank_and_dedupe(raw_items, budget=active_budget))
        context_block = _context_block(items, budget=active_budget)
        telemetry = self._record_telemetry(
            query=query,
            route_scopes=scopes,
            items=items,
            budget=active_budget,
            skipped_sensitive=skipped_sensitive,
            raw_count=len(raw_items),
        )
        return CompanionRetrievalResult(
            event_id=telemetry.event_id,
            route=active_route,
            items=items,
            context_block=context_block,
            telemetry=telemetry,
        )

    def list_telemetry(self) -> list[CompanionRetrievalTelemetry]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM companion_retrieval_events
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()
        return [self._map_telemetry(row) for row in rows]

    def _graph_items(
        self,
        query: str,
        *,
        budget: CompanionRetrievalBudget,
    ) -> tuple[list[CompanionRetrievedItem], int]:
        if self.graph_store is None:
            return [], 0
        facts = self.graph_store.search_active(query, limit=budget.max_graph_facts)
        if not facts:
            facts = _dedupe_graph_facts(
                fact
                for term in _significant_terms(query)
                for fact in self.graph_store.search_active(term, limit=budget.max_graph_facts)
            )[: budget.max_graph_facts]
        active_facts = [fact for fact in facts if fact.status == MemoryFactStatus.ACTIVE]
        lines = facts_to_context_lines(active_facts)
        items: list[CompanionRetrievedItem] = []
        skipped = 0
        for fact, line in zip(active_facts, lines):
            text = _context_text(line, limit=budget.max_item_chars)
            if _is_sensitive(text):
                skipped += 1
                continue
            items.append(
                CompanionRetrievedItem(
                    item_id=f"graph:{fact.id}",
                    source_scope="graph_facts",
                    source_id=fact.id,
                    source_hash=_hash_text(fact.fact_key),
                    title="Memory Graph Fact",
                    text=text,
                    score=fact.importance + fact.confidence + min(fact.support_count, 5) * 0.05,
                    retrieval_mode="graph_active",
                )
            )
        return items, skipped

    def _diary_items(
        self,
        vault_id: str,
        query: str,
        *,
        budget: CompanionRetrievalBudget,
    ) -> tuple[list[CompanionRetrievedItem], int]:
        if self.diary_store is None:
            return [], 0
        records = self.diary_store.search(
            DiaryMemorySearch(query=query, top_k=budget.max_diary_objects),
            vault_id=vault_id,
        )
        active_records = [record for record in records if record.status == MemoryFactStatus.ACTIVE]
        results = diary_records_to_search_results(active_records)
        return _items_from_memory_results(results, item_limit=budget.max_item_chars)

    def _vault_items(
        self,
        vault_id: str,
        query: str,
        *,
        scope: str,
        budget: CompanionRetrievalBudget,
    ) -> tuple[list[CompanionRetrievedItem], int]:
        if self.vault_retrieval is None:
            return [], 0
        response = self.vault_retrieval.search(
            vault_id=vault_id,
            query=query,
            top_k=budget.max_vault_results_per_scope,
            source_scope=scope,
            mode="hybrid",
        )
        return _items_from_memory_results(response.results, item_limit=budget.max_item_chars)

    def _record_telemetry(
        self,
        *,
        query: str,
        route_scopes: tuple[str, ...],
        items: tuple[CompanionRetrievedItem, ...],
        budget: CompanionRetrievalBudget,
        skipped_sensitive: int,
        raw_count: int,
    ) -> CompanionRetrievalTelemetry:
        event_id = new_id()
        now = utc_now_iso()
        telemetry = CompanionRetrievalTelemetry(
            event_id=event_id,
            query_hash=_hash_text(query),
            route_scopes=route_scopes,
            result_ids=tuple(item.item_id for item in items),
            result_hashes=tuple(item.source_hash for item in items),
            budget=asdict(budget),
            counts={
                "raw_items_seen": raw_count,
                "items_returned": len(items),
                "sensitive_items_skipped": skipped_sensitive,
                "context_chars": len(_context_block(items, budget=budget)),
            },
            created_at=now,
        )
        self.conn.execute(
            """
            INSERT INTO companion_retrieval_events (
                id, query_hash, route_scopes_json, result_ids_json,
                result_hashes_json, budget_json, counts_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telemetry.event_id,
                telemetry.query_hash,
                _json_list(telemetry.route_scopes),
                _json_list(telemetry.result_ids),
                _json_list(telemetry.result_hashes),
                _json_object(telemetry.budget),
                _json_object(telemetry.counts),
                telemetry.created_at,
            ),
        )
        self.conn.commit()
        return telemetry

    @staticmethod
    def _map_telemetry(row: sqlite3.Row) -> CompanionRetrievalTelemetry:
        return CompanionRetrievalTelemetry(
            event_id=str(row["id"]),
            query_hash=str(row["query_hash"]),
            route_scopes=tuple(_json_list_value(row["route_scopes_json"])),
            result_ids=tuple(_json_list_value(row["result_ids_json"])),
            result_hashes=tuple(_json_list_value(row["result_hashes_json"])),
            budget={key: int(value) for key, value in _json_object_value(row["budget_json"]).items()},
            counts={key: int(value) for key, value in _json_object_value(row["counts_json"]).items()},
            created_at=str(row["created_at"]),
        )


def _items_from_memory_results(
    results: Iterable[MemorySearchResult],
    *,
    item_limit: int,
) -> tuple[list[CompanionRetrievedItem], int]:
    items: list[CompanionRetrievedItem] = []
    skipped = 0
    for result in results:
        text = _context_text(result.snippet, limit=item_limit)
        if _is_sensitive(text):
            skipped += 1
            continue
        source_id = f"{result.note_id}:{result.chunk_id}"
        items.append(
            CompanionRetrievedItem(
                item_id=f"{result.source_scope}:{source_id}",
                source_scope=result.source_scope,
                source_id=source_id,
                source_hash=_hash_text(f"{result.relative_path}\n{result.chunk_id}\n{text}"),
                title=result.title,
                text=text,
                score=float(result.score),
                retrieval_mode=result.retrieval_mode,
            )
        )
    return items, skipped


def _rerank_and_dedupe(
    items: Iterable[CompanionRetrievedItem],
    *,
    budget: CompanionRetrievalBudget,
) -> list[CompanionRetrievedItem]:
    seen: set[str] = set()
    weighted: list[tuple[float, CompanionRetrievedItem]] = []
    for item in items:
        if item.source_hash in seen:
            continue
        seen.add(item.source_hash)
        weight = _scope_weight(item.source_scope) + item.score
        weighted.append((weight, item))
    weighted.sort(key=lambda pair: (-pair[0], pair[1].source_scope, pair[1].item_id))
    return [item for _, item in weighted[: max(1, budget.max_items)]]


def _context_block(items: tuple[CompanionRetrievedItem, ...], *, budget: CompanionRetrievalBudget) -> str:
    if not items:
        return ""
    lines = ["Companion retrieval context:"]
    remaining = max(0, budget.max_context_chars - len(lines[0]))
    for item in items:
        line = f"- [{item.source_scope}] {item.text}"
        if len(line) + 1 > remaining:
            if remaining <= 8:
                break
            line = _context_text(line, limit=remaining - 1)
        lines.append(line)
        remaining -= len(line) + 1
        if remaining <= 0:
            break
    lines.append("Use this context only when relevant; candidate graph facts are not confirmed memory.")
    block = "\n".join(lines)
    return block[: budget.max_context_chars]


def _normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for scope in scopes:
        if scope == "none":
            continue
        if scope == "all":
            candidates = ("personal_memory", "diary_objects", "daily_chat", "knowledge_base", "graph_facts")
        else:
            candidates = (scope,)
        for candidate in candidates:
            if candidate not in COMPANION_RETRIEVAL_SCOPES or candidate in normalized:
                continue
            normalized.append(candidate)
    return tuple(normalized)


def _scope_weight(scope: str) -> float:
    return {
        "graph_facts": 4.0,
        "diary_objects": 3.5,
        "personal_memory": 3.0,
        "knowledge_base": 2.0,
        "daily_chat": 1.0,
    }.get(scope, 0.0)


def _dedupe_graph_facts(facts):
    seen: set[str] = set()
    deduped = []
    for fact in facts:
        if fact.id in seen:
            continue
        seen.add(fact.id)
        deduped.append(fact)
    return deduped


def _significant_terms(query: str) -> tuple[str, ...]:
    stop_words = {
        "about",
        "does",
        "what",
        "when",
        "where",
        "which",
    }
    terms = []
    for raw in query.replace("?", " ").replace(",", " ").split():
        term = raw.strip().casefold()
        if len(term) < 3 or term in stop_words:
            continue
        terms.append(term)
    return tuple(dict.fromkeys(terms))


def _context_text(value: str, *, limit: int) -> str:
    compacted = " ".join(value.strip().split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: max(0, limit - 3)].rstrip() + "..."


def _is_sensitive(value: str) -> bool:
    return not evaluate_memory_content(value).allowed


def _hash_text(value: str) -> str:
    return sha256_hex(value)


def _json_list(values: Iterable[str]) -> str:
    return json.dumps(list(values), sort_keys=True, separators=(",", ":"))


def _json_object(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_list_value(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _json_object_value(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


DEFAULT_CONTEXT_STRATEGY = "deterministic_v1"
DEFAULT_CONTEXT_CHAR_BUDGET = 1200


@dataclass(frozen=True, slots=True)
class CompanionContextBudgetTelemetry(ContextBudgetData):
    pass


@dataclass(frozen=True, slots=True)
class CompanionRerankResult:
    selected: tuple[MemorySearchResult, ...]
    telemetry: CompanionContextBudgetTelemetry


@dataclass(frozen=True, slots=True)
class CompanionRetrievalReport:
    id: str
    agent_run_id: str
    strategy: str
    candidate_count: int
    selected_count: int
    duplicate_drop_count: int
    per_scope_drop_count: int
    budget_drop_count: int
    item_budget: int
    per_scope_limit: int
    char_budget: int
    used_chars: int
    source_counts: dict[str, int]
    selected_scopes: tuple[str, ...]
    created_at: str


class CompanionRetrievalReportStore:
    """Stores context budget telemetry without raw prompts or snippets."""

    def __init__(self, db: str | Path | sqlite3.Connection | None = None) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db or ":memory:") if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def record(
        self,
        *,
        agent_run_id: str,
        query: str,
        telemetry: CompanionContextBudgetTelemetry,
    ) -> CompanionRetrievalReport:
        report_id = new_id()
        created_at = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO companion_retrieval_reports (
                id, agent_run_id, strategy, query_hash, candidate_count, selected_count,
                duplicate_drop_count, per_scope_drop_count, budget_drop_count,
                item_budget, per_scope_limit, char_budget, used_chars,
                source_counts_json, selected_scopes_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                agent_run_id,
                telemetry.strategy,
                _hash_text(query),
                telemetry.candidate_count,
                telemetry.selected_count,
                telemetry.duplicate_drop_count,
                telemetry.per_scope_drop_count,
                telemetry.budget_drop_count,
                telemetry.item_budget,
                telemetry.per_scope_limit,
                telemetry.char_budget,
                telemetry.used_chars,
                _json_object(telemetry.source_counts),
                _json_list(telemetry.selected_scopes),
                created_at,
            ),
        )
        self.conn.commit()
        return self._get(report_id)

    def list_reports(
        self,
        *,
        agent_run_id: str | None = None,
        limit: int = 20,
    ) -> list[CompanionRetrievalReport]:
        clauses: list[str] = []
        params: list[object] = []
        if agent_run_id:
            clauses.append("agent_run_id = ?")
            params.append(agent_run_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM companion_retrieval_reports
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (*params, max(1, min(limit, 100))),
        ).fetchall()
        return [self._map_report(row) for row in rows]

    def _get(self, report_id: str) -> CompanionRetrievalReport:
        row = self.conn.execute(
            "SELECT * FROM companion_retrieval_reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        if row is None:
            raise KeyError(report_id)
        return self._map_report(row)

    @staticmethod
    def _map_report(row: sqlite3.Row) -> CompanionRetrievalReport:
        return CompanionRetrievalReport(
            id=str(row["id"]),
            agent_run_id=str(row["agent_run_id"]),
            strategy=str(row["strategy"]),
            candidate_count=int(row["candidate_count"]),
            selected_count=int(row["selected_count"]),
            duplicate_drop_count=int(row["duplicate_drop_count"]),
            per_scope_drop_count=int(row["per_scope_drop_count"]),
            budget_drop_count=int(row["budget_drop_count"]),
            item_budget=int(row["item_budget"]),
            per_scope_limit=int(row["per_scope_limit"]),
            char_budget=int(row["char_budget"]),
            used_chars=int(row["used_chars"]),
            source_counts={key: int(value) for key, value in _json_object_value(row["source_counts_json"]).items()},
            selected_scopes=tuple(_json_list_value(row["selected_scopes_json"])),
            created_at=str(row["created_at"]),
        )


def rerank_memory_context(
    results: Iterable[MemorySearchResult],
    *,
    preferred_scopes: Iterable[str],
    limit: int = 5,
    per_scope_limit: int = 2,
    char_budget: int = DEFAULT_CONTEXT_CHAR_BUDGET,
) -> CompanionRerankResult:
    candidates = list(results)
    source_counts: dict[str, int] = {}
    for item in candidates:
        source_counts[item.source_scope] = source_counts.get(item.source_scope, 0) + 1

    preferred_order = {scope: index for index, scope in enumerate(preferred_scopes)}
    deduped: list[MemorySearchResult] = []
    seen: set[str] = set()
    duplicate_drop_count = 0
    for item in sorted(
        candidates,
        key=lambda candidate: (
            preferred_order.get(candidate.source_scope, len(preferred_order)),
            -float(candidate.score),
            candidate.relative_path,
            candidate.chunk_id,
        ),
    ):
        dedupe_key = _memory_result_key(item)
        if dedupe_key in seen:
            duplicate_drop_count += 1
            continue
        seen.add(dedupe_key)
        deduped.append(item)

    per_scope_seen: dict[str, int] = {}
    selected: list[MemorySearchResult] = []
    per_scope_drop_count = 0
    budget_drop_count = 0
    used_chars = 0
    item_budget = max(1, limit)
    scope_budget = max(1, per_scope_limit)
    max_chars = max(1, char_budget)
    for item in deduped:
        if len(selected) >= item_budget:
            budget_drop_count += 1
            continue
        scope_seen = per_scope_seen.get(item.source_scope, 0)
        if scope_seen >= scope_budget:
            per_scope_drop_count += 1
            continue
        item_chars = _memory_result_context_chars(item)
        if used_chars + item_chars > max_chars:
            budget_drop_count += 1
            continue
        per_scope_seen[item.source_scope] = scope_seen + 1
        selected.append(item)
        used_chars += item_chars

    telemetry = CompanionContextBudgetTelemetry(
        strategy=DEFAULT_CONTEXT_STRATEGY,
        candidate_count=len(candidates),
        selected_count=len(selected),
        duplicate_drop_count=duplicate_drop_count,
        per_scope_drop_count=per_scope_drop_count,
        budget_drop_count=budget_drop_count,
        item_budget=item_budget,
        per_scope_limit=scope_budget,
        char_budget=max_chars,
        used_chars=used_chars,
        source_counts=source_counts,
        selected_scopes=tuple(item.source_scope for item in selected),
    )
    return CompanionRerankResult(selected=tuple(selected), telemetry=telemetry)


def _memory_result_key(item: MemorySearchResult) -> str:
    snippet = " ".join(item.snippet.split()).casefold()
    if snippet:
        return f"snippet:{item.source_scope}:{item.relative_path}:{snippet}"
    return f"source:{item.source_scope}:{item.relative_path}:{item.chunk_id}"


def _memory_result_context_chars(item: MemorySearchResult) -> int:
    return len(item.snippet)
