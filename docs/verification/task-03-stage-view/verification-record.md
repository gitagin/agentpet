# Task 03 Stage View Verification Record

Status: Completed with automated desktop verification.

Date: 2026-06-20

Task source: `task.md` task three, "改造桌面主舞台为陪伴入口".

## Scope

- The first screen should read as a companion entry, not a command center.
- The stage view should use `apps/desktop/src/productCopy.ts`.
- Primary actions should be limited to chat, memory, and settings.
- Task and knowledge-support entries should remain reachable, but demoted into a
  collapsed "更多能力" section.
- The first screen should not expose "高级工具", "Wiki", "Markdown", "Agent",
  "功能指挥中心", or "桌面记忆助手".
- Existing Live2D, bubble, connection status, chat send, and route behavior must
  continue to work.

## Current Implementation

- `apps/desktop/src/views/StageView.tsx` imports `productCopy`.
- The visible name is `productCopy.displayName`.
- The heading is "今天想从哪里继续？".
- Primary stage actions are:
  - "陪我聊聊" -> chat
  - "看看记忆" -> memory
  - "设置边界" -> settings
- Support actions are under a collapsed `details` section named "更多能力":
  - "提醒和待办" -> agent
  - "整理资料" -> world

No functional route was removed.

## Verification

```powershell
npm run test -- StageView.test.tsx
```

Result: passed, 1 test file and 12 tests.

```powershell
rg -n "高级工具|Wiki|Markdown|Agent|功能指挥中心|桌面记忆助手|任务|知识整理" apps\desktop\src\views\StageView.tsx
```

Result: no matches.

```powershell
npm run typecheck
```

Result: passed.

## Result

Task three is complete at the automated desktop verification level.
