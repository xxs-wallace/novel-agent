# Analyzer Spec

## Source Of Truth

- 产品级核心流程、用户入口、用户可见状态文案和人工确认规则，以 [`../spec.md`](../spec.md) 为准。
- Web 会话框、结构化消息和主界面交互语义，以 [`../web-interface/spec.md`](../web-interface/spec.md) 为准。
- 事实型 Memory、章节摘要、故事大纲、人物档案、世界观、源作品篇章地图和原文回源规则，以 [`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md) 为准。
- 多维叙事索引、IndexCard family、Creative KB 作为特殊索引的边界，以 [`../narrative-indexer/spec.md`](../narrative-indexer/spec.md) 为准。
- Writer 大纲研究循环可作为参考，但 Analyzer 不属于 Writer workflow，见 [`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md) 和 [`../writer-agent-layered-generation/designs/outline-research-loop.design.md`](../writer-agent-layered-generation/designs/outline-research-loop.design.md)。

## Purpose

Analyzer（原 Outline Analyzer）是一个可选、独立、只读的小说分析模块。历史 Web channel、job type 和本 spec 目录名可以继续使用 `outline_analyzer` 作为兼容标识，但领域服务与用户语义 SHOULD 使用 Analyzer 命名。

它的目标不是直接生成续写 artifact，而是帮助用户和系统在合适的分析工作流中讨论：

- 当前故事已经发生了什么。
- 哪些主线、支线、伏笔、人物关系和世界观约束仍未解决。
- 用户提出的后续走向是否合理。
- 哪些走向需要补充事实证据、用户授权或进一步原文阅读。
- 如果要继续写，哪些历史章节、事件或原文片段最值得重点回读。

Analyzer 的用户可见形态 SHOULD 是会话框中的“小说专家意见”模式。用户可以在不启动 Writer 的情况下，多轮询问当前小说的剧情合理性、未解之谜、角色动机、结构风险和可能走向。

## Product Boundary

Analyzer SHALL：

- 只读取当前 book 的 Memory、索引、粗读导入的原始 documents、close-read 产物和可用 artifacts。
- 只在当前会话消息流中输出分析、建议、问题和候选走向。
- 支持多轮对话，后续问题可引用同一 Analyzer 会话中的上文。
- 在证据不足时显式说明缺口，并可请求进一步读取特定 Memory 节点、章节摘要或原文片段。
- 区分 `confirmed fact`、`reasonable inference`、`uncertain gap`、`user preference` 和 `speculative option`。
- 在推荐故事走向时给出依据、收益、风险、仍需确认的问题。

Analyzer SHALL NOT：

- 修改 Memory、KB、Writer run state、workflow state 或任何正式续写 artifact。
- 把自己的候选走向写入 `BookContinuationPlan`、`BatchPlan`、`ChapterBrief` 或正文草稿。
- 自动触发 Writer 继续执行。
- 把候选推断、低置信读法或用户闲聊偏好升级为正式事实。
- 一次性把整本小说原文塞进模型 prompt。
- 在缺少模型能力时使用本地 heuristic 伪装已经完成语义分析。

## Scope

首版 Scope：

- 支持 `outline_analysis` 和 `relationship_analysis` 两种分析类型。
- `outline_analysis` 支持大纲层 / 全书宏观层分析。
- `relationship_analysis` 支持围绕两个或多个角色的关系、共同经历、情感债务、阵营约束、关系走向和关系线结构风险进行分析。
- 可读取故事大纲、章节摘要、人物档案、世界观、源作品篇章地图、Memory Page root、粗读 documents 摘录。
- 支持模型主导的多轮 Analyzer Research Loop。
- 支持通过共享 `NarrativeInquiryBroker` 发起 grep-like `text_search` 词面定位请求，在 root summary / Memory root、人物档案、outline segment、chapter summary、index card 和受限 document scope 中定位候选章节或 source_doc_ids。
- 支持向用户提出非阻塞讨论问题。
- 支持建议“应重点回读哪些章节或原文片段”。

非首版 Scope：

- 正文章节草稿逐段评审。
- 独立文风 / 文笔专项评审工作流。
- Reviewer 对生成结果的质量审阅。
- 自动把 Analyzer 结论注入 Writer prompt。
- 自动更新 Memory、人物档案、世界观或故事大纲。

## Analyzer Intent Gate And Analysis Types

Analyzer SHALL 在构造本地 root summary 级提示后，通过 `AnalyzerIntentGate` 的模型 seed prompt 识别本轮问题的 `AnalyzerAnalysisType`。Gate 是 Analyzer 的第一个模型步骤：它基于用户问题、会话摘要和本作 root summary 选择工作流、提出极简初始证据方向，并把结果写入 `AnalyzerSeedPacket`。Gate 不负责给出最终语义结论。

首版 `AnalyzerAnalysisType`：

- `outline_analysis`：用于主线 / 支线 / 伏笔 / 结构位置 / 因果链 / 节奏 / 世界观约束 / 后续剧情走向等宏观问题。
- `relationship_analysis`：用于人物关系、感情线、共同经历、关系转折、人物之间的债务或承诺、第三方关系约束、关系线后续设计等问题。

`AnalyzerIntentGate` SHALL：

- 输入用户问题、Analyzer 会话摘要、本作 root summary / root summaries 和两个可用 analysis type 的简短定义。
- 输出 `analysis_type`、`confidence`、`matched_signals`、`required_evidence_plan` 和可选 `secondary_analysis_types`。
- 由模型判断问题属于哪种分析工作流；不得用本地关键词 heuristic 伪装模型已经完成意图判断。
- Gate prompt 只能使用通用、非作品专名的分析类型说明；不得在默认词典、prompt 或测试默认数据中写入只服务某一部小说的角色名、设定名或桥段偏好。
- Gate payload SHALL NOT 包含完整 `AnalyzerSeedPacket`、`character_index`、`world_concept_index`、`sources` 或详细检索地图；这些内容只进入后续 `OutlineAnalyzer` / `RelationshipAnalyzer` workflow prompt。
- 当问题同时包含大纲走向和人物关系时，优先选择最能决定取证路径的类型；例如“某两个人关系如何发展”应进入 `relationship_analysis`，并可在 secondary 中保留 `outline_analysis`。
- 当置信度不足时 SHALL 在 Gate 输出中标记低置信和 secondary 类型，并让后续 loop 先请求澄清性证据或向用户提出非阻塞问题；不得用本地默认值掩盖不确定性。
- 若缺少可用模型或 Gate JSON 无法在重试后解析，Analyzer SHALL 返回 `needs_model` / `failed`，不得创建伪造的 `analysis_type` 继续生产路径。

`outline_analysis` 的默认取证计划 SHOULD：

1. 查看 story overview、outline segment roots、source arc、open threads 和相关 compact cards。
2. 围绕用户问题请求 `index_card_search` / `factual_event_card_search` / `mystery_card_search` / `theme_signal_card_search`。
3. 对命中的 outline segment SHALL 能下钻或映射到对应 chapter summary。
4. 当摘要层不足以判断动机、措辞、在场人物或关系张力时，再请求 `raw_excerpt`。
5. 当语义索引未能定位细节问题时，SHOULD 使用 `text_search` 将问题拆成少量通用关键词，在 outline segment、chapter summary、character profile、index card 等等价 locator 分支中做交集匹配；失败分支只进入 trace，不应污染 notebook 的事实结论。

`relationship_analysis` 的默认取证计划 SHOULD：

1. 识别用户问题中的参与角色；如果角色职能词或称谓不唯一，先列出候选和证据缺口。
2. 查询相关角色的人物档案概述、当前状态、近期变化、`story_events_json`、`relationships_json` 和 `recent_activity_json`。
3. 按 query 关键词和参与角色筛选人物档案中的相关事件，而不是固定截取前若干条。
4. 当关系判断依赖共同经历、付出、救助、冲突、承诺、背叛、身体 / 身份 / 目标变化或其他关系转折时，RelationshipAnalyzer SHOULD 使用 `character_profile` request 的 `metadata.story_events_offset` 分页读取相关角色的 `story_events_json`。单次分页读取的 `story_events` 内容 SHALL 不超过 4KB；返回 evidence SHOULD 包含下一页 offset / total / has_more，以便模型继续翻阅 experience。
5. 构造共同经历候选：综合角色档案交集、人物状态卡、叙事场景卡、chapter summary、outline segment 和必要原文摘录，定位直接互动、关系变化、身份/身体/目标变化、承诺/冲突/救助/背叛/牺牲等通用关系转折。
5a. 若人物档案或语义卡片无法定位共同经历，RelationshipAnalyzer SHOULD 使用 `text_search` 对参与角色名、关系关键词和用户给出的细节关键词做交集定位，再基于候选 chapter/source_doc_ids 请求 `chapter_summary` 或 bounded `raw_excerpt`。
6. 若用户问题涉及已有伴侣、阵营、家族、组织或社会身份约束，查询第三方关系和世界 / 社会规则。
7. 在最终回答中分离已确认事实、基于共同经历的合理推断、证据缺口、可选关系走向和需要用户确认的价值偏好。

## Analyzer Chat Mode

Web 主界面 SHOULD 在会话顶部提供“小说专家意见”按钮。

当用户启用该模式：

- 同一个聊天输入框进入 Analyzer mode。
- 用户消息 SHALL 以结构化 payload 标记，例如 `channel = outline_analyzer`。
- 后端 SHALL 创建 Analyzer 后台任务，而不是在消息接口中同步阻塞调用 Analyzer，也不是走普通自然语言回执或 Writer action。
- 用户消息 SHALL 立即进入消息流；系统 SHOULD 追加或返回可见的“小说专家正在分析”状态，并带可追踪的 `job_id` / `turn_id` 技术详情。
- Analyzer 回复作为普通 assistant message 出现在同一消息流中；任务失败时 SHALL 追加 error message；需要用户补充时 SHALL 追加 assistant message 并保持 Analyzer turn 为未完成状态。
- 用户可退出 Analyzer mode，回到普通 Agent / Writer 输入。

Analyzer mode MAY 与 Writer review gate 并存，但不得绕过 Writer gate：

- 若当前 Writer 正等待用户确认，Analyzer 可以讨论问题和提供建议。
- Analyzer 的回答不得自动成为 Writer 的 `supplement_text`、`revision_feedback` 或 `answer_text`。
- 用户若想采纳 Analyzer 建议，仍必须在 Writer 对应输入框或决策卡中明确提交。

## Analyzer Background Job And Recoverable Turn State

Analyzer SHALL 作为可观测、可恢复的后台任务执行。

- Web Analyzer message endpoint MUST NOT 长时间同步等待模型返回。
- 每条 Analyzer 用户问题 SHOULD 创建一个 `outline_analyzer` job，并绑定一个 `turn_id`。
- `outline_analyzer` job MUST 覆盖当前 task 的用户可见状态，例如“小说专家正在分析剧情”。
- 当 Analyzer job 正在运行时，任务列表和任务详情 SHOULD 显示该 job，而不是只回落到 close-read checkpoint / paused 状态。
- Analyzer job MAY 与 Writer gate 并存，但不得自动确认、提交、恢复或取消 Writer gate。

Analyzer turn 至少支持以下状态：

- `queued`：已收到用户问题，等待后台任务运行。
- `running`：Analyzer loop 正在调用模型、查询证据或整理结论。
- `need_user_input`：Analyzer 已判断必须补充用户偏好、授权边界或上下文；已向用户提问，但最终分析尚未完成。
- `succeeded`：本轮 Analyzer 已输出最终分析结论。
- `failed`：模型、JSON、检索、超时或系统错误导致本轮无法完成。
- `cancelled`：用户或系统取消本轮分析。
- `interrupted_can_resume`：进程重启或中断后发现 turn 尚未完成，且存在足够 trace 可恢复或继续。

Analyzer turn state SHOULD 持久化在当前 book 的 Analyzer 专用目录下，例如 `.memory/analyzer/{book_id}/`。持久化内容 SHOULD 同时支持人工审计和程序恢复：

- `conversation memory`：已完成 Analyzer 对话的压缩历史，供后续 turn 理解上文；它不是正式小说 Memory，不得被 Writer / Analyzer 作为 confirmed canon 直接读取，除非明确标注为 Analyzer 对话上下文。
- `turn metadata`：`book_id`、`turn_id`、`job_id`、`user_message_id`、`assistant_message_id`、状态、时间、错误摘要和 source refs。
- `active notebook`：本轮尚未完成时的 AnalyzerNotebook、已确认 evidence、待确认缺口和用户偏好问题。
- `prompt trace`：本轮尚未完成时，每次模型调用的 prompt 输入、模型结构化输出、research request、broker evidence bundle、triage / commit 结果和 final / need_user_input 依据。

Prompt trace 保留规则：

- 若 turn 已 `succeeded`，系统 SHOULD 将最终回答、sources、结论摘要和必要 conversation memory 写入历史；中间 prompt trace MAY 被删除、压缩或仅作为调试 artifact 保留。
- 若 turn 为 `running`、`need_user_input`、`failed`、`cancelled` 或 `interrupted_can_resume`，系统 MUST 保留本轮已发生的 prompt trace，直到该 turn 产生最终结论或被用户明确废弃。
- `need_user_input` 虽然已经给出 assistant message，但不代表 turn 完成；用户补充信息后，Analyzer SHALL 结合补充文本、active notebook、已提交 evidence 和保留的 prompt trace 继续分析。
- 重启后系统 SHOULD 扫描 Analyzer state；对未完成 turn 恢复为 `need_user_input`、`interrupted_can_resume` 或 `failed`，并在消息流中同步可见状态。
- 系统不得用对话记录重新猜测未完成 turn 的内部状态；若 prompt trace 不足以恢复，必须显式标记 `failed` / `interrupted_can_resume` 并说明需要重新运行。

## Initial Analysis Problem

分析一本小说不能把整本书一次性喂给模型。Analyzer SHALL 使用与 code agent 类似的探索-执行分离：

1. 首轮只给模型轻量的 `AnalyzerSeedPacket`，让模型理解当前小说的可查询地图。
2. 模型根据用户问题和 seed，自主判断还需要哪些信息。
3. 模型发出语义型 research request，而不是直接读取任意文件或编写 SQL。
4. 共享 `NarrativeInquiryBroker` 将 request 翻译为 Narrative Indexer / Memory Query / Character / World / SourceArc / Creative KB 查询。
5. 模型根据返回 evidence 更新 `AnalyzerNotebook`。
6. 信息仍不足时继续请求补充；若需要回读原文，模型必须说明章节或片段的选择理由。
7. 达到预算、信息足够或需要用户偏好确认后，模型给出会话回答。

如果第 7 步返回需要用户补充偏好或授权，Analyzer SHALL 进入 `need_user_input`，并保留本轮 prompt trace 与 notebook；用户补充后继续同一 turn，而不是开启一个仅凭聊天历史的新分析。

## Analyzer Seed Packet

`AnalyzerSeedPacket` 是每次 Analyzer 回答开始时的轻量输入。它不包含完整原文。

推荐字段：

```json
{
  "book_id": "book-001",
  "user_question": "当前未解之谜里哪条最适合下一阶段回收？",
  "analysis_type": "outline_analysis",
  "intent_gate": {
    "confidence": 0.82,
    "matched_signals": ["未解之谜", "下一阶段回收"],
    "required_evidence_plan": ["open_threads", "mystery cards", "outline segment drill-down"]
  },
  "conversation_brief": "本轮对话已讨论过旧案线索和主角信任危机。",
  "modeling_status": {
    "documents_ready": true,
    "close_read_ready": true,
    "character_profiles_ready": true,
    "world_summary_ready": true,
    "story_outline_ready": true,
    "source_arc_map_ready": true
  },
  "story_overview": "全书高层摘要，控制在短文本预算内。",
  "outline_index": [
    {
      "thread_id": "thread-001",
      "title": "旧案证据来源",
      "status_hint": "unresolved",
      "related_chapter_range": "12-18"
    }
  ],
  "source_arc_index": [
    {
      "arc_id": "arc-002",
      "title": "调查转入公开冲突",
      "chapter_range": "20-31",
      "function_hint": "midpoint escalation"
    }
  ],
  "character_index": [
    {
      "character_id": "char-001",
      "canonical_name": "主角",
      "aliases": [],
      "role_hint": "protagonist",
      "status_hint": "active"
    }
  ],
  "world_concept_index": [
    {
      "concept_id": "world-001",
      "term": "关键世界规则",
      "kind": "rule",
      "scope_hint": "能力限制"
    }
  ],
  "chapter_index": [
    {
      "chapter_id": "chapter-012",
      "document_title_index": 12,
      "title": "第十二章",
      "summary_hint": "旧案证据首次浮出水面。",
      "importance_hint": "high"
    }
  ],
  "memory_page_roots": [
    {
      "page_id": "outline-segment-001",
      "page_type": "outline_segment",
      "source_range": "chapter 1-20",
      "summary": "第一阶段主线压缩摘要。"
    }
  ]
}
```

要求：

- Seed 只给模型“可查询入口”，不展开全部章节、人物档案或原文。
- `analysis_type` 和 `intent_gate` 用于约束本轮取证顺序和 prompt 工作流，不得代替 evidence 或最终判断。
- `chapter_index` 可以包含全部章节的标题和极短 hint；若章节数量极大，SHOULD 先返回 outline segment / source arc 级索引。
- `conversation_brief` 只总结当前 Analyzer 会话，不得把 Analyzer 候选推断写成 Memory 事实。
- 若 close-read 尚未完成，Analyzer 可以降级为“粗读文档级分析”，但回答必须标记证据不足。

## Analyzer Research Requests

模型发出的 request 是语义对象，不是 SQL 或文件路径。

统一字段：

```json
{
  "type": "story_detail",
  "query": "旧案证据来源的首次出现、后续影响和当前未解状态",
  "purpose": "判断下一阶段是否适合回收该伏笔",
  "priority": "high",
  "expected_depth": "chapter_summary"
}
```

首版 SHOULD 支持以下 request types：

- `story_overview`：获取更完整的全书或某阶段摘要。
- `open_threads`：查询未解伏笔、未回收关系线、未解决冲突。
- `story_detail`：查询某事件、因果链、冲突或伏笔的历史经过。
- `character_profile`：查询人物状态、目标、关系、能力边界和最近变化。
- `world_concept`：查询世界观规则、限制、代价和禁止突破点。
- `source_arc`：查询源作品篇章地图、结构位置和功能段。
- `chapter_summary`：查询一个或多个章节摘要。
- `raw_excerpt`：在已有摘要不足时，回读特定 document / chapter 的原文摘录。
- `structure_pattern`：查询 Creative KB 中与当前讨论相关的结构模式。
- `index_card_search`：查询 Narrative Indexer 中与当前问题相关的 compact cards。
- `factual_event_card_search`：查询事实事件索引卡片。
- `character_state_card_search`：查询人物状态和关系变化索引卡片。
- `mystery_card_search`：查询伏笔、未解问题和异常线索索引卡片。
- `theme_signal_card_search`：查询主题表达、作者态度和情绪基调索引卡片。

## Raw Text Read Policy

Analyzer MAY 请求读取原文，但必须遵守“必要、可解释、受预算限制”原则。

模型请求 `raw_excerpt` 时 SHALL 说明：

- 为什么章节摘要或大纲不足以回答当前问题。
- 需要回读哪个章节、事件、document 或 source range。
- 期望从原文中确认什么，例如人物动机、语气、证据细节、关系张力、伏笔措辞。
- 这次回读会影响哪一个分析判断。

本地 Broker SHALL：

- 只返回被选中的原文摘录，不返回整本书。
- 优先返回与 request 目的相关的片段、上下文窗口和来源索引。
- 支持将短章节引用（例如 `35`、`chapter-35`、`第35章`）规范化到 Memory chapter id，并可从短章节范围中解析受预算的候选章节。
- 控制单次返回 token / char 预算。
- 在返回结果中标注 `source_doc_ids`、`chapter_index`、`excerpt_type` 和裁剪说明。

当章节摘要、索引卡、`importance_reason`、`importance_facets` 或其他 summary-derived annotation 与其他证据在人物、对象、次数、代价、因果、时间线或在场者等可核验事实上冲突时，Analyzer SHALL 将其视为 candidate/conflicting evidence，并请求 `raw_excerpt` 或更直接的章节事实核验；最终回答必须以原文或更直接事实证据为标准，不得把冲突摘要注释升级为 confirmed fact。

当用户问题要求的回答粒度超过当前 summary / locator evidence 能直接支撑的事实细节时：

- chapter summary、outline segment、index card、人物档案和 `text_search` 结果只能作为定位线索，不能替代缺失的更直接事实证据。
- 是否需要 `raw_excerpt` SHALL 由模型基于 evidence sufficiency 判断：用户问题需要什么事实粒度、拟回答会断言什么、已提交 evidence 是否已经覆盖这些断言。
- 一旦模型判断现有 locator 已收敛到少量候选章节、document 或 source range，但仍无法完整回答，Analyzer SHALL 请求 bounded `raw_excerpt`。
- 若无法通过人物档案、场景卡、chapter summary、outline root / segment 或 `text_search` 将范围收敛到少量章节或 document，Analyzer SHALL 明确说明当前无法定位具体剧情范围，并请求用户提供章节、幕名、前后事件或关键词。
- Analyzer SHALL NOT 从第一章开始无界阅读，也不得在缺少可执行定位时无限循环思考。
- 最终回答在没有 committed evidence 覆盖所需事实粒度时，不得给出超出证据的具体断言，只能说明已定位范围、证据缺口和下一步需要的线索。

Analyzer SHALL NOT 因为模型要求“读取所有原文”而满足该请求。本地 Broker 必须拒绝或拆分为可预算的 request。

## Analyzer Loop State

每轮模型应返回一个 loop state：

```json
{
  "status": "need_more_info",
  "requests": [],
  "notebook_delta": {
    "confirmed_facts": [],
    "reasonable_inferences": [],
    "uncertain_gaps": [],
    "candidate_directions": [],
    "chapters_worth_raw_read": [],
    "questions_for_user": []
  }
}
```

状态枚举：

- `need_more_info`：需要继续查询 Memory、章节摘要、人物、世界观或原文摘录。
- `ready_to_answer`：信息足以回答当前用户问题。
- `needs_user_preference`：资料可支持多个方向，需要用户选择偏好或授权边界。
- `insufficient_memory`：当前建模基础不足，无法做可靠分析。
- `budget_exhausted`：预算耗尽，只能给出带缺口声明的暂定分析。

## Analyzer Notebook

`AnalyzerNotebook` 是单次或单会话内的临时分析笔记。

它 MAY 在运行期保存到 debug trace 或 conversation payload，但 SHALL NOT 写入正式 Memory。

推荐内容：

- `confirmed_facts`：来自 Memory / 原文证据的事实。
- `reasonable_inferences`：基于证据的解释。
- `uncertain_gaps`：证据不足或多解的部分。
- `open_threads`：仍未解决的伏笔、冲突、人物关系或世界观问题。
- `candidate_directions`：可讨论的后续走向。
- `blocked_directions`：不应推进或风险过高的走向。
- `chapters_worth_raw_read`：建议重点回读的章节或原文片段。
- `user_preferences`：当前 Analyzer 对话中用户表达的偏好，必须标明来源为 conversation，不得写入 Memory。

## Response Requirements

Analyzer 回复用户时 SHALL：

- 先给结论或简短判断。
- 说明依据来自哪些来源类型，例如故事大纲、章节摘要、人物档案、原文片段。
- 区分事实、推断、缺口和建议。
- 给出 2-4 个可讨论走向时，说明每个走向的收益、风险和需要确认的问题。
- 对需要原文回读的章节给出选择理由。
- 避免替用户直接决定重大角色命运、终局秘密或世界规则突破。

Analyzer 回复用户时 SHOULD NOT：

- 输出内部 JSON，除非用户明确要求技术详情。
- 把内部 stage、artifact id 或 SQL 查询作为普通主内容。
- 用“我已经完全读完整本书”之类表述夸大上下文覆盖。

## Relationship To Writer

Analyzer 和 Writer 共享 Memory Query / Narrative Inquiry 思想，但职责不同：

- Analyzer 是探索和讨论工具，输出在会话流中，不改变正式 workflow。
- Writer 是执行工具，生成可审阅、可修改、可写回的续写 artifact。
- Analyzer 的 notebook 可在未来作为 Writer 的可选参考输入，但必须经过显式用户动作，例如“采纳这段专家意见作为 Writer 补充说明”。
- 在未定义该显式动作前，Analyzer 输出不得自动进入 Writer prompt。

## Failure And Degraded Modes

- 若没有可用模型，Analyzer SHALL 返回 `needs_model` 或等价用户可见错误，不得生成伪分析。
- 若 Memory 缺失，Analyzer SHALL 说明缺少哪些建模产物，并建议先完成粗读 / 精读 / 人物档案 / 世界观 / 故事大纲。
- 若只有粗读 documents，没有 close-read Memory，Analyzer MAY 只做低置信文档级讨论，并明确标注“未完成精读，分析不稳定”。
- 若 request 超出预算，Broker SHALL 返回预算错误或裁剪结果，Analyzer 必须在回答中说明限制。
