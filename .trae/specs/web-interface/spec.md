# Web Interface Spec

## Purpose

本文定义 Novel Agent 的 Web 工作台。当前产品仍在快速迭代阶段，正式图形界面 SHALL 转向“Python 后端 + Web 前端”的前后端分离架构，不继续沿 PySide GUI 路线扩展。

Web 端必须参考当前 Textual TUI 的流程语义，但采用浏览器工作台的信息架构：

- 左侧：任务列表与任务进度。
- 中间：使用者与 Agent 的会话框。
- 右侧：close-read 与 Writer 结果浏览器，采用目录树 + 详细内容。

上游语义来源：

- [`../spec.md`](../spec.md)：产品级流程、用户可见状态和人工确认规则。
- [`../cli-interface/design.md`](../cli-interface/design.md)：TUI 已定义的命令、状态侧栏、artifact 审阅、确认点与恢复语义。
- [`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md)：Writer 分层生成与可恢复状态机。

## Product Boundary

Web 工作台 SHALL 是面向作者用户的主图形入口。旧 PySide GUI 不再作为新功能承载面，只可作为历史原型或 smoke 对照保留。

Web 工作台 SHALL 复用现有 Python 交互层：

- `WorkflowFacade`：调用粗读、精读、Creative KB、benchmark 和 Writer workflow。
- 共享 Agent 接口 / action adapter：Web 的按钮、列表点击、菜单与表单提交最终都调用和 CLI/TUI 相同的后端能力。
- `CommandRouter`：继续服务 CLI/TUI slash command；Web 仅在命令面板、开发者入口或高级输入中复用它，不把 slash command 作为主交互。
- `StatusPresenter` / `WriterStatusPresenter`：用户可见状态词典。
- `ArtifactPresenter` 或其 Web 扩展：把 artifact 转换成用户可读视图。
- `RunEventStream` / `MessageStream`：后台任务进度与会话消息。

Web 工作台 SHALL NOT：

- 直接拼 Writer prompt。
- 直接修改 Memory 规则。
- 绕过 orchestration 写 workflow state。
- 把内部 JSON、stage、checkpoint id 当作用户主内容展示。

Web 工作台 SHALL 在 Writer 审阅流程中提供结构化 action：

- 使用 `Scoped Artifact Revision` 支持用户用自然语言反馈修订当前审阅 artifact。
- 使用章节验收决策卡支持接受、按长度重写、重做章节规划、作废和稍后决定。
- 所有修订、验收与回写动作 SHALL 调用 `WorkflowFacade` / Writer workflow / 共享 action adapter，不得由 Web 后端直接拼 prompt、写 Memory 或改 workflow state。

## Technology Direction

调研后推荐技术路线：

- 后端：FastAPI + Pydantic + Uvicorn。
  - FastAPI 原生适合 Python API 层、OpenAPI 文档、Pydantic 契约和 ASGI 长连接。
  - Agent 进度流优先使用 SSE；用户输入和操作使用 REST。
  - 长任务使用应用内 `JobManager` + asyncio task + 持久事件日志；FastAPI `BackgroundTasks` 只用于短小清理任务，后续可升级 Celery / RQ。

- 前端：Vite + React + TypeScript。
  - 当前不需要 SSR，优先快速开发、热更新和清晰构建。
  - Server state 使用 TanStack Query。
  - 路由使用 TanStack Router 或轻量 React Router；首版可单路由，保留 URL 可分享的 task/artifact/search params。
  - UI 基础组件使用 shadcn/ui + Radix primitives。
  - 三栏可调布局使用 shadcn/ui Resizable。
  - 右侧目录树使用 MUI X Tree View 或封装后的自研 tree adapter；必须支持键盘导航、展开/折叠、选中和后续 lazy loading。
  - 正文渲染使用 Markdown / rich text viewer，不直接展示 JSON。

参考资料：

- FastAPI SSE：<https://fastapi.tiangolo.com/tutorial/server-sent-events/>
- FastAPI Background Tasks caveat：<https://fastapi.tiangolo.com/tutorial/background-tasks/>
- Vite React TypeScript：<https://vite.dev/guide/>
- TanStack Query：<https://tanstack.com/query/v>
- TanStack Router：<https://tanstack.com/router/router/docs>
- shadcn/ui Resizable：<https://ui.shadcn.com/docs/components/resizable>
- MUI X Tree View：<https://mui.com/components/tree-view>

## User-Facing Layout

### 1. Left Task Rail

左侧 SHALL 展示任务列表与任务进度。

每个任务至少展示：

- task id / book id。
- 原文路径或短标题。
- 粗读进度：documents 数、checkpoint、是否完成。
- 精读进度：已精读章节 / documents、是否落后于粗读。
- Creative KB 状态。
- Writer 状态：未开始、规划中、待审阅、正文生成中、待验收、已完成。
- 当前阻塞点，例如“请审阅本批剧情大纲”。

用户 SHALL 能在左侧：

- 点击“创建任务”按钮打开任务创建表单。
- 点击任务列表中的 task id / task card 选择任务。
- 查看任务详情。
- 预览删除任务的本地建模产物。
- 重置精读。
- 从任务菜单启动粗读、精读、KB 或 Writer。

### 2. Center Conversation

中间 SHALL 是用户与 Agent 的会话框。

会话框 SHALL 展示：

- 用户输入。
- Agent 回复。
- 后台任务进度。
- 错误与恢复建议。
- 阻塞确认卡片。
- scoped revision 反馈入口。

会话输入 SHALL 支持：

- 自然语言续写方向。
- 多行中文输入。
- 粘贴长文本。
- `@artifact` / `@人物` / `@章节` 引用。

Web 主界面 SHOULD NOT 要求用户输入 `/writer`、`/close-read`、`/task` 等 CLI 指令。对应能力 SHOULD 通过按钮、列表点击、菜单、wizard 和决策卡触发。

slash command MAY 作为高级命令入口保留：

- 命令面板中的“高级命令”。
- 开发者 / smoke / debug 模式。
- 用户明确输入 `/` 时的兼容路径。

当 Agent 等待人工确认时，中间会话区 SHALL 展示结构化决策卡片，而不是要求用户输入内部 workflow action。

### 3. Right Result Explorer

右侧 SHALL 展示 close-read 与 Writer 结果。

右侧采用“双层结构”：

- 上层：目录树。
- 下层或右侧：选中节点的详细内容。

目录树至少包含两个顶层 tab：

- `Close-read`
- `Writer`

详细内容 SHALL 是用户需要理解的正文、摘要、卡片和表格，不直接展示 JSON。JSON 只可在技术详情或开发者模式中查看。

## Close-Read Result Views

Close-read 目录树 SHOULD 包含：

- 总览
  - 建模准备度
  - 总体剧情摘要
  - 已处理章节范围
- 章节摘要
  - 按卷 / 章节 / document title index 分组
  - 每章显示剧情概括、角色状态变化、伏笔和信息增量
- 人物百科
  - 按主角 / 配角 / 反派 / 阵营或用户自定义标签分组
  - 每个人物再分层展示：
    - 基本信息
    - 当前目标
    - 关系网络
    - 性格与说话方式
    - 已知秘密
    - 禁止误写点
    - 最近变化
- 世界观
  - 地点
  - 组织
  - 规则
  - 物品
  - 时间线
- 故事大纲
  - 主线
  - 支线
  - 未回收伏笔
- 源作品篇章地图
  - 篇章结构
  - 节奏节点
  - 高潮与转折

人物文档 SHALL 默认按“百科条目”展示，而不是原始 JSON。复杂字段可通过二级目录树展开。

## Writer Result Views

Writer 目录树 SHOULD 包含：

- Run 总览
  - 当前状态
  - 待确认步骤
  - 产物路径
  - 下一步动作
- 全书续写规划
  - 续写目标
  - 世界观补充
  - 人物补充
  - 高潮与回收
- 本批剧情大纲
  - 起点状态
  - 阶段目标
  - 主要冲突
  - 情绪节奏
  - 预计收束
- 章节标题与梗概
  - 按章节分组
  - 目标、冲突、关系推进、禁止项
- 章节长度计划
  - 默认字数
  - 单章预算
  - 重点章节与高潮章节
- 本章写作材料
  - 事实型上下文
  - 风格与桥段参考
  - 禁止项
- 正文草稿
  - 字数
  - 开头预览
  - 连续性检查
  - 完整正文渲染
- 写回确认
  - 人物状态变化
  - 世界状态变化
  - 新伏笔
  - 已回收信息

Writer 详细内容 SHALL 优先使用卡片、段落、表格和折叠小节展示。高级 JSON 入口必须折叠，并明确标记为“技术详情”。

Writer 审阅卡片 SHALL 支持：

- “确认并继续”：确认当前审阅步骤，推进到下一阶段。
- “按反馈修改”：提交 `Scoped Artifact Revision` 请求，展示候选 diff。
- “应用此修订”：保存已校验候选，但不自动确认当前审阅步骤。
- “放弃此修订”：保留原 artifact。
- “稍后继续”：保留当前 checkpoint。

正文草稿验收卡片 SHALL 支持：

- 接受本章。
- 调整字数后重写。
- 修改章节梗概后重写。
- 作废本次草稿。
- 稍后再决定。

除“接受本章”外，其它验收分支 SHALL NOT 触发 `Freeze E`、Memory writeback 或 Creative KB 写回。

## Web Actions And CLI Command Parity

Web SHALL 支持 TUI 的命令语义，但主交互必须采用网页原生动作，而不是把 slash command 暴露为主要入口。

| CLI / TUI 语义 | Web 主交互 | 后端 action |
|---|---|---|
| `/tasks` | 左侧任务列表自动加载 / 刷新按钮 | `list_tasks` |
| `/task <id>` | 点击左侧 task id / task card | `select_task` |
| `/new-task` | “创建任务”按钮 + dialog | `create_task` |
| `/delete-task` | task card 菜单“删除任务” + 预览确认 dialog | `delete_task` |
| `/reset-close-read` | task 菜单“重置精读” | `reset_close_read` |
| `/read` | task action “开始粗读 / 继续粗读” | `start_read` |
| `/close-read` | task action “运行精读” | `start_close_read` |
| `/query` | 右侧 Close-read 树节点点击 / 查询 tab | `query_close_read` |
| `/kb` | task action “构建 Creative KB” | `build_creative_kb` |
| `/benchmark` | “运行端到端评测”按钮 + dialog | `run_smoke_benchmark` |
| `/creative-kb-benchmark` | “运行 KB 评测”按钮 + dialog | `run_creative_kb_benchmark` |
| `/writer` | “开始续写”按钮 + Writer intent wizard | `start_writer` |
| `/resume` | 阻塞任务 badge / “继续流程”按钮 | `resume` |
| `/artifacts` | 右侧 Result Explorer | `list_artifacts` |
| `/open` | artifact detail “打开文件位置 / 复制路径” | `open_artifact` |
| `/save` | artifact 编辑器“保存修改”按钮 | `save_artifact` |
| `/confirm` | 决策卡“接受并继续”按钮 | `confirm_current_step` |
| `/back` | 决策卡“返回上一层”按钮 | `go_back` |
| `/help` | 顶部帮助 / 命令面板 | `show_help` |
| `/debug` | 技术详情 drawer | `show_debug_details` |

Writer Web-only actions:

| Web 场景 | Web 主交互 | 后端 action |
|---|---|---|
| 受控修订当前审阅 artifact | “按反馈修改”表单提交 | `request_scoped_artifact_revision` |
| 应用受控修订候选 | diff 卡片“应用此修订” | `apply_scoped_artifact_revision` |
| 放弃受控修订候选 | diff 卡片“放弃此修订” | `discard_scoped_artifact_revision` |
| 章节验收接受 | 章节验收卡“接受本章” | `accept_chapter` |
| 调整字数后重写 | 章节验收卡“调整字数后重写” | `revise_chapter_length` |
| 修改章节梗概后重写 | 章节验收卡“修改章节梗概后重写” | `replan_chapter` |
| 作废当前草稿 | 章节验收卡“作废本次草稿” | `discard_chapter` |
| 稍后再决定 | 章节验收卡“稍后再决定” | `defer_chapter_acceptance` |

Web 高级命令入口 MAY 兼容以下 slash command：

- `/status`
- `/tasks`
- `/task`
- `/new-task`
- `/delete-task`
- `/reset-close-read`
- `/read`
- `/close-read`
- `/query`
- `/kb`
- `/benchmark`
- `/creative-kb-benchmark`
- `/writer`
- `/resume`
- `/artifacts`
- `/open`
- `/save`
- `/confirm`
- `/back`
- `/help`
- `/debug`

所有 Web button action SHALL 发送 HTTP 请求给后端，由后端 action adapter 调用共享 Agent 接口。前端不得直接实现 CLI parser，不得绕过共享后端 facade。

## API Contract

Web 后端 SHALL 暴露稳定 API。

任务与状态：

- `GET /api/tasks`
- `POST /api/tasks`
- `GET /api/tasks/{task_id}`
- `DELETE /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/reset-close-read`
- `GET /api/tasks/{task_id}/status`

会话与命令：

- `GET /api/tasks/{task_id}/messages`
- `POST /api/tasks/{task_id}/messages`
- `POST /api/tasks/{task_id}/actions`
- `POST /api/tasks/{task_id}/commands`
  - 仅用于高级 slash command 兼容，不作为 Web 主路径。

后台任务：

- `POST /api/tasks/{task_id}/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`
- `GET /api/jobs/{job_id}/events`

结果浏览：

- `GET /api/tasks/{task_id}/artifact-tree?surface=close-read|writer`
- `GET /api/artifacts/{artifact_id}/view`
- `GET /api/artifacts/{artifact_id}/technical`
- `POST /api/artifacts/{artifact_id}/save`
- `POST /api/artifacts/{artifact_id}/revision-request`
- `POST /api/artifacts/{artifact_id}/revision-apply`

`revision-request` / `revision-apply` MAY 作为 artifact 资源型别名存在；Web 主交互 SHOULD 优先通过 `POST /api/tasks/{task_id}/actions` 发送上述结构化 action，以便会话消息、决策卡、job 和状态刷新走同一套 adapter。

## View Models

后端 SHALL 不把原始 artifact JSON 直接发给普通视图，而是转换为 view model。

核心模型：

- `TaskSummary`
- `TaskProgress`
- `ConversationMessage`
- `JobSummary`
- `JobEvent`
- `ArtifactTreeNode`
- `ArtifactView`
- `DecisionCard`
- `PersonEncyclopediaEntry`
- `ChapterSummaryView`
- `WriterRunView`

`ArtifactView` SHALL 至少包含：

- `artifact_id`
- `title`
- `kind`
- `source`
- `sections`
- `markdown`
- `cards`
- `tables`
- `children`
- `technical_available`

## Status Vocabulary

Web 主界面 SHALL 使用产品级中文状态文案。禁止在主界面泄露：

- `artifact saved`
- `checkpoint confirmed`
- `Freeze B pending`
- `freeze_a_review`
- `batch_review`
- `freeze_d_review`
- `wait_length_review`
- `wait_chapter_acceptance`
- `wait_chapter_review`
- `writeback_review`

这些内部字段只允许出现在技术详情中。

## Acceptance

Web 端被认为达到 TUI parity 的条件：

- 左侧任务列表可展示多任务进度；点击 task id / task card 即可切换当前任务。
- “创建任务”是按钮 + dialog，不要求用户输入 `/new-task`。
- 粗读、精读、Creative KB、Writer、恢复、确认、返回、保存都能通过合适的 Web 按钮 / 菜单 / 决策卡触发。
- 中间会话可发送自然语言，能展示 Agent 进度与阻塞决策；slash command 仅作为高级兼容入口。
- 右侧目录树可浏览 close-read 与 Writer 结果，详细内容不直接展示 JSON。
- 人物资料以百科条目展示，支持二级目录树。
- 后端 API 复用 `WorkflowFacade`、`StatusPresenter`、`ArtifactPresenter` 等共享语义。
- SSE 能实时回流 read、close-read、KB、Writer 与 benchmark 进度。
- Scoped Artifact Revision 能通过 Web action 生成候选 diff、应用或放弃候选；应用候选后仍需用户显式确认当前审阅步骤。
- 章节验收能通过 Web action 表达接受、按长度重写、重做章节规划、作废和稍后决定；非接受分支不得回写 Memory / KB。
- 测试覆盖 API contract、view model 转换、三栏布局、目录树、会话与 SSE。
