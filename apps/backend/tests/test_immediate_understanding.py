from app.agents.immediate_understanding import (
    extract_immediate_understanding,
    immediate_understanding_context_block,
)


def test_extracts_current_turn_style_task_topic_and_constraints_without_raw_text() -> None:
    understanding = extract_immediate_understanding(
        "For this turn only, be blunt and review this backend migration. Do not save this."
    )

    assert understanding.interaction_style == "direct"
    assert understanding.applies_this_turn_only is True
    assert understanding.current_task is not None
    assert "review this backend migration" in understanding.current_task
    assert understanding.current_topic == "code"
    assert understanding.temporary_constraints == (
        "applies only to the current turn",
        "do not save this request as memory",
    )
    assert understanding.trace["raw_text_stored"] is False
    assert "For this turn only" not in str(understanding.trace)


def test_context_block_is_prompt_ready_and_marks_state_only() -> None:
    understanding = extract_immediate_understanding("Be concise and explain the failing test.")

    block = immediate_understanding_context_block(understanding)

    assert "Current-turn understanding" in block
    assert "state-only" in block
    assert "not durable memory" in block
    assert "interaction_style: concise" in block
    assert "current_task:" in block
    assert "source_hash:" in block


def test_this_turn_only_style_is_not_carried_into_later_understanding() -> None:
    first = extract_immediate_understanding("Only this time, be blunt with the critique.")
    second = extract_immediate_understanding("Now let's talk normally.", existing=first)

    assert first.interaction_style == "direct"
    assert first.applies_this_turn_only is True
    assert second.interaction_style is None
    assert second.applies_this_turn_only is False


def test_non_temporary_style_can_carry_inside_supplied_session_state() -> None:
    first = extract_immediate_understanding("Be concise while we debug this test.")
    second = extract_immediate_understanding("Next failure is in the API.", existing=first)

    assert first.interaction_style == "concise"
    assert second.interaction_style == "concise"
    assert second.current_task is not None
    assert "Next failure is in the API." in second.current_task

