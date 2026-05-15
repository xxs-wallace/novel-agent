# Web Interface Implementation Prompts

下面只有两条完整 prompt，可直接复制给其他 Agent 执行。不要让执行 Agent 再切换 worktree；当前工作目录就是 `/Users/luliao/agent/smolagents-gui-sync`，分支是 `codex/gui-sync-tui-to-gui`。

---

## Prompt 1: Python FastAPI Backend

你是 Web-Backend-Agent。请在当前 worktree `/Users/luliao/agent/smolagents-gui-sync` 中实现 Novel Agent Web 工作台的 Python 后端，不要切换或新建其他 git worktree。

先阅读这些文件：

- `.trae/specs/web-interface/spec.md`
- `.trae/specs/web-interface/design.md`
- `.trae/specs/cli-interface/design.md`
- `novel_agent/app/cli/facade.py`
- `novel_agent/app/cli/router.py`
- `novel_agent/app/cli/status.py`
- `novel_agent/app/cli/events.py`
- `novel_agent/app/cli/artifacts.py`

核心目标：

实现 FastAPI 后端 skeleton，让 Web 前端可以通过 HTTP action 调用和 CLI/TUI 共享的 Agent 对外接口。Web 主交互是按钮、列表点击、菜单、wizard 和决策卡，不是 slash command。后端可以保留 `/commands` 作为高级 slash command 兼容入口，但 Web 主路径必须是 `/actions` 或具体 REST endpoint。

必须遵守：

- 不要把 `/writer`、`/close-read`、`/task`、`/new-task` 等 CLI 指令作为 Web 主接口。
- Web action payload 传 action id 和结构化参数，例如 `{ "action": "start_writer", "payload": {...} }`。
- 后端 action adapter 必须复用或准备复用 `WorkflowFacade`、`StatusPresenter`、`WriterStatusPresenter`、`ArtifactPresenter`、`RunEventStream` 等共享层。
- 后端不得直接拼 Writer prompt，不得直接修改 Memory 规则，不得绕过 Writer orchestration 写 workflow state。
- 用户可见响应不得泄露 `freeze_d_review`、`wait_chapter_acceptance`、`batch_review`、`writeback_review` 等内部 stage；内部字段只能出现在 technical/debug 响应中。
- 普通 artifact view 不要直接返回 raw JSON；raw JSON 只能从 technical endpoint 获取。
- 遵循 Pythonic / OOP 原则，为新增功能写单元测试。

建议新增模块：

- `novel_agent/app/web/__init__.py`
- `novel_agent/app/web/main.py`
- `novel_agent/app/web/deps.py`
- `novel_agent/app/web/schemas.py`
- `novel_agent/app/web/routes/tasks.py`
- `novel_agent/app/web/routes/messages.py`
- `novel_agent/app/web/routes/actions.py`
- `novel_agent/app/web/routes/jobs.py`
- `novel_agent/app/web/routes/artifacts.py`
- `novel_agent/app/web/services/web_session_service.py`
- `novel_agent/app/web/services/web_action_service.py`
- `novel_agent/app/web/services/job_manager.py`
- `novel_agent/app/web/services/artifact_tree_service.py`
- `novel_agent/app/web/services/artifact_view_service.py`

建议新增测试：

- `novel_agent/tests/test_web_api_contract.py`
- `novel_agent/tests/test_web_job_manager.py`
- `novel_agent/tests/test_web_artifact_views.py`

实现范围：

1. FastAPI app
   - 提供可导入的 `app`。
   - 支持 `python -m novel_agent.app.web.main` 或等价方式启动。
   - 挂载 routers。

2. Pydantic schemas
   - `TaskSummary`
   - `TaskProgress`
   - `ConversationMessage`
   - `WebActionRequest`
   - `WebActionResult`
   - `DecisionCard`
   - `JobSummary`
   - `JobEventView`
   - `ArtifactTreeNode`
   - `ArtifactView`
   - `ArtifactSection`
   - `ArtifactCard`
   - `ArtifactTable`
   - `ApiError`

3. Task / message / action API
   - `GET /api/tasks`
   - `POST /api/tasks`
   - `GET /api/tasks/{task_id}`
   - `DELETE /api/tasks/{task_id}`，默认 dry-run，确认参数才执行删除
   - `POST /api/tasks/{task_id}/reset-close-read`
   - `GET /api/tasks/{task_id}/status`
   - `GET /api/tasks/{task_id}/messages`
   - `POST /api/tasks/{task_id}/messages`
   - `POST /api/tasks/{task_id}/actions`
   - `POST /api/tasks/{task_id}/commands`，仅高级兼容

4. Web actions
   `/actions` 至少支持：
   - `select_task`
   - `create_task`
   - `start_read`
   - `start_close_read`
   - `build_creative_kb`
   - `start_writer`
   - `resume`
   - `confirm_current_step`
   - `go_back`
   - `save_artifact`
   - `show_debug_details`

   可以先对长任务返回 job stub，但接口和测试必须稳定。

5. Job manager + SSE
   - `POST /api/tasks/{task_id}/jobs`
   - `GET /api/jobs/{job_id}`
   - `POST /api/jobs/{job_id}/cancel`
   - `GET /api/jobs/{job_id}/events`
   - `JobManager` 管理 queued / running / succeeded / failed / cancelled。
   - 事件至少包含 `event_id`、`job_id`、`kind`、`message`、`payload`、`created_at`。
   - fake runner 测试必须能 emit 事件并被 SSE/replay 读到。
   - 错误事件要包含恢复建议，不向用户返回 traceback。

6. Artifact tree / view API
   - `GET /api/tasks/{task_id}/artifact-tree?surface=close-read|writer`
   - `GET /api/artifacts/{artifact_id}/view`
   - `GET /api/artifacts/{artifact_id}/technical`
   - Close-read tree 至少包含：总览、章节摘要、人物百科、世界观、故事大纲、源作品篇章地图。
   - Writer tree 至少包含：Run 总览、全书续写规划、本批剧情大纲、章节标题与梗概、章节长度计划、本章写作材料、正文草稿、写回确认。
   - 人物资料要转换成百科式 view：基本信息、当前目标、关系网络、性格与说话方式、已知秘密、禁止误写点、最近变化。
   - Writer artifact 要转换成段落、卡片或表格，不直接展示 JSON。
   - `technical` endpoint 可以返回 raw JSON，但普通 `view` endpoint 不应返回 raw dump。

测试要求：

- 用 FastAPI `TestClient` 或 `httpx.AsyncClient`。
- 覆盖 task 创建、task 选择 action、自然语言 message、action endpoint、commands 兼容 endpoint。
- 断言 `/actions` payload 不需要 slash command 字符串。
- 覆盖用户可见状态不泄露内部 stage。
- 覆盖 fake job event、cancel、failure recovery suggestion、event replay。
- 覆盖 artifact tree 和 artifact view，确保普通 view 不直接展示 raw JSON。

验收命令：

```bash
.venv/bin/python -m pytest \
  novel_agent/tests/test_web_api_contract.py \
  novel_agent/tests/test_web_job_manager.py \
  novel_agent/tests/test_web_artifact_views.py -q
```

若当前 `.venv` 不存在，可使用 `/Users/luliao/agent/smolagents/.venv/bin/python` 并设置 `PYTHONPATH=/Users/luliao/agent/smolagents-gui-sync`。完成后汇报修改文件、测试结果和未完成风险。

---

## Prompt 2: React Web Frontend

你是 Web-Frontend-Agent。请在当前 worktree `/Users/luliao/agent/smolagents-gui-sync` 中实现 Novel Agent Web 工作台前端，不要切换或新建其他 git worktree。

先阅读这些文件：

- `.trae/specs/web-interface/spec.md`
- `.trae/specs/web-interface/design.md`
- 后端 Agent 已实现或正在实现的 `novel_agent/app/web/schemas.py` 与 API routes；如果后端还没完成，就先用 mock API / MSW。

核心目标：

创建 Vite + React + TypeScript 前端，实现三栏工作台：

- 左侧：任务列表与任务进度。
- 中间：使用者与 Agent 的会话框。
- 右侧：close-read 与 Writer 结果浏览器，采用目录树 + 详细内容。

Web 主交互必须是按钮、列表点击、菜单、wizard 和决策卡，不是 slash command。slash command 只能作为高级命令入口或 debug 兼容路径。前端按钮和菜单发送 HTTP action 给后端，不在前端拼业务逻辑。

必须遵守：

- “创建任务”是左侧按钮 + dialog，不要求用户输入 `/new-task`。
- 选择任务是点击左侧 task id / task card，不要求用户输入 `/task`。
- 粗读、精读、Creative KB、Writer、恢复等都通过按钮或 task action menu 触发，不要求用户输入 `/read`、`/close-read`、`/writer`。
- Writer 通过“开始续写”按钮打开 Writer intent wizard。
- 确认、返回、保存、章节验收通过决策卡或编辑器按钮触发。
- 前端 action 请求发送 `{ action, payload }` 到 `/api/tasks/{task_id}/actions` 或具体 endpoint，不发送 slash command 字符串。
- 普通右侧详情不得显示 raw JSON；raw JSON 只能在技术详情 drawer 中显示。
- 主界面不得显示 `freeze_d_review`、`wait_chapter_acceptance`、`batch_review` 等内部 stage。

建议技术：

- Vite + React + TypeScript。
- TanStack Query 管理 server state。
- shadcn/ui / Radix 风格组件。
- 三栏布局用 resizable panels。
- 右侧树可用 MUI X Tree View，或先封装一个可替换的 tree adapter。
- Markdown / rich text viewer 展示正文。
- Vitest + React Testing Library；可用 MSW mock API。

建议新增结构：

- `web/package.json`
- `web/vite.config.ts`
- `web/tsconfig.json`
- `web/src/main.tsx`
- `web/src/App.tsx`
- `web/src/styles.css`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/api/tasks.ts`
- `web/src/api/actions.ts`
- `web/src/api/artifacts.ts`
- `web/src/api/jobs.ts`
- `web/src/components/layout/WorkspaceShell.tsx`
- `web/src/components/tasks/TaskRail.tsx`
- `web/src/components/tasks/CreateTaskDialog.tsx`
- `web/src/components/tasks/TaskActionMenu.tsx`
- `web/src/components/conversation/ConversationPane.tsx`
- `web/src/components/conversation/MessageList.tsx`
- `web/src/components/conversation/DecisionCard.tsx`
- `web/src/components/conversation/WriterIntentWizard.tsx`
- `web/src/components/conversation/ScopedRevisionComposer.tsx`
- `web/src/components/results/ResultExplorer.tsx`
- `web/src/components/results/ArtifactTree.tsx`
- `web/src/components/results/ArtifactDetail.tsx`
- `web/src/components/results/PersonEntryView.tsx`
- `web/src/components/results/WriterArtifactView.tsx`
- `web/src/components/results/TechnicalDetailsDrawer.tsx`
- `web/src/test/*`

实现范围：

1. Workspace shell
   - 三栏布局：TaskRail / ConversationPane / ResultExplorer。
   - 宽屏三栏常驻，窄屏左侧 drawer、右侧 bottom sheet 或 tab。
   - 顶部显示当前任务、运行状态和设置入口。

2. TaskRail
   - 显示 task id / source path / 粗读进度 / 精读进度 / KB 状态 / Writer 状态 / 阻塞点 badge。
   - “创建任务”按钮打开 `CreateTaskDialog`，提交调用 `POST /api/tasks`。
   - 点击 task card 选择任务，加载 status、messages、artifact tree。
   - Task action menu 包含：开始粗读、运行精读、构建 Creative KB、开始续写、重置精读、删除任务。
   - 删除任务先预览确认。

3. ConversationPane
   - 消息列表显示用户、Agent、进度、错误、恢复建议。
   - 输入框默认为自然语言输入，支持多行中文和长文本。
   - 自然语言提交调用 `POST /api/tasks/{task_id}/messages`。
   - 用户明确输入 `/` 时才走高级 commands 兼容。
   - “开始续写”按钮打开 Writer intent wizard，并把最近自然语言目标预填。
   - Wizard 提交调用 `postAction({ action: "start_writer", payload })`。
   - 决策卡支持：接受并继续、按我的反馈修改、手动编辑、返回上一层、稍后继续、接受本章、调整字数后重写、修改章节梗概后重写、作废本次草稿、确认写回续写记忆。
   - 决策按钮提交 action id 和 payload，不提交 slash command。
   - SSE job events 追加为 Agent 进度消息。

4. ResultExplorer
   - `Close-read` / `Writer` tabs。
   - 左侧或上部树支持展开、折叠、选中。
   - 选中节点后调用 artifact view API。
   - Close-read tree 展示：总览、章节摘要、人物百科、世界观、故事大纲、源作品篇章地图。
   - Writer tree 展示：Run 总览、全书续写规划、本批剧情大纲、章节标题与梗概、章节长度计划、本章写作材料、正文草稿、写回确认。
   - 人物资料用百科式 `PersonEntryView` 展示：基本信息、当前目标、关系网络、性格与说话方式、已知秘密、禁止误写点、最近变化。
   - Writer artifact 用 `WriterArtifactView` 展示为段落、卡片、表格或正文 markdown。
   - 技术详情 drawer 默认关闭；只有打开 drawer 才显示 raw JSON。

5. API client
   - 封装 `getTasks`、`createTask`、`selectTask`、`postMessage`、`postAction`、`getArtifactTree`、`getArtifactView`、`streamJobEvents`。
   - 如果后端未完成，先用 mock adapter 或 MSW，保持接口形状与 spec 一致。

测试要求：

- Vitest + React Testing Library。
- 覆盖：
  - 三栏区域渲染。
  - “创建任务”按钮打开 dialog，提交调用 `createTask`。
  - 点击 task card 切换 selected task。
  - task action menu 调用 `postAction()`，payload 是 action id，不是 slash command。
  - 自然语言输入调用 messages endpoint，不调用 commands endpoint。
  - 点击“开始续写”打开 Writer wizard，提交 action=`start_writer`。
  - 决策卡按钮调用 action id。
  - ResultExplorer 点击人物节点展示百科字段。
  - 技术详情 drawer 关闭时 raw JSON 不出现，打开时才出现。

可选 Playwright smoke：

- 点击“创建任务” -> 点击 task card -> 点击“开始粗读” -> mock SSE 进度 -> 右侧 artifact 更新。
- 点击“开始续写”按钮打开 Writer wizard，而不是输入 `/writer`。

验收命令：

```bash
cd web
npm test -- --run
npm run typecheck
```

如果当前环境没有 Node/npm 或依赖安装失败，请不要改无关后端代码；在最终汇报里说明阻塞、已完成文件和建议的安装命令。
