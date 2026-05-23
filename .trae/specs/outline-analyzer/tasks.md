# Outline Analyzer Tasks

本任务清单只拆分 Outline Analyzer 与共享 Narrative Inquiry 能力，不替代 [`spec.md`](spec.md)、[`design.md`](design.md)、[`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md) 或 Web / Writer 侧 spec。

## Reading Rules

- 涉及 Analyzer 产品边界、只读约束、聊天模式和输出要求时，必须先读 [`spec.md`](spec.md)。
- 涉及 Analyzer Research Loop、`NarrativeInquiryBroker`、文学分析维度和实现阶段时，必须先读 [`design.md`](design.md)。
- 涉及 Memory Page、BTree descent、事实查询、原文回源和 evidence trace 时，必须先读 [`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md) 与 [`../narrative-memory-context/design.md`](../narrative-memory-context/design.md)。
- 涉及 Web 会话框、结构化消息、普通聊天不推进 workflow 时，必须先读 [`../web-interface/spec.md`](../web-interface/spec.md)。
- 涉及 Writer handoff、采纳 Analyzer 建议进入 Writer prompt 或 Writer review gate 时，必须先读 [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md)。
- 本任务文件不勾选实现状态，除非明确执行对应 QA / 验收。

## Group A: Shared Narrative Inquiry Layer

- [ ] Task A1: 定义共享 `NarrativeInquiryBroker` 边界
  - `来源`: [`design.md`](design.md) 3.4, [`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md)
  - [ ] 明确 `NarrativeInquiryBroker` 是 Analyzer、Writer Research、Reviewer 可复用的 evidence harness
  - [ ] 明确事实型请求必须优先调用 `NarrativeMemoryQueryService`
  - [ ] 禁止上层 agent 直接扫描 Memory SQLite、Markdown 或 documents 绕过 Memory Query Layer
  - [ ] 明确 Broker 不生成剧情建议、不写 Memory、不生成 Writer artifact

- [ ] Task A2: 定义统一 Narrative Inquiry request schema
  - `来源`: [`design.md`](design.md) 3.4.3
  - [ ] 支持 `story_detail`
  - [ ] 支持 `fact_check`
  - [ ] 支持 `related_documents`
  - [ ] 支持 `chapter_summary`
  - [ ] 支持 `character_profile`
  - [ ] 支持 `world_concept`
  - [ ] 支持 `source_arc`
  - [ ] 支持 `open_threads`
  - [ ] 支持 `raw_excerpt`
  - [ ] 支持 `structure_pattern`
  - [ ] 每种 request 必须包含 `query`、`purpose`、`priority` 和可选 `expected_depth`

- [ ] Task A3: 定义统一 `EvidenceBundle`
  - `来源`: [`design.md`](design.md) 3.4.2
  - [ ] 固化字段：`request_id`、`request_type`、`query`、`status`、`fact_status`
  - [ ] 固化证据字段：`evidence_items`、`chapter_refs`、`source_doc_ids`、`excerpts`、`sources`
  - [ ] 固化缺口和可审计字段：`missing_facets`、`trace`
  - [ ] 明确 `EvidenceBundle` 可以停在摘要层，不保证每次都有 document excerpt
  - [ ] 明确 `fact_status` 至少支持 `confirmed / candidate / missing / conflicting / insufficient_context`

- [ ] Task A4: 实现 Broker 到 Memory Query 的适配
  - `来源`: [`design.md`](design.md) 3.4.1, [`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md) 的 BTree Descent Query
  - [ ] `story_detail` 映射到 `NarrativeMemoryQueryService.root_scan / drill_down / resolve_*`
  - [ ] `fact_check` 映射为带事实判断目标的 Memory Query
  - [ ] `related_documents` 映射为 chapter / document refs 查询
  - [ ] `raw_excerpt` 只能基于已选择的 chapter / document refs 执行
  - [ ] 保留 `memory_query_trace`，并并入 `EvidenceBundle.trace`

- [ ] Task A5: 实现 Broker 到 Character / World / SourceArc / Creative KB 的适配
  - `来源`: [`design.md`](design.md) 3.4
  - [ ] `character_profile` 查询人物档案、关系、近期行动和证据状态
  - [ ] `world_concept` 查询世界规则、限制、代价和禁止突破点
  - [ ] `source_arc` 查询源作品篇章地图、结构位置和未回收线索
  - [ ] `open_threads` 查询故事大纲、章节摘要或 source arc 中的未解问题
  - [ ] `structure_pattern` 查询 Creative KB 中的结构模式，不把其结果当作事实 Memory

## Group B: Analyzer Core Loop

- [ ] Task B1: 定义 `AnalyzerSeedPacket`
  - `来源`: [`spec.md`](spec.md) 的 Analyzer Seed Packet, [`design.md`](design.md) 4
  - [ ] 包含 `book_id`、`user_question`、`conversation_brief`
  - [ ] 包含 `modeling_status`
  - [ ] 包含 `story_overview`
  - [ ] 包含 `outline_index` / open thread 标题级索引
  - [ ] 包含 `source_arc_index`
  - [ ] 包含 `character_index`
  - [ ] 包含 `world_concept_index`
  - [ ] 包含 `chapter_index`
  - [ ] 包含 `memory_page_roots`
  - [ ] 保证 seed 只提供可查询地图，不展开完整原文

- [ ] Task B2: 实现 `AnalyzerSeedBuilder`
  - `来源`: [`design.md`](design.md) 3.2, 4
  - [ ] 从当前 book 的结构化 Memory 读取 seed 输入
  - [ ] 缺失结构化 Memory 时可回退到 Markdown artifact 摘要
  - [ ] 控制 seed 文本预算
  - [ ] 对超长小说使用 question-aware seed trimming
  - [ ] 不将 Analyzer 候选推断写入 seed 的 confirmed facts

- [ ] Task B3: 定义 `AnalyzerNotebook`
  - `来源`: [`spec.md`](spec.md) 的 Analyzer Notebook, [`design.md`](design.md) 3.5
  - [ ] 记录 `confirmed_facts`
  - [ ] 记录 `reasonable_inferences`
  - [ ] 记录 `uncertain_gaps`
  - [ ] 记录 `open_threads`
  - [ ] 记录 `candidate_directions`
  - [ ] 记录 `blocked_directions`
  - [ ] 记录 `chapters_worth_raw_read`
  - [ ] 记录来自当前会话的 `user_preferences`
  - [ ] Notebook 不写入正式 `.memory`、Creative KB 或 Writer artifact

- [ ] Task B4: 实现 Analyzer Research Loop
  - `来源`: [`design.md`](design.md) 5
  - [ ] 模型每轮返回结构化 loop output
  - [ ] 支持状态 `need_more_info`
  - [ ] 支持状态 `ready_to_answer`
  - [ ] 支持状态 `needs_user_preference`
  - [ ] 支持状态 `insufficient_memory`
  - [ ] 支持状态 `budget_exhausted`
  - [ ] 每轮将 requests 交给 `NarrativeInquiryBroker`
  - [ ] 每轮将 evidence 和 notebook delta 追加到临时分析状态
  - [ ] 达到预算时返回带缺口声明的暂定分析

- [ ] Task B5: 实现 Analyzer budget 与 raw excerpt 限制
  - `来源`: [`design.md`](design.md) 5.2, 6.3
  - [ ] 支持 `max_rounds`
  - [ ] 支持 `max_requests_per_round`
  - [ ] 支持 `max_total_requests`
  - [ ] 支持 `max_raw_excerpt_requests`
  - [ ] 支持 `max_raw_excerpt_chars_per_request`
  - [ ] 禁止模型请求“读取全部原文”
  - [ ] `raw_excerpt` 必须带 read reason、expected confirmation 和影响的分析判断

## Group C: Literary Analysis Prompt

- [ ] Task C1: 设计 Analyzer system prompt
  - `来源`: [`design.md`](design.md) 7.1, 8
  - [ ] 明确 Analyzer 是只读模块
  - [ ] 明确不能写 Memory、Writer artifact 或推进 workflow
  - [ ] 明确不要声称已经读完整本书
  - [ ] 明确必须区分事实、推断、缺口、用户偏好和候选方案
  - [ ] 明确需要读原文时必须说明为什么摘要不足
  - [ ] 明确重大剧情转向保持保守
  - [ ] 明确分析大纲时覆盖文学维度

- [ ] Task C2: 设计 Analyzer loop prompt
  - `来源`: [`design.md`](design.md) 7.2
  - [ ] 输入 `AnalyzerSeedPacket`
  - [ ] 输入当前 `AnalyzerNotebook`
  - [ ] 输入上轮 `EvidenceBundle` 摘要
  - [ ] 输入剩余 budget
  - [ ] 输入当前用户问题
  - [ ] 输入最近 Analyzer conversation brief
  - [ ] 输入可用 request types 与输出 schema

- [ ] Task C3: 设计 Analyzer final answer prompt
  - `来源`: [`design.md`](design.md) 7.3, 8.10
  - [ ] 输出按“结论 / 文学分析 / 事实依据 / 风险 / 可选走向 / 建议回读章节 / 需要用户确认”组织
  - [ ] 至少覆盖与当前问题最相关的 3-5 项文学维度
  - [ ] 候选走向给出收益、风险和需要确认的问题
  - [ ] 建议回读章节必须给出文学理由和事实确认目标
  - [ ] 默认不输出 JSON，除非用户明确要求技术详情

- [ ] Task C4: 固化文学分析维度 rubric
  - `来源`: [`design.md`](design.md) 8
  - [ ] Plot Architecture：结构位置、主线目标、阶段功能
  - [ ] Causality And Motivation：因果链、行动动机、触发点
  - [ ] Character Arcs And Relationships：人物弧线、关系边界、选择压力
  - [ ] Conflict And Stakes：冲突升级、失败代价、选择困境
  - [ ] Foreshadowing, Mystery, And Payoff：伏笔状态、回收时机、悬念保留
  - [ ] Pacing And Chapter Function：章节功能、节奏重复、重点章与过渡章
  - [ ] Theme And Emotional Throughline：主题、情绪主线、情感回响
  - [ ] Worldbuilding And Rule Consistency：世界观约束、能力限制、最小设定补全
  - [ ] Reader Expectation And Genre Contract：类型承诺、反转公平性、读者期待
  - [ ] Continuation Quality Rubric：Canon fit、因果强度、人物压力、张力增长、伏笔时机、节奏适配、主题共鸣、读者承诺

## Group D: Important Chapter Selection And Raw Excerpt

- [ ] Task D1: 实现 `ChapterReadPlan`
  - `来源`: [`design.md`](design.md) 6.2
  - [ ] 输出 `document_title_index`
  - [ ] 输出章节标题
  - [ ] 输出 `read_reason`
  - [ ] 输出 `expected_confirmation`
  - [ ] 输出 `priority`
  - [ ] 输出 `excerpt_focus`
  - [ ] 不允许无理由直接请求整章全文或整本原文

- [ ] Task D2: 实现重点章节候选信号
  - `来源`: [`design.md`](design.md) 6.1
  - [ ] 用户问题命中人物、地点、组织、物品或世界规则
  - [ ] open thread 首次出现、最近推进和当前未解状态
  - [ ] 人物关系转折章节
  - [ ] SourceArcMap 中的开端、转折、中点、危机、高潮、收束章节
  - [ ] 高密度因果、秘密、背叛、调查突破、失败代价章节
  - [ ] 被多个 IndexCard 或 outline segment 引用的关键章节
  - [ ] close-read 标记的高重要度、uncertainty、provisional 状态

- [ ] Task D3: 实现 raw excerpt escalation
  - `来源`: [`design.md`](design.md) 6.3
  - [ ] 默认从 seed index 开始
  - [ ] 先查询 outline segment / source arc
  - [ ] 再查询 chapter summary
  - [ ] 再查询 character / world detail
  - [ ] 仅当摘要无法回答措辞、动机、在场信息、关系张力、伏笔原句时请求 raw excerpt
  - [ ] `raw_excerpt` 结果必须包含来源、裁剪说明和 trace

## Group E: Web And CLI Integration

- [ ] Task E1: Web 会话框接入 Analyzer mode
  - `来源`: [`spec.md`](spec.md) 的 Analyzer Chat Mode, [`design.md`](design.md) 9
  - [ ] 顶部提供“小说专家意见”按钮
  - [ ] 启用后同一个聊天输入框进入 Analyzer mode
  - [ ] 发送消息时带 `payload.channel = outline_analyzer`
  - [ ] Analyzer 回复作为 assistant message 展示
  - [ ] 退出 Analyzer mode 后恢复普通自然语言或 Writer gate 上下文

- [ ] Task E2: Web 保证 Analyzer 不绕过 Writer gate
  - `来源`: [`design.md`](design.md) 9.2
  - [ ] Writer 正在 review gate 时，用户仍可进入 Analyzer mode 讨论
  - [ ] Analyzer 回复不得自动成为 `supplement_text`
  - [ ] Analyzer 回复不得自动成为 `revision_feedback`
  - [ ] Analyzer 回复不得自动成为 Writer 问题回答
  - [ ] 用户采纳建议时必须显式提交到 Writer 对应结构化 action

- [ ] Task E3: CLI / TUI 接入 Analyzer
  - `来源`: [`design.md`](design.md) 10
  - [ ] 提供 `/analyze <question>`
  - [ ] 提供 `/analyzer` 或命令面板入口
  - [ ] 默认只输出聊天回答
  - [ ] 不自动推进 Writer
  - [ ] 建议回读章节展示为可读列表，不展示内部 SQL 或 raw ids 作为主内容

- [ ] Task E4: 可选 Writer handoff
  - `来源`: [`spec.md`](spec.md) Relationship To Writer, [`design.md`](design.md) Phase 4
  - [ ] 增加显式“采纳 Analyzer 建议为 Writer 补充说明”的用户动作
  - [ ] Handoff 前必须可编辑、可取消、可审阅
  - [ ] Handoff 后通过 Writer 既有结构化 action 提交
  - [ ] Analyzer 输出仍不得自动进入 Writer prompt

## Group F: Testing And Acceptance

- [ ] Task F1: Analyzer 最小冒烟测试
  - `来源`: 用户验收口径：复用已构建 Memory，给出进一步分析结论
  - [ ] 使用已完成粗读 / close-read 的测试 Memory，不重新跑完整续写
  - [ ] 向 Analyzer 提出宏观问题，例如“当前未解之谜哪条最适合下一阶段回收”
  - [ ] 验证 Analyzer 返回进一步分析结论，而不是只回显 Memory 摘要
  - [ ] 验证回答包含事实依据或来源标签
  - [ ] 验证回答包含至少一个风险、缺口或需要用户确认的问题
  - [ ] 验证不写 Memory、不创建 Writer artifact、不推进 Writer workflow

- [ ] Task F2: Memory Query / Analyzer 边界测试
  - `来源`: [`design.md`](design.md) 3.4.1
  - [ ] Memory Query 返回 evidence、chapter refs、document ids、excerpt 和 trace
  - [ ] Analyzer 基于 evidence 输出文学分析和候选走向
  - [ ] Analyzer 不直接扫描 SQLite / Markdown / documents
  - [ ] Broker 层保留 request 与 evidence trace

- [ ] Task F3: EvidenceBundle contract 测试
  - `来源`: [`design.md`](design.md) 3.4.2
  - [ ] 覆盖 found / missing / conflicting / insufficient_context
  - [ ] 覆盖只有摘要层证据、无 excerpt 的返回
  - [ ] 覆盖带 document excerpts 的返回
  - [ ] 覆盖 trace 可解释最终回源 document 的原因

- [ ] Task F4: Analyzer Research Loop 测试
  - `来源`: [`design.md`](design.md) 5
  - [ ] 覆盖 `need_more_info -> ready_to_answer`
  - [ ] 覆盖 `needs_user_preference`
  - [ ] 覆盖 `insufficient_memory`
  - [ ] 覆盖 `budget_exhausted`
  - [ ] 覆盖模型 JSON 失败后有限重试，仍失败返回 failed / blocked
  - [ ] 禁止使用本地 heuristic 伪装语义分析成功

- [ ] Task F5: ChapterReadPlan 与 raw excerpt 测试
  - `来源`: [`design.md`](design.md) 6
  - [ ] 验证摘要不足时生成 ChapterReadPlan
  - [ ] 验证 raw excerpt 带 read reason 和 expected confirmation
  - [ ] 验证 raw excerpt 受预算限制
  - [ ] 验证请求读取整本原文会被拒绝或拆分

- [ ] Task F6: Web / CLI 交互测试
  - `来源`: [`design.md`](design.md) 9, 10
  - [ ] Web 点击“小说专家意见”后消息进入 `outline_analyzer`
  - [ ] Web 普通聊天不进入 Analyzer mode
  - [ ] Writer gate 存在时 Analyzer 不自动提交 Writer action
  - [ ] CLI `/analyze` 只输出 Analyzer 回答，不推进 Writer

## Dependencies

- Task A2 depends on Task A1.
- Task A3 depends on Task A1 and Task A2.
- Task A4 depends on Task A2, Task A3 and existing `NarrativeMemoryQueryService`.
- Task A5 depends on Task A2 and Task A3.
- Task B1 depends on Task A1.
- Task B2 depends on Task B1.
- Task B3 depends on Task B1.
- Task B4 depends on Task A4, Task A5, Task B1 and Task B3.
- Task B5 depends on Task B4.
- Task C1-C4 depend on Task B1 and Task B3.
- Task D1-D3 depend on Task A4 and Task B4.
- Task E1-E3 depend on Task B4 and minimal Analyzer service facade.
- Task E4 depends on Task E1-E2 and Writer structured action contracts.
- Task F1 depends on Task E1 or Task E3 plus a minimal Analyzer service facade.
- Task F2-F5 depend on Task A4, Task B4 and D tasks as applicable.
- Task F6 depends on Task E tasks.
