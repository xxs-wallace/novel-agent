# Writer Status Refactor Prompts

本文为 [`tasks.md`](tasks.md) 中 `Group G: Writer 用户可见状态重构` 生成可交给独立 agent 执行的 prompt。默认使用“总执行 prompt”；若需要分批派工，再使用后续阶段 prompt。

## Prompt 0: 顺序完成 Writer 状态重构全部任务

```text
你的角色：Writer-Status-Refactor-Agent。

工作目录：/Users/luliao/agent/smolagents

任务目标：
按顺序完成 .trae/specs/writer-agent-layered-generation/tasks.md 中 Group G 的 Task 16、Task 17、Task 18、Task 19、Task 20。不要只改文案，要把状态翻译层、CLI 输出、GUI 输出、状态机不一致点和测试一起完成。

必须先阅读：
1. AGENTS.md
2. .trae/specs/spec.md
3. .trae/specs/writer-agent-layered-generation/design.md
4. .trae/specs/writer-agent-layered-generation/tasks.md 的 Group G
5. .trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md
6. .trae/specs/writer-agent-layered-generation/contracts.md

建议重点阅读代码：
1. novel_agent/app/orchestrators/writer_workflow.py
2. novel_agent/app/orchestrators/writer_layered_generation.py
3. novel_agent/app/orchestrators/writer_execution.py
4. novel_agent/app/run_interactive.py
5. novel_agent/app/gui/main.py
6. novel_agent/app/gui/writer_cli.py
7. novel_agent/tests/test_run_interactive_pipeline.py
8. novel_agent/tests/test_writer_execution_workflow.py

实现边界：
1. 内部状态名可以继续存在于 workflow_state.json、checkpoint、日志和技术详情中。
2. CLI / GUI 主界面必须展示中文用户流程状态，不得把 artifact saved、Freeze B pending、freeze_d_review、wait_chapter_acceptance、checkpoint confirmed 作为主文案。
3. 保存 artifact 只显示“已保存你的修改”，不能自动推进流程。
4. WriterStatusPresenter 应尽量独立，供 CLI 和 GUI 共用。
5. 不要破坏现有 Writer workflow、Freeze record、review decision、writeback gate 的语义。
6. 遵守 OOP 原则，Pythonic，新增功能必须补测试。
7. 不要删除用户已有改动，不要做无关重构。

执行顺序：
1. 完成 Task 16：建立 WriterStatusPresenter 或等价状态翻译层。
2. 完成 Task 17：替换 CLI / run_interactive / writer_cli 中的内部状态主文案。
3. 完成 Task 18：替换 GUI Writer 面板状态和按钮文案，补齐 wait_chapter_review GUI 入口。
4. 完成 Task 19：核对 MODE_CONFIRMATION_POINTS 与 prepare_planning 等实际行为，修复 Batch 模式 Freeze A 确认点不一致，或更新模式定义并补测试。
5. 完成 Task 20：补状态翻译、CLI 输出、GUI 文案、wait_chapter_acceptance 四分支、wait_chapter_review 可继续路径、Batch 模式行为测试。
6. 每完成一个任务，更新 .trae/specs/writer-agent-layered-generation/tasks.md 中对应 checkbox。只有实现与测试都满足时才能勾选。

必须覆盖的用户文案：
- artifact saved -> 已保存你的修改
- batch_review / Freeze B pending -> 请审阅本批剧情大纲
- freeze_d_review -> 请确认本章写作材料
- wait_chapter_acceptance -> 请验收当前章节
- writeback_review -> 请确认写回续写记忆
- wait_chapter_review -> 请调整章节规划后重写
- checkpoint confirmed -> 已确认，继续下一步
- pending -> 等待你确认

验收标准：
1. CLI 主输出不包含 artifact saved、Freeze B pending、freeze_d_review、wait_chapter_acceptance、checkpoint confirmed。
2. GUI Writer 状态栏和按钮不把 Freeze A/B/C/D/E 作为主文案。
3. 技术详情仍可查看内部 stage、run id、freeze record、checkpoint path。
4. wait_chapter_acceptance 展示四个主要分支：接受本章、调整字数后重写、修改章节梗概后重写、作废草稿，并说明后续状态。
5. wait_chapter_review 有可继续路径。
6. Batch 模式 Freeze A 行为与 spec / mode definition 一致。
7. 新增/修改测试通过。至少运行 Writer workflow、run_interactive、GUI/presenter 相关测试；如果无法跑全量测试，说明原因。

交付要求：
1. 输出修改文件列表。
2. 输出已完成任务编号和未完成/阻塞项。
3. 输出测试命令与结果。
```

## Prompt 1: Task 16 状态翻译层

```text
你的角色：Writer-StatusPresenter-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 16。

重点：
1. 定义 WriterStatusPresenter 或等价 presenter。
2. 将内部 stage / event 翻译为中文用户文案。
3. 输出结构应包含：用户主状态、背景说明、下一步动作、技术详情。
4. CLI 和 GUI 都应能复用，不要把映射散落在多个界面函数里。

必须覆盖：
- artifact saved -> 已保存你的修改
- batch_review / Freeze B pending -> 请审阅本批剧情大纲
- freeze_d_review -> 请确认本章写作材料
- wait_chapter_acceptance -> 请验收当前章节
- writeback_review -> 请确认写回续写记忆
- wait_chapter_review -> 请调整章节规划后重写
- completed / halted / pending / confirmed / needs_review

建议关注代码：
- novel_agent/app/orchestrators/writer_workflow.py
- novel_agent/app/run_interactive.py
- novel_agent/app/gui/main.py
- novel_agent/app/gui/writer_cli.py
- novel_agent/tests/test_writer_execution_workflow.py

验收：
- 有状态翻译单测，覆盖所有 Writer 用户确认点。
- 内部状态仍可作为 technical detail 返回。
- 完成后勾选 Task 16。
```

## Prompt 2: Task 17 CLI / 交互输出替换

```text
你的角色：Writer-CLI-Copy-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 17。

重点：
1. 将 run_interactive.py、writer_cli.py 中展示给用户的内部状态替换为 WriterStatusPresenter 输出。
2. _prompt_writer_review 等交互提示显示中文状态、背景说明和下一步动作。
3. 保存 artifact 后显示“已保存你的修改”，并明确“保存不等于确认”。
4. 章节验收提示显示：接受本章、调整字数后重写、修改章节梗概后重写、作废草稿、稍后决定。
5. wait_length_review 说明它可能来自初次长度确认，也可能来自“调整字数后重写”。

禁止：
- 不得在主输出中展示 freeze_d_review、wait_chapter_acceptance、checkpoint confirmed、Freeze B pending。
- 不得改变 Writer workflow 的业务语义。

验收：
- CLI 输出测试断言主输出不包含内部状态码。
- 章节验收和长度重修路径有中文提示测试。
- 完成后勾选 Task 17。
```

## Prompt 3: Task 18 GUI Writer 面板替换

```text
你的角色：Writer-GUI-Copy-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 18。

重点：
1. _refresh_writer_state_buttons 使用中文状态和下一步说明。
2. _writer_actions_for_stage 的按钮文案去掉 Freeze A/B/C/D/E 主文案。
3. batch_review 按钮显示“确认本批剧情大纲”。
4. freeze_d_review 按钮显示“确认本章写作材料”，并说明不会立刻写回。
5. wait_chapter_acceptance 显示完整验收动作。
6. 为 wait_chapter_review 补齐 GUI 动作入口，支持返回章节梗概调整后继续。

建议关注代码：
- novel_agent/app/gui/main.py
- novel_agent/app/orchestrators/writer_workflow.py
- novel_agent/tests/**

验收：
- GUI 状态/按钮文案测试或 presenter 快照测试通过。
- 主界面不把 Freeze A/B/C/D/E 作为主要状态展示。
- 技术详情仍能显示内部 stage。
- 完成后勾选 Task 18。
```

## Prompt 4: Task 19 模式确认点与状态机对齐

```text
你的角色：Writer-StateMachine-Alignment-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 19。

重点：
1. 核对 MODE_CONFIRMATION_POINTS 与 prepare_planning()、prepare_batch_plan()、prepare_chapter_package()、prepare_execution() 的实际行为。
2. 解决 Batch 模式是否需要停在“请审阅全书续写规划”的不一致。
3. 确认 wait_chapter_review 从验收分支进入后有可继续执行路径。

决策规则：
1. 如果 design/spec 明确 Batch 模式应确认全书规划，则实现 Batch 在 Freeze A 前停留并补测试。
2. 如果现有产品意图是 Batch 跳过 Freeze A 人工确认，则更新 mode definition / tasks 注释，并补测试证明行为一致。
3. 不允许保留“文档说 A、代码做 B”的状态。

验收：
- Batch 模式 Freeze A 行为一致性测试通过。
- wait_chapter_review 可继续路径测试通过。
- 没有破坏 Assist / Auto 模式现有测试。
- 完成后勾选 Task 19。
```

## Prompt 5: Task 20 测试与快照验收

```text
你的角色：Writer-Status-Test-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 20。

测试必须覆盖：
1. 状态翻译单测，覆盖所有 Writer 用户确认点。
2. CLI 输出测试，断言主输出不包含 artifact saved、Freeze B pending、freeze_d_review、wait_chapter_acceptance。
3. GUI 状态/按钮文案测试或 presenter 快照测试。
4. wait_chapter_acceptance 四分支中文文案测试：
   - accepted -> 请确认写回 / 本章已完成路径
   - revise_length -> 请确认章节长度与节奏
   - replan_chapter -> 请调整章节规划后重写
   - discarded -> 流程已暂停
5. wait_chapter_review 可继续路径测试。
6. Batch 模式 Freeze A 行为一致性测试。

建议关注测试文件：
- novel_agent/tests/test_run_interactive_pipeline.py
- novel_agent/tests/test_writer_execution_workflow.py
- 可新增专门的 presenter 测试文件

验收：
- 目标测试通过。
- 若全量测试过慢，可运行相关测试子集并说明。
- 完成后勾选 Task 20。
```

## Prompt 6: 一次性完成 Outline Research Loop / 交互式大纲扩写落地

```text
你的角色：Writer-Outline-Research-Implementer。

工作目录：/Users/luliao/agent/smolagents

任务目标：
尽可能一次性完成 .trae/specs/writer-agent-layered-generation/tasks.md 中 `Group I: Outline Research Loop 落地` 的 Task 47、Task 48、Task 49、Task 50、Task 51、Task 52、Task 53、Task 54。

这组任务的产品目标是：Writer 在生成高密度大纲前，不再只依赖 Agent 预组装的大 prompt，而是先给模型一个精炼的 OutlineSeedPacket，让模型自己提出需要进一步了解的 story_detail / character_profile / world_concept / structure_pattern 请求；本地 Agent 再把这些语义请求解析为 Memory / SQLite / Markdown / KB 查询；经过多轮 tool-call-like research 后，由模型判断信息是否足够。如果信息不足，模型必须返回具体 blocking gaps 和需要用户补充的问题；如果可以带假设继续，必须把 assumptions 显式写入规划产物。

必须先阅读：
1. AGENTS.md
2. .trae/specs/spec.md
3. .trae/specs/writer-agent-layered-generation/spec.md
4. .trae/specs/writer-agent-layered-generation/design.md
5. .trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md
6. .trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md
7. .trae/specs/writer-agent-layered-generation/tasks.md 的 Group I
8. .trae/specs/cli-interface/design.md 的 Writer 大纲研究循环交互映射
9. .trae/specs/narrative-memory-context/spec.md
10. .trae/specs/creative-knowledge-base/spec.md 或现有 KB 服务实现

建议重点阅读代码：
1. novel_agent/app/orchestrators/writer_layered_generation.py
2. novel_agent/app/orchestrators/writer_workflow.py
3. novel_agent/app/orchestrators/writer_execution.py
4. novel_agent/app/schemas/orchestration_schema.py
5. novel_agent/app/services/outline_service.py
6. novel_agent/app/services/
7. novel_agent/app/repos/
8. novel_agent/app/runner/close_read_runner.py
9. novel_agent/runs/writer.py
10. novel_agent/tests/test_writer_layered_generation_orchestrator.py
11. novel_agent/tests/test_writer_execution_workflow.py
12. novel_agent/tests/test_cli_textual_components.py

如果某些文件不存在，请先用 `rg --files` 和 `rg` 找到等价实现，不要硬编码不存在路径。

实现总原则：
1. 遵守 OOP 原则，保持 Pythonic，新增功能必须有单元测试或 workflow 测试。
2. 不要做无关重构，不要改动与 Outline Research Loop 无关的 Writer 行为。
3. 默认测试不得触发真实 LLM、不得访问互联网；模型调用使用 fake adapter / stub。
4. CLI / TUI 只作为交互外壳；本任务重点在 Writer orchestration / service / schema / tests。不要把 prompt 组装、Memory 查询、SQLite 查询或文件写入放到 CLI 层。
5. Writer 初始 prompt 不能塞入完整 Memory、完整人物档案、完整世界观、完整历史时间线。必须通过 OutlineSeedPacket 提供索引级候选信息，再由模型提出 ResearchRequest。
6. tool-call-like research 不是让模型直接查询本地数据库。模型只返回结构化 ResearchRequest；本地 Context Broker / resolver 负责翻译和查询。
7. candidate / inferred / assumption 不能被当作 confirmed fact。所有进入 planning_notebook 的信息必须带 fact_status 和 sources。
8. 如果预算耗尽，不得静默继续。必须进入 Sufficiency Gate，返回 enough / needs_user_input / proceed_with_assumptions / blocked 之一。
9. 用户补充信息只能作为 `user_authorized` evidence，不得直接写入正式 Memory，除非另有明确的 Memory 写回流程和用户确认。
10. 不要删除用户已有改动；如果发现工作区已有相关改动，先读懂并在其上继续。

建议实现顺序：

阶段 1：Task 47，运行时 schema 与落盘结构
- 在合适的 schema 模块中定义或补齐：
  - OutlineSeedPacket
  - ExtractedCharacterMentions
  - CharacterMentionResolution
  - ResearchRequest，覆盖 story_detail、character_profile、world_concept、structure_pattern
  - ResearchBudget
  - StoryDetailResult / ResearchResult
  - PlanningNotebook
  - SufficiencyDecision，覆盖 enough / needs_user_input / proceed_with_assumptions / blocked
- 设计稳定 JSON 序列化，支持 runs 目录落盘：
  - outline_seed_packet.json
  - outline_research_trace.json
  - planning_notebook.json
  - sufficiency_decision.json
- 补 schema 测试：序列化、缺字段、非法 status、source path / artifact path 关联。

阶段 2：Task 48，用户概述人物提及抽取与 Character Memory 对齐
- 从 user_story_overview、desired_actions、avoidances、preferred_outcome、notes 中抽取人物姓名、称谓、别名、上下文片段、置信度和 possible role hint。
- 实现或接入 Character Memory / alias / evidence 对齐，输出 resolved / ambiguous / missing。
- resolved 必须绑定既有 character_id；ambiguous 生成用户选择请求；missing 生成是否新增人物的确认请求。
- 未经用户确认新增的人名不得进入 CharacterCastPlan。
- 补测试：既有人物命中、别名命中、多候选歧义、缺失人物、用户拒绝新增。

阶段 3：Task 49，OutlineSeedPacket 装配
- 汇总用户意图、故事规模、高潮输入、人物提及对齐结果。
- 装配可查询人物索引：只包含姓名、别名、极短标签，不展开完整档案。
- 装配世界观精炼梗概和世界观概念名词索引。
- 装配历史故事精炼总览和当前续写起点。
- 可选装配未决伏笔 / SourceArcMap / ArcPatternCard 的标题级索引。
- 增加快照测试，断言 seed packet 信息密度、字段边界和不包含完整 Memory。

阶段 4：Task 50，Context Broker 与 request resolver
- 实现 Context Broker，接收 ResearchRequest，调用对应 resolver，返回 ResearchResult。
- character_profile resolver 返回人物状态、能力边界、关系状态、最近变化、fact_status、sources。
- world_concept resolver 返回规则、限制、代价、例外、禁止突破点、fact_status、sources。
- structure_pattern resolver 调用 KB 层结构模式 / ArcPatternCard 检索，返回候选与来源。
- 支持请求去重、预算不足时低优先级降级、结果裁剪。
- 测试必须覆盖来源记录、裁剪、重复请求合并、candidate 不被当 confirmed。

阶段 5：Task 51，Story Detail Resolver 与历史大纲索引
- 定义最低可用 ChapterSummaryIndex。每条摘要保存人物、概念、事件概要、结果、source document / chapter / segment 位置。
- 设计可升级 HistoricalOutlineEventIndex 事件卡结构。
- 实现 story_detail query understanding：把自然语言 query 解析为 characters、concepts、event intent、time hints、facets_needed。
- 用章节摘要 / 事件卡检索候选，并做 rerank。
- 返回 matches、confidence、covered_facets、missing_facets、sources。
- 只展开高相关候选的详细材料。
- 测试覆盖“最近一次信任冲突”“某伏笔来源”“某事件结果”等自然语言 query。

阶段 6：Task 52，Outline Research Loop 控制器与预算门禁
- 根据 OutlineSeedPacket 调用模型，要求模型返回结构化 ResearchRequest 列表或 SufficiencyDecision。
- 每一轮调用 Context Broker，把 ResearchResult 回传模型。
- 维护 planning_notebook：confirmed facts、candidate facts、constraints、candidate plot moves、blocked plot moves、open questions、assumptions。
- 执行 ResearchBudget：
  - max_rounds
  - max_requests_per_round
  - max_total_requests
  - max_return_tokens_per_request
- 预算耗尽后必须进入 Sufficiency Gate。
- 支持 needs_user_input：暂停 workflow，保存 blocking questions，等待用户补充后继续一小轮 research 或进入大纲生成。
- 支持 proceed_with_assumptions：允许低风险继续，但 assumptions 必须进入 BookContinuationPlan sources / assumptions。
- 支持 blocked：返回 required_actions，不生成正式 BookContinuationPlan。
- 测试覆盖多轮请求、预算耗尽、用户补充、带假设继续、blocked。

阶段 7：Task 53，接入 Book / Batch / Chapter 规划
- 在生成 BookContinuationPlan 前执行 Outline Research Loop。
- 将 planning_notebook 和 SufficiencyDecision 作为 Book Planner 输入。
- needs_user_input 时进入可恢复等待态，不推进 Freeze A。
- proceed_with_assumptions 时生成低风险草案，并把 assumptions 标注到正式大纲。
- blocked 时提示缺失建模步骤，不生成正式 BookContinuationPlan。
- Batch / Chapter 规划可以复用已有 planning_notebook，必要时追加局部 research，但不要每次无脑重跑完整 research。
- 增加端到端测试：用户概述 -> 人物抽取 -> research -> BookContinuationPlan -> batch_review。

阶段 8：Task 54，测试与 CLI 联动验收基线
- 新增或补齐 novel_agent/tests/test_writer_outline_research.py。
- 单元测试覆盖所有 schema、resolver、sufficiency status。
- workflow 测试覆盖：
  - needs_user_input 暂停与用户回答后继续
  - proceed_with_assumptions 写入正式大纲
  - blocked 不生成正式大纲
  - research trace / planning notebook / sufficiency decision 落盘
- CLI fake facade 测试覆盖 research trace、用户补充问题和继续按钮；如果 CLI 接口尚未实现，只补 facade 层或 ViewModel 边界测试，不要把业务逻辑塞进 CLI。
- 默认测试不得触发真实 LLM；所有模型输出用 fake adapter / stub。

建议的模型适配边界：
- 新增一个 OutlineResearchModelAdapter 或等价接口，至少支持：
  - propose_research_requests(seed_packet, notebook, prior_results, budget_state)
  - decide_sufficiency(seed_packet, notebook, budget_state)
  - generate_outline(seed_packet, notebook, sufficiency_decision)
- 生产 adapter 可以暂时沿用项目现有 LLM 调用方式；测试 adapter 必须 deterministic。
- 模型返回必须做 JSON / schema 校验；非法 JSON、非法 request type、超预算请求、越权字段都不能写入 notebook。

建议的 Context Broker 返回格式：
- request_id
- request_type
- query / key
- results
- fact_status: confirmed | candidate | assumption | user_authorized | missing
- sources
- confidence
- covered_facets
- missing_facets
- token_estimate 或 summary_size

用户补充边界：
- needs_user_input 最多给用户 1-3 个具体问题。
- blocking gaps 必须清楚说明为什么阻塞大纲生成。
- 用户回答进入 planning_notebook 时标记为 user_authorized。
- 高风险缺口包括主要人物身份、终局秘密、世界规则突破、关系跃迁、新人物是否成立。高风险缺口不得自动 proceed_with_assumptions。

真实模型 smoke / benchmark 边界：
- 本任务默认不实现真实 LLM benchmark；但代码结构要允许后续 agentic-benchmark 的 `--outline-research-author-brief` 调用正式 Outline Research Loop。
- 不要为了测试绕过正式 Writer 接口另写一套 benchmark-only 大纲 prompt。

完成标准：
1. Task 47-54 对应 checkbox 只有在实现与测试完成后才勾选。
2. 新增/修改测试通过。优先运行：
   - .venv/bin/python -m pytest novel_agent/tests/test_writer_outline_research.py -q
   - .venv/bin/python -m pytest novel_agent/tests/test_writer_execution_workflow.py -q
   - .venv/bin/python -m pytest novel_agent/tests/test_writer_layered_generation_orchestrator.py -q
   - 如果修改 CLI facade / ViewModel，再运行 .venv/bin/python -m pytest novel_agent/tests/test_cli_textual_components.py -q
3. 如果某些测试文件不存在，运行最接近的现有 Writer / CLI 测试，并说明替代原因。
4. `git diff --check` 必须通过。
5. 最终回复列出：
   - 已完成的 Task 编号
   - 修改文件
   - 新增对象 / 服务 / adapter
   - 测试命令与结果
   - 未完成或需要产品决策的阻塞项

强制禁止：
- 不得让 CLI / TUI 直接拼 Writer prompt。
- 不得让 CLI / TUI 直接查 SQLite、Memory 或 Markdown。
- 不得把后续 benchmark reference-only 材料接入 Writer。
- 不得把 assumptions 写成 confirmed facts。
- 不得在默认测试里调用真实 LLM 或互联网。
- 不得重写整个 Writer workflow；保持改动围绕 Outline Research Loop。
```
