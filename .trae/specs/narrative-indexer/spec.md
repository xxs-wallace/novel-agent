# Narrative Indexer Spec

## Source Of Truth

- 产品级核心流程、用户入口、用户可见状态文案和人工确认规则，以 [`../spec.md`](../spec.md) 为准。
- 粗读入库、`documents` 基线、章节边界和原文回源规则，以 [`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md) 为准。
- 创作参考片段、桥段聚类、`SceneBrief -> 粗筛 -> rerank` 的现有能力，以 [`../creative-knowledge-base/spec.md`](../creative-knowledge-base/spec.md) 为准。
- Outline Analyzer 只读分析流程，以 [`../outline-analyzer/spec.md`](../outline-analyzer/spec.md) 为准。
- Writer 分层生成与 Outline Research Loop，以 [`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md) 为准。

## Purpose

Narrative Indexer 是 close-read 之后、Analyzer / Writer / Outline Research 之前的统一索引框架。

它的目标不是新增一个和 Memory / KB 平行的孤立系统，而是把来自同一批 `documents` 和 close-read 产物的多类信息整理成可检索、可回源、可裁剪的 `IndexCard` family。

Creative KB SHALL 被重新定位为 Narrative Indexer 下的一种特殊索引：`CreativeReferenceCard`。它保留桥段参考、情绪机制、风格特征和可迁移写法能力，但不再作为与事实 Memory 完全平行的概念存在。

## Positioning

Narrative Indexer 负责回答：

- 当前小说有哪些可检索的事实事件、人物变化、世界规则、伏笔、主题信号和创作参考片段。
- 这些索引项如何从上层摘要逐层回源到 scene、chapter、document。
- 哪些连续原文窗口构成了场景，场景在源作品中承担铺垫、过渡、关系转折、设定揭示、高潮或收束等什么结构功能。
- 哪些索引项的摘要足以支持 Analyzer / Writer，哪些需要进一步回读原文。
- 同一 `document` 如何派生出多种不同用途的 card，而不混淆事实索引与创作参考索引。

Narrative Indexer 不负责：

- 原文导入与章节切分。
- 人物档案、世界观文档、章节摘要和故事大纲的长期事实维护。
- 正文生成。
- Analyzer 的文学判断。
- Writer 的规划 artifact 生成。
- 用本地 heuristic 伪装模型已经完成语义建卡。

## Core Principles

- `documents` 是所有 index card 的共同 leaf source。
- close-read 是主要语义抽取入口；Indexer 主要把 close-read 结果整理成可检索 card，而不是重新读取全书原文。
- Narrative Scene Indexer SHALL 使用章节/outline 摘要定位候选，再用带 overlap 的连续原文窗口评估场景边界和结构功能；不得只依据单个 document 判断场景重要性。
- `SourceArcMap` SHALL 从 SceneCards 聚合生成，而不是作为 SceneCards 或 ArcPatternCard 的主要上游语义判断来源。
- 同一个 source document 可以派生多种 card，但每种 card 必须声明 `card_type` 和消费边界。
- 事实型 card 可以支持 Analyzer / Writer 的连续性判断；创作参考型 card 只能支持写法、桥段、风格和结构迁移，不得被当作事实证据。
- 每张 card MUST 带有可回源索引，例如 `source_doc_ids`、`source_title_indexes`、`outline_segment_ids` 或 `source_doc_range`。
- 每张 card SHOULD 标注摘要是否足够，以及何时需要 raw excerpt。
- 在线检索 SHOULD 先查 compact cards，再按需 BTree descent 或 raw excerpt；不得一开始就读取大量原文。

## Card Families

### FactualEventCard

用于记录剧情事实、事件因果、主线推进和关键选择。

推荐字段：

```json
{
  "card_id": "event-card-001",
  "card_type": "factual_event",
  "label": "关键选择或事件标签",
  "summary": "事实型事件摘要。",
  "participants": ["character-id-or-name"],
  "source_doc_ids": ["doc-001"],
  "source_title_indexes": [12],
  "importance_facets": ["mainline_turn", "protagonist_choice"],
  "query_facets": ["人物性格", "后续行动", "剧情走向"],
  "summary_sufficiency": "sufficient | needs_raw_for_dialogue | needs_raw_for_emotional_texture | needs_raw_for_author_statement",
  "raw_read_reason": "string | null",
  "status": "provisional | committed"
}
```

### NarrativeSceneCard

用于记录由连续 `documents` 构成的叙事场景，以及该场景在源作品中的结构功能。SceneCard 是比单个事件更高一级、比 SourceArcMap 更细一级的索引单元，既可以支撑 Analyzer 判断“哪些局部值得回读原文”，也可以支撑 Writer / Reviewer 定位人物关系、情绪转折和设定揭示。

生成 SceneCard 时，Narrative Scene Indexer SHOULD 使用如下输入结构：

- 当前滑动窗口前方的高度压缩剧情梗概。
- 当前窗口内连续若干 `documents` 的原文，默认允许 overlap，避免同一场景被切在 batch 边界。
- 当前滑动窗口后方的高度压缩剧情梗概。
- 已有 chapter summaries、outline segments、相关人物/世界概要。

推荐字段：

```json
{
  "card_id": "scene-card-001",
  "card_type": "narrative_scene",
  "label": "场景标签",
  "summary": "该连续场景发生了什么，以及为什么重要。",
  "scene_type": "daily_baseline | relationship_setup | relationship_turning_point | emotional_climax | plot_turning_point | world_reveal | mystery_setup | transition_bridge | aftermath | resolution",
  "participants": ["character-id-or-name"],
  "source_doc_ids": ["doc-001", "doc-002"],
  "source_title_indexes": [12],
  "scene_boundary": {
    "start_doc_id": "doc-001",
    "end_doc_id": "doc-002",
    "boundary_confidence": 0.0,
    "overlap_window_id": "string"
  },
  "trigger": "场景触发条件或前因。",
  "turning_point": "场景内最重要的变化或选择。",
  "outcome": "场景结果。",
  "character_pressure": ["人物承受的压力、欲望或矛盾"],
  "relationship_movements": ["关系变化"],
  "world_or_mystery_signals": ["设定揭示、谜团、伏笔"],
  "future_consequence": "该场景对后续剧情的影响。",
  "query_facets": ["人物性格", "关系转折", "后续行动"],
  "summary_sufficiency": "sufficient | needs_raw_for_dialogue | needs_raw_for_emotional_texture | needs_raw_for_author_statement",
  "raw_read_reason": "string | null",
  "status": "provisional | committed"
}
```

### CharacterStateCard

用于记录人物状态、动机、关系变化、关键选择和人物线索。

该 card SHOULD 连接到 Character Memory 的 `character_id`，并优先引用相关 `FactualEventCard.card_id`，避免在人物维度重复复制完整剧情。

### WorldConceptCard

用于记录世界观设定、规则、限制、势力、组织、物品、地理、历史、能力体系、禁忌和代价。规则只是世界观概念的一种，SHOULD 用 `payload.kind = "rule"` 表达，不应把所有世界观信息都硬归为 rule。

该 card 可以支持 Analyzer / Writer 判断“某个走向是否违反设定”，但不得覆盖正式 World Memory；World Memory 仍是事实型世界观的 source of truth。

### MysteryForeshadowCard

用于记录未解谜团、伏笔、异常信息、可疑矛盾、未来可能回收点。

该 card 应明确区分：

- 已确认未解。
- 可能伏笔。
- 证据不足的可疑点。

### ThemeSignalCard

用于记录主题表达、作者态度、价值判断、象征意义、叙事反复出现的母题。

该 card 通常服务 Analyzer，也可以辅助 Writer 保持主题连续性；若涉及文风或表达方式，MAY 连接到 `CreativeReferenceCard`。

### CreativeReferenceCard

用于记录桥段写法、情绪机制、人物关系表达、风格特征和可迁移参考片段。

Creative KB 当前的 `fragment_card` SHALL 被视为 `CreativeReferenceCard` 的现有实现或兼容形态。

该 card 不得作为剧情事实依据。若 Writer 需要事实约束，必须同时查询事实型 card 或 Memory。

### ArcPatternCard

用于记录从 SceneCards 聚合出的 `SourceArcMap`、章节摘要和故事大纲中沉淀出的可迁移篇章结构模式。

该 card 描述结构模式，而不是要求续写照搬源作品事件。

## IndexCard Common Contract

所有 card family SHOULD 支持共同字段或等价字段：

```json
{
  "card_id": "string",
  "card_type": "factual_event | narrative_scene | character_state | world_concept | mystery_foreshadow | theme_signal | creative_reference | arc_pattern",
  "book_id": "string",
  "source_doc_ids": ["string"],
  "source_title_indexes": [0],
  "source_doc_range": "string | null",
  "outline_segment_ids": ["string"],
  "summary": "string",
  "query_facets": ["string"],
  "importance_facets": ["string"],
  "consumer_hints": ["analyzer", "writer", "outline_research", "reviewer"],
  "summary_sufficiency": "sufficient | needs_raw | needs_model_review",
  "raw_read_reason": "string | null",
  "status": "provisional | committed",
  "confidence": 0.0,
  "created_at": "string",
  "updated_at": "string"
}
```

## Query Model

NarrativeInquiryBroker SHOULD query Narrative Indexer before requesting raw documents.

推荐顺序：

1. 使用 user question / writer goal / reviewer issue 生成 `IndexQueryIntent`。
2. 在 compact `IndexCard` 上粗筛候选。
3. 对候选 card 执行小批量或逐张 triage。
4. Commit 相关 card 到当前 agent notebook / context。
5. 仅当 card 标注摘要不足，或 triage 明确需要原文时，触发 BTree descent / raw excerpt。

## Relationship To Existing Modules

- Narrative Memory：维护事实型长期资产和 BTree Page；Indexer 从这些资产派生事实索引卡片。
- Creative KB：维护创作参考卡片、聚类和 rerank；它是 Indexer 的 `creative_reference` card family。
- SourceArcMap：由 Narrative Indexer 基于 `narrative_scene` cards 聚合出的源作品篇章视图，用于定位结构范围和沉淀 arc pattern；不再作为 Memory 层独立生成的上游结构判断。
- Analyzer：只读消费 Indexer 和 Memory，不写回 card。
- Writer：消费事实型 card 保持连续性，消费创作参考 card 获取写法参考。
- Outline Research：消费 event / mystery / arc pattern card，输出 Writer planning artifact。
- Reviewer：消费事实型 card 检查违背原作，消费创作参考 card 检查风格或桥段迁移风险。

## Migration Rule

首版 SHALL 保持现有 Creative KB 表和服务可用，不要求立即迁移数据库。

实现可以先增加 `IndexCard` facade：

- 将现有 `fragment_cards` 映射为 `CreativeReferenceCard`。
- 将 close-read 产出的 chapter summaries / outline segments 与 NarrativeSceneCards 中的事实变化映射为 `FactualEventCard`。
- 使用 Narrative Scene Indexer 从连续 document 滑动窗口生成 `NarrativeSceneCard`。
- 将人物档案里的 `story_events` 映射为 `CharacterStateCard`。
- 将世界观更新映射为 `WorldConceptCard`；规则、势力、物品、地理、历史和能力体系使用 `payload.kind` 区分。
- 将 `NarrativeSceneCard` 聚合为 `SourceArcMap`，再从 `SourceArcMap` 与 SceneCards 中沉淀 `ArcPatternCard`。
- 旧数据若只有 SourceArcMap、没有 SceneCards，迁移器 MAY 将其转成 `ArcPatternCard` 或 provisional SceneCards，但产物必须标注 `fallback` / `provisional`，不得当作新的标准生成路径。

长期 MAY 迁移到统一表：

- `index_cards`
- `index_card_edges`
- `index_card_fts`

但迁移不得破坏现有 Writer 对 Creative KB 的消费路径。
