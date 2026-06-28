# TASK-0504 Growth Feedback Mechanism

Date: 2026-06-21
Agent: Codex backend-worker + frontend
Status: Completed
Verification Level: L3 real chat trigger + automated UI/API checks

## Goal

Make the desktop pet's growth visible by tying growth dimensions to real local
memory and activity data, then showing the user a growth history page.

## Growth Dimensions

The implemented snapshot exposes four dimensions. All are derived from existing
local data, not random time passage.

| Key | User-facing label | Real trigger data | User-visible meaning |
| --- | --- | --- | --- |
| `memory_depth` | 记忆脉络 | `daily_chat_memory_entries`, active/candidate `memory_graph_facts` | More diary and long-term memory lets the pet continue topics across sessions. |
| `response_affinity` | 回应默契 | preference/boundary facts and diary memory objects | More style/preference memory makes replies closer to the user's habits. |
| `trust_boundary` | 安心边界 | reversible `agent_actions`, reverted/skipped actions, `memory_feedback_events` | The pet visibly learns from review, rollback, and skipped unsafe memory. |
| `knowledge_links` | 知识连接 | non-core `Wiki/*.md` pages and Wiki actions | Knowledge pages become visible connective tissue for future recall. |

## Implemented Surfaces

- Backend read-only API: `GET /api/growth/snapshot`.
- Backend service: `GrowthSnapshotService`, derived from existing SQLite tables
  and Vault Wiki page count.
- Desktop page: `GrowthWindowView`, available through `#growth`.
- Stage entry: "成长记录" under the collapsed "更多能力" group.
- Bottom navigation tab: "成长".
- Electron route/proxy allowlist: `growth` route and exact
  `/api/growth/snapshot` GET proxy route.

## Completion Boundary

This task is Completed for the stated DoD:

- At least one growth dimension can be triggered through real use. The
  `test_chat_stream_auto_archives_daily_memory_and_records_action` test now
  completes a real `/api/chat` exchange, waits for `chat.daily_archive`, and
  verifies `memory_depth` advances in `/api/growth/snapshot`.
- The growth record page correctly displays dimensions and history from the
  backend snapshot in `GrowthWindowView.test.tsx`.

This is not a 7-day retention validation. TASK-0506 remains the place for
multi-user longitudinal evidence.

