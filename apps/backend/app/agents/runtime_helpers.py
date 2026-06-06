from __future__ import annotations

import logging
import re

from .events import AgentContinuitySignalEvent
from .services import ContinuityServiceProtocol, ContinuitySignalProtocol


logger = logging.getLogger(__name__)


def _chat_system_prompt() -> str:
    return (
        "你是住在用户桌面上的中文桌宠伙伴，不是文档查询助手。"
        "默认用自然、温和、简洁的中文陪用户聊天、解释、追问、给建议，可以有一点轻松的桌宠语气。"
        "短寒暄或待机回复要像桌面边上有人轻声接话：一到两句即可，可以说“我在呀”“先从哪件小事开始？”。"
        "避免客服式或工具式开场，不要说“有什么可以帮你”“我可以帮你”“作为 AI 助手”“很高兴为你服务”，也不要在每句末尾堆 emoji。"
        "知识库只是你的“记忆本”能力：只有用户明确要求查本地知识库、笔记、记忆、文档、之前记录，"
        "或问题显然依赖用户私有资料时，才使用或引用检索上下文。"
        "如果没有检索上下文，就按一般对话正常回答；不要先声明要搜索，也不要把普通问题变成检索任务。"
        "如果用户明确查记忆但没有找到资料，要坦诚说明没有翻到，不要编造用户记忆；可以继续追问背景，"
        "也可以说明自己能先按一般经验陪用户分析。"
        "用户明确要求保存长期信息时才创建记忆提案；明确要求待办、计划或提醒时才创建任务。"
        "不要声称已经写入记忆或创建任务，除非工具事件已经完成。"
    )


def _continuity_context_block(continuity: ContinuityServiceProtocol | None) -> str:
    if continuity is None:
        return ""
    try:
        return continuity.context_block()
    except Exception:
        logger.warning("Continuity context block failed; using empty context", exc_info=True)
        return ""


def _continuity_presence_context_block(continuity: ContinuityServiceProtocol | None) -> str:
    if continuity is None:
        return ""
    try:
        return continuity.presence_context_block()
    except Exception:
        logger.warning("Continuity presence context block failed; using empty context", exc_info=True)
        return ""


def _continuity_signal(continuity: ContinuityServiceProtocol | None) -> ContinuitySignalProtocol | None:
    if continuity is None:
        return None
    try:
        return continuity.presence_signal()
    except Exception:
        logger.warning("Continuity presence signal failed; skipping signal", exc_info=True)
        return None


def _continuity_signal_event(agent_run_id: str, signal: ContinuitySignalProtocol) -> AgentContinuitySignalEvent:
    return AgentContinuitySignalEvent(
        agent_run_id=agent_run_id,
        kind=signal.kind,
        title=signal.title,
        summary=signal.summary,
        intensity=signal.intensity,
        display_hint=signal.display_hint,
        source_state_keys=list(signal.source_state_keys),
    )


def _message_with_continuity_context(user_message: str, continuity_block: str) -> str:
    if not continuity_block.strip():
        return user_message
    return (
        f"{continuity_block.strip()}\n\n"
        f"Current user message:\n{user_message}"
    )


def _chunk_text(text: str, size: int = 80) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


def _strip_memory_command(message: str) -> str:
    prefixes = (
        "remember this:",
        "remember that:",
        "remember:",
        "please remember",
        "save this memory:",
        "记住：",
        "记住:",
        "记住",
        "记得：",
        "记得:",
        "记得",
        "保存记忆：",
        "保存记忆:",
        "加入记忆：",
        "加入记忆:",
    )
    stripped = message.strip()
    lowered = stripped.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return stripped[len(prefix) :].strip(" :：") or stripped
    return stripped


def _strip_search_command(message: str) -> str:
    prefixes = (
        "search memory for",
        "search memories for",
        "find in memory",
        "lookup memory",
        "recall",
        "搜索记忆：",
        "搜索记忆:",
        "搜索记忆",
        "查找记忆：",
        "查找记忆:",
        "查找记忆",
        "检索记忆：",
        "检索记忆:",
        "检索记忆",
        "回忆",
    )
    stripped = message.strip()
    lowered = stripped.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return stripped[len(prefix) :].strip(" :：") or stripped
    return stripped


def _task_title(message: str) -> str:
    title = message.strip()
    delayed_reminder = re.match(
        r"^(?:\d{1,2}|[零〇一二两三四五六七八九十]{1,4})\s*(?:秒钟|秒|分钟|小时)\s*后\s*(?:提醒我|提醒)\s*(?P<title>.+)$",
        title,
        flags=re.IGNORECASE,
    )
    if delayed_reminder is not None:
        title = delayed_reminder.group("title").strip(" :：")
        return title or message.strip()
    for prefix in (
        "remind me to",
        "reminder:",
        "todo:",
        "task:",
        "提醒我：",
        "提醒我:",
        "提醒我",
        "提醒：",
        "提醒:",
        "提醒",
        "待办：",
        "待办:",
        "任务：",
        "任务:",
    ):
        if title.lower().startswith(prefix):
            title = title[len(prefix) :].strip(" :：")
            break
    return title or message.strip()


def _wiki_title(message: str) -> str:
    content = _strip_wiki_command(message)
    first_line = next((line.strip(" #") for line in content.splitlines() if line.strip()), "")
    if ":" in first_line:
        first_line = first_line.split(":", 1)[0].strip()
    if "：" in first_line:
        first_line = first_line.split("：", 1)[0].strip()
    return first_line[:60] or "Knowledge Note"


def _strip_wiki_command(message: str) -> str:
    prefixes = (
        "add to wiki:",
        "update wiki:",
        "create wiki page:",
        "save to knowledge base:",
        "archive to wiki query archive:",
        "archive to wiki archive query:",
        "add to wiki synthesis:",
        "add to wiki synthesize:",
        "add to wiki lint report:",
        "add to wiki lint:",
        "archive to wiki:",
        "organize into wiki:",
        "写入wiki：",
        "写入wiki:",
        "更新wiki：",
        "更新wiki:",
        "整理到wiki：",
        "整理到wiki:",
        "保存到知识库：",
        "保存到知识库:",
        "归档到知识库：",
        "归档到知识库:",
        "创建wiki页面：",
        "创建wiki页面:",
    )
    stripped = message.strip()
    lowered = stripped.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix.lower()):
            return stripped[len(prefix) :].strip(" :：") or stripped
    return stripped
