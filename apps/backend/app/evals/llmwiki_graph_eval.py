"""Deterministic LLM Wiki graph and lifecycle evaluation.

The fixture is synthetic. SQLite remains authoritative, Kuzu is evaluated as
an optional projection, and model extraction/synthesis is deliberately outside
this runner because no fixed model observation is available.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
import re
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.memory_entity_graph import ENTITY_TYPES, RELATION_TYPES, MemoryEntityGraphStore
from app.services.memory_graph import MemoryFactCandidate
from app.services.memory_graph_kuzu import KuzuGraphService
from app.storage.database import Database, MigrationRunner


DATASET_SCHEMA_VERSION = "llmwiki-graph-eval-dataset.v1"
REPORT_SCHEMA_VERSION = "llmwiki-graph-eval-report.v1"
EVALUATOR_VERSION = "llmwiki-graph-eval.v1"
REQUIRED_LIFECYCLE_TAGS = frozenset(
    {
        "preference",
        "boundary",
        "project",
        "goal",
        "event",
        "duplicate_evidence",
        "correction",
        "forgotten",
        "conflict",
        "expired",
        "sensitive",
    }
)
FACT_STATUSES = frozenset(
    {"active", "candidate", "stale", "quarantined", "superseded", "rejected", "forgotten", "archived"}
)
OPERATION_TYPES = frozenset({"replay_relation", "correct_relation", "forget_entity", "correct_claim"})
QUERY_KINDS = frozenset({"traverse", "facts"})
PROHIBITED_FIXTURE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:ghp_|gho_|ghu_|github_pat_|xoxb-|AKIA)[A-Za-z0-9_-]+\b"),
    re.compile(r"\b(?:password|passwd|pwd|secret|token|api_key)\s*=", re.IGNORECASE),
    re.compile(r"\b[A-Za-z]:[\\/]"),
    re.compile(r"(?<![A-Za-z0-9])/(?:home|root|Users)/", re.IGNORECASE),
)


class GraphEvaluationContractError(ValueError):
    pass


def load_graph_fixture(path: Path) -> dict[str, Any]:
    serialized = path.read_text(encoding="utf-8")
    if any(pattern.search(serialized) for pattern in PROHIBITED_FIXTURE_PATTERNS):
        raise GraphEvaluationContractError("graph fixture contains a prohibited private field")
    raw = json.loads(serialized)
    if not isinstance(raw, dict):
        raise GraphEvaluationContractError("graph fixture root must be an object")
    if raw.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise GraphEvaluationContractError("unsupported graph fixture schema")
    if raw.get("synthetic_only") is not True:
        raise GraphEvaluationContractError("graph fixture must be synthetic_only")
    if not _required_str(raw, "corpus_version").startswith("llmwiki-graph-lifecycle-synthetic-"):
        raise GraphEvaluationContractError("graph fixture corpus must be explicitly synthetic")
    if not isinstance(raw.get("random_seed"), int):
        raise GraphEvaluationContractError("graph fixture random_seed must be an integer")

    vaults = _required_string_list(raw, "vaults")
    if len(vaults) != len(set(vaults)):
        raise GraphEvaluationContractError("graph fixture vault keys must be unique")

    entities = _required_object_list(raw, "entities")
    entity_keys = _unique_keys(entities, "entity")
    for entity in entities:
        if _required_str(entity, "entity_type") not in ENTITY_TYPES:
            raise GraphEvaluationContractError("graph fixture contains an invalid entity type")
        _required_str(entity, "name")
        if str(entity.get("risk_tier", "low")) not in {"low", "medium", "high"}:
            raise GraphEvaluationContractError("graph fixture contains an invalid risk tier")

    claims = _required_object_list(raw, "claims")
    claim_keys = _unique_keys(claims, "claim")
    for claim in claims:
        if _required_str(claim, "subject") not in entity_keys:
            raise GraphEvaluationContractError("graph fixture claim subject is unknown")
        _required_str(claim, "predicate")
        _required_str(claim, "value")
        if not isinstance(claim.get("evidence"), bool):
            raise GraphEvaluationContractError("graph fixture claim evidence must be boolean")
        _validate_status(claim)
        vault = claim.get("vault")
        if vault is not None and vault not in vaults:
            raise GraphEvaluationContractError("graph fixture claim vault is unknown")

    relations = _required_object_list(raw, "relations")
    relation_keys = _unique_keys(relations, "relation")
    for relation in relations:
        if _required_str(relation, "relation_type") not in RELATION_TYPES:
            raise GraphEvaluationContractError("graph fixture contains an invalid relation type")
        if _required_str(relation, "subject") not in entity_keys:
            raise GraphEvaluationContractError("graph fixture relation subject is unknown")
        if _required_str(relation, "object") not in entity_keys:
            raise GraphEvaluationContractError("graph fixture relation object is unknown")
        if not isinstance(relation.get("evidence"), bool):
            raise GraphEvaluationContractError("graph fixture relation evidence must be boolean")
        _validate_status(relation)

    operations = _required_object_list(raw, "operations")
    derived_statement_keys: set[str] = set()
    for operation in operations:
        operation_type = _required_str(operation, "operation")
        if operation_type not in OPERATION_TYPES:
            raise GraphEvaluationContractError("graph fixture operation is unknown")
        target = _required_str(operation, "target")
        if operation_type in {"replay_relation", "correct_relation"} and target not in relation_keys:
            raise GraphEvaluationContractError("graph fixture relation operation target is unknown")
        if operation_type == "forget_entity" and target not in entity_keys:
            raise GraphEvaluationContractError("graph fixture entity operation target is unknown")
        if operation_type == "correct_claim" and target not in claim_keys:
            raise GraphEvaluationContractError("graph fixture claim operation target is unknown")
        if operation_type in {"correct_relation", "correct_claim"}:
            new_key = _required_str(operation, "new_key")
            if new_key in claim_keys | relation_keys | derived_statement_keys:
                raise GraphEvaluationContractError("graph fixture operation new_key is not unique")
            derived_statement_keys.add(new_key)

    cases = _required_object_list(raw, "cases")
    case_ids = _unique_keys(cases, "case", key_name="case_id")
    del case_ids
    known_statements = claim_keys | relation_keys | derived_statement_keys
    lifecycle_cases = 0
    no_evidence_cases = 0
    lifecycle_tags: set[str] = set()
    for case in cases:
        group = _required_str(case, "group")
        if group not in {"lifecycle", "no_evidence"}:
            raise GraphEvaluationContractError("graph fixture case group is unknown")
        lifecycle_cases += int(group == "lifecycle")
        no_evidence_cases += int(group == "no_evidence")
        query_kind = _required_str(case, "query_kind")
        if query_kind not in QUERY_KINDS:
            raise GraphEvaluationContractError("graph fixture case query_kind is unknown")
        if query_kind == "traverse":
            if _required_str(case, "entity") not in entity_keys:
                raise GraphEvaluationContractError("graph traversal case entity is unknown")
            max_hops = case.get("max_hops")
            if not isinstance(max_hops, int) or max_hops not in {1, 2}:
                raise GraphEvaluationContractError("graph traversal max_hops must be 1 or 2")
        else:
            _required_str(case, "query")
            vault = case.get("vault")
            if vault is not None and vault not in vaults:
                raise GraphEvaluationContractError("graph fact case vault is unknown")
        expected = set(_required_string_list(case, "expected"))
        excluded = set(_required_string_list(case, "excluded"))
        if expected & excluded:
            raise GraphEvaluationContractError("graph case expected and excluded keys overlap")
        if not expected | excluded <= known_statements:
            raise GraphEvaluationContractError("graph case references an unknown statement")
        tags = set(_required_string_list(case, "tags"))
        if not tags:
            raise GraphEvaluationContractError("graph case must contain at least one tag")
        if group == "lifecycle":
            lifecycle_tags.update(tags)
        elif expected:
            raise GraphEvaluationContractError("no-evidence cases cannot expect answerable statements")
    if lifecycle_cases < 20:
        raise GraphEvaluationContractError("graph fixture requires at least 20 lifecycle cases")
    if no_evidence_cases < 10:
        raise GraphEvaluationContractError("graph fixture requires at least 10 no-evidence cases")
    missing_tags = REQUIRED_LIFECYCLE_TAGS - lifecycle_tags
    if missing_tags:
        raise GraphEvaluationContractError(f"graph fixture lacks lifecycle tags: {sorted(missing_tags)}")
    return raw


def run_graph_evaluation(
    *,
    fixture_path: Path,
    work_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    fixture_path = fixture_path.resolve()
    fixture = load_graph_fixture(fixture_path)
    run_root = work_dir.resolve()
    run_root.mkdir(parents=True, exist_ok=False)
    database_path = run_root / "llmwiki-graph-eval.sqlite3"
    MigrationRunner(Database(database_path)).apply()
    _create_vaults(database_path, fixture, run_root)

    store = MemoryEntityGraphStore(database_path)
    try:
        entity_ids, statement_ids, operation_results = _materialize_fixture(store, fixture)
        id_to_statement_key = {statement_id: key for key, statement_id in statement_ids.items()}
        sqlite_started = time.perf_counter_ns()
        sqlite_cases = _evaluate_authority_cases(
            store,
            fixture,
            entity_ids=entity_ids,
            id_to_statement_key=id_to_statement_key,
        )
        sqlite_latency_ms = _elapsed_ms(sqlite_started)

        graph_root = run_root / "kuzu"
        kuzu_service = KuzuGraphService(database_path, graph_root)
        try:
            rebuild_started = time.perf_counter_ns()
            rebuild = kuzu_service.rebuild()
            rebuild_latency_ms = _elapsed_ms(rebuild_started)
            if rebuild.generation.status == "active":
                kuzu_cases = _evaluate_traversal_cases(
                    kuzu_service,
                    fixture,
                    entity_ids=entity_ids,
                    id_to_statement_key=id_to_statement_key,
                    required_source="kuzu",
                )
                kuzu_channel = _channel_summary(
                    kuzu_cases,
                    expected_source="kuzu",
                    evidence_status="synthetic_fixture_only",
                )
                kuzu_channel["generation_id"] = rebuild.generation.id
                kuzu_channel["rebuild_latency_ms"] = rebuild_latency_ms
                kuzu_channel["node_count"] = rebuild.node_count
                kuzu_channel["edge_count"] = rebuild.edge_count
                _remove_projection(Path(rebuild.database_path or ""))
            else:
                kuzu_cases = []
                kuzu_channel = {
                    "status": "not_run" if rebuild.fallback_reason == "kuzu_dependency_missing" else "failed",
                    "evidence_status": "insufficient_sample",
                    "sample_size": 0,
                    "passed_count": 0,
                    "reason": rebuild.fallback_reason or rebuild.generation.error_code,
                    "rebuild_latency_ms": rebuild_latency_ms,
                }

            fallback_cases = _evaluate_traversal_cases(
                kuzu_service,
                fixture,
                entity_ids=entity_ids,
                id_to_statement_key=id_to_statement_key,
                required_source="sqlite",
            )
            fallback_channel = _channel_summary(
                fallback_cases,
                expected_source="sqlite",
                evidence_status="synthetic_fixture_only",
            )
            fallback_channel["fallback_reasons"] = dict(
                sorted(Counter(str(case.get("fallback_reason") or "missing") for case in fallback_cases).items())
            )
        finally:
            kuzu_service.close()
    finally:
        store.close()

    traversal_sqlite = [case for case in sqlite_cases if case["query_kind"] == "traverse"]
    authority_cases = [case for case in sqlite_cases if case["query_kind"] == "facts"]
    sqlite_channel = _channel_summary(
        traversal_sqlite,
        expected_source="sqlite",
        evidence_status="synthetic_fixture_only",
        require_source=False,
    )
    authority_summary = _case_group_summary(authority_cases)
    lifecycle_cases = [case for case in sqlite_cases if case["group"] == "lifecycle"]
    no_evidence_cases = [case for case in sqlite_cases if case["group"] == "no_evidence"]
    correction_cases = [case for case in lifecycle_cases if "correction" in case["tags"]]
    correction_metric = _ratio_metric(correction_cases)
    no_evidence_metric = _ratio_metric(no_evidence_cases)
    false_activations = sum(bool(case["actual"]) for case in no_evidence_cases)
    equivalence = _equivalence_summary(
        traversal_sqlite,
        kuzu_cases,
        fallback_cases,
        kuzu_available=kuzu_channel["status"] != "not_run",
    )

    graph_status = "failed"
    if all(case["passed"] for case in sqlite_cases) and fallback_channel["status"] == "passed":
        graph_status = "passed" if kuzu_channel["status"] == "passed" else "insufficient_sample"
    fixture_hash = _sha256_file(fixture_path)
    evaluator_hash = _sha256_file(Path(__file__).resolve())
    configuration = {
        "evaluator_version": EVALUATOR_VERSION,
        "fixture_sha256": fixture_hash,
        "evaluator_sha256": evaluator_hash,
        "max_hops": [1, 2],
        "sqlite_authority": True,
        "kuzu_projection_optional": True,
        "fallback_fault": "remove published derived projection",
        "model_calls": 0,
    }
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": graph_status,
        "claim_boundary": (
            "L2 synthetic graph/lifecycle evaluation; no provider, model extraction, answer synthesis, "
            "real user, 7-day trial, or 24-hour soak observation"
        ),
        "fixture": {
            "schema_version": fixture["schema_version"],
            "corpus_version": fixture["corpus_version"],
            "sha256": fixture_hash,
            "synthetic_only": True,
            "case_count": len(fixture["cases"]),
            "lifecycle_case_count": len(lifecycle_cases),
            "no_evidence_case_count": len(no_evidence_cases),
        },
        "configuration": configuration,
        "configuration_sha256": _sha256_json(configuration),
        "input_hashes": {
            "fixture_sha256": fixture_hash,
            "evaluator_sha256": evaluator_hash,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "kuzu": _package_version("kuzu"),
        },
        "channels": {
            "sqlite_graph": sqlite_channel,
            "kuzu_acceleration": kuzu_channel,
            "sqlite_graph_fallback": fallback_channel,
            "authority_fact_filter": authority_summary,
        },
        "equivalence": equivalence,
        "lifecycle": {
            "status": "passed" if all(case["passed"] for case in lifecycle_cases) else "failed",
            "sample_size": len(lifecycle_cases),
            "passed_count": sum(bool(case["passed"]) for case in lifecycle_cases),
            "correction_propagation": correction_metric,
            "operation_invariants": operation_results,
        },
        "no_evidence": {
            **no_evidence_metric,
            "false_activation_numerator": false_activations,
            "false_activation_denominator": len(no_evidence_cases),
        },
        "ablation": {
            "status": "partial",
            "deterministic_sqlite_graph": {
                "status": "measured",
                "sample_size": len(sqlite_cases),
                "passed_count": sum(bool(case["passed"]) for case in sqlite_cases),
                "quality": _safe_ratio(sum(bool(case["passed"]) for case in sqlite_cases), len(sqlite_cases)),
                "latency_ms": sqlite_latency_ms,
                "model_call_count": 0,
                "external_request_count": 0,
                "estimated_cost_usd": 0.0,
            },
            "llm_extraction_synthesis": {
                "status": "not_run",
                "evidence_status": "insufficient_sample",
                "sample_size": 0,
                "reason": "No fixed or live model observation was executed; quality, latency and cost are not inferred.",
            },
        },
        "case_results": sqlite_cases,
    }
    _write_report(output_dir.resolve(), report)
    return report


def _materialize_fixture(
    store: MemoryEntityGraphStore,
    fixture: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], list[dict[str, object]]]:
    entity_ids: dict[str, str] = {}
    statement_ids: dict[str, str] = {}
    relations_by_key: dict[str, Mapping[str, Any]] = {}
    for raw in fixture["entities"]:
        key = str(raw["key"])
        entity = store.create_entity(
            entity_type=str(raw["entity_type"]),
            canonical_name=str(raw["name"]),
            entity_key=f"eval:{key}",
            status=str(raw.get("status", "active")),
            risk_tier=str(raw.get("risk_tier", "low")),
            confidence=float(raw.get("confidence", 0.9)),
            metadata={"fixture": str(fixture["corpus_version"]), "logical_key": key},
        )
        entity_ids[key] = entity.id

    for raw in fixture["claims"]:
        key = str(raw["key"])
        evidence_id = f"eval-evidence-{hashlib.sha256(key.encode()).hexdigest()[:32]}" if raw["evidence"] else None
        if raw.get("expires_at"):
            entity = store.get_entity(entity_ids[str(raw["subject"])])
            result = store.upsert_candidate(
                MemoryFactCandidate(
                    category="claim",
                    subject=entity.canonical_name,
                    predicate=str(raw["predicate"]),
                    object=str(raw["value"]),
                    source_text=f"synthetic evidence for {key}",
                    source_type="synthetic_eval",
                    confidence=float(raw.get("confidence", 0.9)),
                    entity_type=entity.entity_type,
                    expires_at=str(raw["expires_at"]),
                )
            )
            fact = result.fact
        else:
            fact = store.create_claim(
                subject_entity_id=entity_ids[str(raw["subject"])],
                predicate=str(raw["predicate"]),
                literal_value=str(raw["value"]),
                source_text=f"synthetic evidence for {key}",
                source_type="synthetic_eval",
                confidence=float(raw.get("confidence", 0.9)),
                evidence_id=evidence_id,
                metadata={"fixture": str(fixture["corpus_version"]), "logical_key": key},
            )
        requested_status = raw.get("status")
        if requested_status is not None and fact.status.value != requested_status:
            fact = store.update_status(fact.id, str(requested_status), reason="synthetic_eval_setup")
        statement_ids[key] = fact.id
        vault = raw.get("vault")
        if vault is not None:
            store.bind_artifact(
                fact_id=fact.id,
                vault_id=str(vault),
                artifact_type="source",
                artifact_ref=f"synthetic/{key}",
            )

    for raw in fixture["relations"]:
        key = str(raw["key"])
        relations_by_key[key] = raw
        fact = _create_relation(store, raw, entity_ids)
        requested_status = raw.get("status")
        if requested_status is not None and fact.status.value != requested_status:
            fact = store.update_status(fact.id, str(requested_status), reason="synthetic_eval_setup")
        statement_ids[key] = fact.id

    operation_results: list[dict[str, object]] = []
    for raw in fixture["operations"]:
        operation = str(raw["operation"])
        target = str(raw["target"])
        if operation == "replay_relation":
            before = store.get(statement_ids[target])
            replayed = _create_relation(store, relations_by_key[target], entity_ids)
            passed = replayed.id == before.id and replayed.support_count == before.support_count
        elif operation == "correct_relation":
            old, replacement = store.correct_relation(
                statement_ids[target],
                relation_type=str(raw["relation_type"]),
                subject_entity_id=entity_ids[str(raw["subject"])],
                object_entity_id=entity_ids[str(raw["object"])],
                source_text=f"synthetic correction for {target}",
            )
            statement_ids[str(raw["new_key"])] = replacement.id
            passed = old.status.value == "superseded" and replacement.status.value == "active"
        elif operation == "forget_entity":
            forgotten = store.update_entity_status(
                entity_ids[target],
                "forgotten",
                reason="synthetic_eval_forget",
            )
            passed = forgotten.status == "forgotten"
        elif operation == "correct_claim":
            old, replacement = store.correct_claim(
                statement_ids[target],
                literal_value=str(raw["value"]),
                source_text=f"synthetic correction for {target}",
                source_type="synthetic_eval",
            )
            statement_ids[str(raw["new_key"])] = replacement.id
            passed = old.status.value == "superseded" and replacement.status.value == "active"
        else:
            raise GraphEvaluationContractError("unsupported graph fixture operation")
        operation_results.append({"operation": operation, "target": target, "passed": passed})
    return entity_ids, statement_ids, operation_results


def _create_relation(
    store: MemoryEntityGraphStore,
    raw: Mapping[str, Any],
    entity_ids: Mapping[str, str],
):
    key = str(raw["key"])
    evidence_id = f"eval-relation-evidence-{hashlib.sha256(key.encode()).hexdigest()[:32]}" if raw["evidence"] else None
    return store.create_relation(
        relation_type=str(raw["relation_type"]),
        subject_entity_id=entity_ids[str(raw["subject"])],
        object_entity_id=entity_ids[str(raw["object"])],
        source_text=f"synthetic evidence for {key}",
        source_type="synthetic_eval",
        confidence=float(raw.get("confidence", 0.9)),
        evidence_id=evidence_id,
    )


def _evaluate_authority_cases(
    store: MemoryEntityGraphStore,
    fixture: Mapping[str, Any],
    *,
    entity_ids: Mapping[str, str],
    id_to_statement_key: Mapping[str, str],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        started = time.perf_counter_ns()
        if case["query_kind"] == "traverse":
            relations = store.traverse(
                entity_ids[str(case["entity"])],
                max_hops=int(case["max_hops"]),
            )
            actual = _logical_statement_keys(
                [relation.fact.id for relation in relations],
                id_to_statement_key,
            )
        else:
            facts = store.answerable_graph_facts(
                query=str(case["query"]),
                vault_id=str(case["vault"]) if case.get("vault") is not None else None,
            )
            actual = _logical_statement_keys([fact.id for fact in facts], id_to_statement_key)
        results.append(_case_result(case, actual, latency_ms=_elapsed_ms(started), source="sqlite"))
    return results


def _evaluate_traversal_cases(
    service: KuzuGraphService,
    fixture: Mapping[str, Any],
    *,
    entity_ids: Mapping[str, str],
    id_to_statement_key: Mapping[str, str],
    required_source: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        if case["query_kind"] != "traverse":
            continue
        started = time.perf_counter_ns()
        traversal = service.traverse(
            entity_ids[str(case["entity"])],
            max_hops=int(case["max_hops"]),
        )
        actual = _logical_statement_keys(
            [relation.fact.id for relation in traversal.relations],
            id_to_statement_key,
        )
        result = _case_result(
            case,
            actual,
            latency_ms=_elapsed_ms(started),
            source=traversal.source,
        )
        result["fallback_reason"] = traversal.fallback_reason
        result["passed"] = bool(result["passed"] and traversal.source == required_source)
        results.append(result)
    return results


def _case_result(
    case: Mapping[str, Any],
    actual: Sequence[str],
    *,
    latency_ms: float,
    source: str,
) -> dict[str, Any]:
    expected = sorted(str(item) for item in case["expected"])
    excluded = sorted(str(item) for item in case["excluded"])
    actual_sorted = sorted(actual)
    return {
        "case_id": str(case["case_id"]),
        "group": str(case["group"]),
        "query_kind": str(case["query_kind"]),
        "tags": sorted(str(item) for item in case["tags"]),
        "expected": expected,
        "excluded": excluded,
        "actual": actual_sorted,
        "source": source,
        "latency_ms": latency_ms,
        "passed": actual_sorted == expected and not set(actual_sorted) & set(excluded),
    }


def _channel_summary(
    cases: Sequence[Mapping[str, Any]],
    *,
    expected_source: str,
    evidence_status: str,
    require_source: bool = True,
) -> dict[str, Any]:
    passed_count = sum(
        bool(case["passed"] and (not require_source or case.get("source") == expected_source))
        for case in cases
    )
    latencies = [float(case["latency_ms"]) for case in cases]
    return {
        "status": "passed" if cases and passed_count == len(cases) else "failed",
        "evidence_status": evidence_status,
        "sample_size": len(cases),
        "passed_count": passed_count,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "hard_max": round(max(latencies, default=0.0), 4),
        },
    }


def _case_group_summary(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    passed_count = sum(bool(case["passed"]) for case in cases)
    return {
        "status": "passed" if cases and passed_count == len(cases) else "failed",
        "evidence_status": "synthetic_fixture_only",
        "sample_size": len(cases),
        "passed_count": passed_count,
    }


def _equivalence_summary(
    sqlite_cases: Sequence[Mapping[str, Any]],
    kuzu_cases: Sequence[Mapping[str, Any]],
    fallback_cases: Sequence[Mapping[str, Any]],
    *,
    kuzu_available: bool,
) -> dict[str, object]:
    sqlite_by_id = {str(case["case_id"]): list(case["actual"]) for case in sqlite_cases}
    kuzu_by_id = {str(case["case_id"]): list(case["actual"]) for case in kuzu_cases}
    fallback_by_id = {str(case["case_id"]): list(case["actual"]) for case in fallback_cases}
    fallback_equal = sqlite_by_id == fallback_by_id
    kuzu_equal = sqlite_by_id == kuzu_by_id if kuzu_available else None
    if not fallback_equal or kuzu_equal is False:
        status = "failed"
    elif kuzu_equal is None:
        status = "insufficient_sample"
    else:
        status = "passed"
    return {
        "status": status,
        "sample_size": len(sqlite_cases),
        "sqlite_vs_kuzu_equal": kuzu_equal,
        "sqlite_vs_fallback_equal": fallback_equal,
        "kuzu_evidence_status": "synthetic_fixture_only" if kuzu_available else "insufficient_sample",
    }


def _ratio_metric(cases: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    numerator = sum(bool(case["passed"]) for case in cases)
    denominator = len(cases)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": denominator,
        "value": _safe_ratio(numerator, denominator),
        "evidence_status": "synthetic_fixture_only" if denominator else "insufficient_sample",
    }


def _create_vaults(database_path: Path, fixture: Mapping[str, Any], run_root: Path) -> None:
    with Database(database_path).session() as conn:
        for vault in fixture["vaults"]:
            vault_key = str(vault)
            conn.execute(
                "INSERT INTO vaults(id, root_path, name) VALUES (?, ?, ?)",
                (vault_key, str(run_root / f"vault-{vault_key}"), f"Synthetic {vault_key}"),
            )


def _logical_statement_keys(
    statement_ids: Sequence[str],
    id_to_statement_key: Mapping[str, str],
) -> list[str]:
    return [id_to_statement_key.get(statement_id, "unmapped_statement") for statement_id in statement_ids]


def _remove_projection(path: Path) -> None:
    if not path:
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _write_report(output_dir: Path, report: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "graph-report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# LLM Wiki graph lifecycle evaluation",
        "",
        f"- status: `{report['status']}`",
        f"- evaluator: `{report['evaluator_version']}`",
        f"- corpus: `{report['fixture']['corpus_version']}`",
        f"- lifecycle cases: `{report['fixture']['lifecycle_case_count']}`",
        f"- no-evidence cases: `{report['fixture']['no_evidence_case_count']}`",
        f"- SQLite graph: `{report['channels']['sqlite_graph']['status']}`",
        f"- Kuzu acceleration: `{report['channels']['kuzu_acceleration']['status']}`",
        f"- SQLite fallback: `{report['channels']['sqlite_graph_fallback']['status']}`",
        f"- graph equivalence: `{report['equivalence']['status']}`",
        "- LLM extraction/synthesis: `not_run` (no fixed or live model observation)",
        "- evidence boundary: synthetic L2 only; this is not 7-day user or 24-hour stability evidence.",
    ]
    (output_dir / "graph-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    artifact_hashes = {
        "schema_version": "llmwiki-graph-eval-artifact-hashes.v1",
        "artifacts": {
            "graph-report.json": _sha256_file(output_dir / "graph-report.json"),
            "graph-report.md": _sha256_file(output_dir / "graph-report.md"),
        },
    }
    (output_dir / "artifact-hashes.json").write_text(
        json.dumps(artifact_hashes, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _required_str(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GraphEvaluationContractError(f"{key} must be a non-empty string")
    return value.strip()


def _required_object_list(raw: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
        raise GraphEvaluationContractError(f"{key} must be a non-empty object list")
    return value


def _required_string_list(raw: Mapping[str, Any], key: str) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise GraphEvaluationContractError(f"{key} must be a string list")
    return [item.strip() for item in value]


def _unique_keys(
    items: Sequence[Mapping[str, Any]],
    label: str,
    *,
    key_name: str = "key",
) -> set[str]:
    keys = [_required_str(item, key_name) for item in items]
    if len(keys) != len(set(keys)):
        raise GraphEvaluationContractError(f"graph fixture {label} keys must be unique")
    return set(keys)


def _validate_status(raw: Mapping[str, Any]) -> None:
    status = raw.get("status")
    if status is not None and status not in FACT_STATUSES:
        raise GraphEvaluationContractError("graph fixture contains an invalid fact status")
    confidence = raw.get("confidence", 0.9)
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise GraphEvaluationContractError("graph fixture confidence must be between zero and one")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1))
    return round(ordered[index], 4)


def _elapsed_ms(started_ns: int) -> float:
    return round((time.perf_counter_ns() - started_ns) / 1_000_000, 4)
