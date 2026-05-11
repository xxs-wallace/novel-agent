# Novel Agent

Novel Agent 是一个面向作者的小说续写工作台，用于把长篇原文导入本地、完成粗读/精读建模、构建创作知识库，并在人工审阅确认的节奏下生成后续章节。

本项目基于 [huggingface/smolagents](https://github.com/huggingface/smolagents.git) 研发，继续复用其 Agent、Tool 与模型接入能力，并在此基础上扩展了小说续写相关的 `novel_agent` 模块和统一 CLI / TUI 工作台。

## 主要功能

- 原文导入与粗读：把小说原文切分并写入本地索引，形成后续建模的 `documents` 基线。
- 精读建模：抽取章节信息、人物档案、世界观摘要、故事大纲和事实型记忆。
- 精读产物查询：可在同一工作台里查询人物档案、剧情总览、故事大纲和 source arc 等建模结果。
- Creative KB：构建桥段卡片、结构模式与风格参考，用于续写时检索相似桥段。
- Writer 分层生成：按“全书规划 -> 批次大纲 -> 章节梗概 -> 长度计划 -> 写作材料 -> 正文草稿 -> 验收写回”的流程推进。
- 人工审阅与可恢复运行：每个关键产物都先展示摘要，用户可以修改、保存、确认，再进入下一步。
- 按反馈受控修订：审阅规划类产物时，可以让系统只针对当前 artifact 生成候选修改、展示 diff，并在用户接受后写回。
- Benchmark 回归：支持最小续写回归、端到端 Agentic benchmark 和 Creative KB benchmark，用于检查 Writer 与 KB 增益。
- 统一 CLI / TUI：粗读、精读、知识库和 Writer 不再分散在多个用户入口中，而是在同一个工作台里切换。

## 环境准备

需要 Python 3.10 及以上版本。推荐直接使用仓库根目录的启动脚本，它会自动创建或复用 `.venv` 并安装缺失依赖：

```bash
./novel-agent
```

如果希望手动安装：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[openai]"
```

本项目默认使用 DeepSeek 兼容 OpenAI 的接口能力。运行前请设置 `DEEPSEEK_API_KEY`：

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
```

也可以把 key 放在自己的 shell 配置或本地环境管理工具中，只要启动 `novel-agent` 时进程能读取到 `DEEPSEEK_API_KEY` 即可。

## 启动 CLI 工作台

开发者推荐入口：

```bash
./novel-agent
```

安装为 console script 后也可以使用：

```bash
novel-agent
```

等价的开发调试入口：

```bash
python -m novel_agent.app.cli_tui
```

启动后会进入 Textual 全屏 TUI。首屏会提供常用动作，例如选择或创建任务、继续上次会话、导入/粗读原文、运行精读建模、查看建模状态、构建 Creative KB、开始或恢复 Writer。

旧入口 `python -m novel_agent.app.run_interactive` 仅保留给 smoke、兼容测试和迁移期调试，不再作为正式用户入口。

CLI 工作台已经实现的交互能力包括：

- prompt-first 首页：输入框默认聚焦，首屏动作分行展示，也支持直接输入自然语言续写方向。
- 三段式工作台：消息流、artifact 摘要/编辑区、状态侧栏和底部输入区分离，后台输出不会覆盖正在编辑的输入。
- 中文友好输入区：支持中英文混排、多行输入、长文本粘贴、历史记录和常见行编辑快捷键。
- Slash command autocomplete 与 `Ctrl+P` 命令面板：命令定义由同一个 `CommandRouter` 提供，并按上下文隐藏或提示不可用动作。
- `@` artifact 引用：输入 `@` 时可选择当前会话产物或最近 runs 文件，并插入短 token，避免长路径塞满输入框。
- Artifact 审阅与编辑：JSON / Markdown 产物默认展示结构化摘要，大文件折叠预览；保存前会做 JSON 与关键 schema 校验。
- 阻塞决策面板：需要确认时底部输入区切换为结构化选项，支持保存、确认、返回上一层、章节验收和稍后继续。
- 技术详情与错误恢复：内部 stage、run id、checkpoint、artifact path 和折叠日志放在技术详情中；错误会给出可继续操作的建议。

## 基本使用流程

1. 设置 `DEEPSEEK_API_KEY`。
2. 运行 `./novel-agent` 进入工作台。
3. 使用 `/new-task <task_id> <source_path>` 创建任务，或用 `/tasks` 查看已有任务。
4. 使用 `/read` 导入并粗读原文。
5. 使用 `/close-read` 运行精读建模。
6. 使用 `/query summary total`、`/query character <name>` 等命令检查精读产物。
7. 使用 `/kb` 构建或查看 Creative KB。
8. 使用 `/writer` 开始或恢复分层续写。
9. 在每个审阅节点中修改、保存、确认产物，确认后系统才会进入下一步。

其中 `task_id` 对应同一本书在粗读、精读、Creative KB 和 Writer 中共用的 `book_id`。

## 主要命令

| 命令 | 用法 |
| --- | --- |
| `/status` | 查看当前项目的原文、精读记忆、人物档案、世界观、故事大纲、Creative KB 与 Writer 状态。 |
| `/tasks` | 列出所有任务，以及 documents、chapters、粗读进度和精读进度。 |
| `/task <task_id>` | 进入指定任务。 |
| `/new-task <task_id> <source_path>` | 创建新任务并记录原文路径。 |
| `/reset-close-read` | 清空当前任务的精读进度与派生产物，保留粗读 documents。 |
| `/read` | 进入原文导入/粗读流程。 |
| `/close-read` | 进入精读与记忆抽取流程。 |
| `/query summary total` | 查看当前任务的精读总览。 |
| `/query character <name>` | 查询指定人物档案。 |
| `/query outline` | 查看故事大纲建模结果。 |
| `/query source_arc` | 查看源作品篇章地图。 |
| `/kb` | 构建或查看 Creative KB。 |
| `/benchmark longzu-32kb` | 运行端到端 Agentic benchmark，并把 Reviewer 摘要回流到消息流。 |
| `/benchmark --source <path>` | 使用指定原文运行 benchmark。 |
| `/creative-kb-benchmark longzu-32kb --writer-ab --dry-run-model` | 运行 Creative KB benchmark；`--writer-ab` 会比较 Writer A/B 增益，`--dry-run-model` 用于无真实 LLM 的测试链路。 |
| `/writer` | 开始或恢复 Writer 分层生成。 |
| `/resume` | 恢复最近一次未完成流程。 |
| `/artifacts` | 查看当前会话产物。 |
| `/open` | 打开当前重点产物。 |
| `/save` | 保存当前 artifact 编辑内容。 |
| `/confirm` | 确认当前审阅步骤，并允许系统继续推进。 |
| `/back` | 在 Writer 审阅流程中返回上一层可修改节点。 |
| `/help` | 查看当前上下文可用操作。 |
| `/debug` | 查看内部 stage、run id、artifact path 等技术详情。 |

常用快捷键：

| 快捷键 | 行为 |
| --- | --- |
| `Enter` | 发送当前输入。 |
| `Shift+Enter` | 在输入框内换行。 |
| `Ctrl+P` | 打开命令面板。 |
| `Ctrl+S` | 保存当前 artifact。 |
| `Ctrl+Enter` | 确认当前审阅步骤。 |
| `Ctrl+O` | 打开当前重点 artifact。 |
| `Ctrl+D` | 展开或收起技术详情。 |
| `Ctrl+L` | 切换运行日志显示。 |
| `Esc` | 关闭弹层；运行中可请求暂停。 |

## Writer 审阅节点

Writer 不会直接“一键吐出全文”，而是按可审阅、可修改、可恢复的方式推进：

1. 生成并审阅全书续写规划。
2. 生成并审阅本批剧情大纲。
3. 生成并审阅章节标题与故事梗概。
4. 规划并确认章节长度。
5. 整理并确认本章写作材料。
6. 生成正文草稿并进行连续性检查。
7. 用户接受、调整长度重生成、退回重规划或作废。
8. 接受后写回章节、记忆与运行产物。

用户在审阅节点修改后的内容，会作为后续流程的准绳。例如修改批次剧情大纲后，章节梗概会基于修改后的大纲继续生成。

在规划类审阅节点中，还可以选择“按我的反馈修改”。这个路径会把当前 review state、当前 artifact 和用户反馈交给 workflow 层，由 workflow 生成受控候选修改、校验 scope 和 schema、展示修改摘要与 diff。只有用户接受候选后，当前 artifact 才会被写回；保存后仍停留在原审阅节点，不会自动确认，也不会越权修改 Memory、KB、workflow state 或其它产物。

### Writer 分层功能

Writer 层不是单个“续写 prompt”，而是一条带冻结点、回滚和写回门禁的工作流：

- 建模检查：启动 Writer 前检查原文索引、精读记忆、人物档案、世界观、故事大纲、Creative KB 是否足以支撑续写。
- 续写意图：记录本次想写什么、主要角色、避免项、期望结果和补充说明。
- 全书续写规划：生成 `book_continuation_plan.json`，决定后续主线、阶段高潮、必须保留的设定和未决问题。
- 世界观补全：生成 `world_expansion_pack.json`，只补本轮续写需要的最小设定约束。
- 人物需求与补充：区分“用户点名但 Memory 未建档的人”和“剧情结构缺位的人”，必要时生成计划人物、人物引入计划和角色方案。
- 批次剧情规划：生成 `batch_plan.json`，把长线目标拆成本批次入口、冲突、中点、出口和不得提前消费的信息。
- 章节标题与梗概：生成 `chapter_package.json`，明确章节目标、冲突、关系推进、必须出现和禁止出现的内容。
- 章节长度计划：生成 `chapter_length_plan.json`，把默认字数、重点章、高潮章和单章 override 变成正式预算。
- 写作材料冻结：生成 `chapter_execution_input.json`，把章节 brief、长度预算、事实约束、风格参考、人物关系门禁和 Creative KB 检索结果汇总成正文层输入。
- 正文生成与连续性检查：生成 `draft.md`、`continuity_report.json` 和状态变化候选。
- 章节验收与写回：用户接受后才会进入写回确认，最终更新续写记忆和正式产物；未验收草稿不会污染 Memory / KB。

### 当前限制

当前代码已经有 Writer 状态机、冻结点、artifact 摘要、受控修订、决策面板和恢复能力，但 TUI 的 Writer 启动与部分审阅体验仍然偏开发者工具：

- `/writer` 目前会直接用默认参数启动 Writer，没有完整的字段化续写意图向导。
- 自然语言输入已能进入消息流，但还没有完整接入 `intent_payload`、`user_world_notes`、章节数和新角色需求表单。
- “手动编辑”仍会打开 JSON / Markdown artifact，这是高级调试入口，不应该是普通作者完成 Writer 配置的主路径。
- `BookContinuationPlan`、`BatchPlan`、`ChapterPackage`、`ChapterLengthPlan` 等 JSON 应继续保留为可追踪 contract，但主界面应提供带注释的表单或摘要编辑器来修改这些字段。

因此，如果界面要求用户“去填某个 JSON 文件”才能继续，这应视为待修的交互缺口。短期内优先使用“按我的反馈修改”表达修改意图；长期应该把 Writer 启动和每个审阅节点都做成分步向导。

## Benchmark 与回归

CLI / TUI 已接入以下回归能力：

- 最小续写回归：从指定原文窗口读取 prefix，生成后续内容并输出 Reviewer 报告。
- 端到端 Agentic benchmark：通过 `/benchmark longzu-32kb` 或 `/benchmark --source <path>` 驱动 Writer benchmark，并把综合 Reviewer 摘要显示在消息流。
- Creative KB benchmark：通过 `/creative-kb-benchmark longzu-32kb --writer-ab --dry-run-model` 检查建卡、聚类、检索/rerank 和 Writer A/B 增益。
- Benchmark 失败恢复：未知目标、非法参数、未显式选择真实/干跑模型、artifact 写入失败、Reviewer 失败等路径会保留用户命令记录，并显示恢复建议，输入区仍可继续编辑。

真实 LLM 的 CLI / TUI benchmark smoke 默认不会运行。需要显式设置环境变量后再执行慢速测试：

```bash
NOVEL_AGENT_RUN_REAL_CLI_TUI_SMOKE=1 python -m pytest -m slow novel_agent/tests/test_cli_textual_components.py
```

## 运行产物

项目会在本地保存索引、记忆和运行产物，常见目录包括：

- `.indexes/`：每个任务对应的本地 SQLite 索引。
- `.memory/`：世界观、故事大纲、源作品篇章地图等长期记忆产物。
- `runs/`：Writer 运行过程中的规划、草稿、连续性检查和写回产物。
- `runs/benchmarks/`：端到端 Agentic benchmark 产物。
- `runs/creative_kb_benchmarks/`：Creative KB benchmark 产物。

大体量正文默认在界面中只展示摘要和路径，完整内容通过 artifact 文件访问。

## 与 smolagents 的关系

本仓库保留并复用 [huggingface/smolagents](https://github.com/huggingface/smolagents.git) 的基础能力，包括：

- `CodeAgent` / `ToolCallingAgent`
- `Tool` 体系
- OpenAI-compatible、LiteLLM、InferenceClient、Transformers 等模型接入方式
- 原有 `smolagent`、`webagent` 命令

Novel Agent 是在这些能力之上扩展出的小说续写产品层。正式小说续写入口请使用 `./novel-agent` 或 `novel-agent`。

## 开发与测试

安装开发依赖：

```bash
pip install -e ".[dev,openai]"
```

运行测试：

```bash
python -m pytest novel_agent/tests tests
```

只验证 CLI / TUI 入口时可运行：

```bash
python -m pytest novel_agent/tests/test_cli_tui_entrypoint.py novel_agent/tests/test_cli_textual_components.py
```

验证受控 artifact 修订链路：

```bash
python -m pytest novel_agent/tests/test_scoped_artifact_revision.py novel_agent/tests/test_scoped_artifact_revision_workflow.py novel_agent/tests/test_scoped_artifact_revision_integration_safety.py
```
