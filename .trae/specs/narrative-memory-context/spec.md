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
  - 粗读入库时的章节边界候选、章节标题元数据与 document/chapter 对齐约束
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
- 粗读入库阶段 SHALL 在构造 segmentation prompt 前识别章节边界候选；本地规则只产生候选与置信度，不应把少数硬编码格式当作唯一章节切分真相。
- 高置信章节边界 SHALL 作为 segment hard boundary，粗读模型不得把它吞入上一章节 document；中低置信边界 SHOULD 作为模型判定参考，而不是强制切分。
- Character Evidence Agent 的处理粒度 MAY 独立于章节摘要，将多个 `documents` 拼接为一个 evidence batch，用于降低人物抽取与人物性判断的 prompt/JSON 维度。
- Character Evidence Agent 的目标是为 Memory Candidate Agent 提供人物抽取、发言判断、行动状态与关系变化线索；它不是原文 offset 标注或可审计语料回源系统。
- Source Arc Mapping SHOULD 在 close-read 完成后执行，而不是在顺序精读过程中即时决定；该阶段基于完整章节摘要、故事大纲、人物线和世界观，从全局视角记录源作品中相对独立的故事篇章、转折点与功能段落。
- Memory 层保存的 `SourceArcMap` 是源作品事实型篇章地图，不是 Writer 直接套用的新书规划模板；可迁移的谋篇布局、节奏模式和人物登场/关系推进模式 SHOULD 由创作知识库层进一步沉淀为 `NarrativeStructurePattern` 或 `ArcPatternCard`。
- 章节摘要和故事大纲中依赖后文判断的内容 SHOULD 区分 `provisional` 与 `committed` 状态；顺序 close-read 产生的即时判断默认是暂定结果，只有在结合后续窗口或全局篇章地图复核后才可标记为已定稿。

## Memory Layers

### Requirement: Chapter Boundary Detection for Ingest
系统 SHALL 在粗读入库阶段引入 `ChapterBoundaryDetector` 或等价组件，用于发现章节边界候选并保护后续 Memory 的章节级索引。

#### Scenario: Boundary Candidate 输出
- **WHEN** 粗读流程读取原始小说文本、目录或 PDF 书签
- **THEN** `ChapterBoundaryDetector` SHOULD 输出结构化边界候选：
  - `candidate_id`
  - `source_path`
  - `start_offset`
  - `end_offset`
  - `raw_heading`
  - `normalized_heading`
  - `normalized_ordinal`
  - `boundary_type`：例如 `chapter` / `volume` / `part` / `scene`
  - `confidence`
  - `evidence`：例如 `standalone_short_line`、`toc_match`、`ordinal_sequence`、`repeated_book_pattern`
  - `format_family`：例如 `第N章`、`（N）`、`Chapter N`、`roman_numeral`
- **AND** Detector MUST 保留 source offset，供粗读 document 和后续章节摘要回源
- **AND** Detector SHOULD 以“候选 + 置信度”表达判断，不应只返回布尔值

#### Scenario: 粗读 segmenter 集成
- **WHEN** 粗读流程把原文切成 prompt segments
- **THEN** segmenter SHALL 调用 `ChapterBoundaryDetector`
- **AND** 高置信 `chapter` / `volume` / `part` 边界 MUST 成为 segment hard boundary
- **AND** segmenter 不得把高置信章节标题合并进前一个 segment
- **AND** 中低置信候选 MAY 进入 segmentation prompt，交由模型结合上下文决定是否形成新 document/chapter
- **AND** segmenter 的职责仍是控制文本预算、保持字符不丢失和 source offset 连续；章节语义判断由 Detector 候选、模型输出和 validator 共同完成

#### Scenario: 模型分组与 validator
- **WHEN** Segmentation Agent 根据 segments 返回 documents
- **THEN** 模型 SHOULD 返回覆盖连续 `segment_ids` 的 document 分组和章节标题判断
- **AND** Agent MUST 校验所有 segment 是否被连续、无重复、无遗漏地覆盖
- **AND** 如果一个模型返回的 document 内部包含多个高置信章节边界，Agent MUST 拆分该 document 或重跑该 batch
- **AND** 如果章节边界识别不可靠，Agent SHOULD 显式标记该 document/chapter 为 `boundary_status = uncertain` 或等价字段
- **AND** 前端、Writer 和 close-read 不应把 `boundary_status = uncertain` 的章节边界当作已定稿结构事实

#### Scenario: 不同小说格式适配
- **WHEN** 一本书使用非 Markdown 标题或非常规章节格式
- **THEN** Detector SHOULD 结合多种信号发现候选，包括：
  - 目录、PDF 书签或文件名
  - 独立短行
  - 连续编号序列
  - `第N章` / `第N回` / `卷N` / `幕N`
  - `Chapter N` / `Part N`
  - 中文数字、阿拉伯数字、罗马数字与括号编号
  - 同一本书内重复出现的标题格式
- **AND** 对同一本书，Detector SHOULD 动态学习已出现的 `format_family` 和 ordinal sequence；连续出现的格式可提高后续候选置信度
- **AND** 低置信候选不得单独触发强制切章，避免把正文中的编号、日期、对话或列表误判为章节

#### Scenario: Boundary 元数据进入 Memory
- **WHEN** 粗读入库生成 `documents`
- **THEN** 每个 document SHOULD 保存或可重建：
  - `boundary_candidate_id`
  - `raw_heading`
  - `normalized_heading`
  - `boundary_confidence`
  - `boundary_status`
  - `source_start_offset`
  - `source_end_offset`
- **AND** Chapter Summary、Story Outline、SourceArcMap 与 BTree Page SHOULD 优先使用已校验的章节边界元数据
- **AND** 如果后续 close-read 或 SourceArcMap 发现边界错误，系统 SHOULD 能标记并重建受影响的 document/chapter Memory，而不是只在章节摘要层修补标题

### Requirement: BTree-like Narrative Memory
close-read 处理完的 Narrative Memory SHALL 表达为一种 BTree-like 的分层 Page 数据结构，而不是一组彼此孤立的摘要文件。

#### Scenario: Memory Page 节点不变量
- **WHEN** 系统将 close-read 结果写入 Memory
- **THEN** 每一层 Memory Page 节点 SHALL 保存：
  - `page_id`
  - `page_type`
  - `child_refs`：指向下一层 Page 或原始 document/event 的索引
  - `source_doc_range` 或等价的 `source_doc_ids`
  - `summary`：对下一层节点的压缩概括
  - `status`：例如 `provisional` / `committed`
  - `updated_at`
- **AND** Page 的 `summary` MUST 只压缩下一层节点已经表达的信息，不应引入未被下层索引支撑的新事实
- **AND** Page 的 `child_refs` MUST 足以让系统从上层摘要确定性回溯到下一层节点
- **AND** Page SHOULD 支持多个同层 sibling；对几百万字的超长篇小说，根部以下 MAY 存在多个 event-summary Page，而不是强行压缩成单个全书摘要

#### Scenario: Memory BTree 层级
- **WHEN** 系统完成 close-read Memory 写回
- **THEN** 推荐的事实压缩链路 SHOULD 是：
  - `document` leaf：粗读入库的原始文本片段，保存原文、source offset、`doc_id`
  - `chapter` Page：多个连续 `document` 的章节级摘要
  - `event` Page：多个 `chapter.summary_md` 的剧情事件概括
  - `event_summary` Page：多个 `event` 的高层连续摘要
- **AND** 多个 `document` SHOULD 对应一个真实 chapter；如果章节边界识别不可靠，系统 SHOULD 显式标记该 chapter Page 为派生的 `document_title_index` 聚合桶
- **AND** 多个 chapter summary SHOULD 汇聚为一个 event
- **AND** 当信息密度较高时，event 覆盖的原始范围 MAY 退化到单个 chapter，甚至单个 document
- **AND** event summary SHOULD 汇总多个 event，而不是直接跳过 event list 汇总原始 documents

#### Scenario: BTree 压缩比例
- **WHEN** 系统生成 chapter 级 `summary_md`
- **THEN** `summary_md` SHOULD 不超过其覆盖原始文字内容的 1/10
- **AND** 如果源文本信息密度过高导致摘要超过 1/10，系统 SHOULD 将 chapter Page 拆分为更小的 Page 或标记 `compression_warning`
- **WHEN** 系统生成 `event_summary` Page
- **THEN** 单个 `event_summary.summary` SHOULD 不超过约 200 个中文字符
- **AND** 单个 `event_summary` Page SHOULD 目标覆盖约 10 万到 20 万字原始小说文档
- **AND** `event_summary` Page SHOULD 只记录其覆盖的 event id 起止范围，例如 `start_event_id`、`end_event_id` 或等价的连续 `event_id_range`
- **AND** 若 event id 不连续或发生重排，系统 MAY 附加 `event_ids` 列表作为校验索引，但常规 Writer 输入 SHOULD 优先使用起止范围

#### Scenario: 超长篇多 Page 根结构
- **WHEN** 小说原始长度达到数百万字
- **THEN** 系统 SHOULD 允许存在多个 sibling `event_summary` Page
- **AND** 上层 Writer Context SHOULD 按续写位置、用户意图、人物线和相关 event id 范围选择需要展开的 Page
- **AND** 系统不应为了得到唯一总摘要而把多个 event summary 继续压缩到丢失回源能力

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
  - `story_events`

#### Scenario: Character Profile 只保存事实型信息
- **WHEN** 系统更新人物档案
- **THEN** 应优先写入可支持续写一致性的事实、状态与关系变化
- **AND** 不应将桥段写法偏好存入人物档案

#### Scenario: Character Profile 分层表达
- **WHEN** 系统维护人物档案
- **THEN** 人物档案 SHOULD 分为至少两层：
  - 基础属性层：姓名、别名、年龄或阶段、国籍/身份、外貌或显著特征、性格、基础人际关系、能力和特长
  - 人物剧情时间线层：以该人物为维度过滤出的 `story_events`
- **AND** 基础属性层 SHOULD 足够压缩，服务于 Writer 快速理解人物稳定状态
- **AND** 人物剧情时间线层 SHOULD 保留关键事件、关系推进、状态转折与行动结果
- **AND** 每个 `story_event` MUST 带有可回源索引，例如 `event_id`、`source_chapter_indexes`、`source_doc_ids` 或 `source_doc_range`
- **AND** `mentioned_doc_ids` / `speaking_doc_ids` 仍可作为底层索引保存，但不应作为模型筛选人物过往的唯一入口

#### Scenario: Character Event List 与原文回源
- **WHEN** 模型需要确认某人物的过往经历
- **THEN** 系统 SHOULD 先返回该人物的人物剧情时间线，而不是直接返回庞大的 mentioned doc id 列表
- **AND** 模型 MAY 选择其中一个或多个 `event_id` / `source_doc_ids` 请求进一步展开原文证据
- **AND** 系统 SHOULD 通过该事件携带的 `source_doc_ids` 或 `source_doc_range` 返回对应原始 `documents` 的摘录或全文片段

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

#### Scenario: Story Outline 四层结构
- **WHEN** 系统完成 close-read Memory 写回
- **THEN** 叙事事实链 SHOULD 形成四层结构：
  - `document`：粗读入库的原始文档片段，保存原文与 source offset
  - `chapter summary`：close-read 后的章节 Page 概要，压缩多个 document
  - `event list`：从多个 chapter summary 中抽取的结构化关键事件 Page 列表
  - `event summary`：对多个 event Page 的连续自然语言压缩
- **AND** 上层不应丢失下层索引；`summary`、`event list` 和 `event summary` SHOULD 能回到其覆盖的 `source_doc_ids` 或 `source_doc_range`
- **AND** 该四层结构 SHOULD 满足 BTree-like Memory Page 的不变量：每一层 Page 都保存对下一层节点的索引与压缩概括

#### Scenario: Outline Event List 字段
- **WHEN** 系统保存 close-read 产生的大纲事件
- **THEN** 每个事件 SHOULD 至少包含：
  - `event_id`
  - `label`
  - `summary`
  - `document_title_index`
  - `participants`
  - `source_title_indexes`
  - `source_doc_ids`
  - `source_doc_start_id`
  - `source_doc_end_id`
  - `source_doc_range`
  - `event_summary_level`
- **AND** `event_id` SHOULD 在同一书籍内稳定，可用于后续模型请求精确展开该事件
- **AND** `summary` SHOULD 是多个 document/chapter 剧情的浓缩概括，而不是逐段复述
- **AND** `participants` SHOULD 支持反向构建人物维度 event list

#### Scenario: Event Summary
- **WHEN** 系统维护整书或章节范围的大纲
- **THEN** 系统 SHOULD 保存 `event_summary` 或等价字段，作为 event list 的自然语言连续摘要
- **AND** `event_summary` SHOULD 保留事件顺序、因果衔接和主要人物状态变化
- **AND** `event_summary` SHOULD 同样携带或继承覆盖范围的 `source_doc_ids` / `source_doc_range`
- **AND** 单个 `event_summary` SHOULD 是面向 Writer 快速定位历史上下文的 Page 摘要，不超过约 200 个中文字符
- **AND** 单个 `event_summary` SHOULD 目标覆盖约 10 万到 20 万字原始小说文档
- **AND** 常规情况下 `event_summary` 只需要记录对应 event id 的起止范围；系统通过 event id 范围再展开到 event list、chapter summary 和 document

#### Scenario: Event Summary 滚动压缩
- **GIVEN** close-read 已积累 N 个尚未被上层摘要覆盖的 outline events
- **WHEN** N 达到压缩阈值
- **THEN** Agent SHOULD 把这些未压缩 events 按时间顺序发送给模型
- **AND** 模型 SHOULD 判断前部哪些 events 关联性足够强，可以压缩为一个连续 `event_summary`
- **AND** 模型 MUST 返回尾部不相关、太新或需要等待后续上下文的 `event` index
- **AND** Agent MUST 只把非尾部 events 标记为已压缩，尾部 events 继续保留为 pending
- **AND** 任何 `event_summary` MUST 保存其覆盖的 `event_ids`、`source_doc_ids`、`source_doc_range`，以便从摘要回源到 event list 和原始 document

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

### Requirement: BTree Descent + Model-guided Pruning 查询链路
系统 SHALL 支持从上层 Memory Page 逐层向下定位原文证据的查询链路，并允许模型在每一层选择是否继续展开。

#### Scenario: 查询层级下降
- **WHEN** Writer 或 Outline Research Loop 发起故事细节查询
- **THEN** 系统 SHOULD 按如下顺序执行 BTree descent：
  1. `event_summary` root Page：定位剧情大范围
  2. `event list`：展开被选中 event summary 覆盖的 event range
  3. `chapter summary`：展开被选中 event 覆盖的 chapter range
  4. `document`：展开被选中 chapter 覆盖的 document range 或摘录
- **AND** 每一层都 SHOULD 返回当前层候选节点的完整必要信息，例如 id、summary、范围、人物、状态和下层索引
- **AND** 每一层模型决策 MUST 使用结构化输出，至少包含 `need_drill_down`、`selected_ids`、`query_suffix`、`reason` 和 `confidence`
- **AND** 如果模型判断当前层信息已足够回答问题，系统 MAY 停止下降并返回当前层证据

#### Scenario: query_suffix 累积设计
- **WHEN** 模型在某一层选择需要继续查询下层节点
- **THEN** 模型 SHOULD 返回 `query_suffix`，用来描述本层筛选后新增的约束、关注点或歧义
- **AND** Agent MUST 将 `query_suffix` 追加到原始查询尾部，而不是替换原始查询
- **AND** 下一层 prompt MUST 同时包含 `original_query` 与累计 `query_suffix_chain`
- **AND** `query_suffix` SHOULD 简短、可审计，不应包含未由当前层候选支撑的新事实

#### Scenario: Path Context 裁剪策略
- **WHEN** 查询进入下一层 Page
- **THEN** 系统 SHOULD 裁剪掉上一层未被选中的 sibling candidates
- **AND** 系统 MUST 保留：
  - `original_query`
  - 累计 `query_suffix_chain`
  - `path_context`：已选中的上层 Page id、摘要、选择理由、置信度和范围
  - 当前层完整候选节点
- **AND** 上一层的全量候选 sibling 不应继续进入 prompt，除非模型显式返回低置信、空选择或 `need_sibling_scan = true`
- **AND** 该策略的目标是让 token 使用随查询深度近似线性增长，而不是把每一层的全部候选重复携带到下一层

#### Scenario: 查询 prompt 结构
- **WHEN** Agent 调用模型进行某一层节点选择
- **THEN** prompt payload SHOULD 使用如下结构或等价结构：
  - `original_query`
  - `query_suffix_chain`
  - `path_context`
  - `current_level`
  - `current_candidates`
  - `selection_task`
  - `output_schema`
- **AND** `current_candidates` MUST 使用稳定 id，例如 `event_summary_id`、`event_id`、`chapter_id` 或 `doc_id`
- **AND** 模型输出 MUST 可以被 Agent 直接用于下一层确定性查询，不应只返回自然语言描述

#### Scenario: 低置信与相邻 sibling 回退
- **WHEN** 某层模型返回空选择、低置信或 `need_sibling_scan = true`
- **THEN** Agent SHOULD 回到上一层，扩展到相邻 sibling Page 或扩大候选范围
- **AND** Agent SHOULD 记录该回退动作、输入候选 id、最终 selected ids 与原因
- **AND** 如果多次回退仍无法定位，系统 SHOULD 返回 `insufficient_memory_context`，并说明缺失的层级或索引

#### Scenario: 查询可审计轨迹
- **WHEN** BTree descent 查询完成
- **THEN** 系统 SHOULD 保存查询轨迹，至少包含：
  - 每层输入候选 ids
  - 每层 selected ids
  - 每层 `query_suffix`
  - 每层选择理由和置信度
  - 最终返回的 document ids 或摘要节点 ids
- **AND** 该轨迹可用于解释为什么最终回源到某些 document

#### Scenario: Memory 层接口边界
- **WHEN** Writer 或 benchmark 需要查询历史剧情事实
- **THEN** Memory 层 SHOULD 提供稳定接口或等价 facade：
  - `root_scan(query)`：返回 `event_summary` root Page 候选
  - `drill_down(state, selected_ids)`：从当前层展开到下一层候选
  - `resolve_event_ids(event_ids)`：确定性展开 event 到 chapter / document refs
  - `resolve_chapter_refs(chapter_refs)`：确定性展开 chapter summary 与 document refs
  - `resolve_document_refs(doc_ids, excerpt_budget)`：返回 document 原文或裁剪摘录
- **AND** Memory 层 SHALL 负责预算裁剪、状态标注、回源索引和泄漏边界
- **AND** Writer 层 SHALL 负责提出查询意图、选择候选、维护 `query_suffix_chain` 与判断信息是否足够
- **AND** Writer 层不应直接扫描 Memory SQLite / Markdown 来绕过该接口

#### Scenario: 用户反馈触发 Memory Query

- **WHEN** Writer Prompt Loop 收到用户反馈、reviewer feedback 或 retry instruction
- **AND** 当前上下文不足以判断反馈是否应当修改大纲、人物状态或设定边界
- **THEN** Writer SHOULD 将该反馈归一化为新的 `ResearchRequest`
- **AND** 该请求 MAY 触发 `story_detail`、`character_profile` 或 `world_concept` Memory Query
- **AND** Memory Query SHALL 复用与初次用户输入相同的 `NarrativeMemoryQueryService`、预算限制、trace 结构和泄漏审计
- **AND** Memory 层不区分“初始输入”与“用户反馈”的优先级语义；它只接收查询意图、返回候选与证据，是否继续查询由 Writer Prompt Loop 决定

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
