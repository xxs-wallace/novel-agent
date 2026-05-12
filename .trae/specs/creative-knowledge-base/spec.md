# 创作知识库（Creative Knowledge Base）Spec

## Source Of Truth

- 产品级核心流程、UI 交互、用户可见状态文案，以 [`../spec.md`](../spec.md) 为准。
- 本 spec 只定义创作知识库层：桥段卡片、桥段聚类、结构模式参考、在线检索与 rerank。
- 本 spec 的输出会进入核心流程中的“本章写作材料”和“正文生成”阶段，但不直接定义用户界面。

## Why

当前 `novel-continuation-mvp/spec.md` 已同时承载工程闭环、Memory、检索、续写规划等多个主题，人工阅读与模块边界都开始变得臃肿。\
本 spec 负责把“用于桥段检索与仿写参考的创作知识库”单独抽离出来，重点覆盖：

- `fragment_card`
- `fragment_cluster`
- 近重复检测
- 代表片段选择
- `SceneBrief -> 粗筛 -> rerank` 的输入输出 contract

其目标不是保存“小说事实”，而是保存“如何写这类桥段”的可复用知识。

## Positioning

### 与主 MVP spec 的关系

- `../spec.md`：产品级核心流程与 UI 交互 Source of Truth。
- `novel-continuation-mvp/spec.md`：总编排层，负责整体运行闭环与模块拼装。
- 本 spec：创作知识库层，负责桥段库构建、去重、检索、重排。
- `narrative-memory-context/spec.md`：上下文与 Memory 层，负责人物档案、世界观、章节摘要、故事大纲。

### 模块边界

- 本 spec 负责：
  - 桥段级结构化卡片
  - 近重复桥段聚类
  - 代表片段优先策略
  - 续写参考桥段检索
  - 小候选高精度 rerank
- 本 spec 不负责：
  - 人物事实档案维护
  - 世界观事实维护
  - 章节摘要与整书大纲维护
  - 正文生成本身

## Core Principles

- 标签只作为粗筛辅助，不作为桥段检索主依据。
- `fragment_card` 多视图文本字段是桥段检索主载体。
- 在线阶段默认只在小候选集上执行高成本判断。
- 在线阶段不得重新分析大量原文，重分析工作应尽量前移到离线构建阶段。
- 同簇重复桥段不得挤占最终 `1-4` 个参考位。

## Data Model

### Requirement: Fragment Card

系统 SHALL 为每个可复用桥段维护一条 `fragment_card` 记录，用于表达桥段的叙事功能、情绪机制、人物关系与风格特征。

#### Scenario: Fragment Card 固定字段

- **WHEN** 某个 `document` 被进一步加工为桥段卡片
- **THEN** `fragment_card` 至少包含如下字段或等价字段：

```json
{
  "fragment_id": "string",
  "doc_id": "string",
  "document_title": "string",
  "document_title_index": "string",
  "cluster_id": "string",
  "is_cluster_representative": true,
  "source_path": "string",
  "source_offsets": [0, 0],
  "content_summary": "string",
  "narrative_function": ["开场铺垫", "冲突升级"],
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
  "transferability_score": 0.82,
  "context_dependency_level": "low | medium | high",
  "source_excerpt": "string"
}
```

#### Scenario: Fragment Card 字段优先级

- **WHEN** 系统使用 `fragment_card` 参与检索
- **THEN** 应优先依赖以下字段：
  - `content_summary`
  - `narrative_function_text`
  - `emotion_mechanism_text`
  - `character_relation_text`
  - `style_profile_text`
- **AND** `preferred_tags` 只承担过滤和粗筛作用

### Requirement: Fragment Cluster

系统 SHALL 对近重复桥段建立 `fragment_cluster`，避免相似桥段在在线检索和 rerank 中重复占位。

#### Scenario: Fragment Cluster 固定字段

- **WHEN** 系统完成桥段近重复聚类
- **THEN** `fragment_cluster` 至少包含如下字段或等价字段：

```json
{
  "cluster_id": "string",
  "cluster_theme": "string",
  "representative_fragment_id": "string",
  "member_count": 0,
  "dedup_reason": "string",
  "created_at": "string"
}
```

#### Scenario: Cluster 代表片段

- **WHEN** 同一 cluster 内存在多个相似桥段
- **THEN** 系统 SHALL 选择恰好 1 个 `representative_fragment`
- **AND** 其 `fragment_card.is_cluster_representative` SHALL 标记为 `true`

## Offline Pipeline

### Requirement: 离线构建顺序

系统 SHALL 在在线检索前完成桥段卡片构建和去重归并。

#### Scenario: 固定流水线

- **WHEN** 系统处理一批新入库的 `documents`
- **THEN** 应遵循如下顺序或等价顺序：
  1. 生成轻量标签
  2. 生成首版 `fragment_card`
  3. 执行近重复检测
  4. 生成 `fragment_cluster`
  5. 选择 `representative_fragment`
  6. 回填 `cluster_id` 与 `is_cluster_representative`

### Requirement: 近重复检测规则

系统 SHALL 提供明确的近重复检测边界，避免误合并“表层事件相似但写法用途不同”的桥段。

#### Scenario: 去重使用的信号

- **WHEN** 系统比较两个桥段是否近重复
- **THEN** SHOULD 综合以下信号：
  - 词面相似度
  - `preferred_tags` 重合度
  - `content_summary` 相似度
  - `emotion_mechanism_text` 相似度
  - `style_profile_text` 相似度

#### Scenario: 可以合并的典型情况

- **WHEN** 两个桥段在叙事功能、情绪机制、风格写法上都高度相似，仅替换具体对象、人名、地点或少量细节
- **THEN** 系统 SHOULD 倾向于将其归入同一 `fragment_cluster`

#### Scenario: 不应合并的典型情况

- **WHEN** 两个桥段虽然事件表面相似，但以下任一项存在明显差异：
  - 人物气质
  - 情绪表达机制
  - 关系阶段
  - 风格用途
- **THEN** 系统 SHOULD 倾向于保留为不同 `fragment_card`

### Requirement: 代表片段选择规则

系统 SHALL 为每个 `fragment_cluster` 选择更适合作为续写参考的代表片段。

#### Scenario: 代表片段评分因素

- **WHEN** 系统从 cluster 中挑选代表片段
- **THEN** SHOULD 综合以下因素：
  - `transferability_score` 越高越优先
  - `context_dependency_level` 越低越优先
  - 信息完整性越高越优先
  - 风格代表性越稳定越优先

#### Scenario: 代表片段不等于文学性最高

- **WHEN** 某片段文学性极强但高度依赖前后文
- **THEN** 系统 SHOULD 将其降权
- **AND** 系统 SHALL 不把“最华丽”误判为“最适合作为仿写锚点”

## Online Retrieval Contract

### Requirement: SceneBrief 输入 Contract

系统 SHALL 在在线检索前生成结构化 `SceneBrief`，用于定义当前小段的检索意图。

#### Scenario: SceneBrief 固定输入

- **WHEN** 续写主 Agent 准备执行桥段检索
- **THEN** `SceneBrief` 的上游输入至少包含：
  - `anchor_context`
  - `recent_window_summary`
  - `goal`
  - `previous_generated_segment`（可为空）
  - `retrieval_context`（可为空）

#### Scenario: SceneBrief 固定输出

- **WHEN** 系统完成 `SceneBrief` 生成
- **THEN** 应输出如下结构或等价结构：

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

### Requirement: 粗筛 Contract

系统 SHALL 将粗筛设计为小成本、高可解释的候选压缩阶段。

#### Scenario: 粗筛输入

- **WHEN** 系统准备执行粗筛
- **THEN** 输入至少包含：
  - `SceneBrief`
  - `fragment_cards`
  - `fragment_clusters`
  - 可选的 `FTS` 结果

#### Scenario: 粗筛输出

- **WHEN** 系统完成粗筛
- **THEN** 输出至少包含：
  - `candidate_fragment_ids`
  - `matched_by`（如 `fts`、`preferred_tags`、`summary_match`）
  - `filtered_cluster_ids`
  - `coarse_score`

#### Scenario: 粗筛候选上限

- **WHEN** 系统完成粗筛
- **THEN** 候选数 SHOULD 控制在 `12-40`
- **AND** 同一 `cluster_id` 默认不应大量重复进入候选集

### Requirement: Rerank Contract

系统 SHALL 将 rerank 设计为高精度、小候选、固定 rubric 的最终桥段筛选阶段。

#### Scenario: Rerank 输入

- **WHEN** 系统准备执行 rerank
- **THEN** 输入至少包含：
  - `SceneBrief`
  - `candidate fragment_cards`
  - 每个候选的 `source_excerpt`
  - 可选的 `anchor_context` 与 `recent_window_summary`

#### Scenario: Rerank 输出

- **WHEN** 系统完成 rerank
- **THEN** 每个候选至少输出如下结构：

```json
{
  "candidate_id": "string",
  "cluster_id": "string",
  "continuity_fit": 0,
  "scene_function_fit": 0,
  "character_temperament_fit": 0,
  "relationship_state_fit": 0,
  "emotion_expression_fit": 0,
  "style_fit": 0,
  "transferability": 0,
  "context_dependency_penalty": 0,
  "final_score": 0,
  "reason": "string"
}
```

#### Scenario: Rerank 最终输出限制

- **WHEN** 系统完成 rerank 并准备组装 prompt
- **THEN** 最终参考桥段数量 SHOULD 控制在 `1-4`
- **AND** 默认不允许前 4 名全部来自同一 `cluster_id`
- **AND** 若同簇冲突，优先保留 `is_cluster_representative = true` 的候选

## Creative KB Benchmark

创作知识库的 benchmark 目标不是直接判断 Writer 最终正文是否像原文，而是验证：

- KB 是否从真实原文中抽出了可迁移的桥段知识。
- `SceneBrief -> 粗筛 -> rerank` 是否能选出适合作为当前续写参考的片段。
- 选出的片段是否降低 Writer 写作风险，而不是把 Writer 带向错误剧情、错误关系阶段或高上下文依赖片段。
- KB 对 Writer 是否有可观测增益。

### Requirement: Creative KB Benchmark Service

系统 SHOULD 提供 `CreativeKBBenchmarkService` 或等价服务，用于真实 LLM 驱动的 KB 质量冒烟测试。

#### Scenario: Benchmark service 职责

- **WHEN** 用户或自动化任务运行 Creative KB benchmark
- **THEN** benchmark service SHOULD 负责：
  - 从真实 fixture 或指定 source 构造 documents / prefix window
  - 使用真实 LLM 构建 `fragment_cards` 与 `fragment_clusters`
  - 构造若干 held-out `SceneBrief` 测试用例
  - 运行正式 `RetrievalFacade`
  - 保存 coarse / rerank / reference fragments 审计产物
  - 调用 LLM Reviewer 评价建卡、聚类、检索和 rerank 质量
  - 可选运行 Writer A/B 增益诊断
- **AND** benchmark service 不得绕过 `fragment_cards` / `fragment_clusters` 直接从基础检索工具返回最终参考桥段
- **AND** benchmark service 不得把 Reviewer 结论反向注入 KB 构建或 rerank 输入

#### Scenario: Canonical artifacts

- **WHEN** Creative KB benchmark 完成
- **THEN** SHOULD 保存如下产物或等价产物：
  - `kb_build_result.json`
  - `fragment_cards_sample.json`
  - `fragment_clusters_sample.json`
  - `scene_brief_cases.json`
  - `retrieval_cases/<case_id>/scene_brief.json`
  - `retrieval_cases/<case_id>/coarse_result.json`
  - `retrieval_cases/<case_id>/rerank_result.json`
  - `retrieval_cases/<case_id>/selected_reference_fragments.json`
  - `retrieval_cases/<case_id>/decoy_fragments.json`
  - `retrieval_cases/<case_id>/kb_retrieval_reviewer_prompt.json`
  - `retrieval_cases/<case_id>/kb_retrieval_reviewer_report.json`
  - `kb_reviewer_report.json`
  - `summary.json`
- **AND** 如运行 Writer A/B SHOULD 额外保存：
  - `writer_ab/kb_enabled/draft.md`
  - `writer_ab/kb_disabled/draft.md`
  - `writer_ab/kb_random/draft.md`
  - `writer_ab/writer_ab_reviewer_prompt.json`
  - `writer_ab/writer_ab_reviewer_report.json`

### Requirement: 建卡质量评测

系统 SHOULD 使用 LLM Reviewer 检查 `fragment_card` 是否忠实、可检索且可迁移。

#### Scenario: FragmentCard Reviewer 输入

- **WHEN** Reviewer 评价单个或一组 `fragment_card`
- **THEN** 输入 SHOULD 包含：
  - 原始 document excerpt
  - 生成的 `fragment_card`
  - 字段含义 rubric
- **AND** Reviewer SHOULD 检查：
  - `content_summary` 是否忠实原文
  - `narrative_function_text` 是否表达桥段功能，而不是只复述事件
  - `emotion_mechanism_text` 是否提取出情绪表达机制
  - `character_relation_text` 是否避免编造关系事实
  - `style_profile_text` 是否足够短、可检索、可迁移
  - `transferability_score` 与 `context_dependency_level` 是否合理

### Requirement: 聚类与代表片段评测

系统 SHOULD 使用 LLM Reviewer 检查 `fragment_cluster` 是否合并了真正近重复的桥段机制。

#### Scenario: Cluster Reviewer 输入

- **WHEN** Reviewer 评价 cluster
- **THEN** 输入 SHOULD 包含：
  - cluster 内若干 member cards
  - representative card
  - `dedup_reason`
- **AND** Reviewer SHOULD 判断：
  - 同簇片段是否在叙事功能、情绪机制和风格用途上近重复
  - 是否误把表层事件相似但写法用途不同的片段合并
  - representative 是否比其他 member 更适合作为续写参考

### Requirement: 检索 / rerank 质量评测

系统 SHALL 将检索 / rerank 质量作为 Creative KB benchmark 的主评测层。

#### Scenario: Rerank 不是绝对文学评分

- **WHEN** benchmark 评价 rerank 质量
- **THEN** Reviewer 不应凭空判断“某片段文学性好不好”
- **AND** Reviewer SHOULD 基于 `SceneBrief`、系统选中的 top references、同候选集中的 decoy / rejected fragments 做相对排序判断
- **AND** Reviewer SHOULD 回答“系统 top references 是否比 decoy 更适合作为当前 SceneBrief 的桥段参考”

#### Scenario: Rerank Reviewer 输入

- **WHEN** Reviewer 评价一个 retrieval case
- **THEN** 输入 SHOULD 包含：
  - `SceneBrief`
  - `anchor_context`
  - `recent_window_summary`
  - top selected `fragment_cards`
  - rerank scores and reasons
  - decoy fragments
  - 可选 rejected high-score fragments
- **AND** decoy fragments SHOULD 包含：
  - 随机 fragment
  - 同 cluster sibling
  - 高上下文依赖 fragment
  - 表面标签相似但关系阶段或情绪机制不匹配的 fragment

#### Scenario: Rerank Reviewer 检查项

- **WHEN** Reviewer 输出检索 / rerank 报告
- **THEN** checks SHOULD 至少包含：
  - `top1_beats_decoys`
  - `selected_fragments_match_scene_brief`
  - `scene_function_fit`
  - `emotion_mechanism_fit`
  - `relationship_state_fit`
  - `style_reference_value`
  - `transferability`
  - `cluster_diversity`
  - `context_dependency_risk`
  - `negative_transfer_risk`
- **AND** 若 top references 为空，decision SHOULD 为 `fail`
- **AND** 若前 `1-4` 个 selected fragments 大量来自同一 cluster，decision SHOULD 降级
- **AND** 若高上下文依赖片段被排在首位且无明确理由，decision SHOULD 降级

#### Scenario: Rerank Reviewer 输出

- **WHEN** Reviewer 完成检索 / rerank 评测
- **THEN** 输出 SHOULD 至少包含：

```json
{
  "decision": "pass | borderline | fail",
  "score": 0.67,
  "summary": "top references 能提供克制型停顿写法参考，但第二个片段上下文依赖偏高。",
  "checks": {
    "top1_beats_decoys": "pass",
    "selected_fragments_match_scene_brief": "pass",
    "transferability": "borderline",
    "cluster_diversity": "pass",
    "context_dependency_risk": "borderline"
  },
  "selected_fragment_ids": ["fragment-1"],
  "issues": []
}
```

### Requirement: Writer A/B 增益诊断

系统 SHOULD 支持可选 Writer A/B benchmark，用于判断 KB 是否对 Writer 正文生成产生实际增益。

#### Scenario: A/B variants

- **WHEN** benchmark 运行 Writer A/B
- **THEN** SHOULD 至少支持：
  - `kb_enabled`: 正常构建 KB，并允许 Writer 使用正式 `style_reference_bundle`
  - `kb_disabled`: 不构建 KB，或在 Writer execution input 中清空 `style_reference_bundle`
  - `kb_random`: 构建 KB，但注入随机或 decoy reference fragments
- **AND** MAY 支持：
  - `kb_oracle`: 使用人工或 reference truth 附近构造的理想参考片段，只作为诊断上限，不作为 canonical benchmark

#### Scenario: 复用 Writer smoke benchmark

- **WHEN** Creative KB benchmark 需要运行 Writer A/B
- **THEN** SHOULD 复用 `AgenticSmokeBenchmarkService` 的窗口切分、reference synopsis、Writer execution 与 Reviewer 能力
- **AND** 必须显式区分 KB variant
- **AND** 不得把当前默认 Agentic smoke 路径视为 no-KB baseline

当前 Agentic smoke 路径会对 prefix source 运行 `build_creative_kb=True`，并且 Writer execution input 通常会携带 `style_reference_bundle`。因此它更接近 `kb_enabled` variant，而不是 `kb_disabled` variant。

#### Scenario: A/B Reviewer

- **WHEN** Reviewer 比较 A/B drafts
- **THEN** 输入 SHOULD 包含：
  - reference story synopsis
  - optional reference truth
  - `kb_enabled` draft
  - `kb_disabled` draft
  - `kb_random` draft
  - 每个 variant 的 selected fragment ids 与 reference fragments 摘要
- **AND** Reviewer SHOULD 判断：
  - 哪个 draft 更符合 reference synopsis
  - 哪个 draft 在情绪机制、关系阶段、节奏和风格参考上更稳定
  - 是否出现 KB 误迁移导致的大剧情偏移
  - `kb_enabled` 是否显著优于 `kb_disabled` 或 `kb_random`

### Requirement: Creative KB benchmark 通过标准

- **WHEN** 计算 Creative KB benchmark 综合分
- **THEN** `score >= 0.60` SHOULD 视为达到最小 smoke 目标
- **AND** `0.45 <= score < 0.60` SHOULD 视为 `borderline`
- **AND** `score < 0.45` SHOULD 视为 `fail`
- **AND** 空 KB、空 selected fragments、无法回源到 `fragment_cards` 的 references SHOULD 直接判为 `fail`
- **AND** Writer A/B 分数 SHOULD 作为增益诊断信号，不应单独覆盖检索 / rerank 主评测结论

## Agent Boundaries

### Creative Knowledge Base Agent

- 输入：`documents`
- 输出：`fragment_cards`、`fragment_clusters`
- 职责：建卡、轻量标签、去重、代表片段选择

### Retrieval Agent

- 输入：`SceneBrief`、`fragment_cards`、`fragment_clusters`
- 输出：候选桥段、rerank 排序结果
- 职责：粗筛、cluster 去重、固定 rubric rerank

### Writer Agent

- 输入：主锚点、辅锚点、风格规则、`ScenePlan`
- 输出：正文草稿
- 职责：生成正文，不负责桥段建库

## Out of Scope

- 人物档案事实维护
- 世界观详细文档维护
- 章节摘要与整书大纲维护
- 正文一致性检查
