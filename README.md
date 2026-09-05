# Agent Pet

Agent Pet 是面向 Windows 单用户的本地个人 LLM Wiki 与记忆图谱桌面应用。它把聊天、来源、长期记忆、Wiki 页面和任务保存在本机，并允许用户检查、纠正或忘记已经保存的信息。

## 功能

- Electron 桌面宠物与工作台
- FastAPI 本地 sidecar
- SQLite 权威状态与全文检索
- Markdown Vault 与 Wiki
- 可选的 Qdrant 和 Kuzu 检索层
- 带来源的记忆召回、纠正和忘记
- 本地任务、提醒与桌面通知
- OpenAI-compatible 模型配置

本项目是本地单用户应用，不提供团队空间、云同步、企业租户或跨设备协作。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.10+
- Node.js 20+
- npm 10+

## 从源码运行

安装后端：

```powershell
cd apps\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

启动桌面端：

```powershell
cd ..\desktop
npm ci
npm run dev
```

模型地址、模型名称和 API Key 在应用设置中配置。API Key 只保存在本机凭据存储中，不应写入仓库文件。

## 构建 Windows 发布包

安装后端打包依赖：

```powershell
cd apps\backend
.\.venv\Scripts\python.exe -m pip install -e ".[packaging]"
```

构建 sidecar、前端和 Electron ZIP：

```powershell
cd ..\desktop
npm ci
npm run package:win
```

发布产物生成在 `apps\desktop\release`。

## 项目结构

```text
apps/
  backend/   FastAPI sidecar、数据库迁移和打包配置
  desktop/   Electron、React 界面和桌面资源
scripts/
  build-sidecar.ps1
PRODUCT.md   产品边界与核心工作流
```

## 本地数据

运行时数据库、Vault、日志、凭据、缓存和构建产物均由 `.gitignore` 排除。公开仓库不应包含真实用户数据、模型密钥或本机运行记录。

产品定位和行为边界见 [PRODUCT.md](PRODUCT.md)。
