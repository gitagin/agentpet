# Agent Pet

Agent Pet 是一款 Windows 桌面程序，桌面端使用 Electron 和 React，后端以 FastAPI sidecar 方式运行。它用于聊天、管理本地来源、Wiki 和长期记忆，也包含任务与提醒功能。

程序面向单个 Windows 用户，不提供云同步或多人协作。模型服务在应用设置中配置；连接外部模型时，请求会发送到配置的服务。

## 开发环境

- Windows 10/11 x64
- Python 3.10（后端锁文件针对 Windows x64）
- Node.js 20 和 npm

## 本地运行

以下代码块分别从仓库根目录开始，在 PowerShell 中执行。

### 安装后端依赖

```powershell
cd apps\backend
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-win-py310.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e ".[packaging,vector,local-vector]"
.\.venv\Scripts\python.exe -m pip check
```

### 可选：下载本地模型

如果要使用内置的嵌入或重排模型，在仓库根目录运行对应脚本。文件下载到 `apps\backend\models`，不会提交到 Git。

```powershell
.\scripts\download-embedding-model.ps1
.\scripts\download-reranker-model.ps1
```

### 启动桌面端

```powershell
cd apps\desktop
npm ci
npm run dev
```

启动后，在应用设置中填写模型服务地址、模型名称和 API Key。开发模式下，后端默认使用 `apps\backend\.venv` 中的 Python；需要覆盖时可设置 `AGENT_PET_PYTHON`。

## 配置与本地数据

- Windows 上，API Key 使用当前用户的 DPAPI 加密保存。
- 默认 SQLite 数据库为 `%LOCALAPPDATA%\AgentPet\agent_pet.sqlite3`。可用 `AGENT_PET_DATA_DIR` 或 `AGENT_PET_SQLITE_PATH` 覆盖目录或数据库路径。
- 本地数据库不代表模型调用完全离线。配置外部聊天模型或嵌入服务时，相应请求会发送到所填服务。

## 测试与构建

从仓库根目录运行后端测试：

```powershell
apps\backend\.venv\Scripts\python.exe -m pytest apps/backend/tests -q
```

安装过桌面端依赖后，从仓库根目录运行静态检查：

```powershell
cd apps\desktop
npm run typecheck
```

需要构建前端时，在 `apps\desktop` 目录运行 `npm run build`。它会先执行 `typecheck`，再构建前端。

## 构建 Windows ZIP

先按上文安装后端依赖。若要把本地模型放进发布包，先运行两个模型下载脚本。然后从仓库根目录执行：

```powershell
cd apps\desktop
npm ci
npm run package:win
```

ZIP 输出到 `apps\desktop\release`。模型目录完整时，sidecar 构建会校验文件后复制到发布包；模型目录不存在时会提示并继续构建。需要未压缩目录包时运行 `npm run package:win:dir`。

## 目录

- `apps/backend`：FastAPI 后端、SQLite 存储和测试
- `apps/desktop`：Electron 主进程和 React 界面
- `scripts`：模型下载与 sidecar 构建脚本
- `docs/wiki-compilation.md`：Wiki 编译流程
