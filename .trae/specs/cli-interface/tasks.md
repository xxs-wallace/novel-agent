# Tasks

## Reading Rules

- 产品级流程、入口类型与用户可见状态文案，以 [`../spec.md`](../spec.md) 为准。
- CLI / TUI 信息架构、命令面板、状态侧栏、artifact 审阅和 read / Writer 合并入口，以 [`design.md`](design.md) 为准。
- Writer 内部状态含义与确认点，以 [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md) 的 `Writer 用户可见状态词典` 为准。
- read pipeline 的业务实现仍以现有 segmentation / close-read runner 为准；本任务只做统一入口与交互层，不重写粗读/精读业务逻辑。

## Status Legend

- `待新增`：当前设计已明确，但尚未正式实现。
- `部分实现`：当前已有 `run_interactive.py` 或 GUI 旧外壳能力，但仍需重构为统一 CLI / TUI。
- `已实现`：当前仓库代码已具备主要能力，只需保留或补文档。

## Group A: 统一入口与交互骨架

- [x] Task 1: 建立统一 CLI / TUI 用户入口（待新增）
  - `来源`: [`design.md`](design.md) 的 `单一入口与模式切换`
  - `建议只读`: [`../spec.md`](../spec.md), [`design.md`](design.md)
  - `建议只关注代码文件`: `novel_agent/app/run_interactive.py`, `novel_agent/app/gui/writer_cli.py`
  - [x] 定义唯一正式用户入口，进入后再选择粗读、精读、KB、Writer 或恢复流程
  - [x] 保留 Python 冒烟测试脚本作为测试入口，但不得把旧 one-shot CLI 作为正式用户入口
  - [x] 将当前 `pipeline` 与 `writer` 的启动选择收敛到同一个会话模型
  - [x] 支持“继续上次会话 / 导入原文 / 运行精读 / 查看建模状态 / 开始续写 / 恢复 Writer”首屏动作
  - [x] 明确旧 `run_interactive.py` 的过渡策略：先作为 facade 入口，逐步把交互逻辑迁移到 TUI 层

- [x] Task 2: 定义 CLI 交互层架构与共享 facade（待新增）
  - `来源`: [`design.md`](design.md) 的 `技术架构建议`
  - `建议只读`: [`design.md`](design.md), [`../novel-continuation-mvp/spec.md`](../novel-continuation-mvp/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/run_interactive.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/runner/segmentation_runner.py`, `novel_agent/app/runner/close_read_runner.py`
  - [x] 新增或规划 `TuiApp`，负责布局、焦点、输入区、消息流和状态侧栏
  - [x] 新增或规划 `CommandRouter`，统一处理 slash command、命令面板动作和快捷键
  - [x] 新增或规划 `WorkflowFacade`，统一调用 segmentation、close-read、Creative KB 和 Writer orchestration
  - [x] 新增或规划 `RunEventStream`，把后台运行进度转为 UI event，避免直接刷 stdout
  - [x] 确保 CLI 层不直接拼 Writer prompt、不直接修改 Memory 规则、不绕过 orchestration 写运行状态

- [x] Task 3: 建立用户可见状态翻译层 `StatusPresenter`（待新增）
  - `来源`: [`../spec.md`](../spec.md) 的 `User-Facing Status Vocabulary` 与 [`design.md`](design.md) 的 `状态侧栏`
  - `建议只读`: [`../spec.md`](../spec.md), [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/run_interactive.py`, `novel_agent/app/gui/main.py`, `novel_agent/app/gui/writer_cli.py`
  - [x] 将内部状态统一映射为中文用户文案
  - [x] 覆盖 read pipeline 状态：粗读、精读、暂停、失败、完成
  - [x] 覆盖 Writer 状态：`freeze_a_review`、`batch_review`、`freeze_d_review`、`wait_chapter_acceptance`、`writeback_review` 等
  - [x] 将内部 stage、run id、checkpoint id、artifact path 放入技术详情，不作为主状态
  - [x] 增加单元测试，禁止主界面输出 `artifact saved`、`Freeze B pending`、`freeze_d_review`、`wait_chapter_acceptance`

## Group B: TUI 基础体验

- [x] Task 4: 实现中文友好的输入区（待新增）
  - `来源`: [`design.md`](design.md) 的 `输入区设计`
  - `建议只读`: [`design.md`](design.md)
  - [x] 选型或封装支持中文宽字符、输入法组合态、grapheme / wcwidth 感知的输入组件
  - [x] 支持中文、英文、标点混排时的光标移动、退格删除和行内编辑
  - [x] 支持多行输入、历史记录、长文本粘贴
  - [x] 支持常见编辑键：`Ctrl+A/E/B/F/K/U/W`
  - [x] 增加中文回退、混排编辑、多行粘贴的最小交互测试或组件级测试

- [x] Task 5: 实现输出与输入分离的消息流（待新增）
  - `来源`: [`design.md`](design.md) 的 `消息流与运行输出`
  - `建议只读`: [`design.md`](design.md)
  - [x] 将模型输出、runner 进度、系统提示、错误恢复建议渲染到消息流
  - [x] 保证后台运行时 stdout / progress 不覆盖用户正在编辑的输入区
  - [x] 长输出默认摘要展示，详细日志进入可展开技术详情
  - [x] 为粗读/精读展示章节范围、字数、批次数和错误摘要
  - [x] 为 Writer 正文展示路径、字数、目标字数、开头预览和连续性摘要

- [x] Task 6: 实现三段式布局与状态侧栏（待新增）
  - `来源`: [`design.md`](design.md) 的 `页面结构` 与 `状态侧栏`
  - `建议只读`: [`design.md`](design.md)
  - [x] 主区域显示消息流、运行进度和审阅摘要
  - [x] artifact 区支持摘要视图和编辑视图切换
  - [x] 状态侧栏展示项目、当前流程、当前步骤、建模准备度、重点 artifact、下一步动作
  - [x] 技术详情折叠展示内部 stage、run id、checkpoint id 和 artifact path
  - [x] 窄屏时状态侧栏可折叠为 overlay，底部输入区保持稳定可见

- [x] Task 7: 实现 slash command 与命令面板（待新增）
  - `来源`: [`design.md`](design.md) 的 `命令面板与快捷键`
  - `建议只读`: [`design.md`](design.md)
  - [x] 支持 `/status`、`/read`、`/close-read`、`/kb`、`/writer`、`/resume`
  - [x] 支持 `/artifacts`、`/open`、`/save`、`/confirm`、`/back`、`/help`
  - [x] 命令面板按“当前步骤推荐动作 / read pipeline / Writer / artifact / 配置 / debug”分组
  - [x] 支持 `Ctrl+P` 打开命令面板
  - [x] 支持上下文过滤，只展示当前状态下可执行的动作

## Group C: Artifact 审阅、修改与确认

- [x] Task 8: 实现 `ArtifactPresenter` 与结构化摘要（待新增）
  - `来源`: [`design.md`](design.md) 的 `Artifact 审阅与原地修改`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - [x] 为 JSON / Markdown artifact 生成结构化摘要
  - [x] 高亮标题、目标、冲突、关系推进、禁止项、待确认问题、文件路径和下一步动作
  - [x] 对大体量正文、检索上下文、大型 JSON 默认折叠
  - [x] 支持从摘要跳转到编辑视图或外部打开文件
  - [x] 增加 artifact 摘要快照测试，覆盖 BatchPlan、ChapterPackage、ChapterLengthPlan、draft 预览

- [x] Task 9: 实现原地编辑、保存与校验（待新增）
  - `来源`: [`design.md`](design.md) 的 `Artifact 审阅与原地修改`
  - `建议只读`: [`design.md`](design.md), [`../spec.md`](../spec.md)
  - [x] 支持在 CLI 中编辑关键 JSON / Markdown artifact
  - [x] 保存前做 JSON 语法校验和必要 schema 校验
  - [x] 保存后提示“已保存你的修改”，但不推进流程
  - [x] 确认前明确展示“下一步会发生什么”
  - [x] 确保后续 orchestration 读取用户保存后的 artifact，而不是旧内存对象

- [x] Task 10: 实现阻塞决策面板（待新增）
  - `来源`: [`design.md`](design.md) 的 `阻塞决策面板`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md)
  - [x] 当系统等待用户确认时，底部输入区切换为结构化决策面板
  - [x] 每个选项显示后续状态，例如接受本章进入“请确认写回”
  - [x] 支持章节验收：接受本章、调整字数后重写、修改章节梗概后重写、作废草稿、稍后决定
  - [x] 支持规划审阅：保存、确认、返回上一层、稍后继续
  - [x] 决策写入对应 artifact 或调用对应 workflow action

## Group D: Read Pipeline 与 Writer 合并入口

- [x] Task 11: 将粗读 / 分段 pipeline 接入统一 CLI（待新增）
  - `来源`: [`design.md`](design.md) 的 `Read Pipeline 交互设计`
  - `建议只读`: [`design.md`](design.md), [`../novel-continuation-mvp/spec.md`](../novel-continuation-mvp/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/runner/segmentation_runner.py`, `novel_agent/app/run_interactive.py`
  - [x] 支持选择原文路径并启动粗读 / 分段
  - [x] 展示已读取 KB、documents 数、章节范围、checkpoint 位置
  - [x] 支持暂停与恢复
  - [x] 失败时展示普通用户可执行的恢复建议
  - [x] 粗读完成后提示进入精读或查看建模状态

- [x] Task 12: 将精读 / 记忆抽取 pipeline 接入统一 CLI（待新增）
  - `来源`: [`design.md`](design.md) 的 `精读 / 记忆抽取`
  - `建议只读`: [`design.md`](design.md), [`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/runner/close_read_runner.py`, `novel_agent/app/run_interactive.py`
  - [x] 支持从粗读 checkpoint 后继续精读
  - [x] 展示当前处理章节范围、batch 数、章节摘要数量、人物档案更新数量、世界观/大纲更新摘要
  - [x] 展示粗读与精读之间的进度差
  - [x] 精读完成或达到本轮预算后，提示查看建模状态、构建 Creative KB、开始续写或继续精读
  - [x] 失败时展示可恢复步骤和相关 artifact 路径

- [x] Task 13: 将 Creative KB 构建与状态接入统一 CLI（待新增）
  - `来源`: [`design.md`](design.md) 的 `单一入口与模式切换`
  - `建议只读`: [`design.md`](design.md), [`../creative-knowledge-base/spec.md`](../creative-knowledge-base/spec.md)
  - [x] 支持从命令面板或 read 完成提示中构建 Creative KB
  - [x] 展示 fragment cards、clusters、representatives 的构建数量
  - [x] 展示 KB 是否足以支持 Writer 开始续写
  - [x] 构建失败时展示失败 doc 数、错误摘要和可重试动作

- [x] Task 14: 将 Writer 分层生成接入统一 CLI（待新增）
  - `来源`: [`design.md`](design.md) 的 `Writer 交互设计入口`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/run_interactive.py`, `novel_agent/app/gui/writer_cli.py`
  - [x] 从统一 CLI 的建模状态面板进入 Writer
  - [x] Writer 自动消费已完成的粗读、精读和 KB 产物
  - [x] 支持开始新 Writer run 与恢复未完成 Writer run
  - [x] 支持所有 Writer 人工确认点的 artifact 审阅、编辑、保存、确认
  - [x] 不在主界面显示 `Freeze B pending`、`freeze_d_review`、`wait_chapter_acceptance` 等内部文案

## Group E: 测试与验收

- [x] Task 15: CLI 单元与组件测试（待新增）
  - `建议只读`: [`design.md`](design.md)
  - [x] 覆盖状态翻译：内部状态不得直接出现在用户主界面
  - [x] 覆盖中文输入删除、混排编辑、多行粘贴
  - [x] 覆盖 artifact 摘要、高亮、保存、校验失败
  - [x] 覆盖命令面板上下文过滤
  - [x] 覆盖阻塞决策面板选项与后续状态说明

- [x] Task 16: CLI 集成验收测试（待新增）
  - `建议只读`: [`../spec.md`](../spec.md), [`design.md`](design.md)
  - [x] 覆盖同一 CLI 会话中 `粗读 -> 精读 -> 建模状态 -> Writer` 的最小路径
  - [x] 覆盖 `Writer batch_review -> 保存修改 -> 确认 -> chapter_review` 路径
  - [x] 覆盖 `wait_chapter_acceptance -> revise_length -> wait_length_review` 路径
  - [x] 覆盖 `wait_chapter_acceptance -> replan_chapter -> wait_chapter_review` 路径
  - [x] 覆盖运行中暂停和恢复
  - [x] 覆盖窄屏布局下输入区不被输出覆盖

## Group F: Textual 正式入口与全屏 UI

- [x] Task 17: 建立 Textual 正式入口与运行边界（待新增）
  - `来源`: [`design.md`](design.md) 的 `单一入口与模式切换`, `技术架构建议`, `Textual 实现里程碑`
  - `建议只读`: [`../spec.md`](../spec.md), [`design.md`](design.md)
  - `建议只关注代码文件`: `pyproject.toml`, `cli/novel_agent.py`, `novel_agent/app/cli_tui.py`
  - [x] `novel-agent` 项目脚本启动 Textual 全屏 TUI
  - [x] `python -m novel_agent.app.cli_tui` 作为开发调试等价入口
  - [x] 明确 `run_interactive.py` 仅保留为 smoke / 兼容 / 对比调试入口，不作为 Textual CLI 必须复用的代码底座
  - [x] Textual 入口启动失败时给出可执行安装建议，而不是 traceback
  - [x] 增加入口测试，覆盖项目脚本、Textual 依赖和入口模块导入

- [x] Task 18: 拆分 Textual App、Screen 与 Widget 模块（待新增）
  - `来源`: [`design.md`](design.md) 的 `页面结构`, `技术架构建议`
  - `建议只读`: [`design.md`](design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli_tui.py`, `novel_agent/app/cli/`
  - [x] 将单文件 Textual 骨架拆为 `TextualNovelAgentApp`
  - [x] 新增 `HomeScreen`
  - [x] 新增 `WorkbenchScreen`
  - [x] 新增 `StatusSidebar`
  - [x] 新增 `MessageFlow`
  - [x] 新增 `PromptInput`
  - [x] 新增 `ArtifactReviewPane`
  - [x] 新增 `ArtifactEditorPane`
  - [x] 新增 `DecisionPanelWidget`
  - [x] 所有 Widget 只负责展示、输入、焦点和调用 facade，不直接推进业务状态

- [x] Task 19: 实现 prompt-first HomeScreen（待新增）
  - `来源`: [`design.md`](design.md) 的 `单一入口与模式切换`
  - `建议只读`: [`design.md`](design.md)
  - [x] 首页默认聚焦输入框，而不是命令说明墙
  - [x] 首屏动作分行展示：继续上次会话、导入/粗读原文、运行精读建模、查看建模状态、构建 Creative KB、开始或恢复 Writer
  - [x] 支持数字键、上下键、Enter 选择动作
  - [x] 支持直接输入自然语言续写方向并进入 Writer 准备流程
  - [x] 支持 `/` 打开 slash command autocomplete
  - [x] 支持 `Ctrl+P` 打开命令面板
  - [x] 不再出现所有选项挤在一行的 `_prompt_choice()` 体验

- [x] Task 20: 实现 WorkbenchScreen 三段式布局（待新增）
  - `来源`: [`design.md`](design.md) 的 `页面结构`, `状态侧栏`
  - `建议只读`: [`design.md`](design.md)
  - [x] 主区域显示消息流、运行进度和审阅摘要
  - [x] 中部或下方显示当前 artifact 摘要 / 编辑区
  - [x] 右侧状态栏显示项目、流程、当前步骤、建模准备度、当前 artifact、下一步动作
  - [x] 底部固定输入区 / 决策面板 / 快捷操作
  - [x] 宽屏时状态侧栏常驻
  - [x] 窄屏时状态侧栏作为 overlay 打开，不挤压输入区
  - [x] 输入区在消息流新增内容时不位移、不被覆盖

- [x] Task 21: 实现 Textual 主题与状态视觉层级（待新增）
  - `来源`: [`design.md`](design.md) 的 `页面结构`, `消息流与运行输出`
  - `建议只读`: [`design.md`](design.md)
  - [x] 定义基础 Textual CSS token：背景、panel、输入区、边框、选中态、错误、警告、成功
  - [x] 用左边框区分用户输入、系统进度、工具摘要、artifact 审阅、错误恢复建议
  - [x] 长输出默认折叠，展开区域与主消息流有清晰层级
  - [x] 运行中状态有轻量 spinner 或进度提示
  - [x] 视觉样式保持终端原生、低装饰、高反馈

## Group G: Textual 输入、命令与交互组件

- [x] Task 22: 实现 Textual 中文友好 PromptInput（待新增）
  - `来源`: [`design.md`](design.md) 的 `输入区设计`
  - `建议只读`: [`design.md`](design.md)
  - [x] 正式输入区使用 Textual 组件，不调用 `_prompt_text()` / `input()`
  - [x] 支持中文宽字符、中英文混排、输入法组合态
  - [x] 支持多行输入，默认 1 行，最多 6 行，超出内部滚动
  - [x] 支持历史记录、长文本粘贴和常见编辑键 `Ctrl+A/E/B/F/K/U/W`
  - [x] 支持 metadata 行展示当前流程、当前步骤和快捷键
  - [x] 支持运行状态行展示后台任务、暂停提示和输出隔离说明
  - [x] 增加 Textual 组件测试覆盖中文删除、混排光标、多行粘贴

- [x] Task 23: 实现 slash command autocomplete（待新增）
  - `来源`: [`design.md`](design.md) 的 `命令面板与快捷键`
  - `建议只读`: [`design.md`](design.md)
  - [x] 输入 `/` 时在输入框上方展示 autocomplete
  - [x] 命令列表来自 `CommandRouter`，UI 不复制命令定义
  - [x] 支持 `/status`、`/read`、`/close-read`、`/kb`、`/writer`、`/resume`
  - [x] 支持 `/artifacts`、`/open`、`/save`、`/confirm`、`/back`、`/help`
  - [x] 支持上下键选择、Enter 执行、Esc 关闭
  - [x] 根据当前上下文隐藏或置灰不可执行命令，并显示原因

- [x] Task 24: 实现 CommandPalette overlay（待新增）
  - `来源`: [`design.md`](design.md) 的 `命令面板与快捷键`
  - `建议只读`: [`design.md`](design.md)
  - [x] `Ctrl+P` 打开居中 overlay 命令面板
  - [x] 面板包含搜索框、分类列表和 footer 快捷键提示
  - [x] 命令按“当前步骤推荐动作 / read pipeline / Writer / artifact / 配置 / debug”分组
  - [x] 搜索支持拼音/中文关键字的基本模糊匹配
  - [x] 当前上下文不可用命令置灰或隐藏
  - [x] 支持 Enter 执行、Esc 关闭、Tab / Shift+Tab 焦点切换

- [x] Task 25: 实现 `@` 文件与 artifact 引用入口（待新增）
  - `来源`: [`design.md`](design.md) 的 `输入区设计`
  - `建议只读`: [`design.md`](design.md)
  - [x] 输入 `@` 时展示当前会话 artifact、最近 runs 文件、项目内关键文件候选
  - [x] 支持选择 artifact 插入虚拟 token，例如 `[Artifact: batch_plan.json]`
  - [x] 长路径不直接塞满输入框，提交时再解析为真实路径
  - [x] 支持打开所选 artifact 的摘要或编辑视图
  - [x] 为后续 MCP resource 引用预留接口

- [x] Task 26: 实现全局快捷键与焦点管理（待新增）
  - `来源`: [`design.md`](design.md) 的 `命令面板与快捷键`, `页面结构`
  - `建议只读`: [`design.md`](design.md)
  - [x] `Tab` / `Shift+Tab` 在输入区、消息流、artifact 区、状态侧栏之间切换
  - [x] `Ctrl+S` 保存当前 artifact 编辑内容
  - [x] `Ctrl+Enter` 确认当前审阅步骤
  - [x] `Ctrl+O` 打开当前重点 artifact
  - [x] `Ctrl+D` 展开 / 收起技术详情
  - [x] `Ctrl+L` 切换运行日志显示
  - [x] `Esc` 关闭弹层；运行中进入暂停二次确认
  - [x] 快捷键不得破坏输入区常见编辑习惯

## Group H: Textual 后台任务、Artifact 与流程接入

- [x] Task 27: 将 read pipeline 接入 Textual worker（待新增）
  - `来源`: [`design.md`](design.md) 的 `消息流与运行输出`, `Read Pipeline 交互设计`
  - `建议只读`: [`design.md`](design.md), [`../novel-continuation-mvp/spec.md`](../novel-continuation-mvp/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/runner/segmentation_runner.py`, `novel_agent/app/runner/close_read_runner.py`, `novel_agent/app/cli/`
  - [x] 粗读 / 精读在 Textual worker 或 task 中运行
  - [x] runner `progress_callback` 转为 `RunEvent` 进入消息流
  - [x] stdout / stderr 被捕获为折叠日志事件，不直接写终端
  - [x] 展示章节范围、字数、batch 数、documents 数、checkpoint 位置
  - [x] 支持运行中暂停请求和从 checkpoint 恢复
  - [x] 失败时显示普通用户可执行的恢复建议

- [x] Task 28: 将 Creative KB 接入 Textual worker（待新增）
  - `来源`: [`design.md`](design.md) 的 `单一入口与模式切换`, `消息流与运行输出`
  - `建议只读`: [`design.md`](design.md), [`../creative-knowledge-base/spec.md`](../creative-knowledge-base/spec.md)
  - [x] 从 HomeScreen、CommandPalette、read 完成提示中启动 KB 构建
  - [x] KB 构建在 Textual worker 或 task 中运行
  - [x] 展示 fragment cards、clusters、representatives 的数量
  - [x] 展示 KB 是否足以支持 Writer 开始续写
  - [x] 失败时展示失败 doc 数、错误摘要和可重试动作

- [x] Task 29: 将 Writer workflow 接入 Textual 审阅循环（待新增）
  - `来源`: [`design.md`](design.md) 的 `Writer 交互设计入口`, [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md) 的 `Writer 用户可见状态词典`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/cli/`
  - [x] 支持开始新 Writer run
  - [x] 支持恢复未完成 Writer run
  - [x] Writer 自动消费已完成的粗读、精读和 KB 产物
  - [x] 所有人工确认点进入 Textual artifact 审阅 / 决策面板
  - [x] 保存 artifact 不推进流程；确认才调用 workflow action
  - [x] 主界面不得显示 `Freeze B pending`、`freeze_d_review`、`wait_chapter_acceptance`、`artifact saved`

- [x] Task 30: 实现 ArtifactReviewPane 与 ArtifactEditorPane（待新增）
  - `来源`: [`design.md`](design.md) 的 `Artifact 审阅与原地修改`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - [x] JSON / Markdown artifact 默认展示结构化摘要
  - [x] 大体量正文、检索上下文、大型 JSON 默认折叠
  - [x] 支持摘要视图与编辑视图切换
  - [x] 编辑保存前做 JSON 语法校验和必要 schema 校验
  - [x] 保存成功显示 toast：“已保存你的修改”
  - [x] 保存失败显示行列号、错误原因和恢复操作
  - [x] 保存后的内容作为后续 orchestration 输入

- [x] Task 31: 实现 Textual 阻塞决策面板（待新增）
  - `来源`: [`design.md`](design.md) 的 `阻塞决策面板`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md)
  - [x] 系统等待用户确认时，底部输入区替换为 `DecisionPanelWidget`
  - [x] 规划审阅支持保存、确认、返回上一层、稍后继续
  - [x] 章节验收支持接受本章、调整字数后重写、修改章节梗概后重写、作废草稿、稍后决定
  - [x] 每个选项显示后续状态和将调用的 workflow action
  - [x] 支持数字键、上下键、Enter 选择
  - [x] 决策写入对应 artifact 或调用对应 workflow action

- [x] Task 32: 实现 Toast、错误恢复与技术详情 overlay（待新增）
  - `来源`: [`design.md`](design.md) 的 `错误与恢复`, `消息流与运行输出`, `状态侧栏`
  - `建议只读`: [`design.md`](design.md)
  - [x] 保存成功、复制路径、恢复成功等反馈使用 toast
  - [x] JSON 编辑错误、缺少原文、缺少人物档案、连续性失败显示可行动恢复建议
  - [x] 技术详情 overlay 展示内部 stage、run id、checkpoint id、artifact path、折叠日志
  - [x] 技术详情默认折叠，主界面不暴露内部状态词
  - [x] 错误消息不得覆盖输入区

- [x] Task 33: 建立 Textual 组件与快照测试（待新增）
  - `来源`: [`design.md`](design.md) 的 `Textual 实现里程碑`
  - `建议只读`: [`design.md`](design.md)
  - [x] 使用 Textual pilot / snapshot 测试 HomeScreen 首屏动作分行展示
  - [x] 覆盖 WorkbenchScreen 宽屏布局
  - [x] 覆盖窄屏状态侧栏 overlay，输入区稳定可见
  - [x] 覆盖 slash command autocomplete
  - [x] 覆盖 CommandPalette 上下文过滤
  - [x] 覆盖 ArtifactEditor 保存成功与校验失败
  - [x] 覆盖 DecisionPanelWidget 章节验收选项
  - [x] 覆盖后台 RunEvent 不覆盖输入区

- [x] Task 34: Textual 端到端验收与 run_interactive 对比退场（待新增）
  - `来源`: [`design.md`](design.md) 的 `Textual 实现里程碑`, `技术架构建议`
  - `建议只读`: [`../spec.md`](../spec.md), [`design.md`](design.md)
  - [x] 覆盖同一 Textual 会话中 `粗读 -> 精读 -> 建模状态 -> Writer` 最小路径
  - [x] 覆盖 `Writer batch_review -> 编辑保存 -> 确认 -> chapter_review`
  - [x] 覆盖 `wait_chapter_acceptance -> revise_length -> wait_length_review`
  - [x] 覆盖 `wait_chapter_acceptance -> replan_chapter -> wait_chapter_review`
  - [x] 覆盖运行中暂停和从 checkpoint 恢复
  - [x] 对比 `run_interactive.py` 的同等 smoke 输出，仅用于调试差异
  - [x] 明确哪些旧 `_prompt_*` 交互仍暂时保留，哪些正式路径已迁移到 Textual
  - [x] 更新 README 或开发文档，说明正式启动方式为 `novel-agent`

## Group I: Scoped Artifact Revision

- [x] Task 35: 定义 Scoped Artifact Revision 的 workflow contract 与权限边界（待新增）
  - `来源`: [`design.md`](design.md) 的 `Scoped Artifact Revision`, [`../writer-agent-layered-generation/designs/workflow-state-machine.design.md`](../writer-agent-layered-generation/designs/workflow-state-machine.design.md) 的 `Scoped Artifact Revision`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md), [`../writer-agent-layered-generation/designs/workflow-state-machine.design.md`](../writer-agent-layered-generation/designs/workflow-state-machine.design.md), [`../writer-agent-layered-generation/designs/review-writeback.design.md`](../writer-agent-layered-generation/designs/review-writeback.design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`, `novel_agent/app/cli/facade.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 定义 `ScopedArtifactRevisionRequest`，字段至少包含 `request_id`、`run_id`、`target_stage`、`target_artifact_type`、`target_artifact_path`、`user_feedback`、`scope`、`created_at`
  - [x] 定义 `ScopedArtifactRevisionResult`，字段至少包含 `revision_id`、`request_id`、`status`、`change_summary`、`revised_artifact` 或 `patch`、`validation`、`created_at`
  - [x] 定义 stage 到 artifact 类型、schema、allowed fields、forbidden targets 的白名单映射
  - [x] 实现 scope guard：每次请求只能绑定一个当前审阅中的 target artifact，禁止跨 artifact、Memory、KB、workflow state 修改
  - [x] 明确候选结果第一阶段使用完整 revised artifact；若实现选择 JSON Patch，必须补充同等 schema / scope 校验
  - [x] 所有 request / result 可落盘到当前 run 目录，且能关联原 artifact、用户反馈和后续 diff
  - [x] 增加单元测试，覆盖合法 stage、非法 stage、非当前 artifact、越权 target、缺失反馈、schema 字段缺失

- [x] Task 36: 在 Writer workflow / orchestration 层实现受控修订执行链路（待新增）
  - `来源`: [`../writer-agent-layered-generation/designs/workflow-state-machine.design.md`](../writer-agent-layered-generation/designs/workflow-state-machine.design.md) 的 `Scoped Artifact Revision`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/designs/workflow-state-machine.design.md`](../writer-agent-layered-generation/designs/workflow-state-machine.design.md), [`../writer-agent-layered-generation/designs/review-writeback.design.md`](../writer-agent-layered-generation/designs/review-writeback.design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/runs/writer.py`, `novel_agent/app/cli/facade.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 新增 workflow action，例如 `request_scoped_artifact_revision(...)` 或等价 facade 方法
  - [x] 由 orchestration 层根据 target stage 选择白名单上下文并组装 LLM 输入；CLI 不得传入完整 prompt
  - [x] LLM / revision adapter 只能返回结构化候选结果，不允许直接写文件
  - [x] 对候选结果执行 JSON / schema 校验、scope 校验、引用完整性校验和上游冻结约束校验
  - [x] 生成用户可读 diff 与 `change_summary`，供 CLI / GUI 展示
  - [x] 用户接受候选修改后，只有 orchestration 层可以写回当前 target artifact
  - [x] 写回成功后仍停留在原 review stage，不自动推进到下一个 Freeze
  - [x] 写回成功后按现有 rollback propagation 规则标记下游产物失效
  - [x] 增加行为测试，覆盖 `batch_review`、`chapter_review`、`wait_length_review`、`freeze_d_review` 的受控修订 happy path 与校验失败 path

- [x] Task 37: 在 CLI / Textual 审阅界面接入“按我的反馈修改”（待新增）
  - `来源`: [`design.md`](design.md) 的 `Scoped Artifact Revision` 与 `阻塞决策面板`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/`, `novel_agent/app/cli/facade.py`, `novel_agent/app/run_interactive.py`, `novel_agent/tests/test_cli_interface.py`
  - [x] 规划类审阅点的 `DecisionPanelWidget` 增加“按我的反馈修改”和“手动编辑”两个明确动作
  - [x] 用户选择“按我的反馈修改”后，底部区域切换为自然语言反馈输入框
  - [x] CLI 只把当前 artifact 标识、当前 review state 和用户反馈交给 `WorkflowFacade`
  - [x] CLI 不得直接拼 Writer prompt、不得选择 LLM 上下文、不得写 target artifact
  - [x] 展示 orchestration 返回的候选修改摘要、diff、校验结果和错误恢复建议
  - [x] 用户接受候选修改后调用 facade 的 apply action；保存成功提示“已保存你的修改”，但不推进流程
  - [x] 用户拒绝候选修改后回到原审阅状态，保留 request / result 记录但不写 artifact
  - [x] 增加组件测试，覆盖按钮文案、反馈输入、facade 调用参数、diff 展示、校验失败展示和“不自动确认”

- [x] Task 38: Scoped Artifact Revision 集成测试与安全回归（待新增）
  - `来源`: [`design.md`](design.md) 的 `Scoped Artifact Revision`, [`../writer-agent-layered-generation/designs/workflow-state-machine.design.md`](../writer-agent-layered-generation/designs/workflow-state-machine.design.md), [`../writer-agent-layered-generation/designs/review-writeback.design.md`](../writer-agent-layered-generation/designs/review-writeback.design.md)
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md), [`../writer-agent-layered-generation/designs/workflow-state-machine.design.md`](../writer-agent-layered-generation/designs/workflow-state-machine.design.md), [`../writer-agent-layered-generation/designs/review-writeback.design.md`](../writer-agent-layered-generation/designs/review-writeback.design.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/tests/test_cli_interface.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/cli/`
  - [x] 覆盖 `batch_review -> 按反馈修改 -> diff -> 接受候选 -> 仍停留 batch_review -> confirm -> freeze_b`
  - [x] 覆盖 `chapter_review -> 按反馈修改 -> 下游长度计划和正文失效`
  - [x] 覆盖 `wait_length_review -> 按反馈修改` 只允许改长度预算，不允许改章节目标或关系推进
  - [x] 覆盖 `wait_chapter_acceptance -> replan_chapter -> wait_chapter_review -> Scoped Artifact Revision -> 重新确认`
  - [x] 覆盖越权反馈，例如“顺便修改 Memory / 其他批次 / 系统 prompt”，必须被 scope guard 拒绝或剥离，且不得写文件
  - [x] 覆盖 LLM 返回非法 JSON、缺字段、越权字段、引用不存在时不保存并展示恢复建议
  - [x] 覆盖 CLI 主界面不显示内部 stage 作为主文案，不出现未授权 prompt 细节
  - [x] 覆盖 request / result / diff 可追踪落盘，且未 accepted 草稿不得触发 Memory / KB 写回

## Group J: CLI TUI 冒烟 / 集成测试

- [x] Task 39: 增加当前 CLI TUI 的脚本化集成冒烟测试（已实现）
  - `来源`: [`design.md`](design.md) 的 `单一入口与模式切换`, `Read Pipeline 交互设计`, `消息流与运行输出`
  - `建议只读`: [`design.md`](design.md), [`../agentic-benchmark/design.md`](../agentic-benchmark/design.md), [`../creative-knowledge-base/design.md`](../creative-knowledge-base/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/textual_screens.py`, `novel_agent/app/cli/facade.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] 使用 Textual pilot 驱动真实 TUI 输入区提交命令，而不是直接调用底层业务方法
  - [x] 覆盖 `/new-task <task_id> <source_path>` 创建任务并记录原文路径
  - [x] 覆盖 `/read` 从当前任务原文路径进入粗读 / 入库路径
  - [x] 覆盖 `/close-read --batches N` 从 checkpoint 继续精读，并验证 `run_mode=resume`、`max_read_kb=0`、`build_creative_kb=True`
  - [x] 覆盖 `/query character <name>` 与 `/query summary total`，确认人物档案和剧情梗概能从 CLI 查询
  - [x] 覆盖 `/benchmark longzu-32kb`，确认 Writer benchmark summary 能回到消息流
  - [x] 覆盖 `/creative-kb-benchmark longzu-32kb --writer-ab --dry-run-model`，确认 Creative KB benchmark summary 能回到消息流
  - [x] 使用 fake facade 避免默认测试套件触发真实 LLM 请求
  - [x] 断言用户可见消息不泄漏 `artifact saved` 等内部文案

- [ ] Task 40: 增强 CLI TUI benchmark 失败与恢复建议集成测试（待新增）
  - `来源`: [`design.md`](design.md) 的 `错误与恢复`, `消息流与运行输出`
  - `建议只读`: [`design.md`](design.md), [`../creative-knowledge-base/spec.md`](../creative-knowledge-base/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/textual_screens.py`, `novel_agent/tests/test_cli_textual_components.py`, `novel_agent/tests/test_run_creative_kb_benchmark.py`
  - [ ] 覆盖 `/benchmark` 缺少真实模型授权、未知目标、非法参数时的错误消息和恢复建议
  - [ ] 覆盖 `/creative-kb-benchmark` 未显式选择真实 / dry-run 模型、artifact 写入失败、Reviewer 失败时的错误消息和恢复建议
  - [ ] 覆盖后台 worker 抛异常时，消息流显示可行动建议且输入区仍可继续编辑
  - [ ] 确认失败路径不吞掉用户提交命令，用户命令仍作为聊天记录保留

- [ ] Task 41: 增加可显式开启的真实 LLM CLI TUI 慢速 smoke（待新增）
  - `来源`: [`design.md`](design.md) 的 `Textual 实现里程碑`, [`../agentic-benchmark/design.md`](../agentic-benchmark/design.md)
  - `建议只读`: [`design.md`](design.md), [`../agentic-benchmark/design.md`](../agentic-benchmark/design.md), [`../creative-knowledge-base/design.md`](../creative-knowledge-base/design.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_cli_textual_components.py`, `novel_agent/app/cli/facade.py`
  - [ ] 通过 `pytest` marker 或环境变量显式启用，默认 CI / 本地单元测试不得触发真实 LLM
  - [ ] 使用小型 fixture 或 `longzu-32kb` 路径运行真实 `/benchmark`
  - [ ] 可选运行真实 `/creative-kb-benchmark --writer-ab`
  - [ ] 保存运行产物路径，并在失败时输出 Reviewer summary、artifact_dir 和最近恢复建议
  - [ ] 限制耗时和 case 数，避免 TUI smoke 变成长时间质量回归

- [ ] Task 42: 抽象可复用的 TUI smoke harness（待新增）
  - `来源`: [`design.md`](design.md) 的 `技术架构建议`, `Textual 实现里程碑`
  - `建议只读`: [`design.md`](design.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_cli_textual_components.py`, `novel_agent/app/cli/`
  - [ ] 抽出 `submit_command` / `wait_for_worker` 等测试 helper，减少 Textual pilot 测试重复
  - [ ] 为 fake facade 增加更清晰的 call recorder，区分 `read:new`、`read:resume`、`benchmark`、`creative_kb_benchmark`
  - [ ] 支持在同一个 harness 中断言消息流、输入区、状态侧栏和产物区
  - [ ] 保持 helper 只服务测试，不进入生产代码

## Scoped Artifact Revision Agent Prompts

### Prompt A: Core Contract And Scope Guard Agent

```text
你负责实现 .trae/specs/cli-interface/tasks.md 的 Task 35。

目标：为 Scoped Artifact Revision 建立 workflow contract、权限白名单和 scope guard。请先阅读：
- .trae/specs/cli-interface/design.md 的 Scoped Artifact Revision
- .trae/specs/writer-agent-layered-generation/design.md 的 Writer 用户可见状态词典
- .trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md 的 Scoped Artifact Revision
- .trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md 的 Feedback Routing And Scoped Revision

实现要求：
- 定义 ScopedArtifactRevisionRequest / ScopedArtifactRevisionResult 或等价 Python 类型。
- 定义 review stage 到 target artifact、schema、allowed fields、forbidden targets 的白名单。
- 实现 scope guard，确保一次请求只能作用于当前审阅中的单个 artifact。
- 禁止修改 Memory、KB、workflow state、其他批次、其他章节或系统 prompt。
- request / result 必须可落盘到 runs 目录，并能关联原 artifact 与用户反馈。
- CLI 不参与 prompt 组装，不参与上下文选择，不写 artifact。
- 为合法请求、非法 stage、越权 target、缺失反馈、缺字段结果补单元测试。

请只聚焦 contract、guard、persistence 的内聚实现，不实现 Textual UI。完成后勾选 Task 35，并在最终回复列出修改文件和测试命令。
```

### Prompt B: Workflow Revision Execution Agent

```text
你负责实现 .trae/specs/cli-interface/tasks.md 的 Task 36。

目标：在 Writer workflow / orchestration 层实现 Scoped Artifact Revision 执行链路。请先确认 Task 35 的 contract 和 scope guard 已存在；如果不存在，先补最小兼容实现，但不要实现 UI。

实现要求：
- 新增 workflow action / facade 方法，用于提交用户反馈并生成候选修订。
- orchestration 层根据 target stage 选择白名单上下文并组装 LLM 输入；CLI 不能传完整 prompt。
- revision adapter 只返回结构化候选结果，不能直接写文件。
- 对候选结果执行 schema、scope、引用完整性、上游冻结约束校验。
- 生成 change_summary 和用户可读 diff。
- 只有用户接受候选修改后，orchestration 层才能写回当前 target artifact。
- 写回后仍停留在原 review stage，不自动推进 Freeze。
- 写回后触发现有 rollback propagation 规则，使下游产物失效。
- 覆盖 batch_review、chapter_review、wait_length_review、freeze_d_review 的 happy path 和失败 path。

请只聚焦 Writer workflow / orchestration 与测试，不实现 Textual 控件。完成后勾选 Task 36，并在最终回复列出修改文件和测试命令。
```

### Prompt C: CLI / Textual Interaction Agent

```text
你负责实现 .trae/specs/cli-interface/tasks.md 的 Task 37。

目标：在 CLI / Textual 审阅界面接入“按我的反馈修改”，但保持 CLI 是薄交互层。请先阅读：
- .trae/specs/cli-interface/design.md 的 Artifact 审阅、Scoped Artifact Revision、阻塞决策面板、技术架构建议
- .trae/specs/writer-agent-layered-generation/design.md 的用户可见状态词典

实现要求：
- 在规划类审阅点的 DecisionPanelWidget 中增加“按我的反馈修改”和“手动编辑”。
- 选择“按我的反馈修改”后展示自然语言反馈输入框。
- CLI 只把 current review state、target artifact 标识、user feedback 传给 WorkflowFacade。
- CLI 不得拼 Writer prompt，不得选择 LLM 上下文，不得写 target artifact，不得修改 Memory / KB / workflow state。
- 展示 orchestration 返回的 change_summary、diff、validation errors 和恢复建议。
- 用户接受候选时调用 facade apply action；成功后提示“已保存你的修改”，但仍停留当前审阅状态。
- 用户拒绝候选时回到当前审阅状态，不写 artifact。
- 补组件 / facade 测试，覆盖按钮、输入、参数、diff、校验失败和“不自动确认”。

请只聚焦 CLI / Textual / facade 交互边界，不实现 workflow 内部修订逻辑。完成后勾选 Task 37，并在最终回复列出修改文件和测试命令。
```

### Prompt D: Integration And Safety Test Agent

```text
你负责实现 .trae/specs/cli-interface/tasks.md 的 Task 38。

目标：为 Scoped Artifact Revision 编写集成测试和安全回归测试，验证 Task 35-37 的实现确实符合设计。请先阅读：
- .trae/specs/cli-interface/design.md 的 Scoped Artifact Revision
- .trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md 的 Scoped Artifact Revision
- .trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md 的 Feedback Routing And Scoped Revision
- .trae/specs/cli-interface/tasks.md 的 Task 35-37

测试要求：
- 覆盖 batch_review 按反馈修改、展示 diff、接受候选、仍停留 batch_review、再 confirm 进入 freeze_b。
- 覆盖 chapter_review 修改后下游长度计划 / 正文失效。
- 覆盖 wait_length_review 只能改长度预算，不允许改章节目标、关系推进或世界观设定。
- 覆盖 wait_chapter_acceptance 的 replan_chapter 分支回到 wait_chapter_review 后继续 Scoped Artifact Revision。
- 覆盖越权用户反馈：“修改 Memory / 其他批次 / 系统 prompt / workflow state”，必须不写文件。
- 覆盖 LLM 返回非法 JSON、缺字段、越权字段、引用不存在，必须不保存并展示恢复建议。
- 覆盖 CLI 主界面不暴露内部 stage 或未授权 prompt 细节。
- 覆盖 request / result / diff 落盘可追踪，未 accepted 草稿不得触发 Memory / KB 写回。

请优先使用 fake / stub revision adapter，避免真实 LLM 调用。不要重写产品逻辑；若发现 Task 35-37 有缺口，补最小修复并记录。完成后勾选 Task 38，并在最终回复列出测试文件、覆盖场景和测试命令。
```


- Task 2 depends on Task 1
- Task 3 depends on Task 1, Task 2
- Task 4 depends on Task 2
- Task 5 depends on Task 2
- Task 6 depends on Task 2, Task 3
- Task 7 depends on Task 2, Task 3
- Task 8 depends on Task 3
- Task 9 depends on Task 8
- Task 10 depends on Task 3, Task 8
- Task 11 depends on Task 2, Task 3, Task 5
- Task 12 depends on Task 2, Task 3, Task 5, Task 11
- Task 13 depends on Task 2, Task 3, Task 12
- Task 14 depends on Task 2, Task 3, Task 8, Task 9, Task 10, Task 12
- Task 15 depends on Task 3, Task 4, Task 7, Task 8, Task 9, Task 10
- Task 16 depends on Task 11, Task 12, Task 13, Task 14, Task 15
- Task 17 depends on Task 16
- Task 18 depends on Task 17
- Task 19 depends on Task 18
- Task 20 depends on Task 18
- Task 21 depends on Task 18
- Task 22 depends on Task 18
- Task 23 depends on Task 19, Task 22
- Task 24 depends on Task 18, Task 23
- Task 25 depends on Task 22, Task 30
- Task 26 depends on Task 18, Task 22, Task 24
- Task 27 depends on Task 18, Task 20, Task 22
- Task 28 depends on Task 18, Task 22, Task 27
- Task 29 depends on Task 18, Task 22, Task 28
- Task 30 depends on Task 18, Task 8, Task 9
- Task 31 depends on Task 18, Task 10, Task 29, Task 30
- Task 32 depends on Task 18, Task 21, Task 27, Task 29, Task 30
- Task 33 depends on Task 19, Task 20, Task 22, Task 23, Task 24, Task 30, Task 31
- Task 34 depends on Task 27, Task 28, Task 29, Task 30, Task 31, Task 32, Task 33
- Task 35 depends on Task 29, Task 30, Task 31
- Task 36 depends on Task 35
- Task 37 depends on Task 35, Task 36
- Task 38 depends on Task 35, Task 36, Task 37
- Task 39 depends on Task 27, Task 28, Task 33, Task 34
- Task 40 depends on Task 32, Task 39
- Task 41 depends on Task 39, Task 40
- Task 42 depends on Task 39

## Group K: Writer JSON Contract 与 TUI 表单映射

- [x] Task 43: 实现 Writer 启动意图向导 `WriterIntentWizard`
  - `来源`: [`design.md`](design.md) 的 `JSON Contract 与 TUI ViewModel`、`Writer 输入表单到 JSON 参数的映射`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/textual_widgets.py`, `novel_agent/app/cli/textual_screens.py`, `novel_agent/app/cli/facade.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] `/writer` 不直接用空默认参数启动 Writer，而是先进入字段化启动向导
  - [x] 向导字段覆盖主要角色、续写目标、避免项、期望结果、补充说明、世界观补充、批次数量、生成章节数、新角色开关
  - [x] 将向导 ViewModel 映射为现有 `intent_payload`、`user_world_notes`、`target_chapter_count`、`chapter_count`
  - [x] 自然语言首屏输入可作为续写目标预填
  - [x] 提交向导后调用 `WorkflowFacade.start_writer(...)`，保持 JSON-compatible 参数入口不变
  - [x] 增加 Textual 组件测试，断言 facade 收到结构化参数而不是空 payload

- [ ] Task 44: 实现 Writer artifact 字段化审阅 ViewModel
  - `来源`: [`design.md`](design.md) 的 `审阅表单到 Artifact JSON 的映射`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/artifacts.py`, `novel_agent/app/cli/textual_widgets.py`, `novel_agent/app/cli/textual_screens.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [ ] 为 `book_continuation_plan.json` 提供字段化摘要与编辑模型
  - [ ] 为 `batch_plan.json` 提供字段化摘要与编辑模型
  - [ ] 为 `chapter_package.json` 提供章节表格 / 单章展开编辑模型
  - [ ] 为 `chapter_length_plan.json` 提供默认字数与单章预算编辑模型
  - [ ] 保存时由 ViewModel 回写原 JSON，并复用 schema / scope 校验
  - [ ] 高级 JSON 编辑仍保留，但不得作为唯一可行动路径

- [ ] Task 45: 实现章节验收决策表单到 review contract 的映射
  - `来源`: [`design.md`](design.md) 的 `章节验收到 Contract JSON 的映射`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/decisions.py`, `novel_agent/app/cli/textual_widgets.py`, `novel_agent/app/cli/textual_screens.py`, `novel_agent/app/cli/facade.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [ ] 接受本章时由 TUI 收集可选备注，workflow 补齐 `GenerationReviewDecision`
  - [ ] 调整字数后重写时收集 `target/min/max` 与原因，映射为 `LengthPlanUpdate`
  - [ ] 修改章节梗概后重写时收集必须保留、必须改变、禁止沿用，映射为 `ChapterReplanRequest`
  - [ ] 作废草稿时收集作废原因，映射为 `discarded`
  - [ ] TUI 不要求用户填写 `decision_id`、`draft_id`、`created_at` 等技术字段

- [ ] Task 46: 保留并测试 smoke / 自动化 JSON 输入入口
  - `来源`: [`design.md`](design.md) 的 `JSON Contract 与 TUI ViewModel`
  - `建议只读`: [`design.md`](design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/facade.py`, `novel_agent/app/run_interactive.py`, `novel_agent/tests/test_cli_interface.py`, `novel_agent/tests/test_run_interactive_pipeline.py`
  - [ ] 确认 `WorkflowFacade.start_writer(intent_payload=...)` 仍可被测试直接调用
  - [ ] 确认 `run_writer_guided_flow(intent_payload=...)` 仍可被 smoke 构造固定 JSON 输入
  - [ ] CLI TUI fake facade 可断言结构化参数
  - [ ] 文档和测试都明确 JSON 是系统 / 测试边界，不是正式用户边界

- Task 43 depends on Task 29, Task 33, Task 39
- Task 44 depends on Task 30, Task 37, Task 43
- Task 45 depends on Task 31, Task 43
- Task 46 depends on Task 43
