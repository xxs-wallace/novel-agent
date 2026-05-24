# 统一 CLI / TUI 交互设计

## Agent Reading Guide

先读 [`AGENT_CONTEXT.md`](AGENT_CONTEXT.md) 判断是否需要展开本文。CLI/TUI
改动通常不需要通读全文，按变更面选择章节：

- 入口、命令、模式切换：读第 3、6、14 节。
- 状态栏、用户可见文案、运行进度：读第 7、8、13 节，并回查
  [`../spec.md`](../spec.md)。
- Artifact 审阅、字段编辑、Writer review gate 映射：读第 9、10、12 节，
  涉及 JSON 时回查 Writer contracts。
- Textual 组件和实现里程碑：读第 14、15 节。

## 1. 设计结论

CLI 应作为小说续写系统的统一交互工作台，而不是 Writer 或 read pipeline 各自独立启动的命令集合。

本设计建议单独保留为 `.trae/specs/cli-interface/design.md`，不合并进 Writer 的 `design.md`。原因：

- CLI 是跨模块产品入口，必须同时承载粗读、精读、Creative KB、Writer 和运行恢复。
- Writer 的 `design.md` 应聚焦分层生成、冻结点、回写与状态机，不应承担全局界面架构。
- read pipeline 虽然代码上可以独立于 Writer，但用户体验上必须和 Writer 在同一个会话、同一个状态栏、同一套命令体系里切换。
- Web / 历史 GUI 也应复用这套用户可见流程语义，因此 CLI design 应放在核心交互层，而不是某个模块下。

因此文档关系为：

- [`../spec.md`](../spec.md)：产品级 Source of Truth，定义核心流程、入口类型与用户可见状态文案。
- 本文：定义统一 CLI / TUI 的信息架构、交互模式、键盘操作、状态展示和 artifact 审阅设计。
- [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)：只定义 Writer 特有流程和状态含义，并引用本文。

## 2. 借鉴 OpenCode 的核心原则

本系统应借鉴 OpenCode CLI 的产品化 TUI 思路：

- **Prompt-first**：打开 CLI 后首先看到输入入口，而不是命令说明墙。
- **会话式工作台**：运行输出、系统提问、artifact 审阅和用户输入处在同一个会话中。
- **输出与输入分离**：模型流式输出、日志和进度不得插入或覆盖用户正在编辑的输入区。
- **渐进披露**：常用动作直接显示，高级动作通过 `/` 命令、命令面板和详情面板进入。
- **阻塞决策替代输入框**：当系统需要用户确认、选择或授权时，底部输入区切换为结构化决策面板。
- **长内容默认摘要**：大纲、章节正文、大型 JSON、检索上下文默认展示摘要和重点，必要时展开或进入编辑面板。
- **状态文案产品化**：主界面显示“请审阅本批剧情大纲”，而不是 `batch_review`、`Freeze B pending` 或 `artifact saved`。

## 3. 单一入口与模式切换

CLI 应只有一个正式用户入口。这个入口进入统一 TUI 后，用户再选择或输入要做的事。

正式用户入口 SHALL 通过项目脚本启动：

```bash
./novel-agent
```

根目录 `./novel-agent` SHALL 自动创建或复用 `.venv`，安装缺失依赖，并启动 Textual 全屏 TUI。打包安装后的 console script `novel-agent` SHALL 继续指向同一 Textual 入口。`python -m novel_agent.app.run_interactive`、`novel_agent.app.gui.writer_cli` 等旧入口只作为 smoke、兼容测试或迁移脚本保留，不再作为正式用户入口。

推荐首屏能力：

- 选择或创建任务
- 列出所有任务
- 继续上次会话
- 导入/粗读原文
- 运行精读建模
- 查看建模状态
- 开始续写
- 恢复 Writer 流程
- 打开命令面板

推荐 slash command：

| 命令 | 用途 |
|---|---|
| `/status` | 查看当前项目建模、KB、Writer 与运行状态 |
| `/tasks` | 列出所有任务及其粗读、精读进度 |
| `/task <task_id>` | 进入指定任务 |
| `/new-task <task_id> <source_path>` | 创建新任务并记录原文路径 |
| `/reset-close-read` | 清空当前任务的精读进度与精读派生产物，保留粗读 documents |
| `/read` | 进入粗读/分段 pipeline |
| `/close-read` | 进入精读/记忆抽取 pipeline |
| `/kb` | 构建或查看 Creative KB |
| `/benchmark <source_path> --prefix N` | 运行最小续写回归测试：读取前 N 段生成第 N+1 段，并输出 Reviewer 报告 |
| `/writer` | 开始或恢复 Writer 分层生成 |
| `/writer-research` | 查看或继续 Writer 大纲研究循环 |
| `/writer-answer` | 回答大纲研究循环提出的阻塞问题 |
| `/writer-skip-research` | 在允许的产品模式下降级跳过大纲研究，生成低置信草案 |
| `/resume` | 恢复最近一次未完成流程 |
| `/artifacts` | 查看当前会话产物 |
| `/open` | 打开当前重点产物 |
| `/save` | 保存当前编辑内容 |
| `/confirm` | 确认当前审阅步骤 |
| `/back` | 返回上一层可修改节点 |
| `/help` | 查看当前上下文可用操作 |

CLI 不应要求用户退出 read CLI 再启动 writer CLI。正确体验是：

1. 用户在同一会话中完成粗读/精读。
2. 状态栏显示建模准备度。
3. 用户直接输入“开始续写”或执行 `/writer`。
4. Writer 自动消费已经完成的建模与 KB 产物。

首屏不应把所有选项塞进一行 prompt。首屏 SHALL 使用 Textual 的列表、命令面板或 prompt-first 输入区展示可选动作，至少分行显示：

```text
你想做什么？

1  选择或创建任务
2  继续上次会话
3  导入/粗读原文
4  运行精读建模
5  查看建模状态
6  构建 Creative KB
7  运行最小续写回归
8  开始或恢复 Writer
```

任务模型：

- Textual TUI 中的 `task_id` SHALL 对应 read / close-read / KB / Writer 共用的 `book_id`。
- 用户进入 read、close-read、KB 或 Writer 前 SHOULD 先选择已有任务或创建新任务。
- 任务列表 SHALL 展示 task id、原文路径、documents 数、chapters 数、粗读进度、精读进度，以及精读是否已经覆盖当前对象文件。
- 如果用户未选择 task id 就运行 `/read`、`/close-read`、`/kb` 或 `/writer`，界面 SHALL 给出可行动提示：使用 `/tasks` 查看任务，或使用 `/new-task <task_id> <source_path>` 创建任务。

## 4. 页面结构

正式 TUI SHALL 采用 Textual 全屏应用实现三段式布局：

```text
┌──────────────────────────────────────────────────────────────┐
│ 消息流 / 运行进度 / 审阅摘要                                  │
│                                                              │
│  - 系统正在做什么                                             │
│  - 已生成什么                                                 │
│  - 当前需要用户确认什么                                       │
│  - 重点字段高亮                                               │
│                                                              │
├──────────────────────────────────────────────┬───────────────┤
│ 当前 artifact 摘要或编辑区                    │ 状态侧栏       │
│                                              │ 项目健康度     │
│                                              │ 当前步骤       │
│                                              │ 下一步动作     │
├──────────────────────────────────────────────┴───────────────┤
│ 输入区 / 决策面板 / 快捷操作                                  │
└──────────────────────────────────────────────────────────────┘
```

窄屏时：

- 状态侧栏应折叠为 overlay 或通过快捷键打开。
- artifact 编辑区可以切换为全屏编辑视图。
- 底部输入区始终保留，不被日志挤走。

宽屏时：

- 左侧为会话消息流。
- 中间或下方为当前 artifact 审阅编辑区。
- 右侧为项目状态、当前流程、下一步动作、文件路径和技术详情。

Textual Screen / Widget 划分：

- `HomeScreen`：prompt-first 首页，显示输入框、最近会话、首屏动作列表和命令面板入口。
- `WorkbenchScreen`：正式工作台，承载消息流、artifact 审阅/编辑区、状态侧栏和底部输入/决策面板。
- `CommandPalette`：`Ctrl+P` 打开的搜索式命令面板，按上下文过滤命令。
- `ArtifactReviewPane`：artifact 摘要、展开、外部打开入口。
- `ArtifactEditorPane`：JSON / Markdown 原地编辑、校验错误、保存反馈。
- `StatusSidebar`：宽屏常驻，窄屏 overlay。
- `DecisionPanelWidget`：阻塞确认点替代底部输入区。
- `ToastLayer`：非阻塞反馈，例如“已保存你的修改”。

## 5. 输入区设计

输入区必须中文友好：

- 正确处理中文宽字符和中英文混排。
- 正确处理输入法组合态，不在拼音候选阶段误提交。
- 退格删除不得留下半个字符或残影。
- 支持多行输入、历史记录、粘贴长文本。
- 输入区 SHOULD 采用聊天应用式的较大编辑框，常态至少可清晰显示约 6 行内容，避免长续写方向或多行命令上下文挤在一两行里。
- 支持 `Ctrl+A/E/B/F/K/U/W` 等常见行编辑习惯。

实现上不应继续依赖裸 `input()` 作为正式交互输入。正式 TUI SHALL 使用 Textual 输入组件，并明确要求：

- grapheme / wcwidth 感知的光标移动和删除。
- 输入区与输出区分离渲染。
- 模型运行时输入区不可被 stdout 打乱。

正式 TUI 输入区 SHALL 至少包含：

- 多行文本输入，常态显示约 6 行，最多 8-10 行，超过后内部滚动。
- metadata 行，展示当前流程、当前步骤、可用快捷键。
- 运行状态行，展示后台任务、暂停提示和输出隔离说明。
- `/` slash command autocomplete。
- `@` 文件 / artifact 引用 autocomplete（后续可逐步扩展到 MCP resource）。

`run_interactive.py` 中的 `_prompt_text()`、`_prompt_choice()`、`_prompt_yes_no()` 仅允许用于 smoke 和兼容脚本；正式 Textual 路径不得调用这些函数。

提交行为 SHALL 接近聊天应用：

- `Enter` 发送当前输入。
- `Shift+Enter` 保留为换行。
- 提交后输入框必须清空。
- 已提交的自然语言、slash command 和错误命令都应进入消息流，作为用户聊天记录的一部分展示；Textual 屏幕上用户消息应采用右对齐聊天气泡，底层日志仍可保留 `你 · /status` 这种纯文本记录。
- 命令执行结果、错误和恢复建议紧随其后以系统消息展示。

输入区下方应展示当前上下文提示，例如：

```text
Writer · 请审阅本批剧情大纲    Enter 发送 · Shift+Enter 换行 · Ctrl+S 保存 · Ctrl+P 命令面板
```

当系统正在运行长任务时，底部提示切换为：

```text
正在精读第 12-14 章 · 可按 Esc 请求暂停 · 输出不会覆盖输入
```

## 6. 命令面板与快捷键

CLI 应支持 `/` inline 命令，也应支持命令面板。

推荐快捷键：

| 快捷键 | 行为 |
|---|---|
| `Enter` | 发送当前输入，并把输入写入消息流 |
| `Shift+Enter` | 在输入框内换行 |
| `Ctrl+P` | 打开命令面板 |
| `Ctrl+S` | 保存当前 artifact 编辑内容 |
| `Ctrl+Enter` | 确认当前审阅步骤 |
| `Esc` | 关闭弹层；运行中二次确认暂停 |
| `Tab` / `Shift+Tab` | 在编辑区、消息流、状态侧栏之间切换 |
| `Ctrl+O` | 打开当前重点 artifact |
| `Ctrl+D` | 展开/收起技术详情 |
| `Ctrl+L` | 切换运行日志显示 |

命令面板按上下文分组：

- 当前步骤推荐动作
- read pipeline 动作
- Writer 动作
- artifact 动作
- 项目与配置动作
- debug / 技术详情动作

Textual 实现要求：

- `/` 输入时在输入框上方展示 inline autocomplete。
- `Ctrl+P` 打开居中 overlay 命令面板，包含搜索框、分类列表和 footer 快捷键提示。
- 命令面板选项由 `CommandRouter` 提供，UI 层不得复制一份命令真相。
- 当前状态不可执行的命令应隐藏或置灰，并说明原因。
- 用户提交未知或当前不可用的 slash command 时，消息流 SHALL 先保留用户输入，再显示“错误”消息和一条可行动“建议”，例如提示输入 `/help` 或按 `Ctrl+P` 打开命令面板。

## 7. 状态侧栏

状态侧栏展示普通用户能理解的信息，不展示内部状态名作为主文案。

推荐字段：

- 当前项目 / book id
- 当前任务 / task id
- 当前流程：粗读、精读、知识库、Writer
- 当前步骤：例如“请确认章节长度”
- 建模准备度：原文、精读记忆、人物档案、世界观、故事大纲、桥段 KB
- 当前重点 artifact：文件名、保存状态、校验状态
- 下一步动作：例如“确认后将生成章节标题与梗概”
- 技术详情折叠区：内部 stage、run id、artifact path、checkpoint id

示例：

```text
当前流程  Writer 分层生成
当前步骤  请审阅本批剧情大纲
下一步    确认后生成章节标题与梗概
文件      batch_plan.json
状态      有未保存修改
```

## 8. 消息流与运行输出

消息流负责承载系统反馈，但不应变成原始日志倾倒区。

消息类型：

- 用户输入
- 用户提交的 slash command
- 系统进度
- 模型运行摘要
- 工具调用摘要
- artifact 生成提示
- 审阅请求
- 错误与恢复建议

消息流 SHOULD 呈现为对话记录。用户已发送的内容不应残留在底部输入框里，而应转为消息流中的右对齐用户消息；系统响应、命令错误和恢复建议作为后续左侧消息追加。

长输出处理：

- 粗读/精读进度只显示章节范围、字数、批次数、错误摘要。
- Writer 正文只显示路径、字数、目标字数、开头预览和连续性检查摘要。
- JSON artifact 只显示关键字段和“打开编辑”入口。
- 详细日志放入可展开区域或技术详情。

后台任务与 stdout 隔离：

- segmentation、close-read、Creative KB、Writer 均 SHALL 在 Textual worker / task 中运行。
- runner 的 `progress_callback` SHALL 转为 `RunEvent`，进入消息流。
- 旧代码中的 stdout / stderr SHALL 被捕获，转为折叠日志事件，不得直接写终端。
- 运行中用户仍可编辑底部输入；输出不得插入输入区。
- 运行中 `Esc` SHALL 进入暂停确认，而不是直接杀进程或丢失状态。

## 9. Artifact 审阅与原地修改

CLI 必须支持关键产物原地审阅、修改、保存和确认。

最小能力：

- JSON / Markdown 结构化预览。
- 高亮关键字段。
- 编辑后保存到原 artifact 文件。
- 保存后显示“已保存你的修改”。
- 保存不等于确认；确认后才推进流程。
- 保存前做 schema / JSON 语法校验。
- 确认前说明“下一步会发生什么”。

### 9.1 Scoped Artifact Revision

CLI 还必须支持 `Scoped Artifact Revision`：用户不直接编辑 JSON / Markdown，而是选择“按我的反馈修改”，用自然语言说明希望当前产物如何调整。该能力只作用于当前审阅中的 artifact，不是自由聊天，也不是跨文件编辑入口。

交互形态：

```text
请审阅本批剧情大纲

[1] 接受并继续
[2] 按我的反馈修改
[3] 手动编辑
[4] 返回上一层
[5] 稍后继续
```

用户选择“按我的反馈修改”后，底部区域切换为自然语言反馈输入框：

```text
你希望怎么修改这份大纲？

例如：保留当前主线，但把反派登场提前到第二章；
降低男女主关系升温速度；第三章结尾增加悬疑钩子。
```

CLI 职责：

- 收集用户自然语言反馈。
- 把当前 artifact 标识、当前 review state 和用户反馈交给 `WorkflowFacade`。
- 展示 orchestration 返回的候选修改摘要、diff、校验结果和错误恢复建议。
- 在用户接受候选修改后调用保存 / 应用 action。
- 保存成功后仍停留在当前审阅状态，直到用户显式确认。

CLI 禁止事项：

- 不得直接拼 Writer prompt。
- 不得决定哪些上下文可以发送给 LLM。
- 不得绕过 Writer workflow / orchestration 写 artifact。
- 不得直接修改 Memory、KB、workflow state 或非当前 target artifact。
- 不得把用户自然语言反馈当作 shell / 文件操作指令解释。

`Scoped Artifact Revision` 的 prompt 组装、权限检查、上下文白名单、LLM 调用、候选产物校验、文件写入和下游失效传播，必须全部由 Writer workflow / orchestration 层完成。CLI / GUI 只是交互外壳。

### 9.2 JSON Contract 与 TUI ViewModel

CLI / TUI 必须同时满足两个目标：

- 面向用户：通过步骤、表单、摘要、按钮和自然语言反馈完成 Writer 操作。
- 面向测试和恢复：继续保留 JSON-compatible 参数、artifact、checkpoint 和 workflow action。

因此 JSON 不应被删除，也不应成为正式用户的主要输入界面。正确边界是：

```text
用户可见 TUI 控件
  - 输入框 / 多选 / 数字 stepper / checkbox / 决策按钮
  - artifact 摘要 / 字段化编辑 / 自然语言反馈
        ↓
TUI ViewModel
  - WriterIntentForm
  - CharacterSeedForm
  - ArtifactReviewViewModel
  - ChapterAcceptanceForm
        ↓
JSON-compatible workflow contract
  - intent_payload
  - user_world_notes
  - GenerationReviewDecision
  - ScopedArtifactRevisionRequest
        ↓
WorkflowFacade / Writer orchestration
```

正式 Textual 路径 SHALL 优先渲染 ViewModel；JSON 编辑器只作为高级入口、调试入口、迁移入口和 smoke 对照入口。用户选择“手动编辑”时，界面必须提示这是高级操作，并展示字段说明或 schema 校验错误。普通路径应优先使用“按我的反馈修改”或字段化编辑。

JSON contract 仍 SHALL 保留用于：

- `python -m novel_agent.app.run_interactive` smoke / 兼容脚本。
- CLI TUI scripted smoke，通过 fake facade 直接断言参数。
- benchmark / CI 中构造固定输入。
- `runs/` 中 workflow checkpoint、artifact、revision request / result 的可追踪落盘。
- 失败恢复和 bug 复现。

### 9.3 Writer 输入表单到 JSON 参数的映射

`/writer` 不应直接要求用户填 JSON，也不应只靠默认空 `intent_payload` 启动正式流程。正式 TUI SHOULD 在启动 Writer 前进入 `WriterIntentWizard` 或等价分步面板。

推荐步骤：

| TUI 步骤 | 控件 | 写入参数 / JSON 字段 | 说明 |
|---|---|---|---|
| 选择任务 | 任务列表 / `/task` | `book_id` | read、close-read、KB、Writer 共用同一个 `book_id`。 |
| 建模检查 | 只读状态卡 + 修复按钮 | `allow_incomplete_modeling` | 默认不鼓励跳过；如果允许低置信规划，必须明确提示风险。 |
| 故事概述 | 多行文本 | `user_story_overview` / `intent_payload.notes` | 用户用自然语言描述想写什么；系统从中抽取人物提及和剧情目标。 |
| 续写目标 | 多行文本 + 拆条确认 | `intent_payload.desired_actions` | 用户描述想推进的剧情动作，系统可拆成多条目标。 |
| 人物提及确认 | 自动抽取 chips + resolved / ambiguous / missing 分组 | `ExtractedCharacterMentions` / `CharacterMentionResolution` | 用户不必手填完整人物名单；只确认歧义人物和是否新增缺失人物。 |
| 避免项 | 列表编辑 | `intent_payload.avoidances` | 明确不要写的剧情、关系、设定或风格。 |
| 期望结果 | 多行文本 | `intent_payload.preferred_outcome` | 本轮结束时希望达到的状态。 |
| 补充说明 | 多行文本 | `intent_payload.notes` | 其它写作偏好、节奏、风格提示。 |
| 世界观补充 | 多行文本 / 条目列表 | `user_world_notes` | 只记录本轮需要的设定补充和边界。 |
| 新角色策略 | toggle + 角色雏形表单 | `intent_payload.allow_character_cast`、后续 `CharacterSeedInput` | 是否允许补计划角色；角色雏形在后续人物补充步骤确认。 |
| 批次数量 | 数字输入 / stepper | `target_chapter_count` | 本批规划覆盖几章。 |
| 生成章节数 | 数字输入 / stepper | `chapter_count` | 本次先生成几章梗概。 |
| 执行模式 | segmented control | `product_mode` | 普通用户默认 Assist。 |

TUI SHALL 提供“从自然语言自动拆字段”能力，并在提交前展示可编辑摘要。例如用户输入“接着写沈青追查旧案，关系慢热，不要立刻告白”，界面应拆成：

```json
{
  "desired_actions": ["追查旧案"],
  "avoidances": ["不要立刻告白"],
  "preferred_outcome": "",
  "notes": "关系慢热",
  "extracted_character_mentions": [
    {
      "text": "沈青",
      "resolution_status": "resolved"
    }
  ]
}
```

这段 JSON 只用于说明映射和 smoke；正式界面展示应是表单摘要，而不是要求用户直接编辑这段 JSON。

### 9.3A Writer 大纲研究循环交互映射

`/writer` 提交启动向导后，正式 TUI SHOULD 进入“大纲研究”阶段，而不是直接跳到全书大纲草案。该阶段由 Writer orchestration 执行，CLI 只展示研究过程和收集用户补充。

推荐用户可见状态：

| 内部对象 / 状态 | 用户文案 | TUI 展示 |
|---|---|---|
| `ExtractedCharacterMentions` | 请确认识别到的人物 | resolved 人物 chips、ambiguous 选择、missing 新增确认 |
| `OutlineSeedPacket` | 已准备大纲研究资料 | 用户意图、规模、高潮、人物索引、世界观概念、历史总览摘要 |
| `need_more_info` | 正在查找更多故事资料 | 本轮 research requests、工具结果摘要、预算剩余 |
| `needs_user_input` | 需要你补充几个关键问题 | 1-3 个阻塞问题的决策 / 文本输入面板 |
| `proceed_with_assumptions` | 可以带明确假设生成草案 | assumptions、remaining risks、继续 / 返回补充 |
| `blocked` | 前置建模不足 | required_actions、跳转精读 / 建模状态 / 稍后继续 |
| `enough` | 大纲研究已足够 | research summary、进入全书规划 |

推荐新增命令：

| 命令 | 用途 |
|---|---|
| `/writer-research` | 打开当前 Writer research 面板，查看 requests、evidence、budget、notebook 摘要 |
| `/writer-answer` | 在 `needs_user_input` 状态下提交用户补充回答 |
| `/writer-skip-research` | 仅在 debug / Auto Novel 降级场景下跳过 research，必须提示低置信风险 |
| `/open research-trace` | 打开 `outline_research_trace.json` 摘要 |
| `/open planning-notebook` | 打开 `planning_notebook.json` 摘要 |

TUI 面板要求：

- `CharacterMentionResolutionPanel`：展示 `resolved / ambiguous / missing` 三类结果。resolved 只读展示；ambiguous 让用户选择既有人物或确认为新人物；missing 询问是否新增人物，并在确认后打开最小人物档案表单。
- `OutlineResearchPanel`：展示每轮 research request、类型、purpose、priority、返回 evidence 摘要和来源数量。默认不展开完整上下文。
- `SufficiencyDecisionPanel`：展示 known_enough、blocking_gaps、optional_gaps、assumptions、remaining_risks 和 required_actions。
- `UserKnowledgeAnswerPanel`：在 `needs_user_input` 时替代底部输入区，要求用户逐条回答阻塞问题。回答保存为 `user_authorized` evidence，由 workflow 处理。

CLI 禁止事项：

- 不得由 Textual 层直接调用 Memory / SQLite 查询。
- 不得由 Textual 层拼 Outline Research prompt。
- 不得把用户回答直接写入正式 Memory；只能传给 Writer workflow 作为 `user_authorized` research evidence。
- 不得把 `proceed_with_assumptions` 的 assumptions 显示成 confirmed facts。

### 9.4 审阅表单到 Artifact JSON 的映射

规划类 artifact 的正式审阅界面 SHOULD 以字段化摘要为主：

| 审阅状态 | Artifact | TUI 展示 / 可编辑字段 | 高级 JSON 字段示例 |
|---|---|---|---|
| 请审阅全书续写规划 | `book_continuation_plan.json` | 续写目标、终局方向、阶段高潮、人物弧线、必须保留、未决问题 | `continuation_goal`、`ending_direction`、`stage_highlights`、`must_preserve` |
| 请审阅本批剧情大纲 | `batch_plan.json` | 本批目标、主要冲突、情绪节奏、收束点、禁止提前消费、待确认问题 | `batch_goal`、`main_conflict`、`emotional_arc`、`must_not_consume` |
| 请审阅章节标题与梗概 | `chapter_package.json` | 章节标题、章节目标、冲突目标、关系推进、必须出现、禁止项 | `chapters[].title`、`chapters[].goal`、`relationship_targets` |
| 请确认章节长度与节奏 | `chapter_length_plan.json` | 默认目标字数、最小/最大字数、重点章、高潮章、单章预算 | `default_target_chars`、`budgets[].target_chars` |
| 请确认本章写作材料 | `chapter_execution_input.json` | 章节 brief、长度预算、事实约束、风格参考、人物门禁、禁止项 | `chapter_brief`、`length_budget`、`fact_constraints`、`writer_rules` |
| 请确认写回续写记忆 | `memory_writeback.json` / `state_delta.json` | 将写入的人物状态、事实变化、关系变化、伏笔变化 | `character_updates`、`world_updates`、`relationship_updates` |

字段化编辑保存时，TUI 应把 ViewModel 转回原 artifact JSON，并调用同一套 schema / scope 校验。保存后只提示“已保存你的修改”，不得自动确认。

当字段化 UI 尚未覆盖某个复杂字段时，界面可以提供：

- 只读摘要。
- “按我的反馈修改”。
- “高级 JSON 编辑”。

但不得把“高级 JSON 编辑”作为唯一可行动路径。

### 9.5 章节草稿决策到 Contract JSON 的映射

章节草稿决策是最容易把用户逼去填 JSON 的环节，必须通过决策面板收集。

| TUI 决策 | 用户输入控件 | Workflow payload / JSON contract | 后续状态 |
|---|---|---|---|
| 接受本章 | 可选备注 | `GenerationReviewDecision(status="accepted", reason_code="approved")` | 请确认写回 |
| 调整字数后重写 | 目标字数、最小/最大字数、原因、保留方向说明 | `GenerationReviewDecision(status="revise_length")` + `LengthPlanUpdate` | 请确认章节长度与节奏 |
| 修改章节梗概后重写 | 不满意原因、必须保留、必须改变、禁止沿用、可选长度建议 | `GenerationReviewDecision(status="replan_chapter")` + `ChapterReplanRequest` | 请调整章节规划后重写 |
| 作废本次草稿 | 作废原因 | `GenerationReviewDecision(status="discarded")` | 流程已暂停 |
| 稍后再决定 | 无 | 不写正式 decision，只保留 checkpoint | 请决定当前章节草稿 |

CLI / TUI 不应要求用户填写 `decision_id`、`draft_id`、`created_at`、`next_action_checkpoint` 等技术字段。这些字段由 workflow / orchestration 层生成或补齐，必要时放入技术详情。

关键 artifact：

| 流程 | Artifact | 审阅重点 |
|---|---|---|
| 粗读 | 分段结果、导入摘要 | 原文顺序、章节识别、读取进度 |
| 精读 | chapter summaries、人物更新、世界观更新 | 摘要是否准确、人物状态是否误判 |
| KB | fragment cards、structure patterns | 桥段标签、代表片段、适用场景 |
| Writer 全书规划 | `book_continuation_plan.json` 等 | 后续方向、世界观补充、新角色需求 |
| Writer 批次规划 | `batch_plan.json` | 本批目标、冲突、节奏、禁止提前消费 |
| Writer 章节梗概 | `chapter_package.json` | 标题、章节目标、关系推进、禁止项 |
| Writer 长度计划 | `chapter_length_plan.json` | 默认字数、重点章节、单章 override |
| Writer 写作输入 | `chapter_execution_input.json` | brief、事实约束、风格参考、人物门禁 |
| Writer 草稿决策 | `draft.md`、`continuity_report.json` | 正文字数、连续性风险、是否接受或重写 |
| Writer 写回 | `state_delta.json`、`memory_writeback.json` | 将写入的事实、人物和关系变化 |

## 10. 阻塞决策面板

当系统需要用户确认时，底部输入区应切换为决策面板，而不是继续接受自由输入。

规划类审阅点应同时提供“按我的反馈修改”和“手动编辑”。前者触发 `Scoped Artifact Revision`，后者打开原地编辑器。两者都不自动推进流程。

示例：Writer 章节草稿决策

```text
请决定当前章节草稿

草稿：draft.md
字数：4,820 / 目标 5,000
连续性：请查看风险提示

[1] 接受本章
[2] 调整字数后重写
[3] 修改章节梗概后重写
[4] 作废本次草稿
[5] 稍后再决定
```

每个选项必须说明后续状态：

- 接受本章：进入“请确认写回”
- 调整字数后重写：返回“请确认章节长度”
- 修改章节梗概后重写：返回“请审阅章节标题与梗概”
- 作废本次草稿：流程暂停
- 稍后再决定：保持当前状态

对于批次大纲、章节梗概、长度计划、写作输入等规划类审阅，推荐选项为：

- 接受并继续：确认当前 artifact，进入下一个冻结点或生成步骤
- 按我的反馈修改：提交自然语言反馈，调用 `Scoped Artifact Revision`
- 手动编辑：打开 artifact 编辑器
- 返回上一层：回到上游可修改节点
- 稍后继续：保持当前状态

示例：Writer 大纲研究需要用户补充

```text
需要你补充几个关键问题

已确认：
- 主角当前关系状态明确
- 旧案线索来源已有可用证据

阻塞问题：
1. “大反派 X”是新增人物，还是已有角色的隐藏身份？
2. 这一批是否允许揭露旧案证据来源？

[1] 逐条回答
[2] 查看研究记录
[3] 带假设继续生成草案
[4] 返回修改故事概述
[5] 稍后继续
```

如果用户选择“带假设继续”，界面必须展示 assumptions 和 remaining risks，并要求二次确认。若缺口属于终局秘密、主要人物身份、世界规则突破、关系跃迁或新增人物是否成立，界面不得提供静默跳过，只能要求用户回答或返回上游修改。

## 11. Read Pipeline 交互设计

read pipeline 必须作为统一 CLI 的一部分。

### 11.1 粗读 / 分段

用户可见目标：把原文可靠导入系统，并建立章节/文档基线。

粗读必须运行在明确的 task id 下。若 task 尚未创建，用户可通过 `/new-task <task_id> <source_path>` 创建；若 task 已存在，可通过 `/task <task_id>` 进入，再执行 `/read`。

用户可见状态：

| 内部概念 | 用户文案 |
|---|---|
| source selected | 已选择原文 |
| segmentation running | 正在粗读并切分原文 |
| documents indexed | 原文已入库 |
| segmentation paused | 粗读已暂停，可稍后继续 |
| segmentation failed | 粗读遇到问题 |

界面应展示：

- 原文路径
- 已读取 KB / 总 KB
- 新增 documents 数
- 识别到的章节范围
- checkpoint 位置
- 下一步建议：继续粗读、进入精读、查看问题

### 11.2 精读 / 记忆抽取

用户可见目标：让系统读懂已导入章节，形成可用于续写的事实记忆。

精读必须基于当前 task id 的 `.indexes/<task_id>.db` 和 `reading_progress` 判断续跑位置。任务列表应帮助用户确认当前对象文件是否已经精读完成，避免误对另一个 book/task 运行 close-read。

用户需要重新做一次精读时，TUI SHALL 提供 `/reset-close-read`。该命令作用于当前 task：

- 保留粗读 documents 与 segmentation 进度。
- 清空 `reading_progress` 中当前 task 的 close-read stage。
- 清空 close-read 派生的章节摘要、人物档案、世界观/大纲/源作品篇章地图文件等，避免重新精读时与旧产物合并污染。
- 执行后提示用户可重新运行 `/close-read`。

用户可见状态：

| 内部概念 | 用户文案 |
|---|---|
| close_reading | 正在精读章节 |
| memory extraction | 正在整理人物、世界观与大纲 |
| summary review ready | 精读摘要需要检查 |
| memory ready | 精读记忆已可用 |
| close_read paused | 精读已暂停，可稍后继续 |

界面应展示：

- 当前处理章节范围
- 已处理 batch 数
- 章节摘要数量
- 人物档案更新数量
- 世界观更新摘要
- 故事大纲更新摘要
- 与粗读之间的进度差

### 11.3 从 read 到 Writer 的衔接

当用户在同一 CLI 中完成粗读/精读后，系统应主动提示：

```text
精读记忆已可用。你现在可以：

[1] 查看建模状态
[2] 构建 Creative KB
[3] 开始续写
[4] 继续精读更多章节
```

如果用户选择“开始续写”，Writer 不应重新要求用户指定另一个入口，而应直接进入建模准备检查。

## 12. Writer 交互设计入口

Writer 的完整流程由 [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md) 定义。

CLI 层只负责三件事：

- 把 Writer 内部状态翻译为用户状态。
- 展示和编辑 Writer artifacts。
- 根据用户选择调用对应 orchestration 动作。

主界面不得显示：

- `Freeze B pending`
- `freeze_d_review`
- `wait_chapter_acceptance`
- `artifact saved`

应显示：

- “请审阅本批剧情大纲”
- “请确认本章写作材料”
- “请决定当前章节草稿”
- “已保存你的修改”

## 13. 错误与恢复

CLI 必须把错误转成用户能行动的恢复建议。

错误提示 SHOULD 使用聊天式消息流反馈，而不是只在输入框附近闪烁或吞掉输入。对于命令错误，推荐形态为：

```text
你 · /wat
错误 · 未知或当前不可用的命令：/wat
建议 · 输入 /help 查看当前可用命令，或按 Ctrl+P 打开命令面板。
```

示例：

| 场景 | 用户文案 | 可选动作 |
|---|---|---|
| 缺少原文 | 还没有导入原文 | 选择原文并开始粗读 |
| 缺少人物档案 | 还没有人物档案，建议先完成精读建模 | 运行精读 / 继续但降低质量 |
| JSON 编辑错误 | 当前文件不是合法 JSON | 回到编辑 / 查看错误位置 |
| Writer 连续性失败 | 草稿没有通过连续性检查 | 查看问题 / 返回章节梗概 / 返回写作材料 |
| 上游 artifact 已变更 | 下游产物需要重新生成 | 确认回滚 / 取消 |

## 14. 技术架构建议

CLI / TUI 层应是薄交互层，不直接实现业务逻辑。

正式 TUI 框架选型为 Textual。Textual 负责全屏渲染、布局、焦点、快捷键、overlay、toast、worker 和响应式宽窄屏切换；业务推进仍由现有 facade / runner / orchestration 层承担。

推荐分层：

- `TextualNovelAgentApp`：Textual `App`，负责启动、全局 keybinding、theme、screen 路由和 worker 生命周期。
- `TuiApp`：UI-agnostic 会话模型，负责布局数据、当前 artifact、状态、消息流和命令上下文。
- `CommandRouter`：解析 slash command、命令面板动作和快捷键。
- `WorkflowFacade`：统一调用 read pipeline、KB、Writer orchestration。
- `StatusPresenter`：把内部状态翻译成用户文案。
- `ArtifactPresenter`：把 JSON / Markdown artifact 转为摘要、编辑模型和校验错误。
- `DecisionPanel`：渲染阻塞确认点。
- `RunEventStream`：把后台运行进度转为 UI event。

入口关系：

- `./novel-agent`：开发者推荐入口，负责 bootstrap `.venv`、安装依赖并进入正式 Textual 全屏 TUI。
- `novel-agent`：打包安装后的 console script，进入同一 Textual 全屏 TUI。
- `python -m novel_agent.app.cli_tui`：开发调试等价入口。
- `python -m novel_agent.app.run_interactive`：兼容和 smoke 入口，不承担正式用户体验。
- `novel-agent-gui`：历史桌面 GUI 入口；不承载新功能，若保留则只作为兼容 / smoke / 原型对照，并复用同一套 presenter / facade / 状态词典。

`run_interactive.py` 退场边界：

- 仍保留用于 CI smoke、旧测试夹具、迁移期间的输出对比和调试差异定位。
- 正式 Textual 路径不得调用 `_prompt_text()`、`_prompt_choice()`、`_prompt_yes_no()` 或裸 `input()`。
- Textual 可以经 `WorkflowFacade` 临时复用 run_interactive 中已封装的 runner / workflow 启动函数，但用户输入、确认、artifact 审阅和状态展示必须由 Textual Screen / Widget 承担。
- 当 read pipeline、Creative KB 与 Writer orchestration 都提供稳定的非交互 API 后，`run_interactive.py` 中的交互式 `_prompt_*` 逻辑应继续收缩为 smoke-only helper。

Screen 与业务边界：

- Textual Screen / Widget 只负责展示、输入、焦点、快捷键和调用 facade。
- CLI 层不得直接拼 Writer prompt。
- CLI 层不得为 `Scoped Artifact Revision` 选择 LLM 上下文、生成修订 prompt 或写入候选 artifact。
- CLI 层不得直接修改 Memory 规则。
- CLI 层不得绕过 writer workflow / execution orchestrator 写 workflow 状态。
- read pipeline 的业务逻辑仍由 segmentation / close-read runner 承担。

业务代码继续留在：

- segmentation / close-read runners
- Creative KB services
- Writer workflow / execution orchestrators

其中 `Scoped Artifact Revision` 必须落在 Writer workflow / orchestration 层：它接收 CLI 传来的反馈请求，负责权限边界、prompt 组装、LLM 调用、schema / scope 校验、diff 生成、artifact 写入和回滚传播。

CLI 不应直接拼 Writer prompt、不应直接修改 Memory 规则，也不应绕过 orchestration 写运行状态。

## 15. Textual 实现里程碑

Textual 全屏 TUI SHOULD 分阶段落地：

1. `novel-agent` 启动 Textual 骨架，展示 HomeScreen、WorkbenchScreen、状态侧栏、底部输入和消息流。
2. 替换正式路径里的 `_prompt_*`，首屏动作、命令面板和阻塞决策全部使用 Textual widget。
3. 将 segmentation / close-read / KB / Writer 后台执行 worker 化，stdout 捕获为 `RunEvent`。
4. 接入 ArtifactReviewPane 和 ArtifactEditorPane，支持 JSON / Markdown 校验、保存、toast。
5. 接入 Writer 所有人工确认点，保存不推进，确认才调用 workflow action。
6. 增加 Textual 组件测试 / snapshot 测试，覆盖宽屏、窄屏、命令面板、决策面板、输入不被输出覆盖。

## 16. Web / 历史 GUI 复用关系

Web 工作台是当前图形端主路径。若历史桌面 GUI 继续保留作为兼容或 smoke
对照，也应复用本文定义的：

- 用户可见状态文案
- artifact 审阅模型
- 决策面板选项
- 错误恢复建议
- 从 read 到 Writer 的统一入口语义

Web / GUI 可以使用不同布局，但不能改变流程含义。CLI、Web 和历史 GUI
的差异应是展示形态，而不是业务流程。

## 17. 非目标

本文不定义：

- 具体颜色主题 token 的最终视觉值
- 数据库 schema
- Writer prompt 字段
- Memory 抽取 schema
- Web / GUI 组件实现细节
- Textual 每个 widget 的 CSS 最终像素级样式

这些内容分别由实现任务、模块 spec/design 和 contracts 定义。
