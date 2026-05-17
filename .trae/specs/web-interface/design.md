# Web Interface Design

## 1. Design Conclusion

Novel Agent 的图形端应从 PySide GUI 转为浏览器工作台。原因：

- 产品还在快速迭代，Web 前端比跨平台桌面 GUI 更适合快速调整布局、组件和交互。
- 当前 TUI 已经沉淀出稳定的流程语义，Web 可以复用后端 presenter / facade，而不是复刻终端实现。
- 右侧结果浏览需要树、富文本、卡片、表格、百科条目和可调整布局，React 生态更合适。

推荐架构：

```text
React + TypeScript + Vite
        |
        | REST + SSE
        v
FastAPI Web Backend
        |
        v
WorkflowFacade / CommandRouter / Presenters
        |
        v
read pipeline / close-read / Creative KB / Writer workflow
```

Web 端的主交互不是 slash command。网页上的按钮、列表点击、菜单项、wizard submit 和决策卡按钮发送 HTTP action；后端把这些 action 映射到与 CLI/TUI 共享的 Agent 接口。`CommandRouter` 继续作为 CLI/TUI 的命令真相，也可作为 Web 高级命令入口的兼容层，但前端主界面不应要求用户输入 `/writer`、`/close-read`、`/task` 等指令。

## 2. Technology Selection

### Backend

选择 FastAPI。

理由：

- 与现有 Python workflow 同进程集成成本低。
- Pydantic 契约天然适合把内部 artifact 转成 Web view model。
- 自动 OpenAPI 文档利于前后端同步。
- 支持 SSE，适合 Agent 进度、日志和 Reviewer 摘要从后端推到浏览器。

后端运行：

- 开发：`uvicorn novel_agent.app.web.main:app --reload`
- 产品本地模式：Python 启动后自动打开浏览器。
- 未来可作为本地服务或远程服务部署。

长任务策略：

- 首版：应用内 `JobManager` 管理 asyncio task、取消标记、事件缓冲和持久化事件日志。
- SSE endpoint 读取 job event log，支持断线后按 event id 续读。
- FastAPI `BackgroundTasks` 只用于短任务；read / close-read / Writer 这类长任务必须由 `JobManager` 管理。
- 后续多用户 / 多进程部署时，`JobManager` 可迁移到 Redis + RQ / Celery。

### Frontend

选择 Vite + React + TypeScript。

理由：

- 不需要 SSR，Vite 的开发反馈最快。
- React 生态适合三栏工作台、树、富文本、命令面板和复杂表单。
- TypeScript 可对齐后端 OpenAPI 生成的类型。

推荐库：

- TanStack Query：server state、轮询 fallback、mutation、cache invalidation。
- TanStack Router：需要 URL 表达 task/artifact/job 时启用；首版也可以单路由。
- shadcn/ui：按钮、命令面板、dialog、sheet、tabs、resizable panels、toast。
- MUI X Tree View：右侧目录树；后续若需要完全统一视觉，可封装 adapter 或替换为自研 tree。
- react-markdown / markdown renderer：artifact 正文展示。
- Monaco 或 CodeMirror：仅用于技术详情 JSON，不作为默认内容视图。

## 3. Frontend Layout

### Overall Layout

```text
┌──────────────────────────────────────────────────────────────────────┐
│ TopBar: Novel Agent · 当前任务 · 全局命令 · 运行状态 · 设置           │
├───────────────┬──────────────────────────────────────┬───────────────┤
│ TaskRail      │ ConversationPane                     │ ResultExplorer │
│               │                                      │               │
│ 任务列表       │ 用户 / Agent 对话                     │ Close-read tab │
│ 进度条         │ 进度事件                              │ Writer tab     │
│ 阻塞点 badge   │ 决策卡片                              │ Tree + Detail  │
│ 快捷动作       │ 输入框                                │               │
└───────────────┴──────────────────────────────────────┴───────────────┘
```

默认比例：

- 左侧 260px。
- 中间 minmax 420px，占主要空间。
- 右侧 420px。

面板可拖拽调整。窄屏时：

- 左侧变为 drawer。
- 右侧变为 bottom sheet 或 tab。
- 中间会话保持优先。

### TaskRail

组件：

- `TaskList`
- `TaskProgressCard`
- `TaskActionMenu`
- `CreateTaskDialog`
- `DeleteTaskPreviewDialog`

展示：

- 当前任务高亮。
- 每个任务使用 compact progress：粗读、精读、KB、Writer 四段。
- 阻塞任务显示 badge，例如“待审阅”“待验收”“建模缺失”。

交互：

- 顶部“创建任务”按钮打开 `CreateTaskDialog`；提交后 `POST /api/tasks`。
- 点击任务列表里的 task id / task card 即选择任务；前端更新 route / selected task，并请求 `/api/tasks/{task_id}/status`、messages 和 artifact tree。
- task card 菜单提供“开始粗读”“运行精读”“构建 Creative KB”“开始续写”“重置精读”“删除任务”。
- 删除任务必须先显示预览 dialog，再执行确认删除。

### ConversationPane

组件：

- `MessageList`
- `AgentProgressEvent`
- `DecisionCard`
- `WriterQuestionCard`
- `WriterAnswerContext`
- `WriterReviewComposer`
- `CommandInput`
- `CommandPalette`

行为：

- 用户输入 natural language 时，作为 `ConversationMessage(role=user)` 写入。
- 常用流程不要求用户输入 slash command；Writer / close-read / task 切换等由按钮、菜单和左侧列表完成。
- 用户明确输入 `/` 或从高级命令面板执行命令时，才通过 `/api/tasks/{task_id}/commands` 发送。
- 按钮、菜单、wizard 和决策卡通过 `/api/tasks/{task_id}/actions` 或具体 REST endpoint 发送。
- Agent 进度通过 `/api/jobs/{job_id}/events` SSE 追加。
- 当后端返回 `DecisionCard`，输入框上方展示结构化按钮。
- 当 Writer 进入需要用户补充信息的状态时，问题以 Agent 消息中的 `WriterQuestionCard` 展示；用户仍使用同一个聊天输入框回答，但该回答必须绑定 question set，而不是普通无语义聊天。
- `WriterAnswerContext` 负责在输入框附近提示当前回答目标、允许取消回答上下文，并在用户点击“提交回答并继续研究”时通过 action 发送结构化 payload。

命令面板：

- 默认展示“可执行动作”，例如“开始粗读”“运行精读”“构建知识库”“开始续写”“查看帮助”。
- 高级区才展示对应 slash command。
- 不可用动作置灰，并展示原因。

### ResultExplorer

组件：

- `ResultTabs`
- `ArtifactTree`
- `ArtifactDetail`
- `PersonEntryView`
- `ChapterSummaryView`
- `WriterArtifactView`
- `TechnicalDetailsDrawer`

右侧不是文件浏览器，而是“用户理解用内容浏览器”。树节点可以映射到文件、数据库查询结果、组合 view model 或 workflow review state。

## 4. Right-Side Information Model

### Artifact Tree

`ArtifactTreeNode`：

```json
{
  "id": "character:shen-qing",
  "label": "沈青",
  "kind": "person",
  "surface": "close-read",
  "badge": "最近更新",
  "children": [],
  "has_lazy_children": false
}
```

节点类型：

- `overview`
- `chapter`
- `person`
- `person_section`
- `world_item`
- `outline`
- `source_arc`
- `writer_run`
- `writer_stage`
- `writer_artifact`
- `draft`
- `writeback`

### Artifact Detail

`ArtifactView`：

```json
{
  "artifact_id": "writer:run-1:batch-plan",
  "title": "本批剧情大纲",
  "kind": "writer_batch_plan",
  "sections": [
    {"title": "阶段目标", "body": "推进旧案线索到新地点。"},
    {"title": "主要冲突", "body": "主角组与反派压力位正面碰撞。"}
  ],
  "cards": [],
  "tables": [],
  "markdown": "",
  "technical_available": true
}
```

普通模式只展示 `sections`、`cards`、`tables`、`markdown`。技术详情需要用户显式打开。

### Person Encyclopedia

人物条目采用百科式展示：

```text
沈青
身份：……
当前目标：……
关系网络：
  - 顾迟：有限合作，信任未建立
性格与说话方式：……
秘密与限制：……
最近变化：
  - 第 12 章：……
禁止误写：
  - 不要突然告白
```

树结构：

```text
人物百科
  主角
    沈青
      基本信息
      关系网络
      最近变化
      禁止误写
  配角
  反派
  未归类
```

## 5. Backend Module Design

建议新增：

```text
novel_agent/app/web/
  __init__.py
  main.py
  deps.py
  schemas.py
  routes/
    tasks.py
    messages.py
    jobs.py
    artifacts.py
    commands.py
  services/
    web_session_service.py
    job_manager.py
    artifact_tree_service.py
    artifact_view_service.py
    conversation_service.py
```

### WebSessionService

职责：

- 为每个 task 构造 `TuiApp` / `WorkflowFacade`。
- 调用共享 action adapter；必要时兼容调用 `CommandRouter`。
- 把 action / command 结果转成 `ConversationMessage`。
- 把 `StatusPresenter` 输出转成 `TaskProgress`。

### WebActionService

职责：

- 定义 Web action 到共享 Agent 接口的映射。
- 处理按钮 payload、wizard payload 和决策卡 payload。
- 复用 `WorkflowFacade`、`StatusPresenter`、`ArtifactPresenter`、`DecisionPanel`。
- 保持与 CLI/TUI command id 的语义一致，但不要求 Web 前端发送 slash command 字符串。

示例 action：

```json
{
  "action": "start_close_read",
  "payload": {
    "batches": 3,
    "document_kb": 20
  }
}
```

Writer 审阅相关 action 必须继续复用 Writer workflow / facade。Web 层只做结构化参数适配，不直接拼 Writer prompt、不直接写 workflow state、不直接修改 Memory。首批必须覆盖：

| Web action | 用户入口 | payload 关键字段 | 共享层调用 / 语义 |
|---|---|---|---|
| `submit_outline_research_answers` | 大纲研究问题卡“提交回答并继续研究” | `run_id`, `question_set_id`, 可选 `source_message_id`, `answer_text`, 可选 `user_answers[]` | `WorkflowFacade.writer_action(..., action="continue_after_outline_research_input")` |
| `defer_outline_research_answers` | 大纲研究问题卡“稍后继续” | `run_id`, `question_set_id`, 可选备注 | 保留等待态，不推进 workflow |
| `approve_writer_artifact` | artifact review 消息“通过并继续” | `run_id`, `review_id`, `artifact_kind`, 可选 `artifact_id`, `supplement_text`, `source_message_id` | `ArtifactReviewDecision.decision = approved` |
| `request_writer_artifact_revision` | artifact review 消息“不通过并调整” | `run_id`, `review_id`, `artifact_kind`, 可选 `artifact_id`, `revision_feedback`, `source_message_id` | `ArtifactReviewDecision.decision = revision_requested` |
| `defer_writer_artifact_review` | artifact review 消息“稍后继续” | `run_id`, `review_id`, 可选备注 | `ArtifactReviewDecision.decision = deferred` |
| `accept_chapter` | 章节验收卡“接受本章” | `run_id`, `chapter_id`, `draft_id`, 可选 `feedback_text` | `GenerationReviewDecision.status = accepted` |
| `rewrite_chapter` | 章节验收卡“基于反馈重写” | `run_id`, `chapter_id`, `draft_id`, `feedback_text`, 可选 `reason_code` | `GenerationReviewDecision.status = rewrite_requested` |
| `replan_chapter` | 章节验收卡“修改章节梗概后重写” | `run_id`, `chapter_id`, `draft_id`, `feedback_text`, 可选 `reason_code` | `GenerationReviewDecision.status = replan_requested` |
| `discard_chapter` | 章节验收卡“作废本次草稿” | `run_id`, `chapter_id`, `draft_id`, `reason` 或 `feedback_text` | `GenerationReviewDecision.status = discarded` |
| `defer_chapter_acceptance` | 章节验收卡“稍后再决定” | `run_id`, `chapter_id`, `draft_id`, 可选备注 | 不写正式 `GenerationReviewDecision`，保留待验收 review gate |

用户可见响应必须使用 `StatusPresenter` / `WriterStatusPresenter` 的中文状态。`target_stage`、checkpoint id、workflow action 名、原始 `GenerationReviewDecision` JSON 等只能放进 technical/debug 响应。

### JobManager

职责：

- 创建 job id。
- 启动 asyncio task。
- 记录 job status。
- 接收 `RunEventStream` 事件。
- 支持 cancel flag。
- 持久化 job events 到 `runs/web_jobs/<job_id>/events.jsonl`。
- SSE 读取并推送事件。

### ArtifactTreeService

职责：

- 读取数据库、memory 文件和 Writer runs。
- 构造 close-read / Writer 树。
- 隐藏原始文件结构中用户不需要理解的细节。
- 支持 lazy loading。

### ArtifactViewService

职责：

- 把不同 artifact 转成用户可读 view model。
- 人物档案转百科条目。
- 章节摘要转剧情卡片。
- Writer artifact 转审阅卡片。
- 正文草稿转 markdown + 字数 / 连续性摘要。
- 技术详情单独提供。

## 6. API Design

### Task API

- `GET /api/tasks`
  - 返回 `TaskSummary[]`。
- `POST /api/tasks`
  - 创建任务并记录 source path。
- `GET /api/tasks/{task_id}/status`
  - 返回 `TaskProgress`。
- `DELETE /api/tasks/{task_id}`
  - 默认 dry-run，带 `confirm=true` 才删除本地建模产物。

### Message API

- `GET /api/tasks/{task_id}/messages`
  - 返回会话消息。
- `POST /api/tasks/{task_id}/messages`
  - 写入自然语言输入；可触发 Writer intent draft。
- `POST /api/tasks/{task_id}/actions`
  - 执行 Web 主交互 action，例如按钮、菜单、wizard submit、决策卡确认。
- `POST /api/tasks/{task_id}/commands`
  - 兼容高级 slash command；不得作为 Web 主路径。

### Action API

`POST /api/tasks/{task_id}/actions` 使用统一 envelope：

```json
{
  "action": "request_writer_artifact_revision",
  "payload": {
    "artifact_id": "writer:run-1:batch-plan",
    "review_id": "artifact-review-run-1-002",
    "revision_feedback": "把本批中段冲突提前，但不要提前揭示幕后人。"
  }
}
```

Action API 返回：

- `WebActionResult`
- 可选 `JobSummary`，用于长任务或 LLM 修订。
- 可选 `DecisionCard[]`，用于下一步确认、修订、章节验收或写回确认。
- 可选 `ArtifactView` / artifact id，供前端刷新右侧结果。
- 可选 `technical_details`，仅供 debug drawer 展示。

Artifact Review 的 action 语义：

- `approve_writer_artifact` 写入 `ArtifactReviewDecision.approved`；`supplement_text` 必须原文保留，并作为下一轮 Writer 模型 prompt 输入之一。
- `request_writer_artifact_revision` 写入 `ArtifactReviewDecision.revision_requested`；`revision_feedback` 必须原文保留，Writer workflow 负责 prompt 组装、schema 校验、引用完整性校验、回滚传播和新版 artifact 落盘。
- `defer_writer_artifact_review` 只记录稍后继续，不推进 workflow。
- 修订完成后仍回到同一个 artifact review gate；Web 只刷新会话消息和右侧 artifact view，不自动确认继续。
- 校验失败返回用户可读错误和恢复建议，不返回 traceback。
- 普通 view 不返回 revised raw JSON；raw JSON 只可通过 technical endpoint 查看。

Outline Research 用户补充问题的 action 语义：

- 后端把 `needs_user_input` 转成聊天流中的 Agent 消息，消息携带 `WriterQuestionSet` view model。
- `WriterQuestionSet` 至少包含 `run_id`、`question_set_id`、`stage`、`questions[]`、可选 `source_artifact_id` / `artifact_path` 和可执行 action。
- 每个 question 必须有稳定 `question_id`、用户可读问题、是否必答、可选补充说明或关联缺口；前端不得从纯文本中猜测问题编号。
- 用户可以在同一个聊天输入框里自然语言回答；该消息写入会话时必须附带 `channel = writer_question_answer`、`run_id` 和 `question_set_id`。
- 点击“提交回答并继续研究”时，前端发送 `submit_outline_research_answers`，payload 携带 `answer_text` 和可选结构化 `user_answers[]`；后端负责把回答映射到 Writer 的 `continue_after_outline_research_input`。
- 若用户只提交一段自然语言 `answer_text`，后端必须保留原文并进行最小映射；不得为了推进流程伪造未回答问题。
- 普通聊天消息不得自动越过 `needs_user_input` 等待态；继续流程必须来自问题卡按钮或等价结构化 action。

章节验收 action 语义：

- `accept_chapter` 是唯一允许进入写回摘要审阅或正式写回候选的分支。
- `rewrite_chapter` 基于当前已通过的章节 brief、写作输入和用户反馈重写本章；不得触发正式写回。
- `replan_chapter` 以用户反馈驱动 Writer 修订 `ChapterPackage` / `ChapterBrief`，并回到章节梗概 review gate；不得触发正式写回。
- `discard_chapter` 只保留运行产物，不进入 Memory / KB。
- `defer_chapter_acceptance` 不写正式验收 decision，保持当前待验收状态。

### Job API

- `POST /api/tasks/{task_id}/jobs`
  - body：`{ "type": "read|close_read|kb|writer|benchmark", "payload": {} }`
  - 返回 `JobSummary`。
- `GET /api/jobs/{job_id}/events`
  - SSE。
- `POST /api/jobs/{job_id}/cancel`
  - 设置 cancel flag。

### Artifact API

- `GET /api/tasks/{task_id}/artifact-tree?surface=close-read`
- `GET /api/tasks/{task_id}/artifact-tree?surface=writer`
- `GET /api/artifacts/{artifact_id}/view`
- `GET /api/artifacts/{artifact_id}/technical`
- `POST /api/artifacts/{artifact_id}/save`
- `POST /api/artifacts/{artifact_id}/revision-request`
- `POST /api/artifacts/{artifact_id}/revision-apply`

`revision-request` / `revision-apply` 可以作为 `/actions` 的资源型别名存在，但前端主路径 SHOULD 使用 `/api/tasks/{task_id}/actions`，以便所有按钮、决策卡和 wizard 都走同一套 action adapter 与会话消息记录。

## 7. State Management

前端状态分三类：

- Server state：tasks、status、messages、artifact tree、artifact view、job summary。
  - TanStack Query 管理。
- Stream state：SSE 事件。
  - 每个 active job 一个 EventSource；事件写入 Query cache 或 local append buffer。
- UI state：选中的 task、选中的 tree node、面板宽度、打开的 dialog、命令面板搜索词。
  - React state 或 Zustand；首版可不引入全局 store，除非跨组件状态明显增多。

## 8. User Flows

### Flow A: 导入并建模

1. 用户点击左侧“创建任务”按钮，填写 task id 和 source path。
2. 用户点击新任务 card，选择当前任务。
3. 用户点击 task action “开始粗读”。
4. 后端创建 read job。
5. 中间会话显示进度事件。
6. 左侧任务进度更新。
7. 右侧 Close-read 树出现章节摘要。
8. 用户继续点击“运行精读”或“构建 Creative KB”。

### Flow B: 查看人物百科

1. 用户选择任务。
2. 右侧打开 `Close-read` tab。
3. 展开 `人物百科 -> 主角 -> 沈青`。
4. 详情区展示百科条目。
5. 用户可以点击关系网络中的人物跳转到对应条目。

### Flow C0: Writer 大纲研究提问

1. 用户提交 Writer intent 后，后端启动 Outline Research Loop。
2. 当 Writer 判断 `needs_user_input`，后端返回一条 Agent 消息，消息内展示大纲研究问题卡。
3. 用户在同一个聊天输入框中回答问题；输入框处于当前 question set 的回答上下文。
4. 用户点击消息内“提交回答并继续研究”按钮。
5. 前端发送 `submit_outline_research_answers`，payload 携带 `run_id`、`question_set_id`、回答原文和可选逐题结构化回答。
6. 后端将回答记录为 `user_authorized` evidence，调用共享 Writer workflow 继续 research 或生成大纲。
7. 若用户点击“稍后继续”，后端只保留当前等待态和问题消息，不推进 workflow。

### Flow C: Writer 审阅

1. 用户在中间输入续写方向。
2. 用户点击“开始续写”按钮，打开 Writer intent wizard；系统把自然语言预填入对应字段。
3. 用户提交 wizard，后端调用共享 Writer 接口生成全书续写规划。
4. 右侧 Writer 树选中“全书续写规划”。
5. 中间出现“接受并继续 / 按我的反馈修改 / 手动编辑 / 稍后继续”决策卡。
6. 用户选择“通过并继续”时，可在同一个聊天输入框或卡片输入 `supplement_text`；前端发送 `approve_writer_artifact`。
7. 用户选择“不通过并调整”时，必须输入 `revision_feedback`；前端发送 `request_writer_artifact_revision`。
8. 后端将决策交给 Writer workflow；修订完成后右侧刷新新版 artifact，中间回到同一 review gate。
9. 用户选择“稍后继续”时，只保留当前 review gate 和会话消息。

### Flow D: 章节验收

1. 右侧展示正文草稿、字数、连续性摘要。
2. 中间决策卡展示：
   - 接受本章。
   - 基于反馈重写本章。
   - 修改章节梗概后重写。
   - 作废本次草稿。
   - 稍后再决定。
3. 用户选择“接受本章”时，前端发送 `accept_chapter`；Assist 模式后续展示写回确认卡。
4. 用户选择“基于反馈重写本章”时，前端发送 `rewrite_chapter`，payload 携带反馈原文；后端基于当前已通过 brief 和写作输入重写正文。
5. 用户选择“修改章节梗概后重写”时，前端发送 `replan_chapter`，payload 携带反馈原文；后端回到章节梗概 review gate。
6. 用户选择“作废本次草稿”时，前端发送 `discard_chapter`，后端只保留 runs 产物并暂停流程。
7. 用户选择“稍后再决定”时，前端发送 `defer_chapter_acceptance` 或只关闭决策卡；后端不得写正式验收 decision。
8. 用户选择后，Web 只提交用户决策语义，不暴露内部 workflow action 或 stage。

## 9. Testing Strategy

### Backend

- FastAPI route tests with `TestClient` / `httpx.AsyncClient`。
- `ArtifactTreeService` snapshot tests。
- `ArtifactViewService` tests：
  - 人物百科不泄露 JSON。
  - Writer artifact 摘要覆盖规划、批次、章节、写作指导、正文和写回。
- `WebActionService` tests：
  - `approve_writer_artifact` 保留 `supplement_text` 原文，并调用共享 Writer workflow。
  - `request_writer_artifact_revision` 保留 `revision_feedback` 原文，并回到同一 review gate。
  - `submit_outline_research_answers` 调用共享 Writer workflow 的用户补充入口，并保留 `answer_text` 原文。
  - 普通聊天消息不会自动绕过 Outline Research 的 `needs_user_input` 等待态。
  - `accept_chapter` / `rewrite_chapter` / `replan_chapter` / `discard_chapter` / `defer_chapter_acceptance` 映射到正确 contract。
  - 普通 action 响应不泄露内部 stage；technical response 可以包含 raw contract。
- `JobManager` tests：
  - job 状态变化。
  - SSE event 格式。
  - cancel flag。
  - event replay。

### Frontend

- Vitest + React Testing Library：
  - TaskRail progress rendering。
  - 创建任务按钮打开 dialog，提交后调用 `POST /api/tasks`。
  - 点击 task id / task card 后切换 selected task。
  - task action menu 调用 `/api/tasks/{task_id}/actions`，不生成 slash command 字符串。
  - ConversationPane message / decision card。
  - WriterQuestionCard 作为聊天消息渲染问题，使用同一个输入框收集回答，并通过按钮提交结构化 action。
  - ResultExplorer tree selection。
  - PersonEntryView encyclopedia layout。
- MSW mock API：
  - tasks。
  - artifact tree。
  - artifact view。
  - commands。
- Playwright：
  - 三栏布局宽屏。
  - 窄屏 drawer / sheet。
  - 点击“创建任务” -> 点击 task card -> 点击“开始粗读” -> SSE 进度 -> 右侧 artifact 更新。
  - 点击“开始续写”按钮打开 Writer wizard，而不是输入 `/writer`。
  - 右侧详细内容不出现裸 JSON braces。

### Contract Tests

- 后端生成 OpenAPI。
- 前端类型由 OpenAPI 生成。
- CI 检查生成类型是否过期。

## 10. Migration Plan

1. 保留 TUI 作为正式 CLI。
2. 停止扩展 PySide GUI；删除本轮 GUI parity 新代码。
3. 新增 `web-interface` spec / design。
4. 新增 FastAPI skeleton。
5. 新增 React/Vite frontend skeleton。
6. 先实现只读 Web：
   - task list。
   - status。
   - messages。
   - close-read / Writer artifact tree。
   - artifact detail render。
7. 再实现可操作 Web：
   - commands。
   - jobs。
   - SSE。
   - Writer decisions。
   - artifact feedback / save。

## 11. Open Questions

- Web 首版是否只支持本地单用户，还是预留多用户 workspace？
- artifact view model 是否应持久化缓存，还是每次按需生成？
- 是否需要在 Web 中提供正文编辑器，还是首版只提供反馈式修改？
- 右侧目录树是否使用 MUI X Tree View，还是为了视觉一致性自研 headless tree？
