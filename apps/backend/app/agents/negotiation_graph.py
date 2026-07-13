from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph


def build_negotiation_graph(
    *,
    route_node: Callable[[dict[str, Any]], Any],
    semantic_node: Callable[[dict[str, Any]], Any],
    select_after_semantic: Callable[[dict[str, Any]], str],
    orchestrator_node: Callable[[dict[str, Any]], Any],
    invoke_agent_node: Callable[[dict[str, Any]], Any],
    action_node: Callable[[dict[str, Any]], Any],
    synthesizer_node: Callable[[dict[str, Any]], Any],
    finish_node: Callable[[dict[str, Any]], Any],
):
    graph = StateGraph(dict)
    graph.add_node("route", route_node)
    graph.add_node("semantic_analysis_agent", semantic_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("invoke_agent", invoke_agent_node)
    graph.add_node("action_agent", action_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("finish", finish_node)

    graph.add_edge(START, "route")
    graph.add_edge("route", "semantic_analysis_agent")
    graph.add_conditional_edges(
        "semantic_analysis_agent",
        select_after_semantic,
        {
            "orchestrator": "orchestrator",
            "action_agent": "action_agent",
            "synthesizer": "synthesizer",
        },
    )
    graph.add_conditional_edges(
        "orchestrator",
        _select_after_orchestrator,
        {
            "invoke_agent": "invoke_agent",
            "synthesize": "synthesizer",
        },
    )
    graph.add_conditional_edges(
        "invoke_agent",
        _select_after_invocation,
        {
            "orchestrator": "orchestrator",
            "synthesize": "synthesizer",
        },
    )
    graph.add_edge("action_agent", "synthesizer")
    graph.add_edge("synthesizer", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def build_supervisor_graph(
    *,
    route_node: Callable[[dict[str, Any]], Any],
    semantic_node: Callable[[dict[str, Any]], Any],
    select_after_semantic: Callable[[dict[str, Any]], str],
    supervisor_node: Callable[[dict[str, Any]], Any],
    action_node: Callable[[dict[str, Any]], Any],
    synthesizer_node: Callable[[dict[str, Any]], Any],
    finish_node: Callable[[dict[str, Any]], Any],
):
    graph = StateGraph(dict)
    graph.add_node("route", route_node)
    graph.add_node("semantic_analysis_agent", semantic_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("action_agent", action_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("finish", finish_node)

    graph.add_edge(START, "route")
    graph.add_edge("route", "semantic_analysis_agent")
    graph.add_conditional_edges(
        "semantic_analysis_agent",
        select_after_semantic,
        {
            "orchestrator": "supervisor",
            "action_agent": "action_agent",
            "synthesizer": "synthesizer",
        },
    )
    graph.add_edge("supervisor", "synthesizer")
    graph.add_edge("action_agent", "synthesizer")
    graph.add_edge("synthesizer", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def _select_after_orchestrator(graph_state: dict[str, Any]) -> str:
    return graph_state.get("next", "synthesize")


def _select_after_invocation(graph_state: dict[str, Any]) -> str:
    return graph_state.get("next", "orchestrator")
