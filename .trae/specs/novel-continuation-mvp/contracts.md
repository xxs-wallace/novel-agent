# 小说续写系统统一 Contract 草案

## 1. 目的
本文件用于冻结第一批最关键的跨层接口，供以下三层共同遵循：

- [novel-continuation-mvp/spec.md](.trae/specs/novel-continuation-mvp/spec.md)
- [creative-knowledge-base/spec.md](.trae/specs/creative-knowledge-base/spec.md)
- [narrative-memory-context/spec.md](.trae/specs/narrative-memory-context/spec.md)

本草案只处理“模块间如何传数据”，不替代各层自己的详细实现设计。

## 2. Design Principles

- 所有 contract 默认 JSON 兼容
- 所有跨层对象都区分：
  - 必填字段
  - 可选字段
  - 兼容过渡字段
- 第一阶段优先保证：
  - 字段稳定
  - 可落 SQLite
  - 可被 prompt 直接消费
- 允许旧 `ScenePlan` 与新 `SceneBrief` 在过渡期并存

## 3. Shared Conventions

### 3.1 命名约定

- `book_id`: 一本小说的稳定标识
- `doc_id`: `documents` 表主键
- `document_title_index`: 章节逻辑 ID
- `fragment_id`: 创作知识库层片段卡片主键
- `cluster_id`: 创作知识库层近重复聚类主键
- `run_id`: 一次续写运行 ID

### 3.2 时间与路径

- 时间统一使用 ISO 8601 UTC 字符串
- 路径统一使用绝对路径或仓库内可解析相对路径

### 3.3 数组与对象编码

- SQLite 中允许以 JSON 字符串存储
- 跨层传输时应恢复为真实数组 / 对象

## 4. Contract A: FragmentCard

### 4.1 用途

- 创作知识库层的桥段检索主载体
- 供粗筛、rerank、最终 prompt 锚点选择使用

### 4.2 Frozen Fields

```json
{
  "fragment_id": "string",
  "doc_id": "string",
  "document_title": "string",
  "document_title_index": "string",
  "cluster_id": "string | null",
  "is_cluster_representative": false,
  "source_path": "string",
  "source_offsets": [0, 0],
  "source_excerpt": "string",
  "content_summary": "string",
  "narrative_function": ["string"],
  "narrative_function_text": "string",
  "scene_space_tags": ["string"],
  "event_tags": ["string"],
  "emotion_tags": ["string"],
  "emotion_mechanism_text": "string",
  "expression_mode_tags": ["string"],
  "preferred_tags": ["string"],
  "pov_mode": "string",
  "character_focus": ["string"],
  "character_temperament": ["string"],
  "character_relation_text": "string",
  "relationship_state": ["string"],
  "continuity_phase": "string",
  "style_features": {
    "sentence_rhythm": "string",
    "dialogue_density": "string",
    "interiority_density": "string",
    "imagery_density": "string"
  },
  "style_profile_text": "string",
  "transferability_score": 0.0,
  "context_dependency_level": "low | medium | high"
}
```

### 4.3 Required Fields

- `fragment_id`
- `doc_id`
- `document_title`
- `document_title_index`
- `source_excerpt`
- `content_summary`
- `narrative_function_text`
- `emotion_mechanism_text`
- `character_relation_text`
- `style_profile_text`
- `transferability_score`
- `context_dependency_level`

### 4.4 Notes

- `preferred_tags` 只作为辅助信号，不可取代多视图文本字段
- `source_excerpt` 供最终 prompt 使用，长度应可控
- `cluster_id` 在建卡阶段可为空，聚类后回填

## 5. Contract B: FragmentCluster

### 5.1 用途

- 对高相似桥段做近重复归并
- 在在线检索阶段限制重复候选挤占名额

### 5.2 Frozen Fields

```json
{
  "cluster_id": "string",
  "cluster_theme": "string",
  "representative_fragment_id": "string",
  "member_count": 0,
  "dedup_reason": "string"
}
```

### 5.3 Required Fields

- `cluster_id`
- `representative_fragment_id`
- `member_count`
- `dedup_reason`

## 6. Contract C: SceneBrief

### 6.1 用途

- 创作知识库层在线检索意图对象
- 不是写作计划全文，只服务于“检索什么”

### 6.2 Frozen Fields

```json
{
  "scene_objective": "string",
  "emotional_goal": "string",
  "conflict_goal": "string",
  "narrative_function": ["string"],
  "emotion_mode": ["string"],
  "character_temperament": ["string"],
  "relationship_state": ["string"],
  "style_need": ["string"],
  "must_avoid": ["string"],
  "preferred_tags": ["string"]
}
```

### 6.3 Required Fields

- `scene_objective`
- `narrative_function`
- `emotion_mode`
- `must_avoid`

### 6.4 Compatibility Mapping from ScenePlan

```text
ScenePlan.goal -> SceneBrief.scene_objective
ScenePlan.emotional_goal -> SceneBrief.emotional_goal
ScenePlan.conflict_goal -> SceneBrief.conflict_goal
ScenePlan.style_reference_query.narrative_function -> SceneBrief.narrative_function
ScenePlan.style_reference_query.emotion_mode -> SceneBrief.emotion_mode
ScenePlan.style_reference_query.character_temperament -> SceneBrief.character_temperament
ScenePlan.current_relationship_state -> SceneBrief.relationship_state
ScenePlan.forbidden + ScenePlan.avoidance_items -> SceneBrief.must_avoid
ScenePlan.retrieval_hints.preferred_tags -> SceneBrief.preferred_tags
```

## 7. Contract D: ContextAssemblyPayload

### 7.1 用途

- Memory 层输出给续写主 Agent 的事实型上下文包
- 供写作 prompt 和一致性检查复用

### 7.2 Frozen Fields

```json
{
  "chapter_context": [
    {
      "document_title_index": "string",
      "chapter_title": "string",
      "summary_md": "string",
      "importance_score": 0
    }
  ],
  "world_summary_md": "string",
  "character_profiles": [
    {
      "canonical_name": "string",
      "profile_summary_md": "string",
      "aliases": ["string"],
      "importance_score": 0
    }
  ],
  "story_outline_md": "string",
  "missing_context": ["string"]
}
```

### 7.3 Required Fields

- `chapter_context`
- `world_summary_md`
- `character_profiles`
- `story_outline_md`
- `missing_context`

### 7.4 Notes

- `missing_context` 必须显式返回，不允许默默缺失
- `chapter_context` 可以为空数组，但必须存在字段

## 8. Contract E: RetrievalContext

### 8.1 用途

- 基础检索工具的结果摘要
- 作为 `SceneBrief` 的辅助输入，而不是最终参考桥段

### 8.2 Frozen Fields

```json
{
  "character_hits": ["string"],
  "timeline_hits": ["string"],
  "lore_hits": ["string"]
}
```

## 9. Contract F: CoarseRetrievalResult

### 9.1 用途

- 创作知识库层粗筛输出
- 供 rerank 消费

### 9.2 Frozen Fields

```json
{
  "candidate_fragment_ids": ["string"],
  "matched_by": {
    "fragment_id_1": ["fts", "preferred_tags"]
  },
  "filtered_cluster_ids": ["string"],
  "coarse_scores": {
    "fragment_id_1": 0.88
  }
}
```

## 10. Contract G: RerankResult

### 10.1 用途

- 创作知识库层最终候选评分输出
- 供续写主 Agent 组装 prompt

### 10.2 Frozen Fields

```json
{
  "scores": [
    {
      "candidate_id": "string",
      "cluster_id": "string | null",
      "continuity_fit": 0,
      "scene_function_fit": 0,
      "character_temperament_fit": 0,
      "relationship_state_fit": 0,
      "emotion_expression_fit": 0,
      "style_fit": 0,
      "transferability": 0,
      "context_dependency_penalty": 0,
      "final_score": 0.0,
      "reason": "string"
    }
  ],
  "selected_fragment_ids": ["string"],
  "selection_notes": "string"
}
```

### 10.3 Required Rules

- `selected_fragment_ids` 长度必须在 `1-4`
- 默认不允许同一 `cluster_id` 重复占据多个位置，除非显式例外

## 11. Main Layer Input Contracts

### 11.1 To Creative Knowledge Base Layer

```json
{
  "documents": [],
  "anchor_context": "string",
  "recent_window_summary": "string",
  "goal": "string",
  "previous_generated_segment": "string | null",
  "retrieval_context": {
    "character_hits": [],
    "timeline_hits": [],
    "lore_hits": []
  },
  "scene_plan": {}
}
```

说明：

- `scene_plan` 为兼容字段，可为空对象
- 若已有 `SceneBrief`，则本层可跳过旧 `scene_plan`

### 11.2 To Memory Layer

```json
{
  "book_id": "string",
  "document_title_index": "string | null",
  "related_character_names": ["string"],
  "token_budget": {
    "chapter_context_chars": 12000,
    "world_summary_chars": 1024,
    "character_profiles_chars": 12000,
    "story_outline_chars": 10000
  }
}
```

## 12. Main Layer Output Bundle for Writer

### 12.1 WriterInputBundle

```json
{
  "anchor_context": "string",
  "recent_window_summary": "string",
  "scene_brief": {},
  "reference_fragments": [
    {
      "fragment_id": "string",
      "source_excerpt": "string",
      "content_summary": "string",
      "style_profile_text": "string"
    }
  ],
  "context_payload": {},
  "sources": [
    {
      "path": "string",
      "snippet": "string"
    }
  ]
}
```

说明：

- `reference_fragments` 来自 rerank 结果中的 `selected_fragment_ids`
- `context_payload` 必须符合 `ContextAssemblyPayload`

## 13. Versioning Strategy

### 13.1 Version Tag

建议在跨层 payload 中预留可选字段：

```json
{
  "contract_version": "v1"
}
```

第一阶段可先不强制写入 SQLite，但建议在 service 边界保留。

### 13.2 Breaking Change Rule

以下变更视为 breaking change：

- 删除字段
- 改变字段类型
- 改变字段语义

以下变更视为兼容扩展：

- 新增可选字段
- 新增辅助对象
- 增加更严格的值约束但不破坏旧值

## 14. Recommended Code Targets

建议后续代码直接围绕以下对象落地：

- `novel_agent/app/schemas/creative_kb_schema.py`
  - `FragmentCard`
  - `FragmentCluster`
  - `SceneBrief`
  - `CoarseRetrievalResult`
  - `RerankResult`
- `novel_agent/app/schemas/context_assembly_schema.py`
  - `ContextAssemblyPayload`
- `novel_agent/app/schemas/orchestration_schema.py`
  - `RetrievalContext`
  - `WriterInputBundle`

## 15. Immediate Next Steps

基于本 contract 草案，最适合立刻落代码的顺序是：

1. `FragmentCard` / `FragmentCluster` schema
2. `SceneBrief` schema
3. `ContextAssemblyPayload` schema
4. 主层跨层 I/O schema
5. 再进入 repo / service 实现
