# Claude Code 入口

本仓库不维护第二套 Agent 规则。Claude Code 在执行任何任务前必须完整读取根目录
[`AGENTS.md`](AGENTS.md)，并以它作为安全边界、工程约定、验证命令和进度所有权的
唯一指令来源。

按任务需要继续读取：

- [`README.md`](README.md)：产品定位与公开入口；
- [`task.md`](task.md)：当前求职作品集改造计划；
- [`docs/current-specification.md`](docs/current-specification.md)：当前产品与工程规格；
- [`docs/verification-policy.md`](docs/verification-policy.md)：L1—L4 证据规则。

当前代码、migration 和重新运行的测试优先于任何文档。不要在本文件复制命令、
架构说明或权限规则，以免再次产生冲突。
