# 项目改造任务指令集

## 总目标

把当前项目从“研发能力集合”改造成面向中国用户的“本地长期记忆陪伴体”。

第一屏、首次使用、聊天入口、记忆入口、系统回复口吻，都必须围绕同一个体验闭环：

用户自然说话；陪伴体记住重要内容；用户能看到、修改、撤回记忆；第二天和一周后能自然接上上下文。

知识整理、任务、资料归档、工作流、调试、模型配置都只能作为支撑能力，不得抢占首屏和主叙事。

## 硬性规则

一、严格按任务顺序执行。上一项没有通过验收，不得进入下一项。

二、用户可见文案必须使用简体中文。不得新增英文卖点、英文按钮、英文标签、英文说明。代码路径、接口名、测试命令按项目原名保留。

三、不得修改生成物、本地状态和依赖目录，包括 `node_modules`、`dist`、`release`、数据库、日志、临时目录。

四、不得让渲染进程直接访问文件系统、系统命令、令牌或密钥。桌面能力必须继续通过预加载脚本和主进程桥接。

五、不得把“已覆盖”“已完成验收”写入文档，除非已经运行对应验证命令并记录结果。

六、涉及真实知识库绑定、删除、移动、批量改写、数据库结构变更、清理进程或端口，必须先让用户确认。本任务集默认不做这些操作。

七、每个任务完成后必须记录：修改文件、修改意图、验证命令、命令结果。

## 任务一：建立修改基线

目标：确认当前项目结构和入口，避免误改生成物或本地状态。

执行：

一、确认根目录存在后端入口、桌面入口、主界面、聊天页、记忆页和导航文件。

二、读取以下文件，只读不改：

`apps/desktop/src/App.tsx`

`apps/desktop/src/views/StageView.tsx`

`apps/desktop/src/views/ChatWindowView.tsx`

`apps/desktop/src/views/MemoryWindowView.tsx`

`apps/desktop/src/views/navigation.ts`

`apps/desktop/src/features/chat/petInputModes.ts`

`apps/backend/app/agents/runtime_helpers.py`

`apps/backend/app/agents/nodes/chat.py`

三、搜索首屏和聊天入口中出现的工具化表达，例如“任务”“知识整理”“回放”“高级工具”“桌面记忆助手”“Wiki”“Markdown”“Agent”。

验收：

一、输出当前主入口清单。

二、输出需要替换或降级的用户可见表达清单。

三、本任务不得产生代码修改。

建议命令：

`Test-Path apps/desktop/src/App.tsx`

`Test-Path apps/desktop/src/views/StageView.tsx`

`Test-Path apps/desktop/src/views/ChatWindowView.tsx`

`Test-Path apps/desktop/src/views/MemoryWindowView.tsx`

`Test-Path apps/desktop/src/views/navigation.ts`

`Test-Path apps/desktop/src/features/chat/petInputModes.ts`

`Test-Path apps/backend/app/agents/runtime_helpers.py`

`rg "任务|知识整理|回放|高级工具|桌面记忆助手|Wiki|Markdown|Agent" apps/desktop/src`

## 任务二：新建统一中文产品文案模块

目标：把主叙事收敛到一个地方，避免每个页面各说各话。

执行：

一、新建 `apps/desktop/src/productCopy.ts`。

二、导出统一文案对象，至少包含：

产品显示名：建议使用“本地陪伴体”或“桌宠伙伴”，不得使用英文名作为主显示名。

一句话承诺：表达“长期记住你、陪你、记忆留在本机、可查看可撤回”。

首屏三条核心价值：长期陪伴、本地记忆、记忆可控。

首次使用引导文案。

记忆页标题、说明和空状态文案。

聊天页标题、说明和快捷提示文案。

三、把新文案写成普通用户能听懂的话，不出现技术缩写和工程术语。

验收：

一、`productCopy.ts` 只包含中文用户表达和必要的导出结构。

二、不得在该文件中出现“工具集合”“知识库机器人”“研发系统”等表达。

三、不得修改业务逻辑。

建议命令：

`rg "本地陪伴体|桌宠伙伴|长期记住|可撤回" apps/desktop/src/productCopy.ts`

## 任务三：改造桌面主舞台为陪伴入口

目标：让用户第一次看到的不是功能指挥中心，而是一个会长期记住自己的本地陪伴体。

修改文件：

`apps/desktop/src/views/StageView.tsx`

执行：

一、引用任务二的新文案模块。

二、把用户可见名称从偏工具化的名称改为陪伴体名称。

三、把主标题改成“今天想从哪里继续”这一类连续陪伴表达。

四、首屏主操作只保留三类：

陪我聊聊，进入聊天。

看看记忆，进入记忆。

设置边界，进入设置。

五、任务、知识整理、工作流、报告等入口降级到折叠的“更多能力”里，且不得默认展开。

六、不得在首屏出现“高级工具”“Wiki”“Markdown”“Agent”等词。

七、保留桌宠模型、气泡、连接状态和已有发送逻辑，不破坏点击穿透和气泡分页。

验收：

一、首屏第一眼能看出这是陪伴体。

二、任务和知识整理不再是首屏主按钮。

三、原有路由仍可进入，不删除能力，只调整层级。

建议命令：

`rg "高级工具|Wiki|Markdown|Agent|功能指挥中心|桌面记忆助手" apps/desktop/src/views/StageView.tsx`

`Push-Location apps/desktop; npm run typecheck; Pop-Location`

## 任务四：重排底部导航

目标：让主导航服务陪伴闭环，而不是暴露工程模块。

修改文件：

`apps/desktop/src/views/navigation.ts`

可能需要同步修改：

`apps/desktop/src/views/AgentWorkspaceView.tsx`

`apps/desktop/src/views/ChatWindowView.tsx`

`apps/desktop/src/views/MemoryWindowView.tsx`

`apps/desktop/src/views/SettingsWindowView.tsx`

执行：

一、底部主导航改为面向用户的中文标签，建议顺序：

今日、陪伴、记忆、设置。

二、聊天页对应“陪伴”。

三、记忆页对应“记忆”。

四、任务工作台不再作为主导航项；如仍需入口，放到更多能力或设置里的支撑能力区。

五、同步修复所有 `activeTab` 类型错误和测试断言。

验收：

一、主导航不再出现“任务”作为一级入口。

二、页面切换仍可正常路由。

三、类型检查通过。

建议命令：

`rg "activeTab=|primaryNavigationTabs|任务|回放" apps/desktop/src/views`

`Push-Location apps/desktop; npm run typecheck; Pop-Location`

## 任务五：改造聊天入口为陪伴输入

目标：用户打开聊天页时感受到“找陪伴体说话”，不是在选择一组工具模式。

修改文件：

`apps/desktop/src/views/ChatWindowView.tsx`

`apps/desktop/src/features/chat/petInputModes.ts`

同步修改测试：

`apps/desktop/src/features/chat/petInputModes.test.ts`

执行：

一、把聊天页标题改成“陪伴”或“和我说说”。

二、把输入模式标签改成用户语言：

聊天改为陪伴。

记一个改为记住。

新任务改为提醒。

整理 Wiki 改为整理资料或整理知识。

今日复盘改为回顾今天。

三、默认重点突出“陪伴”和“记住”，其他模式降级为次要按钮。

四、快捷示例改成长期记忆陪伴场景，例如：

“我今天有点累”

“记住我最近在准备一件重要的事”

“明天提醒我继续这件事”

“帮我回顾今天”

五、构造发送给后端的意图提示时，可以保留内部能力约束，但最终用户看见的按钮和说明不得出现英文或工程术语。

验收：

一、聊天页没有把“任务”“知识整理”放在第一感知层。

二、用户无需理解资料库、模型、接口即可开始说话。

三、相关单元测试更新并通过。

建议命令：

`Push-Location apps/desktop; npm run test -- petInputModes; Pop-Location`

`Push-Location apps/desktop; npm run typecheck; Pop-Location`

## 任务六：改造首次使用引导

目标：首次使用只问用户一个能启动陪伴关系的问题，不让用户先配置系统。

修改文件：

`apps/desktop/src/App.tsx`

执行：

一、调整 `FirstUseOnboardingCard` 的用户可见文案。

二、首次引导只保留一个必填问题，建议为：

“今天想让我从哪里陪你继续？”

三、称呼、长期跟踪内容、保存位置都改为可选补充，不得阻塞首次聊天。

四、`buildFirstUseOnboardingMessage` 生成的后端提示要明确：

先自然回应用户。

只沉淀高价值、非敏感、可复用的长期记忆。

低置信、敏感或关系身份类内容必须等待确认或跳过。

五、首次引导完成后的提示要表达“可以在记忆里查看和撤回”，而不是只说“整理完成”。

六、不得新增真实知识库绑定动作。

验收：

一、用户第一次打开即可开始聊天。

二、首次引导不要求理解保存位置、知识库、模型或路径。

三、首次引导产生的记忆必须可在记忆页或活动记录中追踪。

建议命令：

`rg "首次|保存位置|知识库|模型|路径|撤回|记忆" apps/desktop/src/App.tsx`

`Push-Location apps/desktop; npm run typecheck; Pop-Location`

## 任务七：改造记忆页为“我的记忆”

目标：让记忆页成为产品信任核心，清楚展示记住了什么、为什么记住、如何修改和撤回。

修改文件：

`apps/desktop/src/views/MemoryWindowView.tsx`

可能需要同步修改：

`apps/desktop/src/features/memory/*`

`apps/desktop/src/services/agentActivity.ts`

执行：

一、页面标题改为“我的记忆”。

二、顶部说明改为用户语言：这里能看到我记住的内容、来源、状态，以及撤回记录。

三、优先展示三块内容：

正在使用的记忆。

待确认的记忆。

最近撤回或跳过的记忆。

四、所有可逆写入必须有清楚的“撤回”入口；已有入口则优化文案，不重复造轮子。

五、把“图谱”“索引”“审计”“工作流”等工程词降级到折叠调试区或设置区。

六、搜索框提示语改为“搜索我记住的事”。

验收：

一、普通用户能理解记忆页是控制自己长期记忆的地方。

二、敏感、隔离、拒绝、撤回等状态仍然准确展示。

三、不得绕过现有记忆安全策略。

建议命令：

`rg "图谱|索引|审计|工作流|Wiki|Markdown|撤回|待确认|我的记忆" apps/desktop/src/views/MemoryWindowView.tsx apps/desktop/src/features/memory apps/desktop/src/services/agentActivity.ts`

`Push-Location apps/desktop; npm run typecheck; Pop-Location`

## 任务八：调整后端聊天口吻和记忆边界

目标：后端生成回答时始终扮演“本地长期记忆陪伴体”，同时不编造记忆、不越权保存。

修改文件：

`apps/backend/app/agents/runtime_helpers.py`

`apps/backend/app/agents/nodes/chat.py`

可能需要同步修改：

`apps/backend/tests/test_agent_runtime_chat.py`

`apps/backend/tests/test_visible_continuity.py`

执行：

一、修改聊天系统提示，使其明确：

你是本地长期记忆陪伴体。

用温和、稳定、有分寸的中文回应。

只有在相关时才引用检索到的记忆。

不把候选、待确认、被拒绝或隔离内容说成已确认记忆。

不编造用户过去说过的话。

如果记忆不确定，要承认可能记错。

涉及健康、法律、金钱、关系危机时，给出边界清楚的支持性表达。

二、保留已有检索、引用、连续性、敏感内容过滤规则。

三、更新测试，覆盖“没有记忆时不编造”“候选记忆不当成确认记忆”“回答口吻是陪伴体”。

验收：

一、后端测试通过。

二、系统提示没有削弱安全边界。

三、回答不再像工具调度器。

建议命令：

`Push-Location apps/backend; python -m pytest -q tests/test_agent_runtime_chat.py tests/test_visible_continuity.py; Pop-Location`

## 任务九：隐藏主体验中的工程术语

目标：项目仍保留工程能力，但普通用户路径不出现工程黑话。

修改范围：

`apps/desktop/src`

执行：

一、搜索用户可见文案中的以下词：

`Wiki`、`Markdown`、`Agent`、`Live2D`、`API`、`Vault`、`token`、`Bearer`

二、普通用户路径中替换为中文表达：

Wiki 改为知识页或知识整理。

Markdown 改为本机文件或本地文本。

Agent 改为后台助手或整理流程。

Vault 改为本机文件夹。

API、token、Bearer 不得出现在普通页面。

三、设置页、开发诊断、模型配置可以保留必要术语，但必须放在明确的高级或调试区域。

四、不得改动内部类型名、接口字段名和测试数据中必要的技术标识。

验收：

一、首屏、聊天页、记忆页没有新增英文用户可见表达。

二、设置页必要术语不影响普通使用路径。

三、类型检查通过。

建议命令：

`rg "Wiki|Markdown|Agent|Live2D|API|Vault|token|Bearer" apps/desktop/src`

`Push-Location apps/desktop; npm run typecheck; Pop-Location`

## 任务十：补充桌面端回归测试

目标：用测试锁住这次产品收敛，防止后续又回到工具集合叙事。

修改范围：

`apps/desktop/src/**/*.test.ts`

`apps/desktop/src/**/*.test.tsx`

执行：

一、更新聊天模式测试，断言主模式标签为中文陪伴表达。

二、更新或新增导航测试，断言一级导航不包含“任务”。

三、更新或新增舞台测试，断言首屏出现长期记忆陪伴承诺，不出现“高级工具”默认展开。

四、更新首次引导相关测试，断言首次使用无需填写保存位置即可提交。

五、不得为通过测试而删除真实功能。

验收：

一、桌面端测试通过。

二、类型检查通过。

建议命令：

`Push-Location apps/desktop; npm run test; Pop-Location`

`Push-Location apps/desktop; npm run typecheck; Pop-Location`

## 任务十一：执行后端安全回归

目标：确认陪伴体口吻调整没有破坏长期记忆、路径安全和自动整理策略。

执行：

一、运行聊天和连续性相关测试。

二、运行记忆策略和安全边界相关测试。

三、如修改了路径、写入、撤回、活动账本相关逻辑，额外运行存储和安全测试。

验收：

一、所有相关测试通过。

二、如有失败，必须说明是源码问题、环境问题还是已有问题，并给出下一步修复。

建议命令：

`Push-Location apps/backend; python -m pytest -q tests/test_agent_runtime_chat.py tests/test_visible_continuity.py tests/test_memory_permissions.py tests/test_memory_hygiene.py tests/test_memory_pollution_regression.py; Pop-Location`

如改动存储或路径：

`Push-Location apps/backend; python -m pytest -q tests/test_storage_paths.py tests/test_security_hardening_mvp.py; Pop-Location`

## 任务十二：执行桌面权限和打包契约回归

目标：确认产品叙事改造没有破坏桌面安全边界。

执行：

一、如果改过 Electron 主进程、预加载或桌面桥接，必须运行 Electron 迁移校验。

二、如果没有改这些文件，也至少运行类型检查。

三、不得因为界面改造而让渲染进程直接读取本地文件或密钥。

验收：

一、权限边界仍然通过校验。

二、没有新增渲染进程直接文件访问。

建议命令：

`Push-Location apps/desktop; node scripts/validate-electron-migration.mjs; Pop-Location`

`Push-Location apps/desktop; npm run package:check; Pop-Location`

## 任务十三：人工体验验收

目标：确认改造后的实际体验符合“本地长期记忆陪伴体”。

执行：

一、启动桌面端或前端开发环境。

二、检查首屏：

第一感知是陪伴体。

主按钮围绕陪伴、记忆、设置边界。

任务和知识整理不抢主位。

三、检查首次使用：

不配置路径也能开始聊天。

引导问题自然，不像系统表单。

四、检查聊天：

用户说“我今天有点累”，产品回应应像陪伴体。

用户说“记住我最近在准备一个重要项目”，产品应进入合适的记忆策略。

五、检查记忆：

能看到记忆来源和状态。

能找到撤回入口。

候选或待确认记忆不会被当成已确认记忆。

验收：

一、记录人工验收结果。

二、如无法启动或环境受限，记录失败命令和原因，不得宣称已完成视觉验收。

建议命令：

`.\scripts\dev-frontend.ps1 -Port 5173`

`Push-Location apps/desktop; npm run electron:dev; Pop-Location`

## 任务十四：更新必要文档

目标：让项目文档和当前产品叙事一致，但不伪造验收状态。

允许修改：

`README.md`

`docs/README.md`

`docs/v0.2-validation.md`

不得修改：

`progress.md`，除非当前执行者明确是协调者角色。

执行：

一、把对外介绍改为“本地长期记忆陪伴体”。

二、说明知识整理、任务、资料归档是内置支撑能力。

三、说明记忆可查看、可修改、可撤回。

四、不得把未验证项目标成已覆盖。

验收：

一、文档没有和当前代码冲突。

二、文档没有融资式空话，必须能落到产品体验。

建议命令：

`rg "产品已成型|工具集合|知识库 Agent|研发系统|本地长期记忆陪伴体|可撤回" README.md docs`

## 任务十五：最终交付检查

目标：确认这次项目修改可交给用户试用和复查。

执行：

一、列出所有修改文件。

二、列出所有运行过的命令和完整结果。

三、列出未完成或无法验证的项目。

四、确认没有改动禁止路径。

五、确认没有泄露令牌、密钥或真实凭据。

六、确认没有直接修改数据库或真实知识库。

最低建议验证命令：

`Push-Location apps/desktop; npm run typecheck; Pop-Location`

`Push-Location apps/desktop; npm run test; Pop-Location`

`Push-Location apps/backend; python -m pytest -q tests/test_agent_runtime_chat.py tests/test_visible_continuity.py tests/test_memory_permissions.py tests/test_memory_hygiene.py tests/test_memory_pollution_regression.py; Pop-Location`

`rg "sk-|pk-|rk-|ghp_|gho_|ghu_|github_pat_|xoxb-|AKIA|Bearer " .`

验收：

一、交付说明必须先讲产品体验变化，再讲技术验证。

二、如果任何验证失败，必须说明原因和影响范围。

三、不得把未跑过的验证写成已通过。
