# Outline Research Loop Design

## 1. Purpose

`Outline Research Loop` 用于升级大纲生成：模型不再被动消费编排器一次性组装的大 prompt，而是先看到轻量索引，再通过多轮语义请求主动读取故事细节、人物档案和世界观概念。

本 design 只定义大纲生成前的研究循环、query 语义和本地解析职责。它不替代 Writer workflow、Memory schema 或 SQLite 表结构。

## 2. Design Principles

- 大纲层是最高信息密度层，应承载人物、场景、行动、结果、关系推进、伏笔和禁止提前消费项。
- 初始 prompt 只提供索引入口，不直接塞入完整 Memory。
- LLM 负责判断“我需要了解什么”；本地 Agent 负责把语义请求翻译成 SQLite / Markdown / Memory 查询。
- 每轮检索结果必须带来源，区分 confirmed fact、inference、candidate 和 user-authorized assumption。
- 模型必须能判断信息是否足够；不足时继续查，查不到时向用户提问。
- Outline Research Loop 不直接生成正文。正文层使用独立的 Draft Research Loop 和 Draft Prose Executor；Draft Research Loop 可复用相同的 Memory Query / Context Broker 能力，但查询目标收束为当前章节草稿所需事实。

## 3. Outline Seed Packet

`OutlineSeedPacket` 是研究循环的初始输入，目标是给模型一张可查询地图。

推荐内容：

```json
{
  "user_intent": {
    "desired_actions": ["追查旧案线索"],
    "avoidances": ["不要提前暴露幕后主使"],
    "preferred_outcome": "找到新证据，但反派仍未现身"
  },
  "story_scale": {
    "target_chapter_count": 12,
    "target_total_chars": 48000,
    "default_chapter_target_chars": 4000,
    "pacing_profile": "slow_burn_then_climax"
  },
  "climax_input": {
    "conflict_climax": "公开对抗中迫使幕后势力暴露关键代价",
    "emotional_climax": "主角在保全关系与追求真相之间作选择",
    "target_chapter_index": 10,
    "must_foreshadow": ["旧案证据来源"],
    "must_not_resolve_before": ["幕后主使身份"]
  },
  "extracted_character_mentions": [
    {
      "text": "顾迟",
      "mention_type": "name",
      "source_text": "让顾迟和沈青在旧案调查中被迫合作",
      "confidence": 0.96,
      "resolution_status": "resolved",
      "resolved_character_id": "char-gu-chi"
    },
    {
      "text": "大反派 X",
      "mention_type": "new_character_hint",
      "source_text": "大反派 X 暂时不要现身",
      "confidence": 0.82,
      "resolution_status": "missing"
    }
  ],
  "character_index": [
    {
      "name": "沈青",
      "aliases": ["阿青"],
      "role_hint": "主角",
      "faction_hint": "旧案调查线",
      "status_hint": "canon_active"
    }
  ],
  "world_overview": "世界观精炼梗概，只描述基础规则和当前故事所处环境。",
  "world_concept_index": [
    {
      "term": "灵脉封禁",
      "kind": "rule",
      "scope_hint": "能力限制 / 地理禁区"
    }
  ],
  "historical_story_overview": [
    {
      "work_id": "book-01",
      "summary": "第一部大致内容。",
      "starts_at": "故事起点",
      "ends_at": "第一部结尾时间"
    }
  ],
  "optional_open_thread_index": [
    {
      "thread_id": "thread-旧案证据",
      "title": "旧案证据来源",
      "status_hint": "unresolved"
    }
  ]
}
```

注意：

- 用户不需要先手工填写涉及人物名单；系统先从用户概述中抽取人物提及，再由本地 Agent 对齐 Character Memory。
- `extracted_character_mentions` 记录本轮用户概述中的重点人物，`character_index` 只提供可查询的人物入口。
- 人物索引只给名字、别名和极短标签，不展开人物档案。
- 世界观只给精炼梗概和概念名词，不展开全部规则。
- 历史故事总览只讲每部小说的大致内容和起止时间，不包含完整时间线。
- 详细事实必须通过 research request 获取。

## 3.1 Character Mention Extraction

在装配 `OutlineSeedPacket` 前，系统应从用户故事概述中抽取人物提及。

输入：

- 用户续写概述
- 用户目标、禁止项和补充说明
- 可选：已有角色名 / 别名轻量索引

模型输出：

```json
{
  "mentions": [
    {
      "text": "顾迟",
      "mention_type": "name",
      "source_text": "让顾迟和沈青在旧案调查中被迫合作",
      "confidence": 0.96,
      "possible_role_hint": "行动支援 / 关系推进对象"
    },
    {
      "text": "大反派 X",
      "mention_type": "new_character_hint",
      "source_text": "大反派 X 暂时不要现身",
      "confidence": 0.82,
      "possible_role_hint": "幕后反派"
    }
  ]
}
```

本地 Agent 随后执行 Character Memory 对齐：

```json
{
  "resolutions": [
    {
      "mention_text": "顾迟",
      "status": "resolved",
      "character_id": "char-gu-chi",
      "matched_by": ["canonical_name"]
    },
    {
      "mention_text": "大反派 X",
      "status": "missing",
      "candidate_matches": []
    }
  ]
}
```

状态语义：

- `resolved`：匹配到既有人物，后续 research 可以请求其 `character_profile`。
- `ambiguous`：可能匹配多个既有人物，需要用户选择。
- `missing`：历史档案中不存在，需要询问用户是否新增人物。

只有当用户确认 `missing` 人物确实是新增人物后，系统才要求用户补充最小 `CharacterSeedInput`。未确认新增的人物不得直接进入 `CharacterCastPlan` 或正式 Character Memory。

## 4. Research Request

模型每轮可以返回 0 到 N 个请求。请求是语义层对象，不是 SQL。

统一字段：

```json
{
  "type": "story_detail",
  "query": "主角上一次因为信任问题和关键同伴发生冲突的经过，以及冲突结束后两人的关系状态",
  "purpose": "判断新大纲中是否可以安排二人短期合作",
  "priority": "high"
}
```

### 4.1 story_detail

用于查询历史剧情片段、前因后果、时间位置和状态变化。

```json
{
  "type": "story_detail",
  "query": "我需要了解主角第一次发现旧案新证据的经过、当时有哪些人在场、这件事造成了什么后果",
  "purpose": "判断后续大纲是否可以回收旧案证据来源",
  "priority": "high"
}
```

### 4.2 character_profile

用于按人名查询人物状态、能力边界、最近行动和关系门禁。

```json
{
  "type": "character_profile",
  "name": "角色A",
  "query": "重点了解当前身份、能力边界、与主角的关系状态、最近一次登场后的状态",
  "purpose": "判断是否适合承担本批次行动支援角色",
  "priority": "high"
}
```

### 4.3 world_concept

用于按概念名词查询世界规则、限制、代价、历史例外和禁止突破点。

```json
{
  "type": "world_concept",
  "concept": "灵脉封禁",
  "query": "需要了解规则、限制、代价、历史例外和禁止突破点",
  "purpose": "避免高潮设计突破既有世界观",
  "priority": "high"
}
```

### 4.4 structure_pattern

用于向 Creative KB 查询适合当前阶段的结构模式。

```json
{
  "type": "structure_pattern",
  "query": "当前批次需要从调查过渡到公开对抗，同时保持关系慢热",
  "purpose": "为第 4-6 章安排铺垫、过渡和小高潮节奏",
  "priority": "medium"
}
```

## 5. Loop State

每轮模型必须返回一个明确状态：

```json
{
  "status": "need_more_info",
  "requests": [],
  "planning_notebook_delta": {
    "confirmed_facts": [],
    "constraints": [],
    "candidate_plot_moves": [],
    "blocked_plot_moves": [],
    "open_questions": []
  }
}
```

状态枚举：

- `need_more_info`：继续向本地查询。
- `needs_user_input`：本地资料无法回答，需要用户确认授权边界或创作偏好。
- `enough`：信息足够，可以生成大纲。
- `proceed_with_assumptions`：剩余缺口低风险，可在明确假设下生成草案。
- `blocked`：建模基础不足，不能生成正式大纲。

如果达到预算上限仍未 `enough`，系统必须输出 `SufficiencyDecision`，并在 `needs_user_input`、`proceed_with_assumptions` 和 `blocked` 之间选择；高风险剧情不得静默假设。

## 6. Research Budget

每次大纲生成必须有预算，避免无止境检索：

```json
{
  "max_rounds": 5,
  "max_requests_per_round": 4,
  "max_total_requests": 12,
  "max_return_tokens_per_request": 2000
}
```

本地 Agent 可以合并重复请求、降低低优先级请求、或在预算不足时只返回索引摘要。

## 7. Context Broker

`Context Broker` 是本地翻译层。

职责：

- 接收模型的语义请求。
- 解析人名、概念、剧情细节意图、时间范围和需要的事实侧面。
- 查询人物 alias、世界观概念索引、历史大纲、outline segment、segment group / outline root、章节摘要、场景卡、源文档引用和 Creative KB。
- 对候选结果去重、rerank、裁剪并标注来源。
- 返回 evidence，不直接修改大纲或 Memory。
- 对 `story_detail`，优先调用 Memory 层的 BTree descent / model-guided pruning 查询接口，避免 Writer 层直接扫描所有章节摘要或原始 document。

不负责：

- 自行生成剧情。
- 替模型决定最终大纲。
- 把 candidate 当作 confirmed fact。
- 维护 Memory Page schema 或写入正式 Memory。

## 8. Story Detail Resolver

`story_detail` 应通过独立 resolver 实现，而不是把 query 直接交给 SQLite。

推荐升级为 BTree descent + model-guided pruning。最低可用版本可以保留两段式 rerank，但长期接口应与 Memory 层 Page 查询对齐。

目标链路：

```text
story_detail request
  -> Memory root_scan(segment_group / outline_root pages)
  -> Writer model selects segment_group / outline_root ids and query_suffix
  -> Memory expands selected roots -> outline_segment candidates
  -> Writer model selects outline_segment ids and query_suffix
  -> Memory expands selected outline_segments -> chapter summary candidates
  -> Writer model selects chapter ids and query_suffix
  -> Memory expands selected chapters -> document candidates / excerpts
  -> Writer model decides stop or selects documents
  -> StoryDetailResult + memory_query_trace
```

每层模型选择 prompt 必须包含：

```json
{
  "original_query": "string",
  "query_suffix_chain": ["string"],
  "path_context": [
    {
      "level": "segment_group | outline_segment | chapter | document",
      "selected_id": "string",
      "summary": "string",
      "source_range": "string",
      "selection_reason": "string",
      "confidence": 0.0
    }
  ],
  "current_level": "segment_group | outline_segment | chapter | document",
  "current_candidates": [],
  "selection_task": "判断是否需要继续展开当前层候选以回答 original_query。",
  "output_schema": {
    "need_drill_down": "boolean",
    "selected_ids": ["string"],
    "query_suffix": "string",
    "reason": "string",
    "confidence": "number",
    "need_sibling_scan": "boolean"
  }
}
```

裁剪规则：

- `original_query` 和累计 `query_suffix_chain` 始终保留。
- 当前层 candidates 必须完整提供必要字段。
- 上一层未被选中的 sibling candidates 默认裁剪掉。
- `path_context` 只保留已选中的 Page breadcrumb、选择理由和置信度。
- 若模型返回低置信、空选择或 `need_sibling_scan = true`，Context Broker 可回到上一层扩展相邻 sibling。

旧两段式兼容路径：

```text
story_detail request
  -> Query Understanding prompt
  -> 查询 Outline Segment Index / Chapter Summary Index
  -> Candidate Segment Rerank prompt
  -> 读取 source_refs 对应摘要或原文片段
  -> 返回 StoryDetailResult
```

### 8.1 Query Understanding

输入：

- `story_detail.query`
- `purpose`
- 人物名索引
- 世界观概念索引
- 精炼历史故事总览

输出结构化检索计划：

```json
{
  "characters": ["主角", "角色A"],
  "concepts": [],
  "plot_intent": "relationship_conflict",
  "facets_needed": ["剧情经过", "冲突原因", "结果", "关系状态变化"],
  "temporal_hint": "最近一次",
  "candidate_keywords": ["信任", "冲突", "合作", "隐瞒"]
}
```

### 8.2 Outline Segment Index

为了让 `story_detail` 稳定工作，历史大纲应能通过 Narrative Memory 索引回 outline segment / chapter / document。

推荐候选段落卡：

```json
{
  "outline_segment_id": "outline-seg-0231",
  "segment_group_id": "outline-root-004",
  "work_id": "book-02",
  "chapter_range": ["ch-118", "ch-121"],
  "timeline_position": "第二部中段",
  "characters": ["主角", "角色A"],
  "locations": ["北境驿站"],
  "concepts": ["密令", "旧案"],
  "segment_summary": "关键同伴隐瞒线索导致主角误判局势，二人短暂决裂。",
  "major_beats": ["同伴隐瞒情报", "主角独自追查", "线索被敌对方利用"],
  "result": "同伴暴露部分真实立场，但仍未完全获得信任。",
  "state_changes": [
    "主角对关键同伴从有限信任退回警惕",
    "关键同伴欠下解释"
  ],
  "source_refs": [
    {
      "document_id": "doc-118",
      "chapter_id": "ch-118",
      "segment_ids": ["seg-118-08", "seg-118-12"]
    }
  ]
}
```

最低可用版本可以先用章节摘要索引过渡，但每条章节摘要仍应保存人物、概念、剧情概要、结果和 source document 位置。完整路径应优先复用 Narrative Memory 的 `outline_root / segment_group -> outline_segment -> chapter -> document` 查询能力；不要在 Writer 层重新创建并行剧情索引。

### 8.3 Candidate Segment Rerank

输入：

- 原始 `story_detail` request
- 结构化检索计划
- 10 到 20 个候选 outline segment、segment group 或章节摘要卡

输出：

```json
{
  "matches": [
    {
      "outline_segment_id": "outline-seg-0231",
      "confidence": 0.91,
      "reason": "直接涉及主角与关键同伴因隐瞒线索产生的信任冲突",
      "covered_facets": ["剧情经过", "冲突原因", "结果", "关系状态变化"]
    }
  ],
  "missing_facets": []
}
```

只有高相关候选才展开详细材料。低相关候选可只返回 id 和简短摘要。

## 9. Result Object

本地返回给 Outline Research Agent 的结果应统一带来源：

```json
{
  "request_id": "req-003",
  "type": "story_detail",
  "status": "answered",
  "summary": "关键同伴曾因隐瞒旧案线索导致主角误判，两人关系退回警惕，但该剧情段落结尾保留了合作可能。",
  "evidence": [
    {
      "source_type": "outline_segment",
      "source_id": "outline-seg-0231",
      "fact_status": "confirmed",
      "text": "outline segment 裁剪摘要",
      "source_refs": [
        {
          "document_id": "doc-118",
          "chapter_id": "ch-118",
          "segment_ids": ["seg-118-08"]
        }
      ]
    }
  ],
  "missing_facets": [],
  "followup_suggestions": [
    "如需安排二人合作，建议继续查询关键同伴最近一次公开站队相关剧情段落。"
  ]
}
```

`fact_status` 至少区分：

- `confirmed`
- `inferred`
- `candidate`
- `user_authorized`

## 10. Planning Notebook

研究循环应持续维护 `planning_notebook.json`：

```json
{
  "confirmed_facts": [],
  "constraints": [],
  "candidate_plot_moves": [],
  "blocked_plot_moves": [],
  "open_questions": [],
  "user_questions": [],
  "research_sources": []
}
```

Notebook 是生成大纲的工作台，不是正式 Memory。进入全书规划 review artifact 的内容必须被整理进正式 `BookContinuationPlan` 或相关 artifact。

## 11. Sufficiency Gate

模型在结束 research 前必须输出信息充足性判断：

```json
{
  "status": "enough",
  "known_enough": [
    "当前主角关系状态足够明确",
    "本批次外部冲突来源明确"
  ],
  "remaining_risks": [
    "某个新角色阵营仍需在 Character Casting 中确认"
  ],
  "assumptions": [
    "本批次不提前揭露幕后主使身份"
  ]
}
```

达到预算上限后，`Sufficiency Gate` 的职责是明确模型生成和用户补充知识的边界：

- 模型可以整合已经确认的事实、推断和结构模式。
- 模型可以提出低风险假设，但必须显式标注。
- 模型不得把终局秘密、主要人物身份、关系跃迁、世界规则突破或新增人物成立与否静默写成事实。
- 用户补充用于确认授权边界、创作偏好和本地资料无法回答的知识；这些回答应记录为 `user_authorized` evidence。

如果是 `needs_user_input`，必须给出少量高价值问题：

```json
{
  "status": "needs_user_input",
  "known_enough": [
    "主角当前关系状态明确",
    "旧案线索来源已有可用证据"
  ],
  "blocking_gaps": [
    {
      "gap": "大反派 X 是否是新增人物，还是已有角色的隐藏身份",
      "why_it_matters": "会影响人物档案、伏笔回收和高潮揭露节奏",
      "question": "大反派 X 是新角色，还是已有角色的隐藏身份？"
    }
  ],
  "optional_gaps": [
    {
      "gap": "顾迟在本批次是否主动暴露更多旧案关联",
      "safe_default": "先保持有限合作，不提前交底"
    }
  ]
}
```

如果可以带假设继续，输出 `proceed_with_assumptions`：

```json
{
  "status": "proceed_with_assumptions",
  "assumptions": [
    "本批次不揭露幕后主使身份",
    "顾迟与沈青只推进到有限信任"
  ],
  "remaining_risks": [
    "若用户希望更快推进关系，需要重做 BatchPlan"
  ],
  "optional_gaps": [
    "顾迟是否主动暴露更多旧案关联可留到后续章节确认"
  ]
}
```

如果建模基础不足，输出 `blocked`：

```json
{
  "status": "blocked",
  "reason": "缺少可用人物档案和历史大纲索引，无法判断续写起点",
  "required_actions": [
    "先完成 close-read / Memory 建模",
    "补充当前续写起点和主要人物"
  ]
}
```

用户回答 `needs_user_input` 后，系统应把回答写入 planning notebook：

```json
{
  "fact_status": "user_authorized",
  "text": "大反派 X 是新增人物，但本批次只作为幕后压力存在，不正式登场。",
  "source": "user_answer",
  "applies_to": ["BookContinuationPlan", "CharacterCasting"]
}
```

## 12. Audit Trail

每次研究循环应落盘 `outline_research_trace.json`，至少记录：

- `OutlineSeedPacket` 摘要
- 每轮 requests
- 每轮 broker results
- 每次 Memory BTree descent 的 `memory_query_trace`
- 每层 Memory candidates 的 input ids、selected ids、`query_suffix`、选择理由、置信度和 sibling scan 回退
- 被合并或跳过的请求
- budget 使用情况
- sufficiency decision
- 进入大纲的主要 evidence id

后续用户审阅 `BookContinuationPlan`、`BatchPlan` 或 `ChapterPackage` 时，系统应能解释关键设计来自哪个事实、哪个推断、哪个用户授权或哪个结构模式。
