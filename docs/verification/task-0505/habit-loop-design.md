# TASK-0505 Habit Loop Mechanism

Date: 2026-06-21
Agent: Codex backend-worker + frontend
Status: Completed
Verification Level: L3 automated trigger and settings coverage

## Goal

Make the desktop pet able to open low-friction daily check-ins without becoming
noisy. The mechanism must be tied to real local state and must let the user
adjust frequency from settings.

## Trigger Rules

The implemented trigger path is `POST /api/habit-loop/trigger`, called by the
desktop pet window through `useProactiveHabitLoop`.

Frequency controls:

| Frequency | Daily cap | Cooldown | Idle guard |
| --- | ---: | ---: | ---: |
| `off` | 0 | disabled | disabled |
| `low` | 1/day | 8 hours | 3 hours after last user chat |
| `normal` | 2/day | 4 hours | 90 minutes after last user chat |
| `high` | 3/day | 2 hours | 45 minutes after last user chat |

Additional guardrails:

- Fixed quiet hours: 22:00-08:00 in the client's timezone.
- No trigger while the desktop pet is already streaming, showing an input dock,
  showing a bubble, showing shortcut actions, or speaking TTS.
- No trigger unless a useful local candidate exists.
- Every shown trigger is recorded in `agent_actions` as
  `habit.proactive_trigger` with low-risk `notify` decision.

## Candidate Priority

The service selects the first useful source in this order:

1. Unfinished or due tasks.
2. Recent daily chat diary entries.
3. Active or candidate long-term memory facts.
4. Recent completed Wiki actions.

This avoids purely random or time-only prompts. If none of these sources exist,
the trigger response is `should_trigger=false` with `reason=no_value_candidate`.

## User Setting

The setting is stored as `proactive_trigger_frequency` in the automation
settings response and persisted in `app_state`. The Settings page exposes a
segmented control with `关闭`, `低频`, `中频`, and `高频`.

## Completion Boundary

This completes TASK-0505 for the stated DoD:

- Proactive trigger function exists and enforces frequency control.
- The user can adjust proactive trigger frequency in Settings.

This is not a seven-day retention study. TASK-0506 remains the place for
multi-user usage data, retention rate, and qualitative feedback.
