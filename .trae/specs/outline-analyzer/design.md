# Outline Analyzer Design

## Agent Reading Guide

先读 [`AGENT_CONTEXT.md`](AGENT_CONTEXT.md) 判断是否需要展开本文。Analyzer
是只读分析链路，默认按环节阅读：

- Session / seed / loop：读第 2、3、4、5 节。
- Evidence 选择、章节选择、raw excerpt 升级：读第 6 节。
- Prompt 行为：读第 7、8 节，并回查 [`prompts.md`](prompts.md)。
- Web / CLI 接入：读第 9、10 节。
- 错误处理和 smoke benchmark：读第 11、12 节。

## 1. Design Goal

Outline Analyzer 的设计目标是把“分析一本小说”拆成可控的 Agent Loop：

- 首轮只给模型轻量地图，不喂整本书。
- 模型像代码阅读 agent 一样提出“我还需要看什么”。
- 共享 `NarrativeInquiryBroker` 将语义请求翻译成 Memory、章节摘要、人物档案、世界观、源作品篇章地图或原文摘录查询。
- 模型在有限预算内逐步形成临时分析笔记。
- 最终只在会话中回答用户，不写入 Writer workflow。

这与 Writer Outline Research Loop 相似，但 Analyzer 的输出不是 `BookContinuationPlan`，而是面向用户的剧情分析、可选走向和阅读建议。

## 2. High-Level Flow

```text
User chat message
  -> Analyzer Session Controller
  -> Build AnalyzerSeedPacket
  -> Analyzer Model: plan next information needs
  -> NarrativeInquiryBroker resolves research requests
  -> Analyzer Model updates AnalyzerNotebook
  -> repeat until ready / budget exhausted / needs user preference
  -> Answer in conversation stream
```

首版可以同步执行；后续若一次分析需要多轮原文回读，可以升级为可取消的后台 job。但即使后台化，用户语义仍应是“和小说专家聊天”，不是 Writer run。

## 3. Components

### 3.1 Analyzer Session Controller

职责：

- 接收 Web / CLI 的 Analyzer 消息。
- 读取当前 `book_id`、用户问题和 Analyzer 会话历史。
- 构造 `AnalyzerSeedPacket`。
- 管理 research budget。
- 调用模型和 `NarrativeInquiryBroker`。
- 将最终答案追加到会话流。

不负责：

- 生成 Writer artifact。
- 修改 Memory。
- 自动把 Analyzer 结果提交给 Writer。

### 3.2 AnalyzerSeedBuilder

职责：

- 从当前 book 的 Memory 和 artifact 中生成轻量 seed。
- 控制 seed 文本预算。
- 只提供索引和摘要入口，不展开完整原文。

推荐输入来源：

- `ModelingStatus`
- 故事大纲摘要和未决线程索引
- 世界观压缩摘要和概念索引
- 人物索引
- 章节标题 / chapter index / 极短 summary hint
- SourceArcMap 的 arc index
- Memory BTree root / outline segment page roots
- 当前 Analyzer 会话摘要

SeedBuilder SHOULD 优先读取结构化 Memory；只有缺失时才回退到 Markdown artifact 摘要。

### 3.3 Analyzer Model

职责：

- 根据 seed 和用户问题判断还需要哪些信息。
- 生成语义型 research request。
- 阅读 evidence bundle。
- 更新临时 `AnalyzerNotebook`。
- 判断是否已经足够回答。
- 生成用户可读分析。

模型 SHALL 使用结构化 loop 输出，而不是自由文本中夹杂工具请求。

推荐每轮输出：

```json
{
  "status": "need_more_info",
  "requests": [
    {
      "type": "story_detail",
      "query": "旧案证据来源的首次出现和当前未解状态",
      "purpose": "判断它是否适合作为下一阶段回收伏笔",
      "priority": "high",
      "expected_depth": "chapter_summary"
    }
  ],
  "notebook_delta": {
    "confirmed_facts": [],
    "reasonable_inferences": [],
    "uncertain_gaps": [],
    "candidate_directions": [],
    "chapters_worth_raw_read": []
  }
}
```

### 3.4 NarrativeInquiryBroker

职责：

- 接收模型发出的语义 request。
- 作为 Analyzer、Writer Research 和未来 Reviewer 可复用的共享 evidence harness。
- 将 request 路由到对应 resolver。
- 对 `story_detail`、`chapter_summary`、`raw_excerpt` 等事实型请求，优先调用 `NarrativeMemoryQueryService`，不得直接扫描 Memory SQLite、Markdown 或 documents 绕过 Memory Query Layer。
- 去重、裁剪、排序 evidence。
- 返回带来源和置信标注的 evidence bundle。

推荐 resolver：

- `StoryOverviewResolver`
- `OpenThreadResolver`
- `StoryDetailResolver`
- `CharacterProfileResolver`
- `WorldConceptResolver`
- `SourceArcResolver`
- `ChapterSummaryResolver`
- `RawExcerptResolver`
- `StructurePatternResolver`

Broker 不应自行生成剧情建议，也不应把 evidence 写回 Memory。

#### 3.4.1 与 Memory Query Layer 的分工

`NarrativeMemoryQueryService` 是事实检索内核，负责从 BTree-like Memory 中定位证据：

- `root_scan(query)`：返回 `outline_root` / `outline_segment` Page 候选。
- `drill_down(state, selected_ids)`：确定性展开到下一层候选。
- `resolve_outline_segment_refs(segment_ids)`：展开 outline segment 到 chapter / document refs。
- `resolve_chapter_refs(chapter_refs)`：展开 chapter summary 与 document refs。
- `resolve_document_refs(doc_ids, excerpt_budget)`：返回受预算裁剪的原文摘录。

`NarrativeInquiryBroker` 是跨 agent 的语义路由层，负责把上层 request 转成一个或多个 Narrative Indexer / Memory Query / Character / World / SourceArc / Creative KB 查询，并把结果归并为统一 `EvidenceBundle`。

`AnalyzerAgent` 只消费 evidence 并做文学分析，不拥有自己的检索系统。

推荐边界：

```text
AnalyzerAgent / WriterResearchAgent / ReviewerAgent
  -> NarrativeInquiryBroker
  -> NarrativeIndexFacade
  -> NarrativeMemoryQueryService + Character / World / SourceArc / Creative KB resolvers
  -> EvidenceBundle + trace
```

因此：

- Narrative Indexer 回答“哪些 compact cards 最可能相关、它们适合 Analyzer / Writer / Reviewer 哪类消费、摘要是否足够、是否建议回读原文”。
- Memory Query 回答“证据在哪里、事实是否被支持、对应 chapter / document / excerpt 是什么”。
- Analyzer 回答“这些事实在剧情结构上意味着什么、哪些走向合理、风险在哪里、还应该讨论什么”。
- Writer Research 回答“基于这些事实应生成或修订什么规划 artifact”。
- Reviewer 回答“生成结果是否违反这些事实或文学目标”。

#### 3.4.2 统一 EvidenceBundle

Broker 返回给上层 agent 的结果 SHOULD 统一为 evidence bundle，而不是各 resolver 自由返回文本。

推荐字段：

```json
{
  "request_id": "req-001",
  "request_type": "story_detail",
  "query": "旧案证据来源的首次出现和当前未解状态",
  "status": "found",
  "fact_status": "confirmed | candidate | missing | conflicting | insufficient_context",
  "evidence_items": [],
  "chapter_refs": [],
  "source_doc_ids": [],
  "excerpts": [],
  "sources": [],
  "missing_facets": [],
  "trace": []
}
```

`EvidenceBundle` 可以包含摘要层证据，也可以包含 document excerpts；上层 agent 不应假设每次查询都会返回原文。

#### 3.4.3 Shared Request Types

Analyzer、Writer Research 和 Reviewer SHOULD 尽量复用同一套 request type：

- `story_detail`
- `fact_check`
- `related_documents`
- `chapter_summary`
- `character_profile`
- `world_concept`
- `source_arc`
- `open_threads`
- `raw_excerpt`
- `structure_pattern`

其中：

- `story_detail` 用于事件、因果链、伏笔状态、关系转折。
- `fact_check` 用于判断某个事实是否被 Memory / 原文支持。
- `related_documents` 用于返回与概念、人物、事件相关的 chapter / document refs。
- `raw_excerpt` 只能在摘要层不足时使用，并必须带 read reason。

这些 request type 的语义归属在 `NarrativeInquiryBroker`，不应由 Analyzer 单独定义一套平行字段。

### 3.5 AnalyzerNotebook

职责：

- 保存当前分析过程中的临时结论。
- 支持模型在多轮查询中避免重复检索。
- 支持最终回答引用依据。

存储策略：

- 首版可以只存在内存中，并随最终消息 payload 返回简要 trace。
- Debug 模式可以落盘到 `runs/analyzer/<session_id>/trace.json`。
- 不得写入 `.memory`、Creative KB 或 Writer artifact。

## 4. Initial Seed Strategy

Analyzer 不能从“全文阅读”开始，而应从“小说地图”开始。

### 4.1 Minimal Seed

当用户第一次点击“小说专家意见”或提出 Analyzer 问题时，系统 SHOULD 装配：

- 用户当前问题。
- 最近 Analyzer 对话摘要。
- 建模准备度。
- 全书极短总览。
- 未决伏笔 / open thread 标题级索引。
- 人物索引。
- 世界观概念索引。
- SourceArcMap 的篇章列表。
- Chapter index：章节号、标题、极短摘要、重要度。
- Memory outline segment root pages。

这一步的目标不是让模型立刻回答所有问题，而是让模型知道“哪里可以继续查”。

### 4.2 Question-Aware Seed Trimming

如果章节数量很多，SeedBuilder SHOULD 根据用户问题做轻量筛选：

- 关键词命中 open thread、人物、世界观概念、章节标题。
- 续写位置附近章节优先。
- SourceArcMap 当前 arc 和相邻 arc 优先。
- 重要度高、伏笔密集、关系变化大的章节优先。

注意：这种筛选只能用于 seed 裁剪，不得作为最终语义判断。真正的“需要看哪些章节”由 Analyzer Model 在 loop 中决定。

### 4.3 Analyzer Retrieval Loop

Analyzer 每次回答 SHOULD 使用固定的探索-过滤-提交链路，而不是把 seed、全部 evidence 和历史对话一次性塞进最终 prompt。

推荐阶段：

1. `Seed`
   - 输入 `AnalyzerSeedPacket`。
   - 只包含 story overview、outline segment roots、source arc index、world concept index、命中角色索引和必要会话摘要。
   - 不展开完整章节摘要、完整人物档案或原文。
2. `Plan`
   - 模型把用户问题转成结构化 research intent。
   - 优先生成 `index_card_search` / `factual_event_card_search` / `character_state_card_search` / `mystery_card_search` / `theme_signal_card_search`。
   - 只有当 compact cards 不足时，才请求 Memory BTree descent 或 raw excerpt。
3. `Retrieve`
   - `NarrativeInquiryBroker` 调用 `NarrativeIndexFacade`、Memory Query、Character、World、SourceArc 或 Creative KB resolver。
   - 返回 compact candidate evidence，不直接进入长期上下文。
4. `Triage`
   - 候选 evidence SHOULD 逐条或小批量交给模型判断相关性。
   - 模型必须输出 selected / rejected / reason / summary_sufficiency 判断。
5. `Commit`
   - 只有 selected evidence 进入 `AnalyzerNotebook` 和后续 prompt。
   - rejected evidence 只进入 trace，不继续进入历史上下文。
6. `Raw Read`
   - 仅当 selected evidence 对当前问题高度相关且摘要不足时触发。
   - request 必须包含 read reason、expected confirmation、affects analysis 和 source refs。

该 loop 的目标是让 Analyzer 的单轮 prompt 远小于全文 baseline，同时允许总过程按需多轮读取；对于百万字小说，应优先增加精确小步读取，而不是扩大单轮上下文。

### 4.4 Conversation Brief

Analyzer 多轮对话需要一个压缩的 `conversation_brief`：

- 只总结用户和 Analyzer 在当前聊天模式中讨论过的问题。
- 标明哪些只是用户偏好，哪些是 Analyzer 候选推断。
- 不得把 Analyzer 上一轮候选走向写成 confirmed fact。

## 5. Research Loop

### 5.1 Loop Algorithm

伪流程：

```text
notebook = empty
seed = build_seed(book_id, question, conversation_history)

for round in max_rounds:
    loop_output = model.plan_or_answer(seed, notebook, evidence_history)

    if loop_output.status == ready_to_answer:
        return model.final_answer(seed, notebook)

    if loop_output.status == needs_user_preference:
        return ask_user_preference(loop_output, notebook)

    if loop_output.status == insufficient_memory:
        return explain_missing_memory(loop_output, notebook)

    requests = budget.filter(loop_output.requests)
    if not requests:
        return answer_with_budget_limit(seed, notebook)

    evidence = broker.resolve(requests)
    notebook.apply(loop_output.notebook_delta)
    evidence_history.append(evidence)

return answer_with_budget_limit(seed, notebook)
```

### 5.2 Budget

推荐默认预算：

```json
{
  "max_rounds": 4,
  "max_requests_per_round": 4,
  "max_total_requests": 10,
  "max_raw_excerpt_requests": 3,
  "max_raw_excerpt_chars_per_request": 3000,
  "max_evidence_chars_per_request": 2500
}
```

预算策略：

- `character_profile`、`world_concept`、`source_arc` 成本较低。
- `chapter_summary` 成本中等。
- `raw_excerpt` 成本最高，必须有选择理由。
- Broker 可以合并重复 request。
- 高优先级 request 优先满足；低优先级 request 可返回索引摘要或跳过。

## 6. Selecting Important Chapters

“哪些章节可能是重点章节，需要阅读原文”是 Analyzer 的核心能力之一。

### 6.1 Candidate Signals

模型和 Broker SHOULD 综合以下信号：

- 用户问题直接提到的人物、地点、组织、物品、世界规则。
- open thread 的首次出现、最近推进、当前未解状态。
- 人物关系发生明显转折的章节。
- SourceArcMap 中的开端、转折、中点、危机、高潮、收束章节。
- 章节摘要中出现高密度因果、秘密、誓约、背叛、调查突破、失败代价。
- Memory Page 中被多个事件引用的关键 chapter。
- close-read 标记的重要度、uncertainty、provisional 状态。
- 与用户续写方向或当前讨论问题高度相关的章节。

### 6.2 Chapter Read Plan

当模型认为需要回读原文时，应先输出 `ChapterReadPlan`，再由 Broker 返回摘录。

推荐字段：

```json
{
  "chapters": [
    {
      "document_title_index": 18,
      "title": "第十八章",
      "read_reason": "旧案证据首次被角色明确质疑，摘要不足以判断证据措辞是否可回收。",
      "expected_confirmation": "确认证据来源、在场人物和角色当时态度。",
      "priority": "high",
      "excerpt_focus": ["证据出现段落", "主角反应", "结尾悬念"]
    }
  ]
}
```

Broker 根据该计划读取有限原文片段：

- 若 document 与 chapter 对齐可靠，读取该 chapter 的相关 document excerpt。
- 若章节过长，先返回章节内 document index 和短摘要，让模型二次选择。
- 若边界不可靠，返回 boundary status，并提示分析置信度下降。

### 6.3 Raw Excerpt Escalation

Analyzer 不应一开始就读原文。推荐升级路径：

1. Seed index。
2. outline segment / source arc。
3. chapter summary。
4. character / world detail。
5. selected raw excerpt。

只有当摘要层无法回答“措辞、动机、在场信息、关系张力、伏笔原句”等问题时，才进入 raw excerpt。

## 7. Prompt Design

### 7.1 System Prompt Requirements

System prompt SHOULD 明确：

- 你是只读 Outline Analyzer。
- 你只能分析和建议，不能写 Memory 或 Writer artifact。
- 不要假装已经读完整本书。
- 先使用 seed 判断信息需求，再请求补充 evidence。
- 必须区分 confirmed fact、reasonable inference、uncertain gap、user preference、speculative option。
- 若需要读原文，必须说明为什么摘要不足以及要确认什么。
- 重大剧情转向必须保守，不替用户授权终局秘密、角色死亡、世界规则突破。
- 分析大纲时必须覆盖文学维度：结构、因果、人物弧线、冲突、伏笔、节奏、主题、世界观约束和读者期待。

### 7.2 Loop Prompt Inputs

每轮 prompt 推荐包含：

- `AnalyzerSeedPacket`
- 当前 `AnalyzerNotebook`
- 上轮 evidence bundle 摘要
- 剩余 budget
- 用户当前 question
- 最近 Analyzer conversation brief
- 可用 request types 和字段说明

### 7.3 Final Answer Prompt

最终回答 prompt 推荐要求：

- 先给结论。
- 按“结论 / 文学分析 / 事实依据 / 风险 / 可选走向 / 建议回读章节 / 需要用户确认”组织。
- 如果证据不足，明确写出不足点。
- 不输出 JSON，除非用户要求技术详情。

## 8. Literary Analysis Dimensions

Analyzer 的价值不只是查询事实，还要帮助用户判断“这个故事往哪里走更像一部合理的小说”。因此 Analyzer prompt SHOULD 明确要求模型从文学结构层面分析大纲。

### 8.1 Plot Architecture

分析问题：

- 当前故事处于开端、发展、中点、危机、高潮、收束中的哪个结构位置。
- 主线目标是否清晰，阶段目标是否足以驱动下一批剧情。
- 新走向是否承接已发生事件，而不是凭空转向。
- 当前大纲是否存在“事件堆叠但缺少推进”的问题。

输出建议：

- 指出当前最应该推进的主线或支线。
- 标记不适合提前消费的高潮、秘密或终局信息。
- 给出 2-4 个结构上可行的后续走向，并说明各自适合的章节位置。

### 8.2 Causality And Motivation

分析问题：

- 每个候选走向是否有足够前因。
- 角色为什么现在行动，而不是更早或更晚。
- 冲突升级是否有可见触发点、代价和后果。
- 是否存在“作者想让事情发生，但角色没有理由这么做”的断裂。

输出建议：

- 列出需要补足的动机、信息差、外部压力或关系刺激。
- 对缺乏因果支撑的走向提出替代触发条件。

### 8.3 Character Arcs And Relationships

分析问题：

- 主要人物当前欲望、恐惧、误判、秘密和关系状态是什么。
- 候选走向是否推进人物弧线，而不只是推进事件。
- 关系变化是否有铺垫，是否越过了当前信任、敌意、亲密度或阵营边界。
- 人物是否在重复旧状态，还是产生了新的选择压力。

输出建议：

- 指出下一阶段最值得推进的人物关系。
- 标记需要保持克制的人物突破。
- 对重要角色给出“可推进 / 应延迟 / 需先补证据”的判断。

### 8.4 Conflict And Stakes

分析问题：

- 当前核心冲突是什么：外部阻力、人物关系、道德选择、秘密暴露、世界规则限制。
- 冲突是否升级，还是只是换场景。
- 失败代价是否具体。
- 候选走向是否能制造新的选择困境。

输出建议：

- 给出能提高张力但不破坏原作逻辑的压力来源。
- 区分短期小冲突、中期结构冲突和长期终局冲突。

### 8.5 Foreshadowing, Mystery, And Payoff

分析问题：

- 哪些伏笔已经铺设，哪些已经推进，哪些仍悬而未决。
- 某个未解之谜现在是否适合回收。
- 回收会不会过早削弱悬念。
- 是否需要先增加误导、代价、局部答案或新问题。

输出建议：

- 将未解之谜分为 `ready_to_payoff`、`needs_more_setup`、`should_delay`。
- 给出“局部回收 / 反转回收 / 延迟回收 / 转移焦点”的方案。

### 8.6 Pacing And Chapter Function

分析问题：

- 当前节奏是铺垫、调查、对抗、情感沉淀、信息爆发还是收束。
- 下一章或下一批章节应承担什么功能。
- 是否连续多章功能重复。
- 是否需要在高强度情节后安排缓冲，或在拖慢后引入转折。

输出建议：

- 建议下一阶段章节功能，例如调查推进、关系试探、小高潮、失败代价、真相碎片。
- 标记重点章、过渡章、高潮前铺垫章。

### 8.7 Theme And Emotional Throughline

分析问题：

- 当前故事的核心主题或情感命题是什么。
- 候选走向是否强化主题，而不是只服务情节刺激。
- 人物选择是否能形成情感回响。
- 情绪曲线是否从上一阶段自然延续。

输出建议：

- 给出每个候选走向对应的情绪收益。
- 标记可能导致主题漂移或情绪割裂的设计。

### 8.8 Worldbuilding And Rule Consistency

分析问题：

- 候选走向是否违反已建立的世界规则、能力限制、组织逻辑、地理和历史事实。
- 是否新增了过强设定、便利道具或无代价解决方案。
- 世界规则是否能制造限制，而不是只提供解法。

输出建议：

- 明确哪些世界观规则必须查询或确认。
- 对新增设定提出“最小补全”建议，只补剧情真正需要的规则。

### 8.9 Reader Expectation And Genre Contract

分析问题：

- 原作类型和当前篇章承诺了什么读者期待。
- 候选走向是否满足、延迟满足或反转这些期待。
- 反转是否公平，是否有足够铺垫。
- 是否突然切换类型，造成阅读契约断裂。

输出建议：

- 说明某个走向会带来怎样的读者期待。
- 标记需要提前铺垫的反转或类型变化。

### 8.10 Continuation Quality Rubric

Analyzer 最终可用以下 rubric 评价候选走向：

```text
1. Canon fit：是否符合已确认事实和世界规则。
2. Causal strength：前因、触发、行动、后果是否连续。
3. Character pressure：是否给人物带来新的选择压力。
4. Tension growth：冲突和代价是否升级。
5. Clue resolution rhythm：重要线索或秘密是否揭示得过早、拖得过久，或缺少必要铺垫。
6. Pacing fit：是否适合当前章节功能和篇章位置。
7. Thematic resonance：是否强化主题和情绪主线。
8. Reader promise：是否符合类型与读者期待。
```

Analyzer 不需要每次完整输出八项评分，但 prompt SHOULD 鼓励模型至少覆盖与当前问题最相关的 3-5 项。

## 9. Web Integration

### 9.1 Interaction

Web Conversation Pane SHOULD：

- 在顶部提供“小说专家意见”按钮。
- 启用后，输入框进入 Analyzer mode。
- 显示上下文提示，例如“正在和小说专家讨论剧情”。
- 发送消息时带 `payload.channel = outline_analyzer`。
- Analyzer 回复仍显示为普通 assistant message。
- 退出模式后，输入框恢复普通自然语言或 Writer gate 上下文。

### 9.2 Coexistence With Writer Gates

当 Writer 正处于 review gate：

- 用户可以切换到 Analyzer mode 讨论如何审阅。
- Analyzer 不得自动提交 Writer 决策。
- 若用户要采纳 Analyzer 建议，必须手动把建议写入 Writer 的补充或修订反馈。

后续 MAY 增加显式按钮：

- “采纳为 Writer 补充说明”
- “采纳为修订反馈草稿”

但该按钮必须生成结构化 user action，且用户可编辑确认。

## 10. CLI Integration

CLI / TUI MAY 提供：

- `/analyze <question>`
- `/analyzer`
- 命令面板中的“小说专家意见”

CLI 与 Web 语义保持一致：

- 默认只输出聊天回答。
- 不自动推进 Writer。
- 若输出建议回读章节，应展示为可读列表，不展示内部 SQL 或 raw ids 作为主内容。

## 11. Error Handling

### 11.1 No Model

如果缺少模型或模型不可用：

- 返回用户可见错误：“Analyzer 需要可用模型才能进行剧情分析。”
- 可以说明已完成只读上下文装配。
- 不得返回本地 heuristic 生成的剧情判断。

### 11.2 Missing Memory

如果缺少必要建模：

- 若没有 documents：提示先导入原文。
- 若没有 close-read：提示只能做低置信粗读分析，建议先精读。
- 若没有人物档案：人物动机和关系分析需要标记为不稳定。
- 若没有故事大纲或 source arc：宏观结构判断需要标记为不稳定。

### 11.3 Model JSON Failure

Loop 输出 JSON 解析失败时：

- 可在有限次数内重试。
- 重试后仍失败，返回 `failed` 或 `blocked`，并在技术详情保留错误。
- 不得改用本地 deterministic fallback 生成语义判断。

## 12. Analyzer Smoke Benchmark

Analyzer 需要一条独立 smoke benchmark，用来验证当前 Agent Loop prompt、seed 裁剪、evidence 召回、triage 和 commit 策略是否接近“完整阅读原文”的分析质量，同时显著降低任意单轮 prompt 和总 prompt 成本。

该 benchmark 是评测路径，不是产品路径。产品中的 Analyzer 仍不得一次性把整本小说原文塞进模型 prompt；完整原文只允许在 benchmark baseline 中作为对照组输入。

### 12.1 Benchmark Goal

Smoke benchmark 需要回答两个问题：

1. **质量问题**：Analyzer Agent Loop 是否能主动选择必要背景知识，最终给出与完整原文阅读 baseline 相同或相近的宏观剧情判断。
2. **效率问题**：Analyzer 依赖 close-read / Memory 的高度概括后，任意单轮 prompt 长度是否显著小于 baseline 原文 prompt，总 prompt 长度是否也低于 baseline。

benchmark 重点验证 prompt / retrieval / triage 设计，不评估 Writer 续写质量，也不自动采纳 Analyzer 输出进入 Writer。

### 12.2 Compared Systems

#### A. Full-Raw Baseline

Baseline 使用 `deepseek-pro` 或同等指定模型，单轮调用完成分析：

```text
system: 你是只读小说分析专家。基于完整原文回答用户问题。
user:
  <normalized_full_original_text>

  用户问题：
  <same_analyzer_user_prompt>
```

输入构造规则：

- 从当前 benchmark book 的原始 source document 读取完整文本。
- 仅去除空格、制表符和换行等空白字符，保留中文标点、章节标题、对话标点和可影响语义的符号。
- 不加入 close-read Memory、人物档案、世界观摘要或 Writer artifact，避免 baseline 获得系统额外加工信息。
- 使用与 Analyzer arm 完全相同的 `user_prompt`。
- 单次模型调用必须记录 prompt char / byte / token estimate、模型名、温度、开始结束时间、响应文本和 API 错误。
- baseline answer SHOULD 以 source hash、prompt id、user prompt 和模型配置作为 cache key 复用；除非显式要求刷新，不应在每次调试 Analyzer prompt 时重复请求完整原文 baseline。

Baseline 的作用不是作为绝对真理，而是作为“完整原文可见时模型会得出的强参照答案”。

#### B. Analyzer Agent Loop

Analyzer arm 使用正式项目路径：

```text
source text
  -> rough-read / close-read / Memory build
  -> Outline Analyzer chat
  -> AnalyzerSeedPacket
  -> Plan
  -> NarrativeInquiryBroker evidence
  -> Triage
  -> Commit
  -> repeat
  -> final answer
```

执行要求：

- 必须先对同一小说执行正式粗读 / 精读，生成当前项目的 Memory、章节摘要、人物档案、世界观、故事大纲或可用 close-read artifacts。
- 调用正式 `OutlineAnalyzerService` 或 Web / CLI 等价入口，不得为 benchmark 另写一套 Analyzer prompt。
- 使用与 baseline 完全相同的 `user_prompt`。
- 每轮模型调用必须记录 stage：`loop`、`triage`、`final`，以及 prompt char / byte / token estimate、evidence bundle count、committed evidence ids、rejected evidence ids、request list 和最终 answer。
- 若模型要求读全书原文，Broker 仍必须按产品规则拒绝或拆成受预算 request；benchmark 不得放宽 Analyzer 的产品约束。

### 12.3 Standard User Prompts

Smoke benchmark SHOULD 固定一组可复用 Analyzer prompt，避免每次手工挑题导致不可比较。Prompt 应使用读者自然会提出的问题，避免偏编辑室或实现侧的抽象术语：

- `protagonist_character_and_next_actions`：评价男主角和女主角的人物性格，推测他们之后会采取什么样的行动，或者发生什么样的故事。
- `worldview_story_theme`：概括描述一下本作的世界观是怎样的，这本书讲述了一个什么样的故事，并且以此推测作者想要表达的观点，或者想要传达给读者的思想。
- `style_and_emotional_tone`：评价一下本作的文笔风格与感情基调，有哪些地方写得较为出彩。

每个 prompt 都应在 baseline 和 Analyzer arm 上各运行一次。多轮 Analyzer 对话 benchmark MAY 把上一题的 Analyzer 回复作为会话历史输入下一题，但 baseline 仍应单题单轮运行，便于衡量单问题完整原文参照。

### 12.4 Metrics

benchmark 至少输出以下指标：

#### Prompt Length Metrics

- `baseline.prompt_chars`
- `baseline.prompt_bytes`
- `baseline.prompt_token_estimate`
- `analyzer.max_single_prompt_chars`
- `analyzer.max_single_prompt_bytes`
- `analyzer.total_prompt_chars`
- `analyzer.total_prompt_bytes`
- `analyzer.total_token_estimate`
- `analyzer.round_count`
- `analyzer.triage_count`
- `analyzer.committed_evidence_count`
- `analyzer.rejected_evidence_count`

建议通过标准：

- `analyzer.max_single_prompt_chars <= 0.35 * baseline.prompt_chars`
- `analyzer.total_prompt_chars <= 0.80 * baseline.prompt_chars`
- 若小说很短导致 baseline 本身不长，可降低为 informational，不作为 hard fail。

#### Retrieval And Evidence Metrics

- Analyzer 发出的 request type 分布。
- 每轮候选 evidence 数量和 commit 数量。
- 被 commit 的 evidence 来源类型：`memory_page_root`、`chapter_summary`、`character_profile`、`world_concept`、`raw_excerpt` 等。
- 是否按题型请求了必要的人物档案、人物关系、关键事件、世界观约束、故事总览、章节摘要或代表性原文片段。
- 是否存在明显无关 evidence 被 commit 到后续 prompt。

建议通过标准：

- 对人物性格与后续行动问题，Analyzer 应 commit 男主角、女主角相关人物档案、关系 evidence，以及能支撑后续行动推测的近期故事细节。
- 对世界观、故事与主题问题，Analyzer 应 commit `story_overview`、`world_concept`、`memory_page_root` 或 source arc 等宏观证据，并能把主题判断与具体故事冲突相连。
- 对文笔风格与感情基调问题，Analyzer 应 commit 章节摘要或代表性原文片段；若当前 Memory 缺少可支撑文笔判断的原文片段，应明确说明风格判断主要来自摘要，置信度较低。
- rejected evidence 不得继续出现在后续 prompt 的 committed evidence digest 中。

#### Answer Quality Metrics

答案质量不应只用字符串相似度。benchmark SHOULD 使用一个独立 Reviewer / Judge 调用，比较 baseline answer 与 Analyzer answer：

```json
{
  "same_core_conclusion": 0-5,
  "character_reading_accuracy": 0-5,
  "worldview_theme_coverage": 0-5,
  "style_tone_sensitivity": 0-5,
  "key_evidence_coverage": 0-5,
  "canon_consistency": 0-5,
  "hallucination_or_overclaim_penalty": 0-5,
  "notes": []
}
```

建议通过标准：

- `same_core_conclusion >= 4`
- 当前 prompt 对应的专项评分应 `>= 4`，无关专项评分 MAY 仅作 informational。
- `key_evidence_coverage >= 3`
- `canon_consistency >= 4`
- `hallucination_or_overclaim_penalty <= 1`

Reviewer prompt 必须同时读取：

- benchmark user prompt
- baseline answer
- Analyzer answer
- Analyzer committed evidence digest
- Analyzer trace summary

Reviewer 不应读取完整原文，除非该 run 明确是人工 debug 模式；否则 Reviewer 会把 baseline 的优势直接变成评分泄漏。

### 12.5 Artifacts

每次 benchmark run SHOULD 落盘到：

```text
runs/benchmarks/outline_analyzer/<run_id>/
  config.json
  source_metadata.json
  prompt_set.json
  baseline/
    request_prompt_stats.json
    answer.md
    raw_response.json
  analyzer/
    seed_packet.json
    prompt_stats.json
    loop_trace.json
    committed_evidence.json
    rejected_evidence.json
    answer.md
    raw_response.json
  judge/
    comparison_prompt.json
    comparison_report.json
  summary.json
```

`summary.json` SHOULD 包含：

- baseline 与 Analyzer 的 prompt length 对比。
- 每个 prompt 的质量评分和 pass / fail。
- Analyzer 最长单轮 prompt 所在 stage。
- Analyzer 总 prompt 是否低于 baseline。
- 失败原因分类：`retrieval_miss`、`triage_overcommit`、`triage_overreject`、`memory_gap`、`model_json_failure`、`model_timeout`、`quality_mismatch`。

### 12.6 Pass / Fail Semantics

benchmark 通过不要求 Analyzer 与完整原文 baseline 逐字一致；它要求 Analyzer：

- 抓住相同或高度相近的人物理解、世界观概括、主题判断、文笔风格判断或后续故事推测。
- 能说明主要依据来自哪些 Memory / 人物 / 世界观 / 章节摘要 / 原文片段。
- 不把证据不足的推断说成 confirmed fact。
- prompt 成本显著低于完整原文 baseline。

benchmark 失败时，应输出可行动的诊断：

- 如果 baseline 提到的关键事实完全没有进入 Analyzer evidence，优先调 `AnalyzerSeedPacket` / `NarrativeInquiryBroker` / Memory Query。
- 如果候选 evidence 命中了但被 triage 丢弃，优先调 triage prompt。
- 如果 evidence 已 commit 但最终答案没用上，优先调 loop / final answer prompt。
- 如果 Analyzer 质量接近但总 prompt 超过 baseline，优先调 evidence digest 压缩、conversation brief 和 request budget。

### 12.7 Model And Timeout Settings

由于 long-context 推理时间可能显著长于普通聊天，benchmark runner SHOULD 支持独立超时配置：

- baseline 单次调用超时：默认 10 分钟。
- Analyzer 单轮 loop / triage / final 调用超时：默认 10 分钟。
- Analyzer 整体 run 超时：默认 30 分钟。

所有 timeout 必须记录为显式 `model_timeout`，不得改用本地 heuristic 生成替代答案。

## 13. Implementation Phases

### Phase 1: Minimal Chat Adapter

- Web / CLI 能进入 Analyzer mode。
- Analyzer 读取已有 Memory 摘要和索引，给出单轮回答。
- 无模型时返回 `needs_model`。
- 不写 Memory，不影响 Writer。

### Phase 2: Analyzer Research Loop

- 引入 `AnalyzerSeedPacket`。
- 引入结构化 request / evidence loop。
- 复用 `NarrativeInquiryBroker` 和 `NarrativeMemoryQueryService`，不得实现 Analyzer 私有检索层。
- 支持 `story_detail`、`character_profile`、`world_concept`、`chapter_summary`。
- 输出临时 `AnalyzerNotebook`。

### Phase 3: Important Chapter Selection And Raw Excerpt

- 支持 `ChapterReadPlan`。
- 支持受预算的 `raw_excerpt`。
- 支持解释“为什么这些章节值得读原文”。

### Phase 4: Optional Writer Handoff

- 增加显式“采纳 Analyzer 建议为 Writer 补充说明”的用户动作。
- Handoff 前必须可编辑、可取消、可审阅。
- Analyzer 输出仍不得自动进入 Writer。

## 14. Open Questions

- Analyzer 会话历史是否需要跨浏览器刷新持久化，还是只绑定当前 Web session。
- `AnalyzerNotebook` 是否需要在 debug drawer 中可查看。
- 是否需要为 Analyzer 单独配置模型、预算和温度，避免与 Writer 正式生成共享高成本模型。
- 重要章节 raw excerpt 的最小回源单元是 document、chapter，还是 Memory Page selected leaf。
- 未来 Reviewer 与 Analyzer 如何共用 evidence bundle，而不把 Reviewer 的生成结果审查职责混入 Analyzer。
- Analyzer smoke benchmark 的默认 source fixture 应使用真实用户任务、`longzu_120kb` 缓存样本，还是新增专门的短中篇 fixture。
