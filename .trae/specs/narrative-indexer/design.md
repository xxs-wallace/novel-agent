# Narrative Indexer Design

## Agent Reading Guide

先读 [`AGENT_CONTEXT.md`](AGENT_CONTEXT.md) 判断是否需要展开本文。Indexer
改动通常按对象或查询链路阅读：

- Card schema / family：读第 3 节，并回查 [`spec.md`](spec.md)。
- Close-read 与 Indexer 分工：读第 4 节。
- Creative KB 接入：读第 5 节，并回查
  [`../creative-knowledge-base/spec.md`](../creative-knowledge-base/spec.md)。
- Query flow / storage：读第 7、8 节。
- Prompt 或 benchmark 影响：读第 9、10 节。

## 1. 目标

Narrative Indexer 将 close-read、BTree Memory Query、Creative KB、Analyzer 和 Writer 的检索思想统一到同一个上位框架：

```text
documents
  -> close-read / post-close-read processing
  -> Narrative Indexer
      -> factual_event cards
      -> narrative_scene cards
      -> character_state cards
      -> world_concept cards
      -> mystery_foreshadow cards
      -> theme_signal cards
      -> creative_reference cards
      -> SourceArcMap derived from scene cards
      -> arc_pattern cards
  -> NarrativeInquiryBroker
  -> Analyzer / Writer / Outline Research / Reviewer
```

这个设计不要求立刻删除 Creative KB。相反，Creative KB 保留现有表、facade、benchmark 和 rerank 能力，并作为 `creative_reference` card family 接入统一 Indexer facade。

## 2. 模块边界

### 2.1 输入

- `documents`
- close-read 章节摘要、人物更新、世界观更新、outline segments
- BTree Memory Page：outline root、outline segment、chapter summary、document refs
- Character Memory：人物基础档案和人物剧情时间线
- World Memory：世界观文档和概要
- 兼容读取旧 `SourceArcMap`，仅作为迁移或 fallback 输入
- Creative KB `fragment_cards` / `fragment_clusters`

### 2.2 输出

- `IndexCard` 兼容对象
- `IndexQueryResult`
- card-level evidence bundle
- card 到 event / chapter / document 的回源 trace

### 2.3 不负责

- 原文切分与入库
- close-read 模型精读本身
- Memory 事实资产覆盖写回
- Creative KB 片段 rerank 的具体评分逻辑
- Analyzer / Writer / Reviewer 的最终语义判断

## 3. 核心对象

### 3.1 IndexCard

推荐 Python schema 草案：

```python
class IndexCard(BaseModel):
    card_id: str
    card_type: Literal[
        "factual_event",
        "narrative_scene",
        "character_state",
        "world_concept",
        "mystery_foreshadow",
        "theme_signal",
        "creative_reference",
        "arc_pattern",
    ]
    book_id: str
    summary: str
    source_doc_ids: list[str] = []
    source_title_indexes: list[int] = []
    source_doc_range: str | None = None
    outline_segment_ids: list[str] = []
    query_facets: list[str] = []
    importance_facets: list[str] = []
    consumer_hints: list[str] = []
    summary_sufficiency: Literal["sufficient", "needs_raw", "needs_model_review"]
    raw_read_reason: str | None = None
    status: Literal["provisional", "committed", "fallback", "failed"]
    confidence: float
    payload: dict[str, Any] = {}
```

`payload` 只保存 card family 的专属字段，不能替代 common fields。

### 3.2 NarrativeSceneCard

`NarrativeSceneCard` 是结构分析的核心中间层。它描述连续正文窗口形成的场景，而不是孤立事件或整段篇章。

推荐 schema 草案：

```python
class NarrativeScenePayload(BaseModel):
    scene_type: Literal[
        "daily_baseline",
        "relationship_setup",
        "relationship_turning_point",
        "emotional_climax",
        "plot_turning_point",
        "world_reveal",
        "mystery_setup",
        "transition_bridge",
        "aftermath",
        "resolution",
    ]
    participants: list[str] = []
    trigger: str = ""
    turning_point: str = ""
    outcome: str = ""
    character_pressure: list[str] = []
    relationship_movements: list[str] = []
    world_or_mystery_signals: list[str] = []
    future_consequence: str = ""
    boundary_confidence: float = 0.0
    overlap_window_id: str = ""
```

`NarrativeSceneCard` 使用 `IndexCard.card_type = "narrative_scene"`，上面的字段保存在 `payload`。它必须保留 `source_doc_ids`、`source_title_indexes` 和 `summary_sufficiency`，以便 Analyzer 决定是否读取原文。

### 3.3 IndexQueryIntent

上层 agent 的自然语言问题先被规整为查询意图：

```json
{
  "original_query": "评价男女主角性格并推测后续行动。",
  "consumer": "analyzer",
  "target_card_types": ["factual_event", "character_state", "theme_signal"],
  "query_facets": ["人物性格", "关系转折", "关键选择", "后续行动"],
  "must_include_characters": [],
  "time_scope": "current_book | recent_window | chapter_range",
  "raw_read_policy": "avoid_unless_needed"
}
```

### 3.4 IndexQueryResult

```json
{
  "intent": {},
  "candidate_cards": [],
  "selected_cards": [],
  "rejected_cards": [],
  "raw_read_recommendations": [],
  "trace": []
}
```

`selected_cards` 是后续 Analyzer / Writer prompt 的主要 evidence。`rejected_cards` 默认只进 trace，不进入后续 prompt。

## 4. Close-read 与 Indexer 的分工

close-read 不应只输出章节摘要。它 SHOULD 同时输出足以构建 index card 的素材：

- 关键事件
- 人物状态变化
- 关系变化
- 世界规则
- 伏笔和未解问题
- 主题信号
- 文风 / 情绪 / 桥段机制候选
- 摘要是否足够，以及是否需要原文回读

Indexer 负责：

- 为这些素材分配 card family。
- 标准化 common fields。
- 建立 card 到 event / chapter / document 的回源索引。
- 建立 card 之间的 edge。
- 生成 FTS / compact retrieval fields。

### 4.1 Narrative Scene Indexer

Narrative Scene Indexer 是 post-close-read 的结构建卡步骤。它不替代章节摘要，也不一开始读取整本原文，而是先用 Memory 的压缩索引定位候选，再用连续原文窗口确认场景。

推荐流程：

```text
chapter summaries / outline segments / outline roots
  -> candidate window planning
  -> sliding raw windows with overlap
  -> SceneCard extraction
  -> SceneCard merge / dedupe
  -> SourceArcMapBuilder
  -> ArcPatternCard derivation
```

每个 sliding window prompt SHOULD 组装为：

- `previous_context_summary`：窗口之前若干 chapter / outline segment 的高度压缩梗概。
- `raw_document_window`：当前连续 documents 原文，默认按文本预算控制，并与相邻窗口 overlap。
- `next_context_summary`：窗口之后若干 chapter / outline segment 的高度压缩梗概。
- `known_character_world_context`：与窗口命中的人物、设定、未解问题相关的压缩 Memory。
- `scene_extraction_task`：要求模型判断窗口内是否存在完整或跨边界场景、场景类型、结构功能、关键人物压力、关系变化、设定/谜团信号和是否需要原文保留。

默认策略：

- 原文窗口按字符预算组装，建议初始值不超过 16KB，可随模型上下文扩大而配置。
- 相邻窗口必须有 overlap；overlap 的目标是避免文档切分刚好把同一场景拆开。
- 输出 SceneCards 后必须进行 merge / dedupe：同一场景被多个窗口命中时合并 source range、保留最高置信结构判断和最完整摘要。
- SceneCards 不只记录高潮，也要记录日常基线、过渡、铺垫、余波、设定揭示和收束；低冲突不等于低价值。

### 4.2 SourceArcMapBuilder

`SourceArcMap` 不再由章节摘要直接生成。它由 SceneCards 聚合而来：

```text
NarrativeSceneCard[]
  -> chronological grouping
  -> source arc boundaries
  -> source_arc_role / chapter_role_map
  -> SourceArcMap
```

聚合规则：

- 相邻 SceneCards 如果共享主线目标、人物线、地点/阶段或未解问题，可归入同一 source arc。
- 篇章边界主要来自 scene_type 和 future_consequence 的变化，例如从 daily_baseline 转入 world_reveal，或从 setup 转入 climax / aftermath。
- `chapter_role_map` 应由覆盖该 chapter 的 SceneCards 综合得出，而不是让模型在缺少场景索引时凭整章摘要猜测。
- 若某章只包含过渡、日常或余波 SceneCards，也必须在 SourceArcMap 中保留其功能。

旧版 `SourceArcMap` 可作为迁移输入，但新流程的标准路径是 `SceneCards -> SourceArcMap -> ArcPatternCard`。

## 5. Creative KB 的新定位

现有 Creative KB：

- `fragment_cards`
- `fragment_clusters`
- `SceneBrief`
- coarse retrieval
- rerank

继续保留。

新定位：

```text
fragment_card == CreativeReferenceCard compatibility shape
```

映射关系：

- `fragment_id` -> `card_id`
- `content_summary` -> `summary`
- `narrative_function_text` / `emotion_mechanism_text` / `style_profile_text` -> `payload`
- `preferred_tags` -> `query_facets`
- `doc_id` / `document_title_index` -> source refs
- `transferability_score` -> creative payload score
- `context_dependency_level` -> creative payload risk

约束：

- `CreativeReferenceCard` 只提供写法和桥段参考。
- 它不能单独支持事实判断。
- Writer 若使用 creative reference，也必须同时经过 factual context / factual cards 约束。
- Analyzer 可以引用 creative reference 讨论文风，但不能把它当作“剧情事实来源”。

## 6. Card Edges

为了避免复制膨胀，card 之间 SHOULD 使用 edge 连接：

```json
{
  "from_card_id": "character-card-001",
  "to_card_id": "event-card-001",
  "edge_type": "derived_from | supports | refines | stylistic_parallel | contradicts | needs_raw",
  "reason": "人物状态变化来自该关键事件。",
  "confidence": 0.82
}
```

常见 edge：

- `CharacterStateCard -> FactualEventCard`
- `MysteryForeshadowCard -> FactualEventCard`
- `ThemeSignalCard -> FactualEventCard`
- `CreativeReferenceCard -> FactualEventCard`
- `FactualEventCard -> NarrativeSceneCard`
- `CharacterStateCard -> NarrativeSceneCard`
- `MysteryForeshadowCard -> NarrativeSceneCard`
- `ThemeSignalCard -> NarrativeSceneCard`
- `ArcPatternCard -> SourceArcMap range`

## 7. Query Flow

Analyzer / Writer / Outline Research 查询时：

```text
question / goal
  -> IndexQueryIntent
  -> compact card retrieval
  -> model triage over cards
  -> selected cards committed to notebook/context
  -> optional BTree descent
  -> optional raw excerpt
```

裁剪规则：

- 未被 triage 选中的 cards 不进入后续 prompt。
- selected card 的 compact summary 优先进入 prompt。
- 原文只在 `summary_sufficiency != sufficient` 或模型明确说明摘要不足时读取。
- raw excerpt request 必须保留 `read_reason`、`expected_confirmation` 和 `affects_analysis`。

## 8. Storage Strategy

### 8.1 短期兼容

不迁移现有表：

- `fragment_cards` 继续服务 Creative KB。
- `chapters` / outline assets 继续服务 Memory。
- SceneCards 可先保存为 `.memory/index_cards/<book_id>.scene_cards.json` 或等价 JSON 资产。
- SourceArcMap 继续使用现有 JSON / Markdown 资产格式，但生成来源改为 SceneCards 聚合；旧 SourceArcMap 只作为兼容读取。

新增 facade：

```python
class NarrativeIndexFacade:
    def search_cards(intent: IndexQueryIntent, budget: IndexQueryBudget) -> IndexQueryResult: ...
    def resolve_card_sources(card_ids: list[str]) -> IndexEvidenceBundle: ...
```

### 8.2 长期统一表

可选迁移：

```sql
CREATE TABLE index_cards (
    card_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    card_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_doc_ids_json TEXT NOT NULL,
    source_title_indexes_json TEXT NOT NULL,
    source_doc_range TEXT,
    outline_segment_ids_json TEXT NOT NULL,
    query_facets_json TEXT NOT NULL,
    importance_facets_json TEXT NOT NULL,
    consumer_hints_json TEXT NOT NULL,
    summary_sufficiency TEXT NOT NULL,
    raw_read_reason TEXT,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

```sql
CREATE TABLE index_card_edges (
    from_card_id TEXT NOT NULL,
    to_card_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY(from_card_id, to_card_id, edge_type)
);
```

## 9. Prompt 影响

### close-read prompt

需要新增“索引素材”职责，但不要求顺序 close-read 直接完成最终场景结构判断：

- 识别关键事件和关键人物状态变化。
- 给出 query facets 和 importance facets。
- 判断 summary 是否足够。
- 给出 raw read recommendation。
- 避免把低置信推断写成事实。

### Narrative Scene Indexer prompt

新增独立 prompt，用于连续原文窗口的场景判断：

- 必须同时读取窗口前后的压缩梗概，判断当前原文窗口在整部小说中的位置。
- 必须允许一个场景跨越多个 documents，并通过 overlap 合并重复命中。
- 必须输出场景类型、结构功能、人物压力、关系变化、设定/谜团信号、后续影响和回源范围。
- 必须判断 SceneCard 摘要是否足够；如果 Analyzer / Writer 需要原文，明确说明 `raw_read_reason`。

### Analyzer prompt

Analyzer 不再直接要求大量章节摘要。它应优先请求：

- `index_card_search`
- `event_card_search`
- `character_state_card_search`
- `mystery_card_search`
- `theme_signal_card_search`

### Writer prompt

Writer context assembly 应分开装配：

- factual cards：连续性和事实约束。
- creative reference cards：写法参考。
- arc pattern cards：结构节奏参考。

这三者在 prompt 中必须使用不同标题，避免模型把写法参考误当成事实。

## 10. Benchmark

Indexer benchmark 应同时检查：

- close-read 是否产出足够高价值 card。
- 查询是否命中 baseline 关键事件。
- 选中的 card 是否能减少原文读取。
- 必须读原文时是否能准确定位 document。
- CreativeReferenceCard 是否仍能提升 Writer 写法，而没有污染事实判断。

Analyzer smoke benchmark SHOULD 增加 card-level trace：

- selected factual cards
- selected theme / mystery cards
- raw-read cards
- rejected cards sample
- final answer 与 selected cards 的对应关系
