# 中文用户测试说明

日期：2026-04-30  
执行者：Codex

本文用于 Windows 本地 v0.1 试运行。当前验收重点是本地后端 sidecar、Electron 控制台和核心业务闭环，不把桌宠视觉细节作为阻断项。

## 基本原则

- 页面、按钮、提示、错误信息面向中国用户，必须显示正常中文。
- 知识库内部路径不强制中文。为了兼容测试、脚本和历史数据，默认记忆提案路径统一使用英文：`Inbox/Pending Memories.md`。
- `.\.tmp` 只是临时测试产物目录，不是用户必须使用的知识库路径。
- 如果要测试真实 Obsidian Vault，先使用副本或备份目录，不要直接绑定唯一的生产笔记目录。

## 推荐测试路径

| 测试目标 | 推荐路径 | 说明 |
| --- | --- | --- |
| 一键后端 smoke | `.\.tmp\runbook-smoke-<timestamp>` | 由 `.\scripts\runbook-smoke.ps1` 自动创建。 |
| 手动临时知识库 | `.\.tmp\PetMemoryVault` | 适合试运行初始化、索引、记忆写入和搜索。 |
| 用户目录试用 | 任意可读写目录或 Obsidian Vault 副本 | 需要确认权限、备份和文件占用情况。 |

初始化知识库后，后端会创建：

```text
Inbox/Pending Memories.md
Memories/
```

这是正常行为。页面仍显示中文，但默认文件夹和文件名可以是英文。

## 基础验证流程

1. 检查是否有残留试运行进程：

```powershell
.\scripts\check-trial-processes.ps1
```

2. 执行 Windows 预检：

```powershell
.\scripts\preflight-windows.ps1
```

3. 执行一键后端 smoke：

```powershell
.\scripts\runbook-smoke.ps1 -Port 8766
```

4. 构建并启动桌面端：

```powershell
cd .\apps\desktop
npm run build
npm run electron:dev
```

如果 Codex 沙箱内 `npm run build` 报 Vite/esbuild `spawn EPERM`，请在普通 Windows PowerShell 中重新执行。

## 控制台核心功能测试

打开控制台后，按以下顺序测试：

1. 点击“健康检查”，确认后端可用，或显示明确中文错误。
2. 在“知识库路径”填写临时目录，例如 `.\.tmp\PetMemoryVault`。
3. 点击“初始化”，再点击“索引”。
4. 在临时目录中准备一个 Markdown 文件，例如 `test.md`，内容包含 `memorytest123` 和中文句子。
5. 在“记忆搜索”中搜索 `memorytest123`，确认能看到结果。
6. 再搜索中文短语，例如 `桌面记忆助手`，确认中文子串也能返回结果。
7. 在“记忆提案”中保持目标路径为 `Inbox/Pending Memories.md`，输入一条测试记忆，点击“创建提案”。
8. 点击“加载待确认”，再点击“确认”，确认内容写入 `Inbox/Pending Memories.md`。
9. 再次点击“索引”，搜索刚写入的关键词。
10. 创建任务、加载任务、完成或取消任务。
11. 测试 Chat SSE，例如输入“搜索记忆 memorytest123”或“记住 memorytest456 是一条测试记忆”。
12. 点击“导出诊断信息”，确认能看到数据库、知识库、索引和任务摘要。

## 记忆搜索注意事项

v0.1 的搜索会先走 SQLite FTS；当 FTS 对中文短语没有结果时，会回退到普通子串搜索。因此推荐测试：

```text
memorytest123
桌面记忆助手
```

如果仍然没有结果，优先检查：

- 当前知识库路径是否正确。
- 是否已经初始化并索引。
- Markdown 文件是否在当前知识库目录内。
- 记忆提案确认后是否重新索引，或确认接口是否返回索引任务。

## 后置 UI 观察项

模型配置请在控制台“设置”里填写“模型提供方、服务地址、模型名称、API 密钥”。打包应用不应要求客户手动设置环境变量。

以下问题暂不阻断 v0.1 核心闭环，只记录为后续桌宠体验改进：

- Live2D 动作不够自然。
- 鼠标穿透和 hitbox 不够精细。
- 桌宠拖动手感不完美。
- 气泡和模型贴合需要继续调整。
- 语音、口型、多角色、边缘吸附、自动更新尚未实现。
