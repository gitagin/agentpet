# 文档索引

这里保留当前运行、验收和发布边界文档；历史计划、一次性清单和旧诊断材料放在 `docs/archive/`。

## 当前文档

| 文件 | 用途 |
| --- | --- |
| `v0.2-validation.md` | 当前 v0.2 验证边界、历史发布记录，以及 2026-06-11 产品叙事改造后的最新人工体验复核记录。 |
| `v0.1-validation.md` | 旧版本地核心闭环验收记录，仅用于追溯 v0.1 基线。 |
| `mvp-acceptance-coverage.md` | `Covered` / `Partial` / `Gap` 验收矩阵，供 `scripts/check-mvp-acceptance-gap.ps1` 和后端测试使用。 |
| `runbook.md` | Windows 本地试运行命令和 smoke 流程。 |
| `electron-migration-checklist.md` | Electron 权限边界基线，由 `apps/desktop/scripts/validate-electron-migration.mjs` 校验。 |

## 当前产品叙事

项目当前对外叙事是“本地长期记忆陪伴体”：桌宠作为入口，陪用户聊天，长期记住重要内容，并让记忆留在本机且可查看、可修改、可撤回。

知识整理、提醒、资料归档、复盘报告、模型配置和调试诊断都是内置支撑能力；它们可以帮助陪伴闭环，但不应抢占首屏和主叙事。

## 最新人工验收边界

2026-06-11 的产品叙事改造复核中，首屏、聊天页和记忆页的可见文案已经按陪伴闭环检查；但真实桌宠入口的“双击 Pet 窗口打开主舞台”没有完成可视通过，仍应按 `Partial` 记录，不能写成已完成验收。

## 归档文档

`docs/archive/` 包含旧计划、诊断、迁移说明和 v0.2 之前的试运行材料。这些文件只作为历史背景，不作为当前产品体验或发布状态的最终依据。

归档文件包括：

- `agent-work-plan.md`
- `integration-notes.md`
- `qa-checklist.md`
- `runbook-smoke-progress.md`
- `security-review.md`
- `user-testing-zh.md`
- `vite-esbuild-eperm-diagnostics.md`
- `windows-electron-trial-packaging.md`

## 维护规则

- 没有实现或验证证据时，不得把状态写成 `Covered`。
- `Covered` / `Partial` / `Gap` 的英文拼写必须保持精确。
- `mvp-acceptance-coverage.md`、`runbook.md` 和 `electron-migration-checklist.md` 仍保留在顶层；除非同步更新引用它们的脚本和测试，不要移动。
- 新的发布门禁或人工体验复核记录优先追加到 `v0.2-validation.md`，直到明确引入后续版本文档。
