# 本地陪伴体

定位声明：本项目保留 `Agent Pet` / `agent-pet` 命名；它是以桌宠为入口的本地长期记忆陪伴体，不是 AI coding agent 监控或评测桌面工具。

[![CI](https://github.com/gitagin/agentpet/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/gitagin/agentpet/actions/workflows/ci.yml)

本项目是一款本地优先的长期记忆陪伴体。它以桌宠作为日常入口，陪用户聊天，记住重要内容，并把记忆留在本机；用户可以查看、修改和撤回已经沉淀的记忆。

## 产品体验

- 长期陪伴：回答前会尽量接上本地聊天日记、长期记忆和已整理资料中的相关上下文。
- 本地记忆：值得留下的内容优先保存在本机状态和用户选择的本机文件夹中。
- 记忆可控：记住了什么、为什么记住、来源和状态都应当可见，低风险记录可撤回，高风险内容必须确认。
- 支撑能力：提醒、知识整理、资料归档、复盘报告和调试诊断是内置支撑能力，不抢占首屏主叙事。

## 模块

- `apps/backend`：本地后端，负责接口、SQLite、检索、记忆、任务、知识整理和活动记录。
- `apps/desktop`：Electron + React 桌面端，负责桌宠、陪伴入口、聊天、记忆页和设置。
- `docs`：运行手册、验收边界和历史验证记录。

## 当前验证边界

最新一次人工体验复核中，前端页面结构已经能体现“本地长期记忆陪伴体”的叙事；但真实桌宠入口里“双击 Pet 窗口打开主舞台”仍未完成可视确认，不能记为已通过。

## 文档

- 当前文档入口见 [`docs/README.md`](docs/README.md)。
- 旧规格仍保留在 [`Development_Documentation.md`](Development_Documentation.md)，当它与当前代码或验收记录冲突时，以当前代码和最新验证结果为准。
- 协调进度记录见 [`progress.md`](progress.md)。
