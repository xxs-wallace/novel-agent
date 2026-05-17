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
- [`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md)：Writer Agent Loop、artifact review gate 与可恢复状态机。

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

- 使用聊天式结构化消息承接 Writer 提问、artifact review 和章节验收。消息可以像普通 Agent 消息一样出现在会话流中，用户也可以使用同一个聊天输入框回答；但消息和回答必须绑定 `run_id`、问题 id 或 review id、artifact 引用与后端 action，不能退化为无语义的普通聊天记录。
- 使用 `ArtifactReviewDecision` 支持用户“通过并补充 prompt 信息”或“不通过并给出调整反馈”；Web 只提交用户决策语义，Writer workflow 负责 prompt 组装和 artifact 修订。
- 使用章节验收决策卡支持接受、基于反馈重写、退回章节梗概重规划、作废和稍后决定。
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
- artifact review 反馈入口。

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

#### Writer 提问的聊天式结构化交互

Writer 在 Outline Research Loop、人物对齐、新角色确认或其它人工补充节点提出问题时，Web SHALL 将问题渲染为会话中的 Agent 消息。该消息可以包含自然语言说明、问题列表和内联动作按钮，交互形态类似聊天产品中的“确认 / 撤销 / 打开”按钮。

这类消息 SHALL 同时携带结构化 payload：

- `run_id`
- `question_set_id`
- `stage`，例如 `outline_research_user_input`
- `questions[]`，每项至少包含 `question_id`、用户可读问题、是否必答、可选回答提示
- `source_artifact_id` 或 `artifact_path`
- 推荐的继续动作，例如 `submit_outline_research_answers`

用户回答 SHOULD 使用同一个聊天输入框完成。当前存在待回答问题时，输入框进入“回答当前问题”上下文；发送后生成一条普通可读的 user message，同时在 payload 中记录它回答的 `question_set_id`。用户点击“提交回答并继续研究”按钮后，前端 SHALL 调用结构化 action，而不是只保存普通 message。

普通聊天消息 SHALL NOT 自动越过 Writer `needs_user_input` 或 artifact review gate。只有用户点击确认按钮或等价结构化 action，才允许后端调用 `continue_after_outline_research_input`、确认新增人物或继续后续 Writer workflow。

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
- 大纲研究
  - 当前问题
  - 已确认信息
  - 仍缺口
  - 可用假设
  - Research trace 与 planning notebook 摘要
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
- 章节写作指导
  - 用户补充原文
  - 派生长度预算
  - 风格与节奏要求
- 本章执行输入
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

- “通过并继续”：提交 `ArtifactReviewDecision.decision = approved`，可携带原始 `supplement_text`，作为下一轮模型 prompt 输入。
- “不通过并调整”：提交 `ArtifactReviewDecision.decision = revision_requested`，必须携带原始 `revision_feedback`，由 Writer workflow 驱动模型修订当前 artifact 并回到同一 review gate。
- “稍后继续”：提交 `ArtifactReviewDecision.decision = deferred` 或等价 action，保留当前可恢复状态。

正文草稿验收卡片 SHALL 支持：

- 接受本章。
- 基于反馈重写本章。
- 修改章节梗概后重写。
- 作废本次草稿。
- 稍后再决定。

除“接受本章”外，其它验收分支 SHALL NOT 触发 Memory writeback 或 Creative KB 写回。

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
| `/confirm` | 决策卡“通过并继续”按钮 | `approve_writer_artifact` 或对应共享确认 action |
| `/back` | 决策卡“返回上一层”按钮 | `go_back` |
| `/help` | 顶部帮助 / 命令面板 | `show_help` |
| `/debug` | 技术详情 drawer | `show_debug_details` |

Writer Web-only actions:

| Web 场景 | Web 主交互 | 后端 action |
|---|---|---|
| Outline Research Loop 需要用户补充 | Agent 消息内问题卡 + 聊天输入回答 + “提交回答并继续研究”按钮 | `submit_outline_research_answers` |
| Outline Research Loop 稍后回答 | 问题卡“稍后继续”按钮 | `defer_outline_research_answers` |
| 通过当前 review artifact | “通过并继续”按钮 + 可选补充输入 | `approve_writer_artifact` |
| 调整当前 review artifact | “不通过并调整”按钮 + 反馈输入 | `request_writer_artifact_revision` |
| 稍后审阅当前 artifact | “稍后继续”按钮 | `defer_writer_artifact_review` |
| 章节验收接受 | 章节验收卡“接受本章” | `accept_chapter` |
| 基于反馈重写本章 | 章节验收卡“基于反馈重写” | `rewrite_chapter` |
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

### Conversational Writer Question Contract

`POST /api/tasks/{task_id}/messages` 可以继续只负责保存用户自然语言；但当消息是对 Writer 问题卡的回答时，payload SHOULD 包含：

```json
{
  "channel": "writer_question_answer",
  "run_id": "run-1",
  "question_set_id": "outline-research-run-1-001",
  "answer_text": "第一个问题的回答……\n第二个问题的回答……"
}
```

真正推动 Writer 继续的动作 SHALL 通过 `/actions`：

```json
{
  "action": "submit_outline_research_answers",
  "payload": {
    "run_id": "run-1",
    "question_set_id": "outline-research-run-1-001",
    "source_message_id": "message-123",
    "answer_text": "第一个问题的回答……\n第二个问题的回答……",
    "user_answers": [
      {
        "question_id": "q1",
        "answer_text": "第一个问题的回答……"
      },
      {
        "question_id": "q2",
        "answer_text": "第二个问题的回答……"
      }
    ]
  }
}
```

后端 SHALL 将该 action 映射为 Writer workflow 的 `continue_after_outline_research_input`。如果前端只提交 `answer_text`，后端 MAY 保留原文并生成最小 `user_answers` 映射；不得因为解析失败而伪造用户答案。用户回答必须作为 `user_authorized` evidence 进入 planning notebook 或等价 Writer artifact。

### Conversational Writer Artifact Review Contract

Writer artifact review 也通过会话消息承载。Agent 消息 SHALL 展示当前 artifact 的用户可读摘要、右侧详情入口和下一步提示；结构化 payload 至少包含：

- `run_id`
- `review_id`
- `artifact_kind`
- `artifact_id` 或 `artifact_path`
- `actions.approve`
- `actions.request_revision`
- `actions.defer`

用户点击“通过并继续”时，前端发送：

```json
{
  "action": "approve_writer_artifact",
  "payload": {
    "run_id": "run-1",
    "review_id": "artifact-review-run-1-004",
    "artifact_kind": "chapter_package",
    "artifact_id": "writer:run-1:chapter-package",
    "source_message_id": "message-456",
    "supplement_text": "本章控制在三千字左右，动作段更紧，结尾不要解释幕后人。"
  }
}
```

用户点击“不通过并调整”时，前端发送：

```json
{
  "action": "request_writer_artifact_revision",
  "payload": {
    "run_id": "run-1",
    "review_id": "artifact-review-run-1-004",
    "artifact_kind": "chapter_package",
    "artifact_id": "writer:run-1:chapter-package",
    "source_message_id": "message-457",
    "revision_feedback": "第二个场景因果太跳，先补人物动机，再进入冲突。"
  }
}
```

`supplement_text` 与 `revision_feedback` 必须原文保留。Web 后端不得自己拼 Writer prompt；它只将结构化决策交给 Writer workflow。

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
- `WriterQuestionSet`
- `WriterArtifactReview`
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
- Outline Research Loop 的用户补充问题以聊天消息展示，用户可用同一输入框回答；只有点击“提交回答并继续研究”等结构化按钮时才继续 Writer workflow。
- Writer artifact review 以聊天消息展示，用户可在同一个输入框输入通过后的补充 prompt 或不通过后的调整反馈；只有结构化按钮才继续 workflow。
- 右侧目录树可浏览 close-read 与 Writer 结果，详细内容不直接展示 JSON。
- 人物资料以百科条目展示，支持二级目录树。
- 后端 API 复用 `WorkflowFacade`、`StatusPresenter`、`ArtifactPresenter` 等共享语义。
- SSE 能实时回流 read、close-read、KB、Writer 与 benchmark 进度。
- Artifact review 能通过 Web action 表达通过并补充、请求调整、稍后继续；补充和反馈原文均能进入 Writer 结构化决策。
- 章节验收能通过 Web action 表达接受、基于反馈重写、重做章节规划、作废和稍后决定；非接受分支不得回写 Memory / KB。
- 测试覆盖 API contract、view model 转换、三栏布局、目录树、会话与 SSE。
