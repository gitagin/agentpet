from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PromptRecentTurn:
    role: Literal["user", "assistant"]
    content: str
    created_at: str | None = None
