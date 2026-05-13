# CLI Interface Textual Implementation Prompts

本文为 [`tasks.md`](tasks.md) 中新增的 Textual 全屏 CLI 任务生成可交给独立 agent 执行的 prompt。Task 1-16 已作为上一阶段完成；本轮默认从 Task 17 开始，推进到 Task 34。

## Prompt 0: 顺序完成 Textual CLI 全屏化任务

```text
你的角色：Textual-CLI-Implementer。

工作目录：/Users/luliao/agent/smolagents

任务目标：
按顺序完成 .trae/specs/cli-interface/tasks.md 中所有未完成的 Textual 任务。当前应从 Task 17 开始，依赖满足后继续 Task 18、Task 19，一直到 Task 34。不要只做设计说明，要落到代码、测试和任务勾选。

必须先阅读：
1. AGENTS.md
2. .trae/specs/spec.md
3. .trae/specs/cli-interface/design.md
4. .trae/specs/cli-interface/tasks.md
5. .trae/specs/writer-agent-layered-generation/design.md
6. 当前 Textual 骨架：novel_agent/app/cli_tui.py
7. 当前 CLI 交互层：novel_agent/app/cli/

关键背景：
1. Task 1-16 已完成基础 presenter/router/facade/状态翻译/artifact/decision 模型。
2. 本轮目标是把正式用户入口升级为 Textual 全屏 TUI。
3. 正式入口是项目脚本 novel-agent，对应 python -m novel_agent.app.cli_tui。
4. run_interactive.py 后续会逐步废弃。它只作为 smoke / 兼容 / 对比调试入口存在，不要求 Textual CLI 保留或复用它的交互代码。

实现边界：
1. Textual CLI 是正式用户入口，必须同时承载粗读、精读、Creative KB、Writer 和恢复流程。
2. Textual Screen / Widget 只负责展示、输入、焦点、快捷键和调用 facade。
3. read pipeline 的业务逻辑仍由 segmentation / close-read runner 承担；Textual 层只做入口、worker、展示、状态翻译和 artifact 审阅。
4. Writer 的业务推进仍由 writer workflow / execution orchestrator 承担；Textual CLI 不得绕过 orchestration 直接写 workflow 状态。
5. CLI 层不得直接拼 Writer prompt，不得直接修改 Memory 规则。
6. 正式 Textual 路径不得调用 run_interactive.py 中的 _prompt_text()、_prompt_choice()、_prompt_yes_no()、input()。
7. 可以为了对比或调试运行 run_interactive.py smoke，但不要把它作为正式 UI 的底座。
8. 遵守 OOP 原则，Pythonic，实现新能力时补单元测试、组件测试或集成测试。
9. 不要删除用户已有改动，不要做无关重构。

执行顺序：
1. 盘点当前 novel-agent 入口、novel_agent/app/cli_tui.py、novel_agent/app/cli/、run_interactive.py、writer_workflow.py、segmentation_runner.py、close_read_runner.py。
2. 完成 Task 17-18：Textual 正式入口边界、App / Screen / Widget 模块拆分。
3. 完成 Task 19-21：HomeScreen、WorkbenchScreen、Textual CSS / 视觉层级。
4. 完成 Task 22-26：PromptInput、slash autocomplete、CommandPalette、@ artifact 引用、全局快捷键与焦点管理。
5. 完成 Task 27-29：read pipeline、Creative KB、Writer workflow 接入 Textual worker / 审阅循环。
6. 完成 Task 30-32：ArtifactReviewPane / ArtifactEditorPane、DecisionPanelWidget、Toast / 错误恢复 / 技术详情 overlay。
7. 完成 Task 33-34：Textual 组件测试、snapshot / pilot 测试、端到端验收、run_interactive 对比退场文档。
8. 每完成一个任务，更新 .trae/specs/cli-interface/tasks.md 中对应 checkbox。只有实现与测试都满足时才能勾选。

验收标准：
1. 启动 .venv/bin/novel-agent 后进入 Textual 全屏 TUI，而不是 input() 问答。
2. 首页 prompt-first，首屏动作分行展示，不出现所有选项挤在一行的体验。
3. 用户主界面不得出现 artifact saved、Freeze B pending、freeze_d_review、wait_chapter_acceptance 这类内部文案。
4. 输出、后台进度和日志不会覆盖用户正在编辑的输入区。
5. 同一 Textual 会话可以从粗读/精读状态进入 Writer，不需要退出再启动另一个 CLI。
6. 关键 artifact 可摘要展示、编辑、校验、保存；保存后提示“已保存你的修改”，但不会自动推进流程。
7. 阻塞确认点显示用户动作、后续状态和将调用的 workflow action。
8. 后台任务使用 Textual worker / task，stdout / stderr 被捕获为折叠日志事件。
9. 宽屏显示状态侧栏，窄屏通过 overlay 展示，底部输入区保持稳定可见。
10. 新增/修改测试通过。至少运行 Textual 入口、CLI 组件、run_interactive 对比 smoke、writer workflow 相关目标测试；如果无法跑全量测试，说明原因。

建议测试命令：
- .venv/bin/python -m ruff check novel_agent/app/cli_tui.py novel_agent/app/cli cli
- .venv/bin/python -m pytest novel_agent/tests/test_cli_tui_entrypoint.py novel_agent/tests/test_cli_interface.py
- .venv/bin/python -m pytest novel_agent/tests/test_run_interactive_pipeline.py novel_agent/tests/test_writer_execution_workflow.py novel_agent/tests/test_writer_layered_generation_orchestrator.py
- 若新增 Textual pilot / snapshot 测试，请一并运行对应测试文件。

交付要求：
1. 输出修改文件列表。
2. 输出已完成任务编号和未完成/阻塞项。
3. 输出测试命令与结果。
4. 明确说明 run_interactive.py 仍保留在哪些对比/调试场景中。
```

## Prompt 1: Task 17-18 Textual 入口与模块拆分

```text
你的角色：Textual-Entry-Foundation-Agent。

工作目录：/Users/luliao/agent/smolagents

目标：
完成 .trae/specs/cli-interface/tasks.md 的 Task 17、Task 18。

必须先阅读：
- AGENTS.md
- .trae/specs/cli-interface/design.md
- .trae/specs/cli-interface/tasks.md
- novel_agent/app/cli_tui.py
- novel_agent/app/cli/
- pyproject.toml

重点：
1. 确认 novel-agent 项目脚本是正式 Textual 入口。
2. 确认 python -m novel_agent.app.cli_tui 是开发调试等价入口。
3. 明确 run_interactive.py 只作为 smoke / 兼容 / 对比调试入口，不要求 Textual CLI 复用它的交互代码。
4. 将单文件 Textual 骨架拆成清晰模块，例如：
   - TextualNovelAgentApp
   - HomeScreen
   - WorkbenchScreen
   - StatusSidebar
   - MessageFlow
   - PromptInput
   - ArtifactReviewPane
   - ArtifactEditorPane
   - DecisionPanelWidget
5. Widget 只负责展示、输入、焦点和调用 facade，不直接推进业务状态。

边界：
- 不要重写 read / Writer 业务逻辑。
- 不要把 run_interactive.py 的 _prompt_* 逻辑搬进 Textual。
- 可以保留当前 cli_tui.py 作为薄入口，但具体 App/Screen/Widget 应拆到可维护模块。

验收：
- .venv/bin/novel-agent 能启动 Textual app。
- Textual 入口缺依赖时给出安装建议。
- 有入口与模块导入测试。
- ruff / compileall 通过。
- 完成后勾选 Task 17-18。
```

## Prompt 2: Task 19-21 Home / Workbench / 视觉层级

```text
你的角色：Textual-Layout-Agent。

工作目录：/Users/luliao/agent/smolagents

目标：
完成 .trae/specs/cli-interface/tasks.md 的 Task 19、Task 20、Task 21。

必须先阅读：
- .trae/specs/cli-interface/design.md
- .trae/specs/cli-interface/tasks.md
- novel_agent/app/cli/
- Textual App / Screen / Widget 模块

重点：
1. HomeScreen 必须 prompt-first，默认聚焦输入框。
2. 首屏动作必须分行展示：继续上次会话、导入/粗读原文、运行精读建模、查看建模状态、构建 Creative KB、开始或恢复 Writer。
3. 支持数字键、上下键、Enter 选择动作。
4. 支持直接输入自然语言续写方向并进入 Writer 准备流程。
5. WorkbenchScreen 实现三段式布局：消息流、artifact 区、状态侧栏、底部输入/决策面板。
6. 宽屏状态侧栏常驻，窄屏状态侧栏 overlay。
7. 定义基础 Textual CSS token 和左边框视觉层级。

验收：
- 首页不再出现所有选项挤在一行的体验。
- 消息流新增内容时，底部输入区不位移、不被覆盖。
- 状态侧栏显示中文用户状态，不暴露内部状态码。
- 有 Textual pilot / snapshot 或组件测试覆盖宽屏、窄屏、首屏动作。
- 完成后勾选 Task 19-21。
```

## Prompt 3: Task 22-26 输入、命令面板、引用与快捷键

```text
你的角色：Textual-Input-Command-Agent。

工作目录：/Users/luliao/agent/smolagents

目标：
完成 .trae/specs/cli-interface/tasks.md 的 Task 22、Task 23、Task 24、Task 25、Task 26。

必须先阅读：
- .trae/specs/cli-interface/design.md 的 输入区设计、命令面板与快捷键
- novel_agent/app/cli/router.py
- novel_agent/app/cli/input.py
- Textual PromptInput / CommandPalette 相关模块

重点：
1. 正式输入区使用 Textual 组件，不调用 _prompt_text() / input()。
2. 支持中文宽字符、中英文混排、输入法组合态、多行输入、历史记录、长文本粘贴。
3. 支持 metadata 行和运行状态行。
4. `/` 输入时展示 slash command autocomplete，命令真相来自 CommandRouter。
5. `Ctrl+P` 打开 CommandPalette overlay，支持搜索、分类、上下文过滤。
6. `@` 输入时展示 artifact / runs / 关键文件引用候选，并插入虚拟 token。
7. 实现全局快捷键：Tab / Shift+Tab、Ctrl+S、Ctrl+Enter、Ctrl+O、Ctrl+D、Ctrl+L、Esc。

边界：
- 快捷键不得破坏输入区常见编辑习惯。
- UI 层不得复制一份命令定义；必须通过 CommandRouter 获取命令和上下文可用性。

验收：
- 中文输入、混排光标、多行粘贴有测试。
- slash autocomplete 和 CommandPalette 有上下文过滤测试。
- @ artifact 引用不会把长路径直接塞满输入框。
- Ctrl+S / Ctrl+Enter 在正确上下文调用保存或确认动作。
- 完成后勾选 Task 22-26。
```

## Prompt 4: Task 27-29 Read / KB / Writer worker 接入

```text
你的角色：Textual-Workflow-Worker-Agent。

工作目录：/Users/luliao/agent/smolagents

目标：
完成 .trae/specs/cli-interface/tasks.md 的 Task 27、Task 28、Task 29。

必须先阅读：
- .trae/specs/spec.md
- .trae/specs/cli-interface/design.md
- .trae/specs/cli-interface/tasks.md
- .trae/specs/writer-agent-layered-generation/design.md
- novel_agent/app/runner/segmentation_runner.py
- novel_agent/app/runner/close_read_runner.py
- novel_agent/app/services/creative_kb_facade.py
- novel_agent/app/orchestrators/writer_workflow.py
- novel_agent/app/cli/facade.py
- novel_agent/app/cli/events.py

重点：
1. 粗读 / 精读在 Textual worker 或 task 中运行。
2. runner progress_callback 转为 RunEvent，进入 MessageFlow。
3. stdout / stderr 捕获为折叠日志事件，不直接写终端。
4. 展示章节范围、字数、batch 数、documents 数、checkpoint 位置。
5. 支持运行中暂停请求和从 checkpoint 恢复。
6. Creative KB 可从 HomeScreen、CommandPalette、read 完成提示启动。
7. Writer 支持开始新 run、恢复未完成 run，自动消费 read / KB 产物。
8. Writer 所有人工确认点进入 Textual artifact 审阅 / 决策面板。

边界：
- 不要把 segmentation / close-read / KB / Writer 业务逻辑搬到 Textual 层。
- Textual CLI 不得绕过 writer workflow / execution orchestrator 写 workflow 状态。
- 主界面不得显示 Freeze B pending、freeze_d_review、wait_chapter_acceptance、artifact saved。

验收：
- 同一 Textual 会话内可从 read 状态进入 Writer。
- 后台运行时输入区可继续编辑，输出不覆盖输入区。
- 失败时显示普通用户可执行的恢复建议。
- 有 deterministic fake / stub 测试，避免依赖真实模型。
- 完成后勾选 Task 27-29。
```

## Prompt 5: Task 30-32 Artifact、决策、Toast 与错误恢复

```text
你的角色：Textual-Artifact-Decision-Agent。

工作目录：/Users/luliao/agent/smolagents

目标：
完成 .trae/specs/cli-interface/tasks.md 的 Task 30、Task 31、Task 32。

必须先阅读：
- .trae/specs/cli-interface/design.md 的 Artifact 审阅与原地修改、阻塞决策面板、错误与恢复
- .trae/specs/writer-agent-layered-generation/contracts.md
- novel_agent/app/cli/artifacts.py
- novel_agent/app/cli/decisions.py
- novel_agent/app/cli/status.py

重点：
1. 实现 ArtifactReviewPane：JSON / Markdown 默认结构化摘要，大内容默认折叠。
2. 实现 ArtifactEditorPane：摘要视图与编辑视图切换，JSON/schema 校验，保存到原 artifact。
3. 保存成功显示 toast：“已保存你的修改”；保存不推进流程。
4. 保存失败显示行列号、错误原因和恢复操作。
5. 实现 DecisionPanelWidget，阻塞确认时替代底部输入区。
6. 规划审阅支持保存、确认、返回上一层、稍后继续。
7. 章节验收支持接受本章、调整字数后重写、修改章节梗概后重写、作废草稿、稍后决定。
8. 实现 Toast、错误恢复与技术详情 overlay。

验收：
- ArtifactEditor 保存成功与校验失败有测试。
- DecisionPanelWidget 每个选项显示后续状态和 workflow action。
- 技术详情默认折叠，主界面不暴露内部状态词。
- 错误消息和 toast 不覆盖输入区。
- 完成后勾选 Task 30-32。
```

## Prompt 6: Task 33-34 Textual 测试与端到端验收

```text
你的角色：Textual-QA-Agent。

工作目录：/Users/luliao/agent/smolagents

目标：
完成 .trae/specs/cli-interface/tasks.md 的 Task 33、Task 34。

必须先阅读：
- .trae/specs/spec.md
- .trae/specs/cli-interface/design.md
- .trae/specs/cli-interface/tasks.md
- 当前所有 Textual App / Screen / Widget / facade / presenter 代码

重点测试：
1. HomeScreen 首屏动作分行展示。
2. WorkbenchScreen 宽屏布局。
3. 窄屏状态侧栏 overlay，输入区稳定可见。
4. slash command autocomplete。
5. CommandPalette 上下文过滤。
6. ArtifactEditor 保存成功与校验失败。
7. DecisionPanelWidget 章节验收选项。
8. 后台 RunEvent 不覆盖输入区。
9. 同一 Textual 会话中 粗读 -> 精读 -> 建模状态 -> Writer 的最小路径。
10. Writer batch_review -> 编辑保存 -> 确认 -> chapter_review。
11. wait_chapter_acceptance -> revise_length -> wait_length_review。
12. wait_chapter_acceptance -> replan_chapter -> wait_chapter_review。
13. 运行中暂停和从 checkpoint 恢复。

run_interactive 对比退场：
1. run_interactive.py 只用于同等 smoke 输出对比和调试差异。
2. 明确哪些旧 _prompt_* 交互仍暂时保留。
3. 明确哪些正式路径已迁移到 Textual。
4. 更新 README 或开发文档，说明正式启动方式为 novel-agent。

验收：
- 新增 Textual pilot / snapshot / 组件测试稳定通过。
- 端到端测试使用 fake / stub，避免真实模型和外部网络。
- 目标测试通过；如果无法跑全量测试，说明原因。
- 完成后勾选 Task 33-34。
```
