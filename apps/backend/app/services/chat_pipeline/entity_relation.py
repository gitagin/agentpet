"""聊天回复后的实体关系抽取阶段。

把 Wiki 入库已有的 LLM 三元组抽取能力（extract_with_policy 的验证/落库/激活），
接入聊天回复后的后台流水线：从用户本轮消息提取实体 + 关系，落库为候选；
当用户使用了显式记忆指令（如"记住…"）时，对低风险、无歧义的批次直接激活，
从而在记忆图谱里产生"实体↔实体"的关系边，而不是只产生孤点。

安全边界沿用 memory_entity_extraction 的既有策略：
- 完整批次校验通过才落库（parse_extraction_output）
- 默认候选态，不激活；只有显式用户声明才尝试激活
- 激活前拒绝 unresolved/sensitive/conflicts/uncertainties 的批次
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.services.agent_actions import AgentActionCreate, AutomationPolicy

if TYPE_CHECKING:
    from app.api.wiring import AppContext

logger = logging.getLogger(__name__)


def _extract_json_object(text: str) -> dict[str, Any]:
    """把模型返回的文本（可能带 markdown 代码块）解析成 JSON 对象。"""
    candidates = [text.strip()]
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidates.append("\n".join(lines).strip())
    for candidate in candidates:
        if not candidate:
            continue
        start_indexes = [i for i in (candidate.find("{"), candidate.find("[")) if i >= 0]
        if not start_indexes:
            continue
        start = min(start_indexes)
        opener = candidate[start]
        closer = "}" if opener == "{" else "]"
        end = candidate.rfind(closer)
        if end < start:
            continue
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("entity_relation_json_unparseable")


async def archive_entity_relations(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    daily_result: Any | None = None,
    diary_object_ids: tuple[str, ...] = (),
    automation,
    policy: AutomationPolicy,
    raise_errors: bool = False,
) -> list[AgentActionEvent]:
    from app.api.services.factory import chat_model_client, memory_entity_graph_store, record_agent_action
    from app.services.memory_consolidation import _looks_explicit_memory_request
    from app.services.memory_entity_extraction import (
        activate_extraction_candidates,
        parse_extraction_output,
        persist_extraction_candidates,
    )

    from . import agent_action_event, skipped_agent_action_event

    source_text = (state.user_message or "").strip()
    if not source_text:
        return []

    skip = lambda title, summary, reason: [  # noqa: E731 - 局部便捷函数
        skipped_agent_action_event(
            context=context,
            state=state,
            action_type="memory.entity_relation.skip",
            title=title,
            summary=summary,
            reason=reason,
        )
    ]

    model = chat_model_client(context)
    if model is None:
        return skip("跳过实体关系抽取", "本机模型未配置，跳过实体关系抽取。", "model_unavailable")

    try:
        response = await model.complete(
            user_message=_user_prompt(source_text),
            system_prompt=ENTITY_RELATION_SYSTEM_PROMPT,
        )
        payload = _extract_json_object(str(response))
        batch = parse_extraction_output(payload, source_text)
    except Exception as exc:
        if raise_errors:
            raise
        logger.warning("Entity relation extraction failed for agent_run_id=%s: %s", state.agent_run_id, exc)
        return skip("跳过实体关系抽取", "本轮对话未提取出可落库的实体关系。", "extraction_failed")

    if not batch.entities and not batch.relations:
        return skip("跳过实体关系抽取", "本轮对话没有新的实体或关系。", "no_signal")

    store = memory_entity_graph_store(context)
    try:
        resolved = persist_extraction_candidates(
            store,
            batch,
            source_text=source_text,
            source_type="user_message",
            source_id=state.message_id,
        )
        activated_count = 0
        if _looks_explicit_memory_request(source_text):
            try:
                activation = activate_extraction_candidates(
                    store,
                    resolved,
                    explicit_user=True,
                    reason="explicit_user_chat",
                )
                activated_count = len(activation.fact_ids)
            except Exception as exc:  # 有 unresolved/sensitive/conflict 时不激活，保持候选
                logger.info("Entity relation activation deferred for agent_run_id=%s: %s", state.agent_run_id, exc)
        entity_count = len(resolved.entities)
        relation_count = len(resolved.relation_ids)
        claim_count = len(resolved.claim_ids)
    finally:
        store.close()

    if not entity_count and not relation_count and not claim_count:
        return skip("跳过实体关系抽取", "实体关系已在图中，无需重复写入。", "no_new_material")

    action = record_agent_action(
        context,
        AgentActionCreate(
            action_type="memory.entity_relation",
            title="提取实体关系",
            summary=(
                f"从对话提取 {entity_count} 个实体、{claim_count} 条属性、"
                f"{relation_count} 条关系" + (f"（已激活 {activated_count} 条）" if activated_count else "")
            ),
            source_agent_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
            source_message_id=state.message_id,
            risk_tier="low",
            decision="notify",
            status="completed",
            metadata={
                "entity_count": entity_count,
                "claim_count": claim_count,
                "relation_count": relation_count,
                "activated_count": activated_count,
                "safe_summary": True,
            },
            reversible=False,
        ),
    )
    return [agent_action_event(state.agent_run_id, action)]


def _user_prompt(source_text: str) -> str:
    return (
        "从下面的用户消息中提取实体、属性和实体间关系，只返回 JSON。\n\n"
        f"用户消息：\n{source_text[:4000]}"
    )


ENTITY_RELATION_SYSTEM_PROMPT = (
    "你是记忆图谱实体关系提取模型。只返回一个 JSON 对象，键为："
    "schema_version, entities, claims, relations, sensitive, conflicts, uncertainties。"
    "schema_version 固定为 \"llmwiki.entity-extraction.v1\"。"
    "不要输出 JSON 之外的任何文字。\n\n"
    "entities 是数组，每项：entity_ref（本批内唯一短 id，如 e1）、entity_type（"
    "self/person/project/preference/boundary/goal/event/concept/source/wiki_page/decision 之一）、"
    "name（实体名）、aliases（别名数组，可为空）、confidence（0-1）、risk_tier（low/medium/high）、"
    "evidence（{start,end} 为支撑该实体的原文起止字符索引）。\n\n"
    "claims 是数组，每项：claim_ref（唯一 id，如 c1）、subject_entity_ref（指向 entities 里的 entity_ref）、"
    "predicate（谓语，短文本）、value（值/宾语）、fact_type（事实类别，短文本）、confidence、evidence。\n\n"
    "relations 是数组，每项：subject（{kind,ref}，kind 为 entity 或 claim）、relation（"
    "prefers/avoids/works_on/knows/related_to/occurred_in/supports/contradicts 之一）、"
    "object（{kind,ref}）、confidence、evidence。"
    "实体间关系（prefers/avoids/works_on/knows/related_to/occurred_in）的 subject 和 object 都必须是 entity；"
    "supports/contradicts 的端点可以是 entity 或 claim。\n\n"
    "sensitive/conflicts/uncertainties 是字符串数组，通常为空。"
    "只提取用户消息里明确提到的信息；不要臆测。没有可提取内容时返回空数组。"
    "不要输出密钥、路径、原始日志等敏感内容。"
)
