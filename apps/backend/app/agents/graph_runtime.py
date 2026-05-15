from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from app.models.api import (
    MemoryProposalActionResponse,
    MemorySearchResponse,
    QueryArchiveRequest,
    TaskCreateResponse,
    WikiIngestPreviewRequest,
    WikiIngestReviewRequest,
    WikiLintProposal,
    WikiPageResponse,
    WikiQueryArchiveProposal,
    WikiSynthesisProposal,
    WikiSynthesizeRequest,
)
from app.models.enums import AgentIntent, AgentRunStatus
from app.models.enums import AgentId

from .events import (
    AgentCitationEvent,
    AgentContinuitySignalEvent,
    AgentDoneEvent,
    AgentErrorEvent,
    AgentEventBase,
    AgentMemoryProposalEvent,
    AgentStatusEvent,
    AgentTaskEvent,
    AgentTokenEvent,
    AgentWikiProposalEvent,
)
from .intent import route_intent
from .memory_router import MemoryRoute, route_memory
from .runtime import (
    AgentRuntimeServices,
    ModelInvocationFailedError,
    _chat_system_prompt,
    _chunk_text,
    _continuity_presence_context_block,
    _continuity_signal,
    _continuity_signal_event,
    _message_with_continuity_context,
    _strip_memory_command,
    _strip_search_command,
    _strip_wiki_command,
    _task_title,
    _wiki_title,
)
from .state import AgentState, SemanticAnalysisResult
from .tools import (
    DEFAULT_MEMORY_TARGET_PATH,
    AgentToolResult,
    AgentToolSet,
    AgentToolName,
    AgentToolUnavailableError,
    SensitiveMemoryRejectedError,
    WikiIngestProposal,
)


MEMORY_CONTEXT_LIMIT = 5
MEMORY_CONTEXT_PER_SCOPE_LIMIT = 2
MEMORY_CONTEXT_SCOPE_ORDER = ("personal_memory", "diary_objects", "daily_chat", "knowledge_base")


class LangGraphAgentRuntime:
    """LangGraph-backed Agent coordinator for the v0.1 core tool paths.

    Chat uses LangChain v1 `create_agent` through the configured chat model
    service. Search, memory proposal, and task nodes invoke LangChain
    `StructuredTool` objects, while LangGraph coordinates routing and event
    emission for the desktop SSE contract.
    """

    def __init__(self, services: AgentRuntimeServices | None = None) -> None:
        self.services = services or AgentRuntimeServices()
        self.toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            memory=self.services.memory,
            tasks=self.services.tasks,
            wiki=self.services.wiki,
            wiki_workflow=self.services.wiki_workflow,
        )
        self.graph = self._build_graph()

    async def run(self, state: AgentState):
        graph_state: dict[str, Any] = {
            "agent_state": state,
            "events": [],
            "failed": False,
        }
        yielded = 0
        async for update in self.graph.astream(graph_state, stream_mode="updates"):
            for node_state in update.values():
                events = node_state.get("events", [])
                for event in events[yielded:]:
                    yield event
                yielded = len(events)

    def _build_graph(self):
        graph = StateGraph(dict)
        graph.add_node("route", self._route_node)
        graph.add_node("semantic_analysis_agent", self._semantic_node)
        graph.add_node("memory_retrieval_agent", self._memory_retrieval_node)
        graph.add_node("knowledge_retrieval_agent", self._knowledge_retrieval_node)
        graph.add_node("chat_agent", self._chat_node)
        graph.add_node("wiki_manager_agent", self._wiki_node)
        graph.add_node("memory_proposal_agent", self._memory_node)
        graph.add_node("task_agent", self._task_node)
        graph.add_node("finish", self._finish_node)

        graph.add_edge(START, "route")
        graph.add_edge("route", "semantic_analysis_agent")
        graph.add_conditional_edges(
            "semantic_analysis_agent",
            self._select_agent_node,
            {
                "chat_agent": "chat_agent",
                "memory_retrieval_agent": "memory_retrieval_agent",
                "knowledge_retrieval_agent": "knowledge_retrieval_agent",
                "wiki_manager_agent": "wiki_manager_agent",
                "memory_proposal_agent": "memory_proposal_agent",
                "task_agent": "task_agent",
            },
        )
        graph.add_edge("chat_agent", "finish")
        graph.add_conditional_edges(
            "memory_retrieval_agent",
            self._select_after_memory_retrieval,
            {
                "knowledge_retrieval_agent": "knowledge_retrieval_agent",
                "chat_agent": "chat_agent",
            },
        )
        graph.add_edge("knowledge_retrieval_agent", "chat_agent")
        graph.add_edge("wiki_manager_agent", "finish")
        graph.add_edge("memory_proposal_agent", "finish")
        graph.add_edge("task_agent", "finish")
        graph.add_edge("finish", END)
        return graph.compile()

    async def _route_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _agent_state(graph_state)
        state.route = route_intent(state.user_message)
        _events(graph_state).append(
            AgentStatusEvent(
                agent_run_id=state.agent_run_id,
                status=state.status,
                intent=state.route.intent,
                message="正在分析语义和上下文需求。",
                stage="route",
            )
        )
        return graph_state

    async def _semantic_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _agent_state(graph_state)
        state.memory_route = route_memory(state.user_message)
        route_semantic = _semantic_from_memory_route(state.memory_route, state)
        state.semantic_analysis = route_semantic
        if not _should_call_semantic_agent(state):
            _append_status(graph_state, "memory router selected context scope", stage="memory_router")
            return graph_state
        _append_status(graph_state, "正在调用语义分析 Agent。", stage="semantic_analysis")
        try:
            semantic_model = self._model_for(AgentId.SEMANTIC_ANALYSIS_AGENT)
            response = await semantic_model.complete(
                user_message=state.user_message,
                system_prompt=_semantic_system_prompt(),
            )
            state.semantic_analysis = _parse_semantic_analysis(response, state.user_message)
        except Exception:
            state.semantic_analysis = route_semantic or _fallback_semantic_analysis(state)
        return graph_state

    def _select_agent_node(self, graph_state: dict[str, Any]) -> str:
        state = _agent_state(graph_state)
        if state.route.intent == AgentIntent.PROPOSE_MEMORY:
            return "memory_proposal_agent"
        if state.route.intent == AgentIntent.MANAGE_WIKI:
            return "wiki_manager_agent"
        if state.route.intent == AgentIntent.CREATE_TASK:
            return "task_agent"
        if state.route.intent == AgentIntent.SEARCH_MEMORY:
            return _select_retrieval_entry_node(graph_state)
        if state.semantic_analysis and state.semantic_analysis.needs_context:
            return _select_retrieval_entry_node(graph_state)
        return "chat_agent"

    def _select_after_memory_retrieval(self, graph_state: dict[str, Any]) -> str:
        plan = graph_state.get("retrieval_plan")
        if isinstance(plan, dict) and plan.get("knowledge"):
            return "knowledge_retrieval_agent"
        return "chat_agent"

    async def _chat_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        try:
            state = _agent_state(graph_state)
            signal = _continuity_signal(self.services.continuity)
            if signal is not None and not graph_state.get("continuity_signal_emitted"):
                _events(graph_state).append(_continuity_signal_event(state.agent_run_id, signal))
                graph_state["continuity_signal_emitted"] = True
            _append_status(graph_state, "正在生成桌宠回复。", stage="chat_generation")
            chat_model = self._model_for(AgentId.CHAT_AGENT)
            if chat_model is not None:
                if state.citations:
                    response = await self._answer_with_chat_model(state)
                else:
                    response, tool_results = await self._run_model_chat_with_tools(state)
                    text_tool_fallback = await self._fallback_text_search_tool_call(state, response)
                    if text_tool_fallback is not None:
                        response, fallback_tool_results = text_tool_fallback
                        tool_results.extend(fallback_tool_results)
                    _emit_tool_results(graph_state, tool_results)
                    if _has_empty_search_result(tool_results):
                        response = await self._answer_with_chat_model(
                            state,
                            _knowledge_not_found_chat_prompt(),
                        )
                if state.semantic_analysis and state.semantic_analysis.needs_context and not state.citations:
                    response = await self._answer_with_chat_model(
                        state,
                        _knowledge_not_found_chat_prompt(),
                    )
            else:
                if state.citations:
                    response = _grounded_response_from_citations(state.citations)
                elif state.semantic_analysis and state.semantic_analysis.needs_context:
                    response = _local_knowledge_not_found_response()
                else:
                    response = state.response_text or "我可以陪你聊天、帮你翻记忆本、创建待确认记忆提案，也可以记录任务和提醒。"

            state.response_text = response
            for chunk in _chunk_text(response):
                _events(graph_state).append(
                    AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk)
                )
            return graph_state
        except (AgentToolUnavailableError, SensitiveMemoryRejectedError) as exc:
            return _record_node_error(graph_state, exc)
        except Exception as exc:
            if self.services.model_registry is not None or self.services.chat_model is not None:
                return _record_node_error(
                    graph_state,
                    exc if hasattr(exc, "code") else ModelInvocationFailedError(),
                )
            return _record_node_error(graph_state, exc)

    async def _run_model_chat_with_tools(
        self,
        state: AgentState,
    ) -> tuple[str, list[AgentToolResult]]:
        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            memory=self.services.memory,
            tasks=self.services.tasks,
            wiki=self.services.wiki,
            wiki_workflow=self.services.wiki_workflow,
            observer=tool_results.append,
        )
        chat_model = self._model_for(AgentId.CHAT_AGENT)
        if hasattr(chat_model, "complete_with_tools"):
            tool_names = _chat_agent_tool_names(state)
            result = await chat_model.complete_with_tools(
                user_message=self._message_with_runtime_context(state),
                system_prompt=_chat_system_prompt(),
                tools=observed_toolset.allowed_tools(tool_names),
            )
            return result.text, tool_results

        response = await chat_model.complete(
            user_message=self._message_with_runtime_context(state),
            system_prompt=_chat_system_prompt(),
        )
        return response, tool_results

    async def _fallback_text_search_tool_call(
        self,
        state: AgentState,
        response: str,
    ) -> tuple[str, list[AgentToolResult]] | None:
        query = _parse_text_search_tool_call(response)
        if query is None:
            return None
        if state.citations:
            return state.response_text or _grounded_response_from_citations(state.citations), []
        if self.services.retrieval is None:
            return _local_knowledge_not_found_response(), []

        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            observer=tool_results.append,
        )
        search_response = await observed_toolset.search_memory(
            query=query or state.user_message,
            top_k=5,
            mode="fts",
        )
        if not search_response.results:
            return _local_knowledge_not_found_response(), tool_results
        return _grounded_response_from_search(search_response), tool_results

    async def _answer_with_chat_model(
        self,
        state: AgentState,
        system_prompt: str | None = None,
    ) -> str:
        chat_model = self._model_for(AgentId.CHAT_AGENT)
        if chat_model is None:
            return _local_knowledge_not_found_response()
        if hasattr(chat_model, "complete_with_tools"):
            result = await chat_model.complete_with_tools(
                user_message=self._message_with_runtime_context(state),
                system_prompt=system_prompt or _chat_system_prompt(),
                tools=(),
            )
            return result.text
        response = await chat_model.complete(
            user_message=self._message_with_runtime_context(state),
            system_prompt=system_prompt or _chat_system_prompt(),
        )
        return response

    async def _fallback_grounded_search(
        self,
        state: AgentState,
    ) -> tuple[str, list[AgentToolResult]]:
        if self.services.retrieval is None:
            return "", []

        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            observer=tool_results.append,
        )
        try:
            search_response = await observed_toolset.search_memory(
                query=state.user_message,
                top_k=5,
                mode="fts",
            )
        except Exception:
            return "", []
        if not search_response.results:
            return "", []
        return _grounded_response_from_search(search_response), tool_results

    async def _fallback_scoped_retrieval(
        self,
        state: AgentState,
        semantic: SemanticAnalysisResult,
    ) -> tuple[str, list[AgentToolResult]]:
        if self.services.retrieval is None:
            return "", []

        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            observer=tool_results.append,
        )
        try:
            search_response = await observed_toolset.search_memory(
                query=semantic.query or state.user_message,
                top_k=5,
                mode="fts",
                source_scope=semantic.source_scope,
            )
        except Exception:
            return "", []
        if not search_response.results:
            return "", tool_results
        return "", tool_results

    async def _fallback_memory_proposal(
        self,
        state: AgentState,
    ) -> tuple[str, list[AgentToolResult]]:
        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            memory=self.services.memory,
            observer=tool_results.append,
        )
        await observed_toolset.propose_memory(
            content=_strip_memory_command(state.user_message),
            target_path=DEFAULT_MEMORY_TARGET_PATH,
            source_message_id=state.message_id,
        )
        return "我已创建一条待确认的记忆提案，请审核后再写入。", tool_results

    async def _fallback_create_task(
        self,
        state: AgentState,
    ) -> tuple[str, list[AgentToolResult]]:
        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            tasks=self.services.tasks,
            observer=tool_results.append,
        )
        await observed_toolset.create_task(
            title=_task_title(state.user_message),
            source_text=state.user_message,
        )
        return "我已创建任务。", tool_results

    async def _optional_task_reply(self, state: AgentState, fallback_response: str) -> str:
        try:
            chat_model = self._model_for(AgentId.TASK_AGENT)
            if chat_model is None:
                return fallback_response
            if hasattr(chat_model, "complete_with_tools"):
                result = await chat_model.complete_with_tools(
                    user_message=_task_confirmation_prompt(state),
                    system_prompt=_task_confirmation_system_prompt(),
                    tools=(),
                )
                return result.text
            return await chat_model.complete(
                user_message=_task_confirmation_prompt(state),
                system_prompt=_task_confirmation_system_prompt(),
            )
        except Exception:
            return fallback_response

    async def _fallback_manage_wiki(
        self,
        state: AgentState,
    ) -> tuple[str, list[AgentToolResult]]:
        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            wiki_workflow=self.services.wiki_workflow,
            observer=tool_results.append,
        )
        kind = _wiki_proposal_kind(state.user_message)
        title = _wiki_title(state.user_message)
        content = _strip_wiki_command(state.user_message)
        if kind == "query_archive":
            proposal = await observed_toolset.plan_wiki_query_archive(
                question=title,
                answer=content,
                citations=state.citations,
                title=f"查询归档 - {title}",
                tags=["agent-chat", "query-archive"],
                agent_run_id=state.agent_run_id,
                source_message_id=state.message_id,
            )
            return (
                f"已拟好查询归档提案：{proposal.target_path}。"
                "确认后才会写入 Markdown。"
            ), tool_results
        if kind == "synthesize":
            proposal = await observed_toolset.plan_wiki_synthesis(
                title=title,
                content=content,
                source_paths=_extract_wiki_paths(content),
                tags=["agent-chat", "synthesis"],
                source_message_id=state.message_id,
            )
            return (
                f"已拟好 Wiki 综合整理提案：{proposal.target_path}。"
                "确认后才会写入 Markdown。"
            ), tool_results
        if kind == "lint":
            proposal = await observed_toolset.plan_wiki_lint(
                write_report=True,
                source_message_id=state.message_id,
            )
            target = proposal.target_path or "no report file"
            return (
                f"已拟好 Wiki lint 提案：{target}。"
                "确认后才会运行并写入报告。"
            ), tool_results

        proposal = await observed_toolset.plan_wiki_ingest(
            title=title,
            content=content,
            tags=["agent-chat", "wiki-proposal"],
            max_pages=5,
            source_message_id=state.message_id,
        )
        targets = proposal.recommended_targets or [plan.target_path for plan in proposal.page_plans]
        return (
            f"已拟好 Vault 写入计划：{proposal.run_id}。"
            f"建议目标 {len(targets)} 个；确认后才会写入 Markdown。"
        ), tool_results

    async def _run_model_agent_with_tools(
        self,
        *,
        agent_id: AgentId,
        state: AgentState,
        tools: tuple[AgentToolName, ...],
        system_prompt: str,
    ) -> tuple[str, list[AgentToolResult]]:
        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            memory=self.services.memory,
            tasks=self.services.tasks,
            wiki=self.services.wiki,
            wiki_workflow=self.services.wiki_workflow,
            observer=tool_results.append,
        )
        chat_model = self._model_for(agent_id)
        if hasattr(chat_model, "complete_with_tools"):
            tools_for_agent = observed_toolset.allowed_tools(tools)
            tools_for_agent = _force_search_memory_source_scope(tools_for_agent, system_prompt)
            result = await chat_model.complete_with_tools(
                user_message=state.user_message,
                system_prompt=system_prompt,
                tools=tools_for_agent,
            )
            return result.text, tool_results

        response = await chat_model.complete(
            user_message=state.user_message,
            system_prompt=system_prompt,
        )
        return response, tool_results

    def _model_for(self, agent_id: AgentId):
        if self.services.model_registry is not None:
            return self.services.model_registry.get(agent_id)
        if agent_id == AgentId.CHAT_AGENT:
            return self.services.chat_model
        return None

    def _message_with_runtime_context(self, state: AgentState) -> str:
        user_message = _message_with_citation_context(state)
        return _message_with_continuity_context(
            user_message,
            _continuity_presence_context_block(self.services.continuity),
        )

    async def _memory_retrieval_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _agent_state(graph_state)
        semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
        aggregation_scopes = _memory_aggregation_scopes(state, semantic)
        if aggregation_scopes:
            memory_scopes = tuple(scope for scope in aggregation_scopes if scope != "knowledge_base")
            graph_state["retrieval_plan"] = {
                "memory": bool(memory_scopes),
                "knowledge": "knowledge_base" in aggregation_scopes,
            }
            if memory_scopes:
                return await self._aggregate_memory_retrieval_node(
                    graph_state,
                    scopes=memory_scopes,
                )
            return graph_state

        effective_scope = _effective_retrieval_source_scope(state, semantic)
        if effective_scope == "diary_objects":
            graph_state["retrieval_plan"] = {"memory": True, "knowledge": False}
            return await self._split_retrieval_node(
                graph_state,
                agent_id=AgentId.MEMORY_RETRIEVAL_AGENT,
                source_scope="diary_objects",
                stage=_stage_for_source_scope("diary_objects"),
                system_prompt_factory=_memory_retrieval_system_prompt,
                daily_chat_fallback=True,
                update_state_scope=False,
            )
        graph_state["retrieval_plan"] = {
            "memory": True,
            "knowledge": effective_scope == "all",
        }
        source_scope = "daily_chat" if effective_scope == "daily_chat" else "personal_memory"
        return await self._split_retrieval_node(
            graph_state,
            agent_id=AgentId.MEMORY_RETRIEVAL_AGENT,
            source_scope=source_scope,
            stage=_stage_for_source_scope(source_scope),
            system_prompt_factory=_memory_retrieval_system_prompt,
            daily_chat_fallback=source_scope == "personal_memory",
            update_state_scope=effective_scope != "all",
        )

    async def _aggregate_memory_retrieval_node(
        self,
        graph_state: dict[str, Any],
        *,
        scopes: tuple[str, ...],
    ) -> dict[str, Any]:
        state = _agent_state(graph_state)
        semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
        if self.services.retrieval is None:
            return graph_state

        query = _retrieval_query(state, semantic)
        _append_status(
            graph_state,
            "retrieving multi-source companion memory",
            stage="multi_source_memory_retrieval",
        )
        observed_toolset = AgentToolSet(retrieval=self.services.retrieval)
        collected = []
        searched_scopes: list[str] = []
        for scope in scopes:
            try:
                response = await observed_toolset.search_memory(
                    query=query,
                    top_k=MEMORY_CONTEXT_LIMIT,
                    mode="fts",
                    source_scope=scope,
                )
            except Exception:
                continue
            searched_scopes.append(scope)
            collected.extend(response.results)

        compressed = _compress_memory_context_results(
            collected,
            preferred_scopes=scopes,
            limit=MEMORY_CONTEXT_LIMIT,
            per_scope_limit=MEMORY_CONTEXT_PER_SCOPE_LIMIT,
        )
        if compressed:
            state.semantic_analysis = semantic.model_copy(
                update={
                    "source_scope": _context_source_scope(compressed, semantic.source_scope),
                    "query": query,
                }
            )
        _emit_tool_results(
            graph_state,
            [
                AgentToolResult(
                    name="search_memory",
                    value=MemorySearchResponse(
                        results=compressed,
                        metadata={
                            "semantic_available": False,
                            "retrieval_mode": "multi_source",
                            "source_scopes": searched_scopes,
                            "compressed_limit": MEMORY_CONTEXT_LIMIT,
                        },
                    ),
                )
            ],
        )
        return graph_state

    async def _knowledge_retrieval_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _agent_state(graph_state)
        semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
        return await self._split_retrieval_node(
            graph_state,
            agent_id=AgentId.KNOWLEDGE_RETRIEVAL_AGENT,
            source_scope="knowledge_base",
            stage="knowledge_base_retrieval",
            system_prompt_factory=_knowledge_retrieval_system_prompt,
            daily_chat_fallback=False,
        update_state_scope=False,
        )

    async def _split_retrieval_node(
        self,
        graph_state: dict[str, Any],
        *,
        agent_id: AgentId,
        source_scope: str,
        stage: str,
        system_prompt_factory,
        daily_chat_fallback: bool,
        update_state_scope: bool,
    ) -> dict[str, Any]:
        try:
            state = _agent_state(graph_state)
            semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
            scoped_semantic = semantic.model_copy(
                update={
                    "source_scope": source_scope,
                    "query": _retrieval_query(state, semantic),
                }
            )
            if update_state_scope:
                state.semantic_analysis = scoped_semantic
            _append_status(
                graph_state,
                f"retrieving {_source_scope_label(source_scope)}",
                stage=stage,
            )

            chat_model = self._model_for(agent_id)
            if chat_model is not None:
                response, tool_results = await self._run_model_agent_with_tools(
                    agent_id=agent_id,
                    state=state,
                    tools=(AgentToolName.SEARCH_MEMORY,),
                    system_prompt=system_prompt_factory(scoped_semantic),
                )
                _emit_tool_results(graph_state, tool_results)
                if daily_chat_fallback and _has_empty_search_result(tool_results):
                    await self._emit_daily_chat_fallback(
                        graph_state,
                        state,
                        scoped_semantic,
                        update_state_scope=update_state_scope,
                    )
                if not _has_tool_result(tool_results, "search_memory"):
                    fallback_response, fallback_results = await self._fallback_scoped_retrieval(
                        state,
                        scoped_semantic,
                    )
                    _emit_tool_results(graph_state, fallback_results)
                    if daily_chat_fallback and _has_empty_search_result(fallback_results):
                        await self._emit_daily_chat_fallback(
                            graph_state,
                            state,
                            scoped_semantic,
                            update_state_scope=update_state_scope,
                        )
                    response = fallback_response
                state.response_text = "" if _has_tool_result(tool_results, "search_memory") else response
                return graph_state

            _, tool_results = await self._fallback_scoped_retrieval(state, scoped_semantic)
            _emit_tool_results(graph_state, tool_results)
            if daily_chat_fallback and _has_empty_search_result(tool_results):
                await self._emit_daily_chat_fallback(
                    graph_state,
                    state,
                    scoped_semantic,
                    update_state_scope=update_state_scope,
                )
            return graph_state
        except Exception as exc:
            return _record_node_error(graph_state, exc)

    async def _emit_daily_chat_fallback(
        self,
        graph_state: dict[str, Any],
        state: AgentState,
        semantic: SemanticAnalysisResult,
        *,
        update_state_scope: bool,
    ) -> None:
        fallback_daily_results = await self._fallback_daily_chat_context(
            state,
            semantic,
            update_state_scope=update_state_scope,
        )
        if fallback_daily_results:
            _append_status(
                graph_state,
                "personal memory missed; checking daily chat",
                stage="daily_chat_fallback",
            )
            _emit_tool_results(graph_state, fallback_daily_results)

    async def _fallback_daily_chat_context(
        self,
        state: AgentState,
        semantic: SemanticAnalysisResult,
        *,
        update_state_scope: bool = True,
    ) -> list[AgentToolResult]:
        if semantic.source_scope not in {"personal_memory", "diary_objects"} or self.services.retrieval is None:
            return []
        observed_toolset = AgentToolSet(retrieval=self.services.retrieval)
        try:
            response = await observed_toolset.search_memory(
                query=semantic.query or state.user_message,
                top_k=5,
                mode="fts",
                source_scope="daily_chat",
            )
        except Exception:
            return []
        if not response.results:
            return []
        if update_state_scope:
            state.semantic_analysis = semantic.model_copy(update={"source_scope": "daily_chat"})
        return [AgentToolResult(name="search_memory", value=response)]

    async def _memory_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        try:
            state = _agent_state(graph_state)
            chat_model = self._model_for(AgentId.MEMORY_PROPOSAL_AGENT)
            if chat_model is not None:
                response, tool_results = await self._run_model_agent_with_tools(
                    agent_id=AgentId.MEMORY_PROPOSAL_AGENT,
                    state=state,
                    tools=(AgentToolName.PROPOSE_MEMORY,),
                    system_prompt=_memory_system_prompt(),
                )
                _emit_tool_results(graph_state, tool_results)
                if not _has_tool_result(tool_results, "propose_memory"):
                    fallback_response, fallback_results = await self._fallback_memory_proposal(state)
                    _emit_tool_results(graph_state, fallback_results)
                    response = fallback_response
                state.response_text = response
                for chunk in _chunk_text(response):
                    _events(graph_state).append(
                        AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk)
                    )
                return graph_state

            content = _strip_memory_command(state.user_message)
            memory_tool = self.toolset.propose_memory_tool()
            proposal = await memory_tool.ainvoke(
                {
                    "content": content,
                    "target_path": DEFAULT_MEMORY_TARGET_PATH,
                    "source_message_id": state.message_id,
                }
            )
            state.proposal_id = proposal.proposal_id
            response = "我已创建一条待确认的记忆提案，请审核后再写入。"
            state.response_text = response
            _events(graph_state).append(
                AgentMemoryProposalEvent(
                    agent_run_id=state.agent_run_id,
                    proposal_id=proposal.proposal_id,
                    status=proposal.status,
                    target_path=DEFAULT_MEMORY_TARGET_PATH,
                )
            )
            _events(graph_state).append(AgentTokenEvent(agent_run_id=state.agent_run_id, text=response))
            return graph_state
        except Exception as exc:
            return _record_node_error(graph_state, exc)

    async def _wiki_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        try:
            state = _agent_state(graph_state)
            chat_model = self._model_for(AgentId.WIKI_MANAGER_AGENT)
            if chat_model is not None:
                response, tool_results = await self._run_model_agent_with_tools(
                    agent_id=AgentId.WIKI_MANAGER_AGENT,
                    state=state,
                    tools=(
                        AgentToolName.PLAN_WIKI_INGEST,
                        AgentToolName.PLAN_WIKI_QUERY_ARCHIVE,
                        AgentToolName.PLAN_WIKI_SYNTHESIS,
                        AgentToolName.PLAN_WIKI_LINT,
                    ),
                    system_prompt=_wiki_system_prompt(),
                )
                _emit_tool_results(graph_state, tool_results)
                if not _has_wiki_proposal_result(tool_results):
                    fallback_response, fallback_results = await self._fallback_manage_wiki(state)
                    _emit_tool_results(graph_state, fallback_results)
                    response = fallback_response
                state.response_text = response
                for chunk in _chunk_text(response):
                    _events(graph_state).append(
                        AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk)
                    )
                return graph_state

            response, tool_results = await self._fallback_manage_wiki(state)
            _emit_tool_results(graph_state, tool_results)
            state.response_text = response
            _events(graph_state).append(AgentTokenEvent(agent_run_id=state.agent_run_id, text=response))
            return graph_state
        except Exception as exc:
            return _record_node_error(graph_state, exc)

    async def _task_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        try:
            state = _agent_state(graph_state)
            response, tool_results = await self._fallback_create_task(state)
            _emit_tool_results(graph_state, tool_results)
            response = await self._optional_task_reply(state, response)
            state.response_text = response
            for chunk in _chunk_text(response):
                _events(graph_state).append(
                    AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk)
                )
            return graph_state
        except Exception as exc:
            return _record_node_error(graph_state, exc)

    async def _finish_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _agent_state(graph_state)
        if not graph_state.get("failed"):
            state.status = AgentRunStatus.SUCCESS
            _append_status(graph_state, "回复已完成，后台保存聊天记忆。", stage="background_memory")
            _events(graph_state).append(
                AgentDoneEvent(
                    agent_run_id=state.agent_run_id,
                    intent=state.route.intent,
                    text=state.response_text,
                )
            )
        return graph_state


def _agent_state(graph_state: dict[str, Any]) -> AgentState:
    return graph_state["agent_state"]


def _events(graph_state: dict[str, Any]) -> list[AgentEventBase]:
    return graph_state["events"]


def _append_status(graph_state: dict[str, Any], message: str, *, stage: str | None = None) -> None:
    state = _agent_state(graph_state)
    _events(graph_state).append(
        AgentStatusEvent(
            agent_run_id=state.agent_run_id,
            status=state.status,
            intent=state.route.intent if state.route else None,
            message=message,
            stage=stage,
        )
    )


def _select_retrieval_entry_node(graph_state: dict[str, Any]) -> str:
    state = _agent_state(graph_state)
    semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
    aggregation_scopes = _memory_aggregation_scopes(state, semantic)
    if aggregation_scopes:
        graph_state["retrieval_plan"] = {
            "memory": any(scope != "knowledge_base" for scope in aggregation_scopes),
            "knowledge": "knowledge_base" in aggregation_scopes,
        }
        return "memory_retrieval_agent"
    effective_scope = _effective_retrieval_source_scope(state, semantic)
    if effective_scope == "knowledge_base":
        graph_state["retrieval_plan"] = {"memory": False, "knowledge": True}
        return "knowledge_retrieval_agent"
    if effective_scope == "diary_objects":
        graph_state["retrieval_plan"] = {"memory": True, "knowledge": False}
        return "memory_retrieval_agent"
    if effective_scope == "all":
        graph_state["retrieval_plan"] = {"memory": True, "knowledge": True}
        return "memory_retrieval_agent"
    graph_state["retrieval_plan"] = {"memory": True, "knowledge": False}
    return "memory_retrieval_agent"


def _effective_retrieval_source_scope(state: AgentState, semantic: SemanticAnalysisResult) -> str:
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY and semantic.source_scope == "none":
        return "all"
    if (
        state.route
        and state.route.intent == AgentIntent.SEARCH_MEMORY
        and semantic.source_scope == "knowledge_base"
        and state.memory_route is not None
        and semantic.reason == state.memory_route.reason
    ):
        return "all"
    return semantic.source_scope


def _retrieval_query(state: AgentState, semantic: SemanticAnalysisResult) -> str:
    if semantic.query.strip():
        return semantic.query
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY:
        return _strip_search_command(state.user_message)
    return state.user_message


def _should_call_semantic_agent(state: AgentState) -> bool:
    if state.memory_route and state.memory_route.semantic_fallback:
        return True
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY:
        return True
    return False


def _semantic_from_memory_route(route: MemoryRoute, state: AgentState) -> SemanticAnalysisResult:
    source_scope = _source_scope_from_memory_route(route)
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY and source_scope in {"none", "knowledge_base"}:
        source_scope = "all"
    return SemanticAnalysisResult(
        needs_context=source_scope != "none",
        source_scope=source_scope,
        query=_strip_search_command(route.query or state.user_message),
        answer_style=route.answer_style,
        confidence=route.confidence,
        reason=route.reason,
    )


def _source_scope_from_memory_route(route: MemoryRoute) -> str:
    scopes = route.all_scopes
    if not scopes or scopes == ("none",):
        return "none"
    first = route.primary_scopes[0] if route.primary_scopes else scopes[0]
    if first in {"knowledge_base", "personal_memory", "diary_objects", "daily_chat"}:
        return first
    return route.legacy_source_scope


def _memory_aggregation_scopes(state: AgentState, semantic: SemanticAnalysisResult) -> tuple[str, ...]:
    route = state.memory_route
    if route is None or not semantic.needs_context:
        return ()
    if route.semantic_fallback:
        return ()
    if route.reason not in {
        "long_term_preference",
        "personal_experience_or_emotional_continuity",
    }:
        return ()
    scopes = tuple(scope for scope in route.all_scopes if scope != "none")
    if len(scopes) <= 1:
        return ()
    effective_scope = _effective_retrieval_source_scope(state, semantic)
    if effective_scope == "all":
        return scopes
    if semantic.reason != route.reason:
        return ()
    return scopes


def _force_search_memory_source_scope(
    tools: list[StructuredTool],
    system_prompt: str,
) -> list[StructuredTool]:
    source_scope = _source_scope_from_prompt(system_prompt)
    if source_scope is None:
        return tools
    wrapped = []
    for tool in tools:
        if tool.name != "search_memory":
            wrapped.append(tool)
            continue

        forced_scope = source_scope

        async def search_memory_with_scope(
            query: str,
            top_k: int = 5,
            mode: str = "fts",
            source_scope: str = "",
            _tool=tool,
            _forced_scope: str = forced_scope,
        ):
            return await _tool.ainvoke(
                {
                    "query": query,
                    "top_k": top_k,
                    "mode": mode,
                    "source_scope": _forced_scope,
                }
            )

        wrapped.append(
            StructuredTool.from_function(
                coroutine=search_memory_with_scope,
                name=tool.name,
                description=tool.description,
                args_schema=tool.args_schema,
            )
        )
    return wrapped


def _source_scope_from_prompt(system_prompt: str) -> str | None:
    marker = "source_scope="
    start = system_prompt.find(marker)
    if start < 0:
        return None
    rest = system_prompt[start + len(marker) :]
    if not rest:
        return None
    quote = rest[0]
    if quote not in {"'", '"'}:
        return None
    end = rest.find(quote, 1)
    if end < 0:
        return None
    scope = rest[1:end]
    if scope in {"personal_memory", "diary_objects", "daily_chat", "knowledge_base", "all"}:
        return scope
    return None


def _has_tool_result(results: list[AgentToolResult], name: str) -> bool:
    return any(result.name == name for result in results)


def _has_empty_search_result(results: list[AgentToolResult]) -> bool:
    return any(
        result.name == "search_memory"
        and isinstance(result.value, MemorySearchResponse)
        and not result.value.results
        for result in results
    )


def _has_wiki_proposal_result(results: list[AgentToolResult]) -> bool:
    return any(
        result.name
        in {
            "plan_wiki_ingest",
            "plan_wiki_query_archive",
            "plan_wiki_synthesis",
            "plan_wiki_lint",
        }
        for result in results
    )


def _should_require_grounding(message: str) -> bool:
    normalized = message.casefold()
    markers = (
        "search memory",
        "search memories",
        "find in memory",
        "lookup memory",
        "search notes",
        "search docs",
        "what do you remember",
        "recall",
        "查一下记忆",
        "查一下知识库",
        "搜索记忆",
        "查找记忆",
        "检索记忆",
        "你记得",
        "知识库里",
        "记忆里",
        "记忆中",
        "笔记里",
        "文档里",
        "之前记录",
        "回忆一下",
    )
    return any(marker in normalized for marker in markers)


def _chat_agent_tool_names(state: AgentState) -> tuple[AgentToolName, ...]:
    names: list[AgentToolName] = []
    if _should_require_grounding(state.user_message) and not state.response_text:
        names.append(AgentToolName.SEARCH_MEMORY)
    if _should_offer_wiki_management(state.user_message):
        kind = _wiki_proposal_kind(state.user_message)
        if kind == "query_archive":
            names.append(AgentToolName.PLAN_WIKI_QUERY_ARCHIVE)
        elif kind == "synthesize":
            names.append(AgentToolName.PLAN_WIKI_SYNTHESIS)
        elif kind == "lint":
            names.append(AgentToolName.PLAN_WIKI_LINT)
        else:
            names.append(AgentToolName.PLAN_WIKI_INGEST)
    return tuple(names)


def _should_offer_wiki_management(message: str) -> bool:
    normalized = message.casefold()
    markers = (
        "obsidian note",
        "obsidian page",
        "vault note",
        "vault page",
        "knowledge-base note",
        "knowledge base note",
        "wiki note",
        "wiki page",
        "query archive",
        "archive query",
        "synthesis",
        "synthesize",
        "wiki lint",
        "lint report",
        "turn this into a note",
        "make this a note",
        "整理成笔记",
        "整理成知识库",
        "查询归档",
        "归档回答",
        "综合整理",
        "wiki 检查",
        "检查 wiki",
        "整理到笔记",
        "整理到 vault",
        "整理到vault",
        "转成笔记",
        "变成笔记",
        "obsidian 笔记",
        "vault 笔记",
    )
    return any(marker in normalized for marker in markers)


def _wiki_proposal_kind(message: str) -> str:
    normalized = message.casefold()
    if any(
        marker in normalized
        for marker in (
            "query archive",
            "archive query",
            "archive answer",
            "归档回答",
            "归档查询",
            "查询归档",
        )
    ):
        return "query_archive"
    if any(
        marker in normalized
        for marker in (
            "synthesize",
            "synthesis",
            "综合整理",
            "综合成",
            "整合成",
            "整理综合",
        )
    ):
        return "synthesize"
    if any(
        marker in normalized
        for marker in (
            "wiki lint",
            "lint report",
            "lint wiki",
            "wiki health",
            "检查 wiki",
            "wiki 检查",
            "wiki 体检",
            "质量报告",
        )
    ):
        return "lint"
    return "ingest"


def _extract_wiki_paths(text: str) -> list[str]:
    paths = re.findall(r"Wiki/[A-Za-z0-9_./\-\u4e00-\u9fff ]+\.md", text)
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        normalized = path.strip().replace("\\", "/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result[:10]


def _semantic_system_prompt() -> str:
    return (
        "你是 semantic_analysis_agent，只输出 JSON。"
        "字段：needs_context(boolean), source_scope(one of none,personal_memory,daily_chat,knowledge_base,all), "
        "query(string), answer_style(one of casual,concise,grounded,clarifying), confidence(number), reason(string)。"
        "判断用户是否在询问个人记忆、每日聊天记录或知识库资料；普通闲聊 needs_context=false。"
    )


def _memory_retrieval_system_prompt(semantic: SemanticAnalysisResult) -> str:
    return (
        "You are memory_retrieval_agent. Use only the search_memory tool. "
        f"You must call search_memory with query={semantic.query!r}, "
        f"source_scope={semantic.source_scope!r}. Do not answer the user. "
        "Do not create memories, wiki pages, tasks, or reminders."
    )


def _knowledge_retrieval_system_prompt(semantic: SemanticAnalysisResult) -> str:
    return (
        "You are knowledge_retrieval_agent. Use only the search_memory tool. "
        f"You must call search_memory with query={semantic.query!r}, "
        "source_scope='knowledge_base'. Do not answer the user. "
        "Do not create memories, wiki pages, tasks, or reminders."
    )


def _parse_semantic_analysis(text: str, user_message: str) -> SemanticAnalysisResult:
    data = json.loads(_extract_json_object(text))
    result = SemanticAnalysisResult.model_validate(data)
    forced_scope = _forced_source_scope(user_message)
    if forced_scope is not None:
        return result.model_copy(
            update={
                "needs_context": True,
                "source_scope": forced_scope,
                "query": user_message,
                "answer_style": "grounded",
                "reason": "forced_date_or_memory_scope",
            }
        )
    if result.needs_context and not result.query.strip():
        return result.model_copy(update={"query": user_message})
    return result


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("semantic_analysis_json_missing")
    return text[start : end + 1]


def _fallback_semantic_analysis(state: AgentState) -> SemanticAnalysisResult:
    source_scope = _fallback_source_scope(state.user_message)
    if source_scope != "none":
        return SemanticAnalysisResult(
            needs_context=True,
            source_scope=source_scope,
            query=_strip_search_command(state.user_message),
            answer_style="grounded",
            confidence=state.route.confidence if state.route else 0.65,
            reason=state.route.reason if state.route else "fallback_context",
        )
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY:
        return SemanticAnalysisResult(
            needs_context=True,
            source_scope="all",
            query=_strip_search_command(state.user_message),
            answer_style="grounded",
            confidence=state.route.confidence,
            reason=state.route.reason,
        )
    if state.route and state.route.intent == AgentIntent.MANAGE_WIKI:
        return SemanticAnalysisResult(
            needs_context=False,
            source_scope="none",
            query=state.user_message,
            answer_style="concise",
            confidence=state.route.confidence,
            reason=state.route.reason,
        )
    return SemanticAnalysisResult(
        needs_context=False,
        source_scope="none",
        query=state.user_message,
        answer_style="casual",
        confidence=0.4,
        reason="fallback_chat",
    )


def _fallback_source_scope(message: str) -> str:
    forced_scope = _forced_source_scope(message)
    if forced_scope is not None:
        return forced_scope
    normalized = message.casefold()
    if re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*(号|日)?", message) or "之前" in message or "回忆" in message:
        return "daily_chat"
    if "知识库" in message or "文档" in message or "笔记" in message or "docs" in normalized:
        return "knowledge_base"
    if any(marker in message for marker in ("我喜欢", "我偏好", "我的喜好", "我的偏好", "你记得我", "记得我")):
        return "personal_memory"
    return "none"


def _forced_source_scope(message: str) -> str | None:
    if _is_daily_chat_date_recall(message):
        return "daily_chat"
    return None


def _is_daily_chat_date_recall(message: str) -> bool:
    if not re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*(?:号|日)?", message):
        return False
    markers = (
        "我说了什么",
        "我们说了什么",
        "咱们说了什么",
        "聊了什么",
        "问了什么",
        "提了什么",
        "说过什么",
        "什么事情",
        "什么事",
    )
    return any(marker in message for marker in markers)


def _parse_text_search_tool_call(text: str) -> str | None:
    if "<tool_call" not in text.casefold():
        return None
    tool_name = re.search(
        r"<function\s*=\s*['\"]?(search_memory|search_notes|search_docs)['\"]?\s*>",
        text,
        re.IGNORECASE,
    )
    if tool_name is None:
        return None
    query = re.search(
        r"<parameter\s*=\s*['\"]?query['\"]?\s*>(.*?)</parameter>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if query is None:
        return ""
    return unescape(re.sub(r"<[^>]+>", "", query.group(1))).strip()


def _grounded_response_from_search(search_response: MemorySearchResponse) -> str:
    return _grounded_response_from_citations(search_response.results)


def _grounded_response_from_citations(results) -> str:
    snippets = [result.snippet.strip() for result in results[:3] if result.snippet.strip()]
    if not snippets:
        return _local_knowledge_not_found_response()
    summary = "；".join(snippets)
    source_label = _source_scope_label(getattr(results[0], "source_scope", "all"))
    return f"我翻到了相关{source_label}：{summary}。如果你愿意，我可以继续帮你整理成更短的结论。"


def _compress_memory_context_results(
    results,
    *,
    preferred_scopes: tuple[str, ...],
    limit: int,
    per_scope_limit: int,
):
    preferred_weight = {
        scope: len(preferred_scopes) - index
        for index, scope in enumerate(preferred_scopes)
    }
    by_scope_count: dict[str, int] = {}
    seen: set[tuple[str, str, str]] = set()
    ranked = sorted(
        results,
        key=lambda result: (
            -preferred_weight.get(result.source_scope, 0),
            -_context_source_weight(result.source_scope),
            -result.score,
            result.relative_path,
            result.heading or "",
        ),
    )
    compressed = []
    for result in ranked:
        key = (
            result.relative_path,
            result.heading or "",
            " ".join(result.snippet.split()).casefold(),
        )
        if key in seen:
            continue
        scope_count = by_scope_count.get(result.source_scope, 0)
        if scope_count >= per_scope_limit:
            continue
        seen.add(key)
        by_scope_count[result.source_scope] = scope_count + 1
        compressed.append(result)
        if len(compressed) >= limit:
            break
    return compressed


def _context_source_weight(source_scope: str) -> int:
    return {
        "personal_memory": 4,
        "diary_objects": 3,
        "daily_chat": 2,
        "knowledge_base": 1,
    }.get(source_scope, 0)


def _context_source_scope(results, fallback: str) -> str:
    scopes = []
    for result in results:
        if result.source_scope not in scopes:
            scopes.append(result.source_scope)
    if len(scopes) == 1:
        return scopes[0]
    if scopes:
        return "all"
    return fallback


def _memory_system_prompt() -> str:
    return (
        "你是 memory_proposal_agent，只能使用 propose_memory 工具创建待确认记忆提案。"
        "不要直接声称已经写入长期记忆。"
    )


def _wiki_system_prompt() -> str:
    return (
        "You are wiki_manager_agent. Use only Wiki proposal tools: plan_wiki_ingest, "
        "plan_wiki_query_archive, plan_wiki_synthesis, or plan_wiki_lint. These tools only "
        "draft, lint, or preview proposed Wiki actions and must not write Markdown. Never "
        "claim the Vault was updated until the user explicitly confirms the proposed apply step."
    )


def _task_system_prompt() -> str:
    return (
        "你是 task_agent，只能使用 create_task 工具创建本地任务或提醒。"
        "不要暴露其他工具，也不要声称执行了未发生的操作。"
    )


def _task_confirmation_system_prompt() -> str:
    return (
        "你是桌面助手。任务或提醒已经由本地服务创建完成。"
        "只用一句简短中文确认，不要调用工具，不要重新解析时间。"
    )


def _task_confirmation_prompt(state: AgentState) -> str:
    parts = [
        f"用户原话：{state.user_message}",
        f"任务标题：{_task_title(state.user_message)}",
    ]
    if state.reminder_id:
        parts.append("提醒状态：已创建提醒")
    else:
        parts.append("提醒状态：只创建了任务")
    return "\n".join(parts)


def _local_knowledge_not_found_response() -> str:
    return "我翻了下记忆本，暂时没有找到能引用的记录，所以这部分我不装懂。你可以告诉我一点背景，我也可以先按一般经验陪你分析。"


def _knowledge_not_found_chat_prompt() -> str:
    return (
        _chat_system_prompt()
        + "当前检索上下文为空。请用桌宠口吻说明没有翻到相关记忆，不要编造用户记忆；"
        "然后给出一个自然追问或提供按一般经验继续分析的选项。"
    )


def _message_with_citation_context(state: AgentState) -> str:
    if not state.citations:
        return state.user_message
    snippets = "\n".join(
        f"- {citation.relative_path}"
        f"{f' / {citation.heading}' if citation.heading else ''}: {citation.snippet}"
        for citation in state.citations[:5]
    )
    semantic = state.semantic_analysis
    answer_style = semantic.answer_style if semantic else "grounded"
    source_scope = semantic.source_scope if semantic else "all"
    source_label = _source_scope_label(source_scope)
    source_instruction = (
        "这些只是聊天日记里的弱记录，不能称为已经确认的长期记忆；"
        "如果据此回答，必须明确说还没沉淀为长期记忆。"
        if source_scope == "daily_chat"
        else f"可以概括为我翻到的{source_label}显示，并在不确定时主动说明。"
    )
    return (
        f"用户问题：{state.user_message}\n\n"
        f"上下文范围：{source_scope}（{source_label}）\n"
        f"回答风格：{answer_style}\n"
        f"已检索到的上下文片段：\n{snippets}\n\n"
        "请用桌宠口吻给出简短自然回答。不要逐条展开引用路径或原始 snippet；"
        f"{source_instruction}"
    )


def _source_scope_label(source_scope: str) -> str:
    return {
        "personal_memory": "记忆本",
        "diary_objects": "结构化聊天日记",
        "daily_chat": "聊天日记",
        "knowledge_base": "资料库",
        "all": "记忆/资料",
    }.get(source_scope, "记忆/资料")


def _stage_for_source_scope(source_scope: str) -> str:
    return {
        "personal_memory": "personal_memory_retrieval",
        "diary_objects": "diary_object_retrieval",
        "daily_chat": "daily_chat_retrieval",
        "knowledge_base": "knowledge_base_retrieval",
        "all": "multi_source_retrieval",
    }.get(source_scope, "multi_source_retrieval")


def _emit_tool_results(graph_state: dict[str, Any], results: list[AgentToolResult]) -> None:
    state = _agent_state(graph_state)
    for result in results:
        value = result.value
        if result.name == "search_memory" and isinstance(value, MemorySearchResponse):
            state.citations = [*state.citations, *value.results]
            for citation in value.results:
                _events(graph_state).append(
                    AgentCitationEvent(agent_run_id=state.agent_run_id, citation=citation)
                )
        elif result.name == "propose_memory" and isinstance(value, MemoryProposalActionResponse):
            state.proposal_id = value.proposal_id
            _events(graph_state).append(
                AgentMemoryProposalEvent(
                    agent_run_id=state.agent_run_id,
                    proposal_id=value.proposal_id,
                    status=value.status,
                    target_path=DEFAULT_MEMORY_TARGET_PATH,
                )
            )
        elif result.name == "create_task" and isinstance(value, TaskCreateResponse):
            state.task_id = value.task_id
            state.reminder_id = value.reminder_id
            _events(graph_state).append(
                AgentTaskEvent(
                    agent_run_id=state.agent_run_id,
                    task_id=value.task_id,
                    status=value.status,
                    reminder_id=value.reminder_id,
                    title=value.metadata.get("title") or None,
                    reminder_status=value.metadata.get("reminder_status") or None,
                    remind_at=value.metadata.get("remind_at") or None,
                    timezone=value.metadata.get("timezone") or None,
                    timezone_label=value.metadata.get("timezone_label") or None,
                )
            )
        elif result.name == "plan_wiki_ingest" and isinstance(value, WikiIngestProposal):
            state.proposal_id = value.run_id
            _events(graph_state).append(_wiki_proposal_event(state, value))
        elif result.name == "plan_wiki_query_archive" and isinstance(value, WikiQueryArchiveProposal):
            state.proposal_id = value.target_path
            _events(graph_state).append(_wiki_proposal_event(state, value))
        elif result.name == "plan_wiki_synthesis" and isinstance(value, WikiSynthesisProposal):
            state.proposal_id = value.target_path
            _events(graph_state).append(_wiki_proposal_event(state, value))
        elif result.name == "plan_wiki_lint" and isinstance(value, WikiLintProposal):
            state.proposal_id = value.target_path or "wiki-lint"
            _events(graph_state).append(_wiki_proposal_event(state, value))
        elif result.name == "manage_wiki_page" and isinstance(value, WikiPageResponse):
            state.response_text = state.response_text or f"Wiki 页面已更新：{value.relative_path}"


def _wiki_proposal_event(
    state: AgentState,
    proposal: WikiIngestProposal | WikiQueryArchiveProposal | WikiSynthesisProposal | WikiLintProposal,
) -> AgentWikiProposalEvent:
    if isinstance(proposal, WikiQueryArchiveProposal):
        return AgentWikiProposalEvent(
            agent_run_id=state.agent_run_id,
            proposal_type="query_archive",
            status=proposal.status,
            title=proposal.title,
            target_paths=[proposal.target_path],
            markdown_preview=proposal.markdown_preview,
            source_message_id=proposal.source_message_id,
            errors=proposal.lint.errors,
            warnings=proposal.lint.warnings,
            findings=[
                {
                    "severity": "error",
                    "code": error,
                    "message": error,
                    "target_path": proposal.target_path,
                }
                for error in proposal.lint.errors
            ],
        )
    if isinstance(proposal, WikiSynthesisProposal):
        return AgentWikiProposalEvent(
            agent_run_id=state.agent_run_id,
            proposal_type="synthesize",
            status=proposal.status,
            title=proposal.title,
            target_paths=[proposal.target_path],
            recommended_targets=[proposal.target_path],
            markdown_preview=proposal.markdown_preview,
            source_message_id=proposal.source_message_id,
        )
    if isinstance(proposal, WikiLintProposal):
        return AgentWikiProposalEvent(
            agent_run_id=state.agent_run_id,
            proposal_type="lint",
            status=proposal.status,
            title=proposal.title,
            target_paths=[proposal.target_path] if proposal.target_path else [],
            recommended_targets=[proposal.target_path] if proposal.target_path else [],
            findings=[issue.model_dump(mode="json") for issue in proposal.issues],
            lint_summary=proposal.summary,
            write_report=proposal.write_report,
            markdown_preview=proposal.markdown_preview,
            source_message_id=proposal.source_message_id,
        )
    return AgentWikiProposalEvent(
        agent_run_id=state.agent_run_id,
        proposal_type="ingest",
        status=proposal.status,
        title=proposal.title,
        run_id=proposal.run_id,
        source_id=proposal.source_id,
        source_hash=proposal.source_hash,
        review_id=proposal.review_id,
        review_status=proposal.review_status,
        summary=proposal.summary,
        review_summary=proposal.review_summary,
        target_paths=[plan.target_path for plan in proposal.page_plans],
        recommended_targets=proposal.recommended_targets,
        findings=[finding.model_dump(mode="json") for finding in proposal.review_findings],
        source_message_id=proposal.source_message_id,
    )


def _record_node_error(graph_state: dict[str, Any], exc: Exception) -> dict[str, Any]:
    state = _agent_state(graph_state)
    graph_state["failed"] = True
    state.status = AgentRunStatus.FAILED
    state.error_code = getattr(exc, "code", exc.__class__.__name__)
    state.error_message = str(exc)
    _events(graph_state).append(
        AgentErrorEvent(
            agent_run_id=state.agent_run_id,
            code=state.error_code,
            message=state.error_message,
        )
    )
    return graph_state
