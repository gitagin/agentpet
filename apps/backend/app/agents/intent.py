from __future__ import annotations

import re

from app.models.enums import AgentIntent

from .memory_router import explicit_memory_read_scope
from .state import AgentRoute


_TASK_PATTERNS = (
    # 只认明确祈使的"创建提醒/任务"，普通名词（task/todo/due/提醒/待办/任务）
    # 出现在陈述或查询里不再触发——否则"我忘了提醒你""这个任务挺重要"
    # "今天的待办完成了吗"会被静默创建垃圾任务（task.create 在自动白名单）。
    r"\b(remind me|remind me to|set a reminder|create a task|add a todo)\b",
    r"(?:\u63d0\u9192\u6211|\u5e2e\u6211\u63d0\u9192|\u8bf7\u63d0\u9192|\u9ebb\u70e6\u63d0\u9192|\u522b\u5fd8\u4e86\u63d0\u9192|\u8bb0\u5f97\u63d0\u9192)",
    r"(?:\u5e2e\u6211|\u8bf7|\u9ebb\u70e6)(?:\u5b89\u6392|\u6392)",
    r"(?:\u5b89\u6392|\u6392)(?:\u4e00\u4e0b|\u4e2a|\u4e0b|\u4e00\u6b21)",
    r"(?:\d{1,2}|[零〇一二两三四五六七八九十]{1,4})\s*(?:秒钟|秒|分钟|小时)\s*后.*(?:提醒我|提醒)",
    # 明确祈使 + 时间 + 要做的事：帮我记一下明天要做的事 / 记下来：下周待办。
    # 注意不能只靠"时间 + 要做的事"——"明天要做的事是什么"是查询、"明天要做的事就是陪家人"是陈述，
    # 误判为任务会静默创建垃圾任务（task.create 属于自动白名单）。
    r"(?:帮我|请|麻烦|别忘了)?记(?:一下|下来|住)?[:：]?\s*(?:明天|后天|今晚|下周|周末|这周|早上|晚上|下午).{0,10}(?:要做|要办|需要做|待办|事项)",
)
_PROPOSE_MEMORY_PATTERNS = (
    r"\b(remember this|remember that|remember:|please remember|save this memory)\b",
    # 只认明确祈使或带冒号的"记住:"，裸"记住"（如"我会记住的"）不再触发，
    # 否则会把口语陈述静默建成垃圾记忆提案（memory.proposal 在自动白名单）。
    r"(?:\u5e2e\u6211\u8bb0\u4f4f|\u8bf7\u5e2e\u6211\u8bb0\u4f4f|\u5e2e\u6211\u8bb0\u5f97|\u4fdd\u5b58\u8bb0\u5fc6|\u52a0\u5165\u8bb0\u5fc6|\u957f\u671f\u504f\u597d|\u957f\u671f\u8bb0\u5fc6|\u4fdd\u5b58\u4e0b\u6765|\u8bb0\u4f4f[:：]|\u8bb0\u5f97[:：])",
)
_SEARCH_PATTERNS = (
    r"\b(search memory|search memories|find in memory|lookup memory|search notes|search docs|what do you remember|recall)\b",
    r"(?:\u641c\u7d22\u8bb0\u5fc6|\u67e5\u627e\u8bb0\u5fc6|\u68c0\u7d22\u8bb0\u5fc6|\u67e5\u4e00\u4e0b\u8bb0\u5fc6|\u67e5\u4e00\u4e0b\u77e5\u8bc6\u5e93|\u4f60\u8bb0\u5f97\u4ec0\u4e48|\u4f60\u8bb0\u5f97\u6211|\u56de\u5fc6\u4e00\u4e0b|\u77e5\u8bc6\u5e93\u91cc|\u7b14\u8bb0\u91cc|\u6587\u6863\u91cc|\u4e4b\u524d\u8bb0\u5f55)",
)
# 口语化"近期聊了什么"类查询：不依赖显式日期或"记忆/记得"标记词，
# 例如"我刚刚说了什么""刚才聊了什么""我之前说过什么"。
# 这类表达此前漏检后降级为普通闲聊，模型没有检索能力会回"我不知道"。
_RECENT_CHAT_RECALL_PATTERNS = (
    # 时间副词 + 对话动词 + 疑问词：我刚刚说了什么 / 刚才聊了什么 / 之前说过什么
    r"(?:刚刚|刚才|刚|之前|上次|昨晚|昨天|今天|前天).{0,8}(?:说|聊|讲|问|提|讨论).{0,4}(?:什么|啥|哪些|怎么)",
    # 对话动词 + 疑问词 + 时间副词（倒装，较少见）：说了什么刚才
    r"(?:说|聊|讲|问|提|讨论)(?:了|过)?(?:什么|啥|哪些).{0,6}(?:刚刚|刚才|刚|之前|上次|昨晚)",
    # 我们聊到哪了：我们/咱们 + 说到/聊到 + 哪里/哪儿/什么/哪
    r"(?:我们|咱们)(?:刚刚|刚才|刚)?(?:说到|聊到)(?:哪里|哪儿|什么|哪)",
    # 无主语变体：之前/上次/刚刚/刚才 + 说到/聊到 + 哪/哪里
    r"(?:之前|上次|刚刚|刚才).{0,4}(?:说到|聊到)(?:哪|哪里|哪儿|什么)",
)
_WIKI_MANAGEMENT_PATTERNS = (
    r"\b(add to wiki|update wiki|create wiki page|organize into wiki|save to knowledge base|archive to wiki)\b",
    r"(?:\u5199\u5165\s*wiki|\u66f4\u65b0\s*wiki|\u521b\u5efa\s*wiki\s*\u9875\u9762|\u6574\u7406\u5230\s*wiki|\u4fdd\u5b58\u5230\u77e5\u8bc6\u5e93|\u5f52\u6863\u5230\u77e5\u8bc6\u5e93|\u6574\u7406\u5230\u77e5\u8bc6\u5e93|\u5199\u5165\u77e5\u8bc6\u5e93)",
)
_HIGH_RISK_MUTATION_PATTERNS = (
    # 目标词含任务/待办/提醒，避免"帮我删除任务"落入任务自动创建（做相反的事）。
    r"(?:删除|移走|移动|批量(?:重写|改写|修改)|覆盖).{0,16}(?:记忆|笔记|文件|文档|资料|知识库|数据库|markdown|vault|sqlite|任务|待办|提醒)",
    r"\b(?:delete|move|bulk\s+(?:rewrite|edit)|overwrite).{0,32}\b(?:memory|memories|notes?|files?|documents?|vault|markdown|database|sqlite|tasks?|todos?|reminders?)\b",
)
_MEMORY_RECALL_MARKERS = (
    "\u4f60\u8bb0\u5f97",
    "\u8bb0\u5f97\u6211",
    "\u4e4b\u524d\u8bb0\u5f55",
    "\u56de\u5fc6\u4e00\u4e0b",
    "\u8bb0\u5fc6\u4e2d",
    "\u8bb0\u5fc6\u91cc",
)
_DAILY_CHAT_MARKERS = (
    "\u6211\u8bf4\u4e86\u4ec0\u4e48",
    "\u6211\u4eec\u8bf4\u4e86\u4ec0\u4e48",
    "\u54b1\u4eec\u8bf4\u4e86\u4ec0\u4e48",
    "\u804a\u4e86\u4ec0\u4e48",
    "\u95ee\u4e86\u4ec0\u4e48",
    "\u63d0\u4e86\u4ec0\u4e48",
    "\u8bf4\u8fc7\u4ec0\u4e48",
)


def route_intent(message: str) -> AgentRoute:
    normalized = " ".join(message.strip().lower().split())
    if not normalized:
        return AgentRoute(
            intent=AgentIntent.CHAT,
            confidence=0.0,
            reason="empty message defaults to chat",
        )

    if is_high_risk_mutation_request(message):
        return AgentRoute(
            intent=AgentIntent.MANAGE_WIKI,
            confidence=0.99,
            reason="high-risk local mutation requires confirmation",
        )

    if _matches_any(_WIKI_MANAGEMENT_PATTERNS, normalized):
        return AgentRoute(
            intent=AgentIntent.MANAGE_WIKI,
            confidence=0.94,
            reason="explicit wiki management command",
        )

    if _matches_any(_TASK_PATTERNS, normalized) and not _is_task_query(message):
        return AgentRoute(
            intent=AgentIntent.CREATE_TASK,
            confidence=0.9,
            reason="explicit task or reminder command",
        )

    if _matches_any(_PROPOSE_MEMORY_PATTERNS, normalized):
        return AgentRoute(
            intent=AgentIntent.PROPOSE_MEMORY,
            confidence=0.95,
            reason="explicit memory proposal command",
        )

    if explicit_memory_read_scope(message) is not None:
        return AgentRoute(
            intent=AgentIntent.SEARCH_MEMORY,
            confidence=0.96,
            reason="explicit memory source read request",
        )

    if _is_daily_chat_recall_query(message) or _is_memory_recall_query(message) or _is_recent_chat_recall_query(message):
        return AgentRoute(
            intent=AgentIntent.SEARCH_MEMORY,
            confidence=0.82,
            reason="context recall question",
        )

    if _matches_any(_SEARCH_PATTERNS, normalized):
        return AgentRoute(
            intent=AgentIntent.SEARCH_MEMORY,
            confidence=0.9,
            reason="explicit memory or knowledge search command",
        )

    question_about_memory = re.search(r"\b(memory|memories|remember)\b", normalized)
    if question_about_memory and "?" in message:
        return AgentRoute(
            intent=AgentIntent.SEARCH_MEMORY,
            confidence=0.72,
            reason="memory-related question",
        )

    return AgentRoute(
        intent=AgentIntent.CHAT,
        confidence=0.55,
        reason="default desktop-pet chat path",
    )


def _matches_any(patterns: tuple[str, ...], message: str) -> bool:
    return any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns)


def is_high_risk_mutation_request(message: str) -> bool:
    normalized = " ".join(message.strip().lower().split())
    return bool(normalized) and _matches_any(_HIGH_RISK_MUTATION_PATTERNS, normalized)


def _is_memory_recall_query(message: str) -> bool:
    return any(marker in message for marker in _MEMORY_RECALL_MARKERS)


_TASK_QUERY_MARKERS = (
    "有哪些",
    "是什么",
    "有几个",
    "多少",
    "什么任务",
    "什么待办",
    "什么安排",
    "什么提醒",
    "待办有",
    "安排有",
    "任务有",
    "提醒有",
    "了吗",
    "怎么样",
    "什么时候",
    "has scheduled",
    "any tasks",
    "what tasks",
    "what reminders",
)


def _is_task_query(message: str) -> bool:
    """True when a task-related message is asking about tasks, not creating one.

    "下周的安排有哪些" / "我有哪些任务" are queries — misclassifying them as
    CREATE_TASK would silently create garbage tasks (task.create is on the
    auto-approval allowlist).
    """
    normalized = message.casefold()
    return any(marker in normalized for marker in _TASK_QUERY_MARKERS)


def _is_recent_chat_recall_query(message: str) -> bool:
    normalized = " ".join(message.strip().lower().split())
    return bool(normalized) and _matches_any(_RECENT_CHAT_RECALL_PATTERNS, normalized)


def _is_daily_chat_recall_query(message: str) -> bool:
    if not re.search(r"\d{1,2}\s*\u6708\s*\d{1,2}\s*(?:\u53f7|\u65e5)?", message):
        return False
    return any(marker in message for marker in _DAILY_CHAT_MARKERS)
