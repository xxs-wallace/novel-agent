# 叙事 Memory 与上下文（Narrative Memory Context）Spec

## Source Of Truth

- 产品级核心流程、UI 交互、用户可见状态文案，以 [`../spec.md`](../spec.md) 为准。
- 本 spec 只定义事实型 Memory 与上下文装配：人物、世界观、章节摘要、故事大纲、源作品篇章地图与精读进度。
- 本 spec 的输出会进入核心流程中的“建模准备”“本章写作材料”“确认写回”等阶段，但不直接定义用户界面。

## Why
小说续写系统中的“人物档案、世界观、章节摘要、整书大纲”更接近长期上下文与事实记忆，而不是创作桥段知识库。  
若将这部分与桥段检索混在同一 spec 中，会导致：

- 阅读路径混乱
- Agent 职责交叉
- 后续并行开发困难

本 spec 将“事实型上下文与长期 Memory”独立出来，服务于：

- 精读 Agent
- Memory 更新 Agent
- 续写主 Agent 的上下文装配

## Positioning

### 与其他 spec 的关系

- `../spec.md`：产品级核心流程与 UI 交互 Source of Truth
- `novel-continuation-mvp/spec.md`：总编排层
- `creative-knowledge-base/spec.md`：桥段知识库与检索层
- 本 spec：事实型上下文与长期 Memory 层

### 模块边界

- 本 spec 负责：
  - 人物档案
  - 世界观文档
  - 章节摘要
  - 故事大纲
  - 源作品篇章地图
  - 精读进度
  - 上下文装配
- 本 spec 不负责：
  - 桥段去重
  - 代表片段选择
  - SceneBrief 检索
  - 桥段级 rerank

## Core Principles

- 优先保存“事实、状态、关系、时间顺序”，而不是保存仿写参考。
- 所有 Memory 更新都应尽量基于章节级精读结果，而不是零散的单段猜测。
- 续写主 Agent 读取 Memory 时优先取结构化结果，不直接回读全书原文。
- Memory 的目标是“持续一致”，不是“文学代表性”。
- Chapter Summary Agent 的处理粒度 SHALL 保持章节级，即继续围绕 `document_title_index` 或超长章节拆批生成章节摘要。
- Character Evidence Agent 的处理粒度 MAY 独立于章节摘要，将多个 `documents` 拼接为一个 evidence batch，用于降低人物抽取与人物性判断的 prompt/JSON 维度。
- Character Evidence Agent 的目标是为 Memory Candidate Agent 提供人物抽取、发言判断、行动状态与关系变化线索；它不是原文 offset 标注或可审计语料回源系统。
- Source Arc Mapping SHOULD 在 close-read 完成后执行，而不是在顺序精读过程中即时决定；该阶段基于完整章节摘要、故事大纲、人物线和世界观，从全局视角记录源作品中相对独立的故事篇章、转折点与功能段落。
- Memory 层保存的 `SourceArcMap` 是源作品事实型篇章地图，不是 Writer 直接套用的新书规划模板；可迁移的谋篇布局、节奏模式和人物登场/关系推进模式 SHOULD 由创作知识库层进一步沉淀为 `NarrativeStructurePattern` 或 `ArcPatternCard`。
- 章节摘要和故事大纲中依赖后文判断的内容 SHOULD 区分 `provisional` 与 `committed` 状态；顺序 close-read 产生的即时判断默认是暂定结果，只有在结合后续窗口或全局篇章地图复核后才可标记为已定稿。

## Memory Layers

### Requirement: Character Memory
系统 SHALL 为重要角色维护持续更新的人物档案。

#### Scenario: Character Profile 字段
- **WHEN** 系统为某人物创建或更新档案
- **THEN** 至少应支持如下字段或等价字段：
  - `character_id`
  - `canonical_name`
  - `aliases`
  - `personality_summary`
  - `occupation`
  - `age_or_stage`
  - `abilities`
  - `recent_activity_scope`
  - `relationship_summary`
  - `chapter_refs`
  - `speaking_character_status`
  - `personhood_evidence_summary`
  - `evidence_level`

#### Scenario: Character Profile 只保存事实型信息
- **WHEN** 系统更新人物档案
- **THEN** 应优先写入可支持续写一致性的事实、状态与关系变化
- **AND** 不应将桥段写法偏好存入人物档案

### Requirement: Character Evidence Batch
系统 SHALL 为 Character Evidence Agent 引入独立于 Chapter Summary Agent 的轻量 batch 工作单元。

#### Scenario: Evidence Batch 输入粒度
- **WHEN** 系统组装 Character Evidence Agent 输入
- **THEN** 可以将多个连续 `documents` 按阅读顺序拼接为一个 `character_evidence_batch`
- **AND** batch 输入 SHALL 包含 `character_evidence_batch_id`、拼接文本、可选的 document 分隔提示和已有上下文摘要
- **AND** batch 边界 SHOULD 主要由文本预算、源顺序和人物抽取效率决定
- **AND** batch 边界不要求等同于 `document_title_index`
- **AND** 该设计不改变 Chapter Summary Agent 的章节级处理粒度

#### Scenario: Character Evidence 输出字段
- **WHEN** Character Evidence Agent 完成一个 evidence batch
- **THEN** 输出至少应包含：
  - `character_evidence_batch_id`
  - `characters`
  - `canonical_name`
  - `aliases`
  - `is_speaking_character`
  - `speaking_evidence`
  - `personhood_evidence`
  - `activity_or_state_evidence`
  - `relationship_evidence`
  - `candidate_type`
  - `confidence`
  - `uncertainty_reason`
- **AND** `speaking_evidence` SHOULD 是简短判断说明，不要求返回原文连续子串
- **AND** `personhood_evidence` SHOULD 说明该候选为什么像真实角色，例如发言、被称呼、执行人物行动、具有身份称谓、与其他角色发生关系
- **AND** `activity_or_state_evidence` SHOULD 描述当前 batch 中可用于更新人物档案的行动、状态、心理或阶段变化
- **AND** `relationship_evidence` SHOULD 描述当前 batch 中可用于更新关系档案的互动或关系变化
- **AND** 输出不得要求模型逐 `doc_id` 返回人物列表、offset 区间或完整原文证据

#### Scenario: 低置信候选过滤
- **WHEN** 某候选只有弱文本共现、没有发言、没有人物行动、没有称谓或关系线索
- **THEN** Character Evidence Agent SHOULD 将其标为低置信候选或不输出
- **AND** Memory Candidate Agent SHOULD 对低置信候选降权，避免把动词、物品、抽象名词或场景词写入人物档案

#### Scenario: 与本地候选名服务关系
- **WHEN** 系统已有 CharacterMentionService 返回的候选名
- **THEN** Character Evidence Agent MAY 将这些候选作为提示
- **AND** Character Evidence Agent 不应完全依赖本地候选名服务
- **AND** Character Evidence Agent 仍应发现本地候选名服务漏掉的真实角色

### Requirement: World Memory
系统 SHALL 为每部小说维护唯一的详细世界观文档与压缩世界观概要。

#### Scenario: World Memory 字段
- **WHEN** 系统维护世界观
- **THEN** 至少应覆盖：
  - 世界类型
  - 时代背景
  - 超能力体系
  - 超自然生物或物品
  - 阵营势力
  - 核心禁忌与规则

#### Scenario: World Summary 压缩
- **WHEN** 详细世界观文档更新
- **THEN** 系统应生成不超过约 1KB 的世界观概要，用于后续 prompt 装配

### Requirement: Chapter Memory
系统 SHALL 为每个 `document_title_index` 维护章节级摘要。

#### Scenario: Chapter Summary 字段
- **WHEN** 精读 Agent 完成某章节处理
- **THEN** 至少应保存：
  - `chapter_id`
  - `document_title_index`
  - `chapter_summary`
  - `summary_status`
  - `evidence_window`
  - `target_range`
  - `intermediate_summaries`
  - `importance_score`
  - `related_chapters`
  - `updated_at`

#### Scenario: Chapter Summary 强调事实推进
- **WHEN** 系统生成章节摘要
- **THEN** 应优先保留地点、人物、行动、关键心理变化和关系变化
- **AND** 弱化低价值重复描写

#### Scenario: Chapter Summary 状态
- **WHEN** Chapter Summary Agent 在顺序 close-read 中刚处理完当前 `document_title_index`
- **THEN** 该章节摘要 SHALL 标记为 `summary_status = provisional`
- **AND** 其中的剧情事件链、人物状态和关键信息 MAY 作为事实型暂存结果使用
- **AND** 其中的结构功能、节奏判断、章节功能归类 SHOULD 被视为暂定结论

#### Scenario: Chapter Summary 延迟定稿
- **WHEN** 系统已经读取到足够后续章节，可以用一个连续上下文窗口复核目标章节
- **THEN** 系统 MAY 使用 `evidence_window` 记录本次复核参考的 `start_document_title_index` 与 `end_document_title_index`
- **AND** 系统 MAY 使用 `target_range` 记录本次定稿覆盖的章节范围
- **AND** 只有被后续窗口或 `SourceArcMap` 复核过的章节摘要才能标记为 `summary_status = committed`
- **AND** 对同一章节，后续 `committed` 摘要 SHOULD 覆盖或优先于较早的 `provisional` 摘要

### Requirement: Story Outline Memory
系统 SHALL 为每部小说维护整书级故事大纲。

#### Scenario: Story Outline 字段
- **WHEN** 系统维护整书大纲
- **THEN** 至少应支持：
  - `book_id`
  - `outline_summary`
  - `outline_status`
  - `evidence_window`
  - `target_range`
  - `major_turning_points`
  - `timeline_notes`
  - `main_character_threads`
  - `updated_at`

#### Scenario: Outline 长度约束
- **WHEN** 大纲超过约 10KB
- **THEN** 系统应优先保留主线推进、关键时间点和主要人物线

#### Scenario: Outline 状态
- **WHEN** Memory Candidate Agent 或顺序 close-read 流程生成即时 `outline_update`
- **THEN** 该大纲片段 SHOULD 标记为 `outline_status = provisional`
- **AND** Writer MAY 使用它理解当前已读剧情，但不应把它视为最终篇章结构判断

#### Scenario: Outline 窗口定稿
- **WHEN** 系统已经获得目标范围前后的足够章节摘要、人物档案和世界观概要
- **THEN** 系统 SHOULD 支持用较大的 `evidence_window` 重算较小的 `target_range` 大纲片段
- **AND** 例如可基于第 10 到第 20 个 `document_title_index` 的故事梗概和人物状态，总结并定稿第 14 到第 18 个 `document_title_index` 的大纲片段
- **AND** 该片段复核完成后可标记为 `outline_status = committed`
- **AND** 对同一 `target_range`，`committed` 大纲片段 SHOULD 覆盖或优先于较早的 `provisional` 片段

### Requirement: Source Arc Map Memory
系统 SHALL 在 close-read 形成完整或足够完整的章节摘要与故事大纲后，支持生成源作品事实型篇章地图 `SourceArcMap`。

#### Scenario: SourceArcMap 生成时机
- **WHEN** 精读阶段已经覆盖当前已入库正文，且章节摘要、故事大纲、人物档案与世界观概要可用
- **THEN** 系统 SHOULD 运行 post-close-read 的源作品篇章地图生成
- **AND** 不应要求 Reading Agent 在顺序 close-read 过程中承担最终源作品篇章边界判断职责
- **AND** `SourceArcMap` 产出的篇章功能和节奏判断 SHOULD 视为 `committed` 级结构信息

#### Scenario: SourceArcMap 输入来源
- **WHEN** 系统生成 `SourceArcMap`
- **THEN** 常规输入 SHOULD 是全书 document/chapter 级故事梗概、故事大纲、人物档案概要、世界观概要、章节重要性与关联信息
- **AND** 不应把整本原文作为常规输入
- **AND** 当 document/chapter 级梗概总量低于约 12KB 或配置的 `source_arc_summary_compression_threshold` 时，系统 SHOULD 直接把这些梗概发送给 Source Arc Mapping Agent，从整体上总结剧情节奏与篇章功能
- **AND** 对超长篇，系统 MUST 在输入超过模型安全预算时先通过模型生成可控压缩的剧情概要单元，再基于这些单元生成 `SourceArcMap`

#### Scenario: 超长故事梗概的重叠窗口压缩
- **WHEN** document/chapter 级故事梗概总量超过约 12KB 或配置的 `source_arc_summary_compression_threshold`
- **THEN** 系统 SHOULD 将连续 document 梗概按默认 8 个 document 一个窗口发送给模型压缩为独立 `plot_summary_unit`
- **AND** 相邻窗口 SHOULD 携带尾部重叠 document 以保留剧情衔接，默认窗口为 `0-7`、`6-13`、`12-19` 这种 8 document window / 2 document overlap / 6 document stride
- **AND** 每个 `plot_summary_unit` SHOULD 保留 `source_doc_ids`、`overlap_doc_ids`、`unit_summary`、`continuity_hooks`、`boundary_events` 与 `uncertainty_notes`
- **AND** 压缩幅度不应过大；压缩输出必须保留主线事件、人物状态变化、关系推进、设定揭示、伏笔与转折边界
- **AND** 测试环境 MAY 使用约 8KB 的阈值触发同一流程，以便进行冒烟测试

#### Scenario: SourceArcMap 字段
- **WHEN** 系统生成或更新 `SourceArcMap`
- **THEN** 至少应包含：
  - `book_id`
  - `source_arc_id`
  - `source_arc_title`
  - `start_document_title_index`
  - `end_document_title_index`
  - `source_arc_role`
  - `core_events`
  - `main_character_threads`
  - `world_or_rule_reveals`
  - `transition_from_previous`
  - `setup_for_next`
  - `pacing_notes`
  - `chapter_role_map`
  - `status`
  - `evidence_window`
- **AND** `source_arc_role` SHOULD 能区分主线推进、过渡缓冲、日常关系、设定揭示、高潮、收束等源作品中的事实功能
- **AND** `chapter_role_map` SHOULD 记录每个 document/chapter 在源作品中的结构功能，例如日常铺垫、新人物登场、关系升温、冲突升级、设定揭示、转场或回收
- **AND** `SourceArcMap` 不应把这些事实功能直接表述成“续写必须照搬”的模板

#### Scenario: 过渡与缓冲篇章
- **WHEN** 某些章节主要承担日常对话、人物内心、关系缓慢推进、生活状态或情绪缓冲
- **THEN** `SourceArcMap` SHOULD 明确标注其过渡或缓冲功能
- **AND** 不应因为缺乏强冲突就将其视为低价值内容

#### Scenario: 向创作知识库沉淀结构模式
- **WHEN** `SourceArcMap` 已可用，且系统需要为 Writer 提供可迁移的全书结构参考
- **THEN** 创作知识库层 SHOULD 基于 `SourceArcMap`、章节摘要和故事大纲沉淀 `NarrativeStructurePattern` 或 `ArcPatternCard`
- **AND** 这些 pattern SHOULD 强调剧情结构特征，例如若干 document/chapters 用于日常与感情生活、新人物登场、配角支线展开、冲突升级、设定揭示、篇章切换或收束
- **AND** Writer SHOULD 优先消费这些结构模式作为谋篇布局参考，而不是直接把源作品的 `SourceArcMap` 当作续写计划

## Progress Memory

### Requirement: Ingest Progress
系统 SHALL 维护原始小说读取与入库进度。

#### Scenario: Ingest Progress 字段
- **WHEN** 系统更新粗读入库进度
- **THEN** 至少记录：
  - `current_file`
  - `file_offset`
  - `last_doc_id`
  - `batch_id`
  - `updated_at`

### Requirement: Reading Progress
系统 SHALL 维护精读进度。

#### Scenario: Reading Progress 字段
- **WHEN** 系统更新精读进度
- **THEN** 至少记录：
  - `last_completed_doc_id`
  - `last_completed_chapter_id`
  - `updated_at`

## Context Assembly

### Requirement: 续写上下文装配
系统 SHALL 为续写主 Agent 提供稳定、可裁剪的长期上下文装配规则。

#### Scenario: 续写上下文输入来源
- **WHEN** 续写主 Agent 组装上下文
- **THEN** 应优先使用：
  - 已 `committed` 的章节摘要
  - 源作品篇章地图片段（仅在需要定位源作品结构或当前续写位置时）
  - 世界观概要
  - 相关人物档案
  - 已 `committed` 的故事大纲
- **AND** 仅在必要时回读原始 `documents`
- **AND** 当只有 `provisional` 摘要或大纲可用时，Context Assembly SHOULD 明确保留其状态，避免 Writer 将暂定结构判断误当作定稿事实

#### Scenario: Context 与创作知识库解耦
- **WHEN** 续写主 Agent 同时需要事实上下文与仿写参考
- **THEN** 本 spec 提供事实型上下文
- **AND** `creative-knowledge-base/spec.md` 提供桥段型参考
- **AND** 两者在装配层合流，但不在存储层混合

## Agent Boundaries

### Reading Agent
- 输入：`documents`
- 输出：章节摘要、世界观更新候选、剧情事实压缩结果
- 职责：章节级精读和压缩
- 约束：处理粒度保持章节级，继续围绕 `document_title_index` 或超长章节拆批运行
- 约束：顺序 close-read 阶段生成的章节摘要默认是 `provisional`，其中结构功能与节奏判断不承担最终定稿职责

### Character Evidence Agent
- 输入：`character_evidence_batch`，可由多个连续 `documents` 拼接而成
- 输出：batch-level 人物抽取结果、发言判断、人物性证据、行动状态证据、关系证据、置信度与不确定原因
- 职责：提高人物候选准确性，并为 Memory Candidate Agent 提供人物档案更新前的结构化证据
- 约束：不负责章节摘要、不负责最终写入人物档案、不要求逐 `doc_id`、offset 或原文连续子串输出

### Memory Candidate Agent
- 输入：章节摘要、Character Evidence batch-level 人物结果、已有 Memory 上下文
- 输出：人物更新候选、世界观更新候选、默认 `provisional` 的大纲更新候选
- 职责：把抽取结果转化为可写入长期 Memory 的候选事实

### Source Arc Mapping Agent / Service
- 输入：document/chapter 级故事梗概或压缩后的 `plot_summary_unit`、故事大纲、人物档案概要、世界观概要、章节重要性与关联信息
- 输出：`SourceArcMap`，包括源作品篇章边界、篇章功能、核心事件、人物线、设定揭示、过渡说明、后续铺垫与章节功能映射
- 职责：在 close-read 之后基于全局视野记录源作品事实型篇章结构，为创作知识库的结构模式沉淀提供输入
- 约束：不读取全书原文作为常规输入，不替代 Chapter Summary Agent，不直接生成续写正文，不生成可迁移剧情结构 pattern
- 约束：其篇章功能和节奏判断可作为 `committed` 级结构信息，供章节摘要和故事大纲定稿流程使用

### Memory Update Agent
- 输入：Memory Candidate Agent 输出的更新候选
- 输出：人物档案、世界观文档、故事大纲、进度状态
- 职责：把章节级信息沉淀为长期 Memory

### Context Assembly Agent / Service
- 输入：续写目标、章节位置、相关角色
- 输出：续写主 Agent 所需的长期上下文包，可在必要时包含相关 `SourceArcMap` 片段
- 职责：裁剪并组装事实型上下文

## Out of Scope

- `fragment_card` 生成
- 近重复检测
- 代表片段选择
- `SceneBrief -> 粗筛 -> rerank`
- 仿写参考桥段的最终排序
- 可迁移剧情结构模式 KB 的存储与检索
