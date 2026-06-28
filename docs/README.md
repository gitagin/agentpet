# 文档索引

这里是 `docs/` 的入口。当前运行时行为以代码、migration 和测试为准；文档只负责导航、解释和记录证据，不能代替验证。

## 当前入口文档

除非当前代码或测试证明相反，后续工作优先从这些文件进入。

| 文件 | 用途 | 边界 |
| --- | --- | --- |
| `current-specification.md` | 当前产品与工程规格入口。 | 是活跃规格，但优先级仍低于代码和测试。 |
| `mvp-acceptance-coverage.md` | `Covered` / `Partial` / `Gap` 验收矩阵。 | 没有匹配证据时不得提升状态。 |
| `verification-policy.md` | L1-L4 验证层级和证据规则。 | 约束状态措辞和完成声明。 |
| `runbook.md` | Windows 本地试运行、smoke 命令和环境坑。 | 标题仍带 v0.1；按活跃本地试运行手册使用，不代表当前版本号。 |
| `electron-migration-checklist.md` | Electron 权限边界、迁移和打包检查。 | 活跃桌面安全参考。 |
| `decisions/naming.md` | 命名决策记录。 | 活跃决策文档。 |
| `decisions/scope-freeze.md` | 陪伴产品与 Office/Excel 自动化边界决策。 | 活跃决策文档；没有后续明确决策前，不要实现泛桌面自动化。 |

## 验证与证据

只有当记录里的命令输出或人工证据仍匹配当前代码时，才可以用它支撑状态声明。

| 位置 | 用途 | 边界 |
| --- | --- | --- |
| `docs/verification/` | 各任务的验证记录。 | 记录是历史快照；行为可能变化时需要重跑命令。 |
| `v0.1-validation.md` | 旧版本地验证命令集和手动试运行笔记。 | 可追溯命令和试运行形状，不是当前版本标签。 |
| `v0.2-validation.md` | 历史 v0.2 验证记录。 | 明确是历史记录；不能覆盖当前 alpha 边界、`progress.md` 或 MVP 矩阵。 |
| `../progress.md` | 仓库根目录的 coordinator 进度账本。 | 非 coordinator 只读；不得把 `Partial` / `Gap` 写高。 |

## 历史或窄用途材料

这些文件仍可能有用，但单独引用时不是当前产品真相。

| 文件或目录 | 当前解释 |
| --- | --- |
| `docs/archive/` | 历史计划、旧诊断、迁移笔记和过期验证材料。除非当前代码和测试确认同一行为，否则只当背景。 |
| `dual-track-memory-baseline-audit.md` | 双轨记忆工作的历史基线审计。里面的 "Required Additions" 可能已经被后续实现和验证记录取代。 |

## 当前产品真相

Agent Pet 不是因为有很多隐藏子系统才强。它只有在普通用户能快速感到下面这些事时才成立：

- 桌宠真实存在；
- 桌宠理解当前对话；
- 记忆和整理动作可见、可控；
- 高风险动作会请求确认；
- 可撤销动作能被查看和撤回。

记忆、Wiki、任务、诊断、模型设置和审计日志都是支撑能力。它们不应该霸占首屏，也不应该逼用户先理解后端架构再开始聊天。

## 清理规则

- 没有用户明确确认，不删除或移动 Markdown 文档。
- 没有当前代码和验证输出支撑，不改写 `Covered`、`Partial`、`Gap`、`Completed` 或其他验证声明。
- 只有活跃引用文档才保留在顶层。
- 一次性日志、被取代计划和旧试运行记录只能在确认后移动到 `docs/archive/`。
- 文档与当前代码冲突时，代码优先；要么更新文档，要么标成历史材料。
- 优先维护短、可导航的文档，不要继续堆大而全的说明。

## 需要确认的清理队列

下面只是候选项。没有明确批准前，不移动、不删除。

| 候选项 | 建议动作 | 为什么需要确认 |
| --- | --- | --- |
| `docs/dual-track-memory-baseline-audit.md` | 如果当前双轨记忆实现和验证记录已完全取代它，则归档。 | 它是 Markdown 历史，也可能解释旧设计意图。 |
| `docs/v0.1-validation.md` | 检查当前 runbook 依赖后，保留为旧验证参考或归档。 | 它混有仍可用命令和旧版本叙事。 |
| `docs/v0.2-validation.md` | 如果后续文档不再引用它，则保留为历史记录或归档。 | 它包含已被取代的发布语言，容易误导后续 agent。 |
| `docs/runbook.md` | 如果 v0.1 标题持续造成误解，确认后再重命名或改标题。 | 重命名 Markdown 会改变文档状态和引用关系。 |
| `docs/archive/*` | 除非点名证明重复或废弃，否则保持原样。 | 归档删除没有 Git 恢复就不可逆。 |

## 维护检查表

- 编辑文档前，先核对正在描述的行为是否仍被当前代码或测试支持。
- 文档-only 状态变更后，运行 `.\scripts\check-mvp-acceptance-gap.ps1`。
- Electron 权限边界文档变更后，还要运行 `Push-Location apps\desktop; node scripts\validate-electron-migration.mjs; Pop-Location`。
- 最终回复必须列出实际运行过的命令和结果。
