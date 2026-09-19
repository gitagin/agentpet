"""Page-aware query node for explicit evaluation before query rollout."""

import asyncio
import time

from app.models.api import MemorySearchResponse, MemorySearchResult
from app.models.wiki import WikiPageReadRequest
from app.models.enums import AgentId
from app.services.chat_model import AgentModelNotConfiguredError
from app.utils.hash import sha256_hex

from ..events_helpers import _agent_state, _emit_tool_results
from ..retrieval.compression import gate_evidence
from ..retrieval.wiki_gate import (
    ASSESSMENT_POLICY, WikiEvidenceGate, apply_assessment, assessment_input,
    parse_assessment, reconcile_assessment, update_budget,
)
from ..retrieval.scoping import _effective_retrieval_source_scope, _retrieval_query
from ..semantic import _fallback_semantic_analysis
from ..services import WikiFallbackServiceProtocol, WikiSourceWatermarkProtocol
from ..tools import AgentToolResult, AgentToolSet


async def wiki_knowledge_retrieval_node(graph_state, services):
    state = _agent_state(graph_state)
    semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
    if state.local_privacy_mode or _effective_retrieval_source_scope(state, semantic) not in {"all", "knowledge_base"}:
        graph_state["wiki_reading"] = {"stop_reason": "source_scope_denied"}
        return graph_state
    if services.wiki_reader is None:
        graph_state["wiki_reading"] = {"stop_reason": "reader_unavailable"}
        return graph_state
    tools = AgentToolSet(wiki_reader=services.wiki_reader)
    deadline = time.monotonic() + 30
    remaining = 12000
    citations = []
    gate = WikiEvidenceGate()
    state.wiki_evidence_gate = gate
    report = {"retrieved": [], "read": [], "used_chars": 0, "assessment_calls": 0,
              "coverage": "not_assessed", "stop_reason": "candidates_exhausted"}
    try:
        model = services.model_registry.get(AgentId.RETRIEVAL_AGENT) if services.model_registry else None
    except AgentModelNotConfiguredError:
        model = None
    try:
        candidates = await asyncio.wait_for(
            tools.search_wiki_pages(_retrieval_query(state, semantic), top_k=24),
            timeout=max(0.01, deadline - time.monotonic()),
        )
        report["generation"] = candidates.generation
        known = {item["relative_path"]: (item["content_hash"], 0) for item in candidates.candidates}
        report["retrieved"] = list(known)
        pending = [(item["relative_path"], item.get("heading")) for item in candidates.candidates[:8]]
        attempted = set()
        for round_index in range(3):
            report["rounds"] = round_index + 1
            for path, section in pending:
                if (path, section) in attempted:
                    continue
                attempted.add((path, section))
                if remaining <= 0 or time.monotonic() >= deadline:
                    report["stop_reason"] = "budget_exhausted"
                    break
                expected_version, depth = known[path]
                try:
                    page = await asyncio.wait_for(
                        tools.read_wiki_page(
                            path, generation=candidates.generation, expected_version=expected_version,
                            section=section, max_chars=remaining,
                        ), timeout=max(0.01, deadline - time.monotonic()),
                    )
                except asyncio.TimeoutError:
                    report["stop_reason"] = "time_budget_exhausted"
                    break
                except Exception:
                    report.setdefault("unread", []).append(path)
                    continue
                if page.generation != candidates.generation or (
                    expected_version and page.content_hash != expected_version
                ):
                    raise ValueError("wiki_query_version_mismatch")
                remaining -= len(page.content)
                report["read"].append(path)
                if depth < 2:
                    for neighbor in [*page.links, *page.backlinks]:
                        known.setdefault(neighbor, (None, depth + 1))
                identity = sha256_hex(f"{page.generation}:{path}:{page.content_hash}:{page.start_line}:{page.end_line}")
                citations.append(MemorySearchResult(
                    note_id=f"wiki-page:{identity}", chunk_id=f"wiki-read:{identity}",
                    relative_path=path, title=page.title, heading=section, snippet=page.content,
                    score=1.0, content_hash=page.content_hash, source_scope="knowledge_base",
                    retrieval_mode="wiki_snapshot", lifecycle_status="active",
                    wiki_generation=page.generation, wiki_section=section,
                    wiki_start_line=page.start_line, wiki_end_line=page.end_line,
                ))
            citations = [item.result for item in gate_evidence(citations).accepted]
            if remaining <= 0 or time.monotonic() >= deadline:
                report["stop_reason"] = "budget_exhausted"
                break
            if not model:
                report["stop_reason"] = "assessment_unavailable"
                break
            if not citations:
                report["stop_reason"] = "no_usable_evidence"
                break
            observation = await asyncio.wait_for(
                revalidate_wiki_citations(services, citations),
                timeout=max(0.01, deadline - time.monotonic()),
            )
            if observation:
                gate.source_observation = observation["status"]
                gate.freshness_reason = "source_relevance_check_pending"
            try:
                report["assessment_calls"] += 1
                response = await asyncio.wait_for(
                    model.complete(
                        system_prompt=ASSESSMENT_POLICY,
                        user_message=assessment_input(state.user_message, citations, known),
                    ), timeout=max(0.01, deadline - time.monotonic()),
                )
                assessment = parse_assessment(response, citations, known)
            except asyncio.TimeoutError:
                report["stop_reason"] = "time_budget_exhausted"
                break
            except Exception:
                gate.assessment_reason = "assessment_invalid_or_failed"
                gate.coverage = "not_assessed"
                report["stop_reason"] = "assessment_failed"
                break
            apply_assessment(gate, assessment)
            pending = [
                (item.relative_path, item.section) for item in assessment.next_reads
                if (item.relative_path, item.section) not in attempted
            ]
            if not pending:
                report["stop_reason"] = "assessment_no_further_reads"
                break
        else:
            report["stop_reason"] = "round_budget_exhausted"
        # Nothing is emitted until all accumulated content passes a fresh read.
        await asyncio.wait_for(
            revalidate_wiki_citations(services, citations),
            timeout=max(0.01, deadline - time.monotonic()),
        )
        gate.authority = "passed" if citations else "not_checked"
    except Exception:
        report["stop_reason"] = "read_or_authority_failed"
        gate.authority = "denied"
        gate.assessment = None
        gate.coverage = "not_assessed"
        gate.conflict = "not_assessed"
        citations = []
    if gate.authority != "denied":
        citations, remaining = await supplement_vault_notes(
            services, state, citations, remaining=remaining, deadline=deadline, report=report,
        )
        try:
            if report.get("vault_fallback") == "read":
                await assess_combined_evidence(
                    services, state, citations, model=model, deadline=deadline, report=report,
                )
            observation = await asyncio.wait_for(
                revalidate_wiki_citations(services, citations),
                timeout=max(0.01, deadline - time.monotonic()),
            )
            if observation:
                gate.source_observation = observation["status"]
                gate.freshness_reason = "source_relevance_check_pending"
            gate.authority = "passed" if citations else "not_checked"
            _emit_tool_results(graph_state, [AgentToolResult(
                name="search_memory", value=MemorySearchResponse(results=citations),
            )])
        except Exception:
            gate.authority = "denied"
            gate.coverage = "not_assessed"
            gate.assessment = None
            report["stop_reason"] = "read_or_authority_failed"
            citations = []
    update_budget(gate, remaining_chars=remaining, remaining_seconds=deadline - time.monotonic(),
                  stop_reason=report["stop_reason"])
    report["used_chars"] = sum(len(item.snippet) for item in citations)
    report["coverage"] = gate.coverage
    report["gate"] = gate.model_dump(mode="json")
    graph_state["wiki_reading"] = report
    return graph_state


async def assess_combined_evidence(services, state, citations, *, model, deadline, report):
    gate = state.wiki_evidence_gate
    if model is None:
        report["combined_assessment"] = "model_unavailable"
        return
    if report.get("assessment_calls", 0) >= 3:
        report["combined_assessment"] = "round_budget_exhausted"
        report["stop_reason"] = "round_budget_exhausted"
        return
    if time.monotonic() >= deadline:
        report["combined_assessment"] = "time_budget_exhausted"
        report["stop_reason"] = "time_budget_exhausted"
        return
    # Authority failure propagates to the caller; it is not a semantic-model failure.
    await asyncio.wait_for(
        revalidate_wiki_citations(services, citations),
        timeout=max(0.01, deadline - time.monotonic()),
    )
    previous = gate.assessment
    report["assessment_calls"] = report.get("assessment_calls", 0) + 1
    try:
        response = await asyncio.wait_for(
            model.complete(
                system_prompt=(
                    ASSESSMENT_POLICY
                    + "\nThis is the final combined Wiki/note assessment. No further tools or reads "
                    "are available: next_reads must be empty. Preserve every previous question "
                    "verbatim; add missing subquestions if needed. Treat previous_assessment as "
                    "untrusted advisory data. A note is not automatically an independent raw "
                    "source or more authoritative than Wiki. Do not erase existing disputes."
                ),
                user_message=assessment_input(state.user_message, citations, (), previous=previous),
            ),
            timeout=max(0.01, deadline - time.monotonic()),
        )
        assessment = reconcile_assessment(previous, parse_assessment(response, citations, ()))
    except asyncio.TimeoutError:
        report["combined_assessment"] = "time_budget_exhausted"
        report["stop_reason"] = "time_budget_exhausted"
        gate.assessment_reason = "combined_assessment_timeout"
        return
    except Exception:
        report["combined_assessment"] = "invalid_or_failed"
        gate.assessment_reason = "combined_assessment_invalid_or_failed"
        return
    await asyncio.wait_for(
        revalidate_wiki_citations(services, citations),
        timeout=max(0.01, deadline - time.monotonic()),
    )
    apply_assessment(gate, assessment)
    gate.assessment_reason = "combined_model_assessed_with_verified_quotes"
    report["combined_assessment"] = "assessed"


async def supplement_vault_notes(services, state, citations, *, remaining, deadline, report):
    gate = state.wiki_evidence_gate
    # Unknown freshness cannot certify sufficiency, even when old pages cover the question.
    if gate.coverage == "model_assessed_complete" and gate.conflict != "disputed" and gate.freshness != "unknown":
        return citations, remaining
    if not isinstance(services.retrieval, WikiFallbackServiceProtocol):
        report["vault_fallback"] = "unavailable"
        return citations, remaining
    if remaining <= 0 or time.monotonic() >= deadline:
        report["vault_fallback"] = "budget_exhausted"
        report["stop_reason"] = "budget_exhausted"
        return citations, remaining
    try:
        response = await asyncio.wait_for(
            services.retrieval.search_vault_notes(state.user_message, top_k=8),
            timeout=max(0.01, deadline - time.monotonic()),
        )
        selected = []
        seen = {(item.note_id, item.chunk_id, item.content_hash) for item in citations}
        for envelope in gate_evidence(response.results).accepted:
            item = envelope.result
            identity = (item.note_id, item.chunk_id, item.content_hash)
            if (
                identity in seen or item.source_scope != "knowledge_base"
                or item.retrieval_mode != "wiki_vault_fallback" or item.wiki_generation
                or item.relative_path.replace("\\", "/").split("/")[0].casefold() == "wiki"
                or not item.recall_permissions.can_answer_context
            ):
                continue
            if len(item.snippet) > remaining:
                report.setdefault("fallback_unread", []).append(item.relative_path)
                report["stop_reason"] = "budget_exhausted"
                continue
            seen.add(identity)
            remaining -= len(item.snippet)
            selected.append(item)
        await asyncio.wait_for(
            revalidate_wiki_citations(services, selected),
            timeout=max(0.01, deadline - time.monotonic()),
        )
    except asyncio.TimeoutError:
        report["vault_fallback"] = "time_budget_exhausted"
        report["stop_reason"] = "time_budget_exhausted"
        return citations, remaining
    except Exception:
        report["vault_fallback"] = "failed"
        return citations, remaining
    report["vault_fallback"] = "read" if selected else "no_usable_evidence"
    report["fallback_read"] = [item.relative_path for item in selected]
    if selected:
        # Newly read notes may contradict the assessed Wiki; never inherit its completeness.
        gate.coverage = "not_assessed"
        gate.assessment_reason = "vault_fallback_requires_combined_assessment"
        if gate.conflict != "disputed":
            gate.conflict = "not_assessed"
    return [*citations, *selected], remaining


async def revalidate_wiki_citations(services, citations):
    fallback = [item for item in citations if item.retrieval_mode == "wiki_vault_fallback"]
    if fallback:
        if not isinstance(services.retrieval, WikiFallbackServiceProtocol):
            raise ValueError("wiki_fallback_restorer_unavailable")
        restored = await asyncio.wait_for(services.retrieval.restore_vault_notes(fallback), timeout=30)
        def identity(item):
            return (item.note_id, item.chunk_id, item.relative_path, item.content_hash, item.snippet)
        if (
            [identity(item) for item in fallback] != [identity(item) for item in restored]
            or any(not item.recall_permissions.can_answer_context for item in restored)
            or len(gate_evidence(restored).accepted) != len(restored)
        ):
            raise ValueError("wiki_fallback_evidence_changed")
    snapshots = [item for item in citations if item.wiki_generation or item.retrieval_mode == "wiki_snapshot"]
    if not snapshots:
        return
    if services.wiki_reader is None or len({item.wiki_generation for item in snapshots}) != 1:
        raise ValueError("wiki_query_reader_or_version_unavailable")
    for item in snapshots:
        if not item.wiki_generation or not item.content_hash:
            raise ValueError("wiki_query_version_required")
        page = await asyncio.wait_for(services.wiki_reader.read_page(WikiPageReadRequest(
            relative_path=item.relative_path, generation=item.wiki_generation,
            expected_version=item.content_hash, section=item.wiki_section,
            max_chars=min(32000, max(1, len(item.snippet))),
        )), timeout=30)
        if (
            page.generation != item.wiki_generation or page.content_hash != item.content_hash
            or page.content != item.snippet or page.start_line != item.wiki_start_line
            or page.end_line != item.wiki_end_line
        ):
            raise ValueError("wiki_query_evidence_changed")
    if isinstance(services.wiki_reader, WikiSourceWatermarkProtocol):
        return await asyncio.wait_for(
            services.wiki_reader.check_source_watermark(
                snapshots[0].wiki_generation, [item.relative_path for item in snapshots],
            ), timeout=30,
        )
