from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.agents.runtime_helpers import _chat_system_prompt, _current_local_time_text


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_current_local_time_text_formats_chinese_weekday() -> None:
    text = _current_local_time_text(datetime(2026, 9, 6, 8, 5, tzinfo=SHANGHAI))

    assert text == "2026年9月6日（星期日）08:05"


def test_current_local_time_text_interprets_naive_datetime_in_machine_timezone() -> None:
    text = _current_local_time_text(datetime(2026, 9, 6, 8, 5, 0))

    assert text == "2026年9月6日（星期日）08:05"


def test_chat_system_prompt_anchors_time_and_points_to_tool() -> None:
    prompt = _chat_system_prompt()

    assert "当前本地时间" in prompt
    assert "每次对话都会刷新" in prompt
    assert "get_current_time" in prompt
    assert "绝不根据训练数据或知识截止日期编造" in prompt
