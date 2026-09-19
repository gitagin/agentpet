# Agent Pet

Agent Pet 是面向 Windows 单用户的本地个人 LLM Wiki 与记忆图谱桌面应用。它把聊天、来源、长期记忆、Wiki 页面和任务保存在本机，并允许用户检查、纠正或忘记已经保存的信息。

## 功能

- Electron 桌面宠物与工作台
- FastAPI 本地 sidecar
- SQLite 权威状态与中文 bigram 全文检索
- Markdown Vault 与 Wiki
- LLM 来源编译、旧页融合、带引用的多来源综合与语义体检（[流程与边界](docs/wiki-compilation.md)）
- 本地语义检索：内置 bge-small-zh-v1.5 向量模型 + bge-reranker-base 重排（数据不出本机）
- 混合检索：FTS + 向量 RRF 融合，向量索引默认走嵌入式本地 Qdrant，另可选 Kuzu 图投影层
- 带来源的记忆召回、纠正和忘记
- 本地任务、提醒与桌面通知
- OpenAI-compatible 模型配置（配置外部 embedding 接口后自动切换为外部语义检索）

本项目是本地单用户应用，不提供团队空间、云同步、企业租户或跨设备协作。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.10+
- Node.js 20+
- npm 10+

## 从源码运行

安装后端（Windows x64 / Python 3.10 锁定基线，含测试、本地向量和打包依赖）：

```powershell
cd apps\backend
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-win-py310.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e ".[packaging,vector,local-vector]"
.\.venv\Scripts\python.exe -m pip check
```

下载内置向量与重排模型（仅首次，模型文件不入仓库）：

```powershell
cd ..\..
.\scripts\download-embedding-model.ps1
.\scripts\download-reranker-model.ps1
```

启动桌面端：

```powershell
cd ..\desktop
npm ci
npm run dev
```

模型地址、模型名称和 API Key 在应用设置中配置。API Key 保存在本机凭据文件里（Windows 上用 DPAPI 按当前用户加密，非 Windows 需显式开启不安全文件凭据才写明文），不应写入仓库文件。

## 构建 Windows 发布包

使用同一锁定环境安装后端打包依赖，不使用全局 Python：

```powershell
cd apps\backend
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-win-py310.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e ".[packaging,vector,local-vector]"
```

构建前先下载内置模型（`scripts/download-embedding-model.ps1` 与 `scripts/download-reranker-model.ps1`），构建脚本会把模型随 sidecar 一起打进发布包。

构建 sidecar、前端和 Electron ZIP：

```powershell
cd ..\desktop
npm ci
npm run package:win
```

发布产物生成在 `apps\desktop\release`。

开发启动和 sidecar 构建默认使用 `apps/backend/.venv`。显式设置
`AGENT_PET_PYTHON` 可覆盖解释器，但需要自行验证版本与锁文件一致。
锁文件固定依赖版本，不承诺跨平台或二进制构建逐字节一致。
后端回归从仓库根目录运行
`apps\backend\.venv\Scripts\python.exe -m pytest apps/backend/tests -q`。
LLM Wiki 重构的完成边界与未通过门槛见[实施状态](docs/wiki-reconstruction-status.md)。

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
