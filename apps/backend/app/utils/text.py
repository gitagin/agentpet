"""Small text predicates shared across services.

Kept here so a rule that several subsystems depend on has exactly one
definition.  ``is_greeting_only`` started inside the continuity service (a
greeting must not become an open thread) and is now also used by prompt
assembly (a greeting must not drag a previous topic back into the answer).
"""

from __future__ import annotations

import re

# 纯问候:整句只有招呼词与标点。中文与英文的常见开场都在这里。
GREETING_ONLY_RE = re.compile(
    r"^(?:hi|hello|hey|yo|good\s+(?:morning|evening|night)|"
    r"嗨+|哈喽|哈啰|你好|您好|在吗|在么|早上好|中午好|下午好|晚上好|晚安|早|睡了|醒着吗)"
    r"[\s!！。.?？~～、,，]*$",
    re.IGNORECASE,
)


def compact_whitespace(text: str) -> str:
    return " ".join(str(text or "").split())


def is_greeting_only(text: str) -> bool:
    """Is this message nothing but a greeting?

    Such a message carries no topic of its own, so anything that follows it
    should come from the user, not from a previous subject the assistant
    happens to remember.
    """
    return bool(GREETING_ONLY_RE.match(compact_whitespace(text)))
