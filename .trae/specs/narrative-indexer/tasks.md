# Narrative Indexer Tasks

## Status Legend

- `待处理`：设计已明确，代码尚未落地
- `兼容迁移`：需要保留旧数据读取，但新 contract 不再鼓励旧 schema

## Tasks

- [ ] Task 1: 定义 IndexCard common schema
  - [ ] 新增 `IndexCard` / `IndexQueryIntent` / `IndexQueryResult` schema
  - [ ] 支持 `factual_event`、`narrative_scene`、`character_state`、`world_concept`、`mystery_foreshadow`、`theme_signal`、`creative_reference`、`arc_pattern`
  - [ ] common fields 必须包含 `card_id`、`card_type`、`summary`、`source_doc_ids`、`source_title_indexes`、`source_doc_range`、`query_facets`、`importance_facets`、`summary_sufficiency`、`raw_read_reason`、`status`
  - [ ] common fields 不包含 outline `timeline_events`、`event_ids` 或 pending event 字段

- [ ] Task 2: 将 Creative KB 接入为 `CreativeReferenceCard`
  - [ ] 保留现有 `fragment_cards` / `fragment_clusters` 表
  - [ ] 增加 adapter：`fragment_card -> CreativeReferenceCard`
  - [ ] 明确 `transferability_score` 和 `context_dependency_level` 只表达创作迁移价值，不表达事实重要度
  - [ ] Analyzer 只有在讨论文风、情绪表达和桥段机制时可读取 CreativeReferenceCard
  - [ ] 事实判断必须同时查询 factual cards 或 Narrative Memory

- [ ] Task 3: 从 close-read / Memory 派生事实型 cards
  - [ ] 从 chapter summaries / outline segments 派生 `FactualEventCard` 候选
  - [ ] 从连续 raw document sliding window 派生 `NarrativeSceneCard`
  - [ ] 从人物档案和 Character Evidence 派生 `CharacterStateCard`
  - [ ] 从 World Memory 派生 `WorldConceptCard`；规则、势力、物品、地理、历史和能力体系用 `payload.kind` 区分
  - [ ] 从未解问题、伏笔和异常信息派生 `MysteryForeshadowCard`
  - [ ] 从主题、作者态度、情绪基调派生 `ThemeSignalCard`
  - [ ] 所有 card 必须保留 source doc/title range，不得只保存自然语言结论

- [ ] Task 4: 替换旧 outline event list 路径
  - [ ] Story Outline Memory 新 contract 使用 `outline_segment` / `outline_root`
  - [ ] close-read prompt 不再要求输出 `timeline_events`
  - [ ] Chapter Event List / Event Summary 相关服务进入迁移删除清单
  - [ ] 旧数据中若存在 `timeline_events`，只允许迁移器读取并转换，不允许进入新模型 prompt
  - [ ] 新 prompt schema 中不得保留 `timeline_events` 作为可选字段

- [ ] Task 4.5: 实现 Narrative Scene Indexer 与 SourceArcMapBuilder
  - [ ] 基于 Memory handoff 的 `previous_context_summary + raw_document_window + next_context_summary` 生成 SceneCards
  - [ ] raw window 支持 overlap，避免同一场景被 document 边界切断
  - [ ] SceneCard 必须输出 `scene_type`、participants、trigger、turning_point、outcome、relationship_movements、world_or_mystery_signals、future_consequence、summary_sufficiency 和 raw_read_reason
  - [ ] SceneCard merge / dedupe 能合并多个 overlap window 命中的同一场景
  - [ ] `SourceArcMap` 由 SceneCards 聚合生成；旧 SourceArcMap 只作为 legacy / fallback 输入
  - [ ] `ArcPatternCard` 从 SceneCards / SourceArcMap 聚合视图沉淀，不直接依赖 Memory 层 SourceArcMap 作为上游判断

- [ ] Task 5: 实现 `NarrativeIndexFacade`
  - [ ] `search_cards(intent, budget)`：返回 compact candidate cards
  - [ ] `resolve_card_sources(card_ids)`：展开 card 的 chapter / document refs
  - [ ] 支持按 `consumer` 区分 Analyzer / Writer / Outline Research / Reviewer 的检索策略
  - [ ] 支持 card-level trace，记录 selected / rejected / raw-read recommendations

- [ ] Task 6: 接入 NarrativeInquiryBroker
  - [ ] 新增 `index_card_search`
  - [ ] 新增 `factual_event_card_search`
  - [ ] 新增 `character_state_card_search`
  - [ ] 新增 `mystery_card_search`
  - [ ] 新增 `theme_signal_card_search`
  - [ ] Broker 应先查询 compact cards，再按需调用 Memory BTree descent 或 raw excerpt

- [ ] Task 7: Benchmark 与验收
  - [ ] Analyzer benchmark 保存 selected cards、rejected cards sample 和 raw-read card trace
  - [ ] 检查 selected cards 是否命中 baseline 关键场景
  - [ ] 检查 summary sufficient 的 card 是否避免了不必要 raw read
  - [ ] 检查 summary insufficient 的 card 是否能准确定位 document
  - [ ] 检查 CreativeReferenceCard 不污染事实判断

## Dependencies

- Task 1 是 Task 2 到 Task 7 的前置。
- Task 3 依赖 Narrative Memory 的 `outline_segment` / `outline_root` 重构。
- Task 4 应先于 Analyzer / Writer prompt 正式迁移。
- Task 4.5 依赖 Task 1、Task 3 和 Narrative Memory Handoff Service。
- Task 6 依赖 Task 5。
- Task 7 依赖 Task 4.5、Task 5 和 Task 6。
