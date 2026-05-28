# Novel Agent

Novel Agent 是一个面向作者的小说续写 Web 工作台，用于把长篇原文导入本地，完成粗读 / 精读建模、叙事索引、Creative KB 构建，并在人工审阅确认的节奏下生成后续章节。

本项目基于 [huggingface/smolagents](https://github.com/huggingface/smolagents.git) 研发，复用其 Agent、Tool 与模型接入能力，并在此基础上扩展 `novel_agent` 的小说续写产品层。当前 README 以 Web 工作台为主入口。

## 主要功能

- 原文导入与阅读建模：导入小说原文，切分 documents，抽取章节摘要、人物档案、世界观摘要、故事大纲、源作品篇章地图和事实型记忆。
- 叙事索引与 Memory 查询：通过统一 inquiry broker 从人物、世界观、章节摘要、source arc、场景卡和原文摘录中按需取证。
- Creative KB：构建桥段卡片、结构模式与风格参考，用于续写、风格对照和 benchmark 检索评估。
- Web 三栏工作台：左侧任务列表，中间会话与 Agent 决策卡，右侧阅读 / Writer 结果浏览器。
- Outline Analyzer：通过“小说专家意见”按钮进入只读分析模式，讨论剧情结构、人物动机、伏笔回收、节奏和风险。
- Reviewer Agent：在 Writer 审阅卡片和结果详情中运行只读评审，输出中文报告和参考评分，不替用户确认或写回。
- Writer 分层生成：模型主导 Agent Loop，在信息不足时查询本地资料或向用户提问，在 artifact review gate 中生成、修订、确认规划和草稿。
- Draft Research + Prose Executor：正文生成前先整理可追踪事实笔记和写作约束，再由受限正文执行器生成 `draft.md`。
- 可恢复运行：后台任务进度、阻塞点、审阅卡、草稿决策和技术详情都会保存在本地，便于稍后继续。

## 环境准备

需要 Python 3.10 及以上版本。推荐使用仓库根目录的 Web 启动脚本，它会自动创建或复用 `.venv` 并安装缺失依赖：

```bash
./novel-agent-web
```

如果希望手动安装：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[openai]"
```

本项目默认使用 DeepSeek 兼容 OpenAI 的接口能力。运行真实模型功能前请设置 `DEEPSEEK_API_KEY`：

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
```

## 启动 Web 工作台

```bash
./novel-agent-web
```

安装为 console script 后也可以使用：

```bash
novel-agent-web
```

默认会启动：

- FastAPI 后端：`http://127.0.0.1:8000`
- Vite 前端：`http://127.0.0.1:5173`

常用启动参数：

```bash
./novel-agent-web --check-only
./novel-agent-web --api-port 8010 --web-port 5174
./novel-agent-web --no-open
```

如果前端依赖尚未安装，启动脚本会在 `web/` 下自动执行 `npm install`。`--check-only` 只检查依赖，不启动服务。

## Web 工作台布局

Web 主界面是三栏布局，窄屏时会折叠成“任务 / 会话 / 结果”三个移动端面板。

- 顶栏：显示 Novel Agent、当前任务、公开状态、最近一次操作提示和“设置”按钮。
- 左侧任务栏：展示任务列表、当前任务进度、阻塞点 badge 和任务操作菜单。
- 中间会话区：展示用户消息、Agent 回复、后台进度、Writer 问题卡、审阅卡、草稿决策卡和输入框。
- 右侧结果浏览器：用“阅读”和“Writer”两个 tab 展示目录树与详情视图。

Web 的主交互是按钮、菜单、wizard、卡片和表单提交，不要求用户输入命令。

## 基本使用流程

1. 运行 `./novel-agent-web` 打开浏览器工作台。
2. 点击左侧“创建任务”，填写 task id / book id 和原文路径。
3. 任务创建后系统会启动原文导入；也可以在任务菜单点击“导入原文”继续导入。
4. 在任务菜单点击“开始阅读”，运行精读建模。
5. 按需点击“构建叙事场景索引”和“构建 Creative KB”。
6. 在右侧“阅读”tab 查看总览、章节摘要、人物百科、世界观、故事大纲和源作品篇章地图。
7. 在会话区点击“小说专家意见”，与 Outline Analyzer 讨论剧情方向；点击“退出专家意见”回到普通会话。
8. 点击“开始续写”，填写 Writer wizard 的续写方向、章节数和每章字数。
9. 按照会话区的 Writer 问题卡、artifact 审阅卡和草稿决策卡逐步确认或修订。
10. 在右侧“Writer”tab 查看全书规划、批次大纲、章节梗概、执行输入、正文草稿、连续性检查和写回摘要。

## 任务栏按钮

左侧任务栏用于管理 book / task 和启动后台流程。

| 按钮或菜单项 | 作用 |
| --- | --- |
| `创建任务` | 打开创建任务弹窗，填写 task id 和原文路径。创建成功后会选择该任务并启动导入。 |
| `刷新` | 重新加载任务列表、进度和结果树。 |
| 点击 task card | 选择当前任务，并刷新会话、状态和右侧结果。 |
| `导入原文` | 启动或继续原文导入 / 粗读。 |
| `开始阅读` | 运行精读建模，生成章节摘要、人物、世界观、故事大纲等 Memory 产物。 |
| `构建叙事场景索引` | 构建 Narrative SceneCard 等用于 Analyzer / Writer / Reviewer 的紧凑证据索引。 |
| `构建 Creative KB` | 构建桥段卡、结构模式和风格参考。 |
| `开始续写` | 先做 Writer preflight 检查，再打开“创建续写任务”wizard。 |
| `恢复续写` | 回到上一次 Writer 的可恢复问题、审阅或草稿决策点。 |
| `删除续写任务` | 预览并删除最近 Writer run，不删除阅读记忆和任务索引。 |
| `重置阅读` | 清空当前任务的精读进度和派生产物，保留原文 documents。 |
| `删除任务` | 先预览会删除的本地建模产物，再确认删除任务。 |

## 会话区按钮

中间会话区是作者与 Agent 协作的主区域。

| 按钮 | 作用 |
| --- | --- |
| `小说专家意见` | 切换到 Outline Analyzer 只读分析模式。发送的问题会带 `outline_analyzer` 语义，不推进 Writer。 |
| `退出专家意见` | 退出 Analyzer 模式，恢复普通会话或 Writer 审阅上下文。 |
| `开始续写` | 从会话区直接打开 Writer wizard。若建模基础不足，会显示缺失项和恢复建议。 |
| `发送` | 记录当前输入。普通模式下是自然语言消息；Writer 问题或审阅上下文中会绑定对应 question / review。 |
| `取消` | 取消当前输入框绑定的问题、审阅或草稿反馈上下文。 |

输入框会根据当前上下文变化：

- Analyzer 模式：向小说专家提问，例如“当前未解之谜哪条最适合下一阶段回收？”
- Writer 问题卡：回答当前大纲研究或正文研究问题。
- Artifact 审阅卡：输入通过补充或调整反馈。
- 草稿决策卡：输入草稿重写、重规划或作废原因。
- 普通模式：输入自然语言续写方向或备注。

## Writer Wizard

点击“开始续写”后，Web 会先检查原文、精读 Memory、故事大纲、Creative KB 等建模基础是否足够。通过 preflight 后打开“创建续写任务”弹窗。

Wizard 字段：

- `User prompt`：本次续写方向、希望人物做什么、避免什么、倾向结局或阶段目标。
- `续写章节数`：目标章节数量。
- `每章字数`：默认单章字数预算。

按钮：

- `取消`：关闭 wizard，不启动 Writer。
- `创建续写任务`：提交 `start_writer` action，进入 Writer Agent Loop。

## Writer 问题卡

当 Outline Research Loop、Draft Research Loop、人物对齐或新角色确认需要用户补充时，会话区会出现 Writer 问题卡。

| 按钮 | 作用 |
| --- | --- |
| `提交回答并继续研究` | 把输入框中的回答绑定到当前 `question_set_id`，继续 Writer research。 |
| `稍后继续` | 保留当前等待态，不推进 workflow。 |

普通聊天消息不会自动越过 Writer 的 `needs_user_input`。只有点击结构化按钮，后端才会继续执行。

## Artifact 审阅卡

全书续写规划、世界观补全、人物补充、批次计划、章节梗概和写回摘要都会以审阅卡形式出现。

| 按钮 | 作用 |
| --- | --- |
| `查看详情` | 在右侧 Writer 结果详情中打开当前 artifact 的用户可读视图。 |
| `Reviewer：大纲合理性` | 对大纲类 artifact 运行只读 Reviewer，检查剧情承接、因果链和阶段推进。 |
| `Reviewer：梗概与人物` | 对章节梗概运行只读 Reviewer，检查人物动机、关系推进和剧情可执行性。 |
| `通过并继续` | 提交 approved 决策；输入框里的补充会作为后续模型 prompt 材料。 |
| `不通过并调整` | 提交 revision feedback；Writer 会修订当前 artifact，并回到同一审阅点。 |
| `稍后继续` | 暂停在当前审阅点，保留可恢复状态。 |

Web 只提交用户决策语义；Writer workflow 负责 prompt 组装、模型修订、状态推进和下游失效。

## 草稿决策卡

正文草稿生成后，会话区会展示草稿预览、字数、连续性检查摘要和决策按钮。

| 按钮 | 作用 |
| --- | --- |
| `查看完整正文` | 在右侧 Writer 结果详情中打开完整 `draft.md`。 |
| `Reviewer：局部连续性` | 检查草稿与最近上下文之间的场景、视角、节奏和文风衔接。 |
| `Reviewer：历史一致性` | 核查草稿中的人物、事件、地点、关系和设定是否与 Memory 冲突。 |
| `Reviewer：文风氛围` | 使用 Creative KB 对照草稿的文风、氛围、桥段执行和细节密度。 |
| `接受本章` | 接受当前草稿，进入写回摘要审阅；只有接受后才允许正式写回 Memory / KB。 |
| `基于反馈重写` | 把输入框反馈交给 Draft Research Loop，生成受控重写计划后重写本章。 |
| `修改章节梗概后重写` | 反馈指向上游结构问题时，回到章节梗概层修订再重写。 |
| `作废本次草稿` | 放弃当前草稿，不写回 Memory / KB。 |
| `稍后再决定` | 保留当前草稿决策点，稍后恢复。 |

`continuity_report` 和 Reviewer 报告只作为风险提示；是否接受仍由用户决定。

## 右侧结果浏览器

右侧不是文件浏览器，而是“用户理解用内容浏览器”。它把数据库、Memory 文件和 Writer runs 转成目录树、卡片、表格、Markdown 和折叠技术详情。

### 阅读 Tab

“阅读”tab 用于查看 close-read 结果：

- 总览：建模准备度、总体剧情摘要、已处理章节范围。
- 章节摘要：按章节 / document title index 展示剧情概括、角色状态变化、伏笔和信息增量。
- 人物百科：基本信息、当前目标、关系网络、说话方式、秘密、禁止误写点和最近变化。
- 世界观：地点、组织、规则、物品、时间线。
- 故事大纲：主线、支线、未回收伏笔。
- 源作品篇章地图：篇章结构、节奏节点、高潮与转折。

### Writer Tab

“Writer”tab 用于查看续写产物：

- Run 总览：当前状态、待确认步骤、产物路径、下一步动作。
- 大纲研究：当前问题、已确认信息、仍缺口、可用假设、research trace 摘要。
- 全书续写规划：续写目标、世界观补充、人物补充、高潮与回收。
- 本批剧情大纲：起点状态、阶段目标、主要冲突、情绪节奏、预计收束。
- 章节标题与梗概：章节目标、冲突、关系推进、scene beats、禁止项。
- 章节写作指导：用户补充、派生长度预算、风格与节奏要求。
- 本章执行输入：事实型上下文、风格与桥段参考、禁止项。
- 正文草稿：字数、开头预览、连续性检查、完整正文。
- 写回确认：人物状态变化、世界状态变化、新伏笔和已回收信息。

详情页中的 `技术详情` 按钮用于查看原始 artifact 路径、trace、内部状态和 JSON。普通阅读路径默认不展示内部 stage、checkpoint id 或 artifact id。

## Outline Analyzer

Outline Analyzer 是只读的小说专家聊天模式。它适合在正式续写前讨论：

- 当前剧情处在什么结构位置。
- 哪些主线、支线、伏笔或谜团适合推进或延后。
- 某个后续走向是否有足够因果和人物动机。
- 关系变化、世界规则突破、终局秘密等高风险安排是否需要用户授权。
- 哪些章节值得回读原文，以及为什么摘要层证据不够。

Analyzer 不会把整本书一次性塞进 prompt。它先构造轻量 `AnalyzerSeedPacket`，随后模型用结构化 research request 主动查询 `story_detail`、`character_profile`、`world_concept`、`chapter_summary`、`raw_excerpt`、`structure_pattern` 等证据。最终回答会区分已确认事实、合理推断、证据缺口、用户偏好和纯候选方案。

Analyzer 不写 Memory、不修改 Writer artifact、不自动提交 Writer 决策。想采纳 Analyzer 建议时，需要把建议手动写入 Writer 的补充说明或修订反馈。

## Reviewer Agent

Reviewer Agent 是模型驱动、只读、可插拔的评审运行时。Web 会在合适的 Writer 审阅卡片、草稿卡片和右侧 artifact 详情里显示 Reviewer 按钮。

当前设计覆盖的 Reviewer 类型包括：

- `outline_plot_development`：评审大纲是否承接前文、因果是否成立、阶段推进是否失衡。
- `chapter_synopsis_plot_character`：评审章节梗概的人物动机、关系推进和剧情可执行性。
- `local_draft_continuity`：评审正文草稿和最近上下文的局部衔接、视角、节奏和文风惯性。
- `memory_draft_consistency`：核查草稿中的事件、人物、地点、关系和设定是否与 Memory 冲突。
- `kb_draft_style_atmosphere`：用 Creative KB 对照草稿的文风、氛围、桥段执行和细节密度。
- `source_chapter_literary_diagnostic`：面向已入库原文章节的文学性和人物塑造诊断，目前属于扩展诊断能力。

Reviewer 报告是参考意见，不是 Writer 或 benchmark 的硬性通过标准。Reviewer 只读 Memory / KB / artifact，不写回，也不替用户点击“通过并继续”。

## Writer Agent

Writer 的核心是模型主导的 Agent Loop：

```text
用户意图 / Memory / KB / runs artifacts
  -> 模型判断需要查询、提问、生成或修订
  -> Agent 执行本地查询或用户交互
  -> 生成或修订可审阅 artifact
  -> 用户通过并补充，或拒绝并给出修订反馈
  -> Draft Research Loop 准备正文事实
  -> Draft Prose Executor 生成草稿
  -> 用户验收、重写、重规划或写回
```

关键规则：

- 用户确认或修改后的规划、梗概、长度预算和写作材料会成为后续输入。
- 上游 artifact 重新通过后，下游依赖产物需要失效或局部重跑。
- 草稿未被用户接受前，不会污染 Memory / KB。
- Draft Prose Executor 不主动查询 Memory，不私自改变上游规划，只消费 Draft Research Loop 整理后的事实包和写作约束。

## 未来开发方向 / TODO

以下方向不是为了把 Novel Agent 改造成通用 Agent 平台，而是继续增强垂直领域 Agent Harness 的可评测性、可编排性和可接入性。

- 模型横向评测矩阵：在同一本小说、同一套固定输入下评测不同模型的续写效果。优先建设 Writer-only 固定输入评测，复用同一份 Memory、叙事索引、Creative KB、SourceArc、用户续写方向、章节目标和授权输入，只替换 Writer / Reviewer 使用的模型，输出事实一致性、人物关系一致性、章节目标完成度、风格贴合度、禁止项违规、人工偏好评分和 Reviewer 分维度报告。后续再扩展到端到端全链路评测，比较不同模型完成原文导入、精读建模、叙事索引、Creative KB 和 Writer 的综合表现。
- 形式化执行图：当前 Writer 已具备 Agent Loop、artifact review gate、Web 决策卡、resume 和 rollback 能力，但部分执行依赖仍隐含在业务代码中。后续可将 Writer / Reviewer / Benchmark 的关键步骤显式建模为 typed graph node，声明每个节点消费和产出的 artifact、可进入条件、失败出口、重试策略、上游修改后的下游失效规则、可并行执行的 Reviewer suite，以及每个节点的耗时、模型、token、工具调用和失败原因，方便 Web 展示、恢复、调试和横向评测。
- MCP / 外部生态接入：将已经具备清晰边界的子能力抽象为 MCP server 或标准 typed tools，供其他 Agent 调用。第一阶段优先暴露只读能力，例如 `memory.query`、`narrative_index.search`、`kb.retrieve`、`outline_analyzer.ask`、`reviewer.review` 和 `artifacts.read`；第二阶段再暴露带副作用的 Writer 能力，例如 `writer.start_or_resume`、`writer.submit_review_decision` 和 `benchmark.run_model_matrix`，并配套 `book_id`、`run_id`、`review_id`、权限边界与 dry-run 模式，避免外部 Agent 绕过人工确认和写回规则。

## Benchmark 与调试 Runner

日常使用请走 Web 工作台。以下 Python runner 主要用于开发、QA 和回归：

```bash
python -m novel_agent.app.run_outline_analyzer_benchmark longzu-120kb --json
python -m novel_agent.app.run_reviewer_smoke --source novel_agent/tests/longzu_120kb.txt
python -m novel_agent.app.run_creative_kb_benchmark longzu-32kb --writer-ab --dry-run-model
```

## 运行产物

项目会在本地保存索引、记忆和运行产物，常见目录包括：

- `.indexes/`：每个任务对应的本地 SQLite 索引。
- `.memory/`：世界观、故事大纲、源作品篇章地图等长期记忆产物。
- `runs/`：Writer 运行过程中的规划、草稿、连续性检查和写回产物。
- `runs/web_jobs/<job_id>/events.jsonl`：Web 后台任务事件日志，用于 SSE 断线恢复和调试。
- `runs/benchmarks/`：端到端 Agentic benchmark 产物。
- `runs/benchmarks/outline_analyzer/`：Outline Analyzer benchmark 的 baseline、Analyzer 回答、trace 和评分摘要。
- `runs/creative_kb_benchmarks/`：Creative KB benchmark 产物。
- `runs/reviewer_smoke/`：Reviewer smoke suite 的建模产物、构造评审目标、tool trace 和 review report。
- `runs/analyzer/<session_id>/trace.json`：Analyzer debug trace，只有 debug 路径需要落盘。

大体量正文默认在 Web 中只展示摘要和路径，完整内容通过右侧详情或 artifact 文件访问。

## 与 smolagents 的关系

本仓库保留并复用 [huggingface/smolagents](https://github.com/huggingface/smolagents.git) 的基础能力，包括：

- `CodeAgent` / `ToolCallingAgent`
- `Tool` 体系
- OpenAI-compatible、LiteLLM、InferenceClient、Transformers 等模型接入方式
- 原有 `smolagent`、`webagent` 命令

Novel Agent 是在这些能力之上扩展出的小说续写产品层。正式小说续写入口请使用 `./novel-agent-web` 或 `novel-agent-web`。

## 开发与测试

安装开发依赖：

```bash
pip install -e ".[dev,openai]"
```

运行测试：

```bash
python -m pytest novel_agent/tests tests
```

验证 Web 工作台：

```bash
cd web
npm test
npm run typecheck
```

验证受控 artifact 修订链路：

```bash
python -m pytest novel_agent/tests/test_scoped_artifact_revision.py novel_agent/tests/test_scoped_artifact_revision_workflow.py novel_agent/tests/test_scoped_artifact_revision_integration_safety.py
```
