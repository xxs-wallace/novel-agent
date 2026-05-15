# Writer Agent 分层生成 Spec

## Source Of Truth

- 产品级核心流程、总编排、用户接口、UI 交互与用户可见状态文案，以 [`../spec.md`](../spec.md) 为准。
- 本 spec 只定义 Writer 分层生成模型、内部冻结点依赖、人物补充、批次规划、章节梗概、长度计划、正文执行边界与写回规则。
- `Freeze A/B/C/D/E`、`checkpoint`、`artifact` 等术语属于内部工程语义；用户界面 SHALL 使用核心 spec 中的自然语言状态。

## Scope

Writer 层负责把已经建模的原作事实、世界观、人物档案、故事大纲、创作知识库和用户续写意图转化为可审阅、可修改、可恢复的续写产物。

本 spec 不重复定义：

- 原文导入与 `documents` 基线，见 [`../novel-continuation-mvp/spec.md`](../novel-continuation-mvp/spec.md)
- 产品主流程与 UI，见 [`../spec.md`](../spec.md)
- 创作知识库字段与 rerank，见 [`../creative-knowledge-base/spec.md`](../creative-knowledge-base/spec.md)
- Memory 字段与上下文装配，见 [`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md)
- 大纲生成 research / query 细节，见 [`designs/outline-research-loop.design.md`](designs/outline-research-loop.design.md)
- 正文执行输入、恢复回滚、章节验收与写回运行边界，见 [`specs/runtime-boundaries.spec.md`](specs/runtime-boundaries.spec.md)

Writer 层新增或消费的对象不得与 [`../novel-continuation-mvp/contracts.md`](../novel-continuation-mvp/contracts.md) 中已冻结的跨层对象冲突。

## Layer Model

### Layer 0: 输入基线层

输入来源：

- 原作已存在正文
- 原作已有故事大纲
- post-close-read 生成的源作品篇章地图 `SourceArcMap`
- 创作知识库沉淀的 `NarrativeStructurePattern` / `ArcPatternCard`
- 人物档案 / 世界观 / 时间线 / 关系状态
- 创作知识库中的结构理论与范文片段
- 用户确认后的续写方向与世界观补充

本层不生成正文，只负责把可用事实组织为后续层的稳定输入。

本层还需要输出：

- `ModelingStatus`
- `MissingModelingSteps`
- `ReadyForContinuation`

只有当建模状态满足最低要求时，系统才应允许进入正式续写流程。

### Layer 0A: 故事规模与高潮约束输入层

目标：

- 在生成 `BookContinuationPlan` 之前，由 TUI 引导用户把“想写什么”补充为“准备写多长、分几章、高潮在哪里”
- 把用户自然语言方向转化为可传给 Book Planner 的规模、节奏和高潮约束
- 帮助初学者不必直接写完整大纲，而是先确认故事长度、章节数量、高潮设计和节奏偏好
- 不要求用户单独预填“涉及人物名单”；人物提及应从用户故事概述中自动抽取

典型输入：

- `StoryScaleInput`
- `PacingSpec`
- `ClimaxPlanInput`
- `UserStoryOverview`
- `ExtractedCharacterMentions`

要求：

- 用户只需要填写自然语言故事方向、目标章节数、目标总字数、默认单章字数、节奏偏好和整本故事高潮；不要求用户手写每章 `scene_beats`
- `PacingSpec` SHALL 是生成 `BookContinuationPlan` 的前置输入，而不是 `BookContinuationPlan` 之后才追加的长度补丁
- `ClimaxPlanInput` SHALL 至少描述冲突高潮、情绪高潮、希望靠近的章节位置，以及必须提前铺垫的伏笔或关系变化
- 若用户只填写章节数或总字数之一，系统 MAY 推导另一个字段，但必须在 TUI 中展示推导结果并允许用户修改
- 该层不得读取 reference truth 原文或 Reviewer 结果；只能消费用户输入和已经确认的建模记忆

### Layer 0A.5: 人物提及抽取与 Memory 对齐层

目标：

- 从用户提供的故事概述、续写意图和补充说明中自动抽取人物姓名、别名、称谓和疑似新角色
- 将抽取结果交给本地 Agent 查询 Character Memory
- 对已存在人物进行对齐，对未匹配人物询问用户是否新增
- 只在确认新增人物时要求用户补充最小人物档案

典型输出：

- `ExtractedCharacterMentions`
- `CharacterMentionResolution`
- `MissingCharacterConfirmationRequest`
- `CharacterSeedInput`

要求：

- 系统 SHALL 优先从用户自然语言概述中抽取人物提及，而不是要求用户先手工填写涉及人物名单
- 模型 SHALL 返回候选人名、称谓、上下文片段和置信度，不直接写入正式人物档案
- 本地 Agent SHALL 使用人物名、别名、称谓和上下文线索查询 Character Memory，并输出 resolved / ambiguous / missing 三类结果
- 对 `resolved` 人物，系统 SHALL 使用既有人物档案作为后续 research 和规划输入
- 对 `ambiguous` 人物，系统 SHALL 让用户选择匹配到哪个既有人物，或确认这是新人物
- 对 `missing` 人物，系统 SHALL 询问用户是否新增人物；只有用户确认新增后，才进入最小人物档案补充
- 用户拒绝新增的人名不得进入 `CharacterCastPlan`，除非后续剧情结构缺位流程重新提出受约束角色需求

### Layer 0B: 大纲研究循环层

目标：

- 在生成 `BookContinuationPlan`、`BatchPlan` 或高密度 `ChapterPackage` 前，让模型先基于轻量索引主动调查所需信息
- 避免由编排器一次性把大量 Memory 和 SQLite 内容拼进 prompt
- 让模型在多轮 tool call 后自行判断信息是否足够；不足时继续查询或向用户提出关键问题

典型输入：

- `OutlineSeedPacket`
- `ResearchBudget`

典型输出：

- `outline_research_trace.json`
- `planning_notebook.json`
- `SufficiencyDecision`

要求：

- 初始输入只应包含用户续写意图、故事规模、高潮约束、人物姓名索引、世界观精炼梗概、世界观概念名词索引、历史故事精炼总览，以及可选未决伏笔标题级索引
- `OutlineSeedPacket` 中的重点人物 SHOULD 来自 `CharacterMentionResolution`，而不是用户手工填写的人物清单
- 模型 SHALL 通过语义请求向本地 Agent 查询更多信息，而不是直接编写 SQL 或读取任意文件
- 语义请求至少 SHOULD 支持 `story_detail`、`character_profile`、`world_concept`
- 本地 Agent SHALL 将语义请求转换为 SQLite / Markdown / Memory / KB 可理解的查询，并返回带来源的 evidence
- 对 `story_detail`，本地 Agent SHOULD 优先调用 Memory 层提供的 BTree descent / page query 接口，而不是由 Writer 直接读取 SQLite、扫描 Markdown 或拼接原文
- Writer 模型 SHALL 负责在每层 Memory candidates 中选择需要继续展开的节点，并返回 `selected_ids`、`query_suffix`、`reason`、`confidence`；Memory 层 SHALL 负责确定性展开 selected ids 到下一层 Page 或 document
- Writer 层不得重定义 Memory Page schema、event summary 压缩规则、chapter summary 回源规则或 document excerpt 裁剪规则
- 模型 MAY 发起多轮请求，但必须受 `ResearchBudget` 限制
- 每轮 research 必须维护或更新 `planning_notebook`
- 若达到预算上限仍缺少关键授权边界，系统 SHALL 向用户提出少量阻塞问题，而不是静默假设高风险剧情
- `SufficiencyDecision` SHALL 明确区分模型可生成内容、需要用户补充的知识、可安全假设的低风险缺口和必须先补建模的阻塞项

#### Memory / Writer 分工

- Memory 层负责：
  - 构建并维护 `event_summary -> event -> chapter -> document` 的 Page 索引
  - 提供 root scan、drill down、event/chapter/document resolver 和 evidence bundle
  - 对候选节点做预算裁剪、状态标注和回源 trace
  - 保证不把 reference-only 或未授权未来信息泄漏给 Writer
- Writer 层负责：
  - 将续写目标、用户反馈、reviewer feedback 或重试原因转化为 research request
  - 调用模型在 Memory candidates 中做选择
  - 维护 `query_suffix_chain`、`path_context` 和 `planning_notebook`
  - 判断信息是否足够，并生成 `BookContinuationPlan` / `BatchPlan` / `ChapterPackage`
  - 不直接写 Memory，不直接把 candidate fact 升级为 confirmed fact
- `OutlineResearchContextBroker` 可以作为 Writer 调用 Memory 的 facade，但不应逐步演变成新的 Memory 存储层或并行检索系统
- Memory Query 的触发源不只限于首次用户输入。Writer Prompt Loop 在收到用户反馈、reviewer 要求调整或生成失败后的 retry instruction 时，也可以像 Code Agent tool call 一样发起 `story_detail` / `character_profile` / `world_concept` 查询；所有查询都必须进入同一套预算、trace、leakage audit 和 sufficiency gate。

### Layer 1: 全书续写规划层

目标：

- 沿着原作已有大纲，补出后续主线发展方向
- 确定长程目标、阶段性高潮、核心矛盾与终局方向
- 明确哪些角色弧线允许推进，哪些关系必须保持克制
- 吸收 `PacingSpec` 与 `ClimaxPlanInput`，生成带章节规模、默认字数和高潮位置的正式续写大纲
- 基于大纲研究循环产出的 evidence、planning notebook 和信息充足性判断生成高密度全书规划

典型输出：

- `BookContinuationPlan`
- `EndingPlan`
- `ArcRoadmap`
- `ChapterOutlineSlots`
- `OpenQuestions`

要求：

- 生成正式 `BookContinuationPlan` 前，系统 SHALL 先完成 Outline Research Loop，除非产品模式显式选择降级为无研究草案
- `BookContinuationPlan` 的关键剧情安排 SHOULD 能追溯到用户输入、confirmed Memory、inferred evidence、Creative KB 结构模式或明确的用户授权假设
- 优先承接已有大纲，不能脱离原作强行另起炉灶
- `BookContinuationPlan` SHALL 包含目标章节数、目标总字数、默认单章目标字数、整体节奏配置和高潮设计；它是后续批次与章节规划的正式大纲
- `BookContinuationPlan.chapter_outline_slots` SHALL 为每个计划章节提供默认字数、章节功能、上层目标、铺垫目标、回收目标和禁止提前消费项；这些 slot 不是最终 `ChapterBrief`，但必须足以指导后续 `BatchPlan`
- 每个章节 slot 的默认字数总和 SHOULD 接近目标总字数；若存在重点章或高潮章，允许局部 override，但必须保留总量解释
- `ChapterLengthPlan` MAY 在 Freeze C 后细化单章 `target/min/max`，但不得反向推翻 Freeze A 中已经确认的总规模、章节数量和高潮位置，除非用户显式要求重做全书续写规划
- 若存在 `NarrativeStructurePattern` / `ArcPatternCard`，必须参考其铺垫、过渡、登场、升级与收束节奏来设计后续 `ArcRoadmap`，而不是只按单章目标推进
- 若存在 `SourceArcMap`，可用它定位源作品当前结构位置和未回收线索，但不得把源作品具体篇章内容直接当作续写计划
- 对新增结局、终局秘密、角色命运变更保持保守
- 必须标注“确认事实 / 推断补全 / 未决问题”

### Layer 1B: 世界观与设定补全层

目标：

- 为 Layer 1 规划所需的新增设定做最小补完
- 仅补后续剧情真的需要的世界规则、组织关系、能力限制、地理与历史信息
- 避免先写正文、后补设定

典型输出：

- `WorldExpansionPack`
- `ConstraintRules`
- `SettingOpenItems`

要求：

- 新设定必须服务于后续剧情，而不是为了显得宏大而堆料
- 每个新增设定都要说明：
  - 为什么需要
  - 与原设定是否冲突
  - 对哪些后续剧情有约束

### Layer 1C: 人物补充层

目标：

- 处理用户概述中已经显式提到、但当前 Memory 中尚未建档，并被用户确认新增的新角色
- 处理剧情规划中尚未被具体人物承接的角色功能位
- 在正文开始前冻结“谁将登场、为何登场、何时登场、不能越界到什么程度”

典型输出：

- `CharacterRequirementReport`
- `CharacterCastRequest`
- `CharacterSeedInput`
- `CharacterCastPlan`
- `PlannedCharacterProfile`
- `CharacterIntroductionPlan`

要求：

- 必须先区分：
  - 显式命名角色：模型从用户概述或规划文本中抽取到的人物提及
  - 隐式角色缺位：剧情结构上需要、但尚未绑定到具体人物的功能位
- 不得要求用户在启动流程中手工列全人物名单，作为进入规划的硬前置
- 不得只靠剧情推断替代显式人物提及抽取和 Memory 对齐
- 模糊人数与阵营要求可以触发受约束候选生成，但不得无约束自由随机
- `PlannedCharacterProfile` 属于 Writer 层上游规划对象，不等同于 Memory 层正式 `character_profiles`
- 只有当角色在正文中首次登场、通过校验并完成回写后，才可转入正式 Character Memory

### Layer 2: 批次剧情规划层

目标：

- 将全书后续剧情拆成若干可执行批次
- 每个批次通常对应“最近 N 章”、一个小篇章，或后续 `ArcRoadmap` 中某个阶段的一段
- 每次执行只规划当前批次，不一次展开全书所有章节细纲

典型输出：

- `BatchPlan`
- `BatchGoals`
- `BatchConflicts`
- `BatchExitConditions`

要求：

- 一个批次必须有明确起点、阶段任务和收束目标
- `BatchPlan` SHALL 以已冻结的 `BookContinuationPlan` 为强前置输入，而不是仅依据用户即时意图直接生成
- `BatchPlan` SHALL 从 `BookContinuationPlan.chapter_outline_slots` 中选择当前批次覆盖范围，并保留对应章节的默认字数、章节功能、铺垫/回收目标和高潮接近度
- 若 KB 层提供相关 `NarrativeStructurePattern` / `ArcPatternCard`，`BatchPlan` SHALL 标注自己借鉴的结构模式、过渡功能、铺垫/回收目标与节奏类型
- 若 Memory 层提供相关 `SourceArcMap`，`BatchPlan` MAY 记录源作品结构参考来源，但不应把源作品 arc 当作目标剧情事实
- 若存在 `CharacterCastPlan`，`BatchPlan` SHALL 同时消费已冻结的人物补充结果，并为首次登场角色预留执行位置
- 批次之间允许重新规划，但不能随意推翻 Layer 1 已冻结的大方向
- 批次是正文生成的上游冻结单位

### Layer 3: 章节标题与梗概层

目标：

- 基于当前批次计划，生成最近 N 章的章节标题与故事梗概
- 将章节梗概提升为正文执行前的高密度约束层，尽量完整描述人物、场景、行动、结果和关系变化
- 将结构理论和关系弧线知识库转化为可写的章节 brief
- 从章节 brief 中派生符合 [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md) 的 `SceneBrief`，供创作知识库层检索使用

典型输出：

- `ChapterPackage`
- `ChapterBrief`
- `ChapterTitle`
- `ChapterSynopsis`
- `ChapterLengthPlan`
- `SceneIntent`
- `SceneBrief`

要求：

- 每章必须说明：
  - 章节目标
  - 情绪目标
  - 冲突目标
  - 关系推进目标
  - 本章结束时应改变什么
- 每章 SHOULD 明确关键场景中的人物、地点、行动、行动结果、状态变化和伏笔处理；正文扩写层不应被迫重新发明这些剧情节点
- 每章必须绑定预算信息：
  - 来自 `BookContinuationPlan.chapter_outline_slots` 的默认目标字数
  - 是否属于重点展开章节
  - 若是重点章节，单章长度 override 是多少
- 每章应根据目标长度生成足够细的内部大纲：
  - `scene_beats`: 当前章内部的场景/段落级目标
  - `transition_requirements`: 从上一章自然过渡到本章目标所需桥接
  - `setup_payoff`: 本章负责埋设或回收的伏笔
  - `pacing_notes`: 节奏密度、详略重点和不得注水的范围
- `scene_beats` SHOULD 由 Writer 根据 `BookContinuationPlan`、`BatchPlan`、用户规模约束和 close-read 记忆自动生成；用户只负责审阅、删除、补充或调整，不应被要求从零填写
- 每章必须绑定来源：
  - 来自大纲的约束
  - 来自世界观的约束
  - 来自人物/关系状态的约束
  - 来自计划角色首次登场约束
  - 来自剧情结构知识库的结构建议
- `ChapterBrief` 属于 Writer 层内部规划对象，不能替代跨层 contract 中的 `SceneBrief`
- 若进入在线检索，必须从 `ChapterBrief` 或兼容旧 `ScenePlan` 派生出 contract 兼容的 `SceneBrief`
- `ChapterBrief -> SceneBrief` 的派生至少遵守以下确定性映射：
  - `ChapterBrief.goal -> SceneBrief.scene_objective`
  - `ChapterBrief.emotional_goal -> SceneBrief.emotional_goal`
  - `ChapterBrief.conflict_goal -> SceneBrief.conflict_goal`
  - `ChapterBrief.plot_function` 或结构意图 -> `SceneBrief.narrative_function`
  - `ChapterBrief.relationship_targets[].current_state/target_state` -> `SceneBrief.relationship_state`
  - `ChapterBrief.forbidden` -> `SceneBrief.must_avoid`
  - 若 `ChapterBrief` 缺少检索所需字段，则允许结合兼容旧 `ScenePlan` 或批次约束补齐，但不得绕过 [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md) 已冻结字段语义

### Layer 4: 正文扩写层

本层负责基于冻结 brief 与正文执行输入扩写正文。

详细输入边界、输入分类与 `ChapterBrief -> SceneBrief` 对齐规则见：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
- [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)

在主 spec 中仅保留摘要：

- Writer 层只消费冻结后的正文输入
- 风格参考不得覆盖事实约束
- 当前分层 Writer 的直接执行输入为 `chapter_execution_input.json`
- 正文扩写层 SHOULD 主要关注文笔、风格、节奏、场景呈现和细节表达，而不是重做大纲或梗概层的剧情决策

### Layer 5: 回写与校验层

本层负责章节校验、章节验收、状态提取与正式回写。

详细产品语义已迁移到：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
- [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)

在主 spec 中仅保留摘要：

- 本层必须提供显式章节验收节点
- 只有 `GenerationReviewDecision.status = accepted` 才允许进入 `Freeze E`
- 未验收、被替换或被作废的草稿不得进入正式 Memory / KB

## Freeze Points

主 spec 中仅保留冻结点摘要：

- `Freeze A`: 全书续写方向冻结
- `Freeze B`: 当前批次计划冻结
- `Freeze C`: 最近 N 章梗概冻结
- `Freeze D`: 单章写作 brief 冻结
- `Freeze E`: 本章已验收终稿与状态变化冻结

详细工作流语义、恢复点与级联回滚规则见：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)

## Writer Agent Boundary

详细正文层边界已迁移到：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)

在主 spec 中仅保留摘要：

- Writer Agent 是受限执行器，而不是自由写作者
- Writer Agent 必须消费冻结后的 brief 与装配后的输入包
- Writer Agent 不得越权修改上游规划或事实边界

## Requirements

### Requirement: 分层生成必须显式化

系统 SHALL 将小说续写/自动生成拆为至少五个可观察层级：全书规划、设定补全、批次规划、章节梗概、正文扩写，并在正文后执行回写与校验。

#### Scenario: 不允许单层直写全书
- **WHEN** 用户请求长程续写或自动生成多章内容
- **THEN** 系统先生成上游规划产物
- **AND** 不直接从用户目标跳到正文

#### Scenario: 先冻结全书级方向再规划批次
- **WHEN** 用户已确认续写方向与世界观补充
- **THEN** 系统先生成 `BookContinuationPlan`
- **AND** 在 `Freeze A` 完成后才允许生成正式 `BatchPlan`
- **AND** `BatchPlan` 不得绕过 `BookContinuationPlan` 直接由即时用户输入生成

### Requirement: BookContinuationPlan 必须吸收故事规模与高潮约束

系统 SHALL 在生成 `BookContinuationPlan` 之前收集故事规模、章节数量、总长度、默认单章长度、节奏偏好和整本故事高潮，并将这些约束写入 Freeze A 的正式全书大纲。

#### Scenario: TUI 引导用户填写故事规模
- **WHEN** 用户输入自然语言故事方向后进入 Writer 启动向导
- **THEN** TUI 要求或引导用户填写目标章节数、目标总字数、默认单章字数和节奏偏好
- **AND** 若用户只填写部分长度字段，系统可给出推导值
- **AND** 推导值必须在生成 `BookContinuationPlan` 前展示给用户确认或修改

#### Scenario: TUI 引导用户填写整本故事高潮
- **WHEN** 用户确认故事规模后
- **THEN** TUI 引导用户填写冲突高潮、情绪高潮、希望高潮靠近的章节位置、必须铺垫的伏笔或关系变化
- **AND** 这些字段进入 `ClimaxPlanInput`
- **AND** Book Planner 不得把高潮提前消费到不符合用户指定位置的章节

#### Scenario: BookContinuationPlan 成为带长度的大纲
- **WHEN** Book Planner 生成 `BookContinuationPlan`
- **THEN** 输出必须包含目标章节数、目标总字数、默认单章目标字数、节奏配置和高潮计划
- **AND** 输出必须包含 `chapter_outline_slots`
- **AND** 每个 slot 至少包含章节序号、默认目标字数、章节功能、高层目标、铺垫目标、回收目标和禁止提前消费项

### Requirement: 大纲生成必须支持 Outline Research Loop

系统 SHOULD 在生成 `BookContinuationPlan`、`BatchPlan` 或高密度 `ChapterPackage` 前执行 Outline Research Loop，让模型基于轻量索引主动请求故事细节、人物档案或世界观概念。

#### Scenario: 初始输入只给索引入口
- **WHEN** 系统准备生成全书或批次大纲
- **THEN** 系统装配 `OutlineSeedPacket`
- **AND** `OutlineSeedPacket` 包含已对齐的重点人物、可查询人物索引、世界观精炼梗概、世界观概念名词索引和历史故事精炼总览
- **AND** 不应把完整人物档案、完整世界观文档或完整历史时间线一次性塞入初始 prompt

### Requirement: 系统必须自动抽取用户概述中的人物提及

系统 SHALL 从用户故事概述中自动抽取人物姓名和称谓，并交给本地 Agent 对齐 Character Memory；只有未匹配人物才进入新增人物确认。

#### Scenario: 自动抽取人物姓名
- **WHEN** 用户提交续写概述、故事目标或补充说明
- **THEN** 模型提取其中的人物姓名、别名、称谓和上下文片段
- **AND** 输出 `ExtractedCharacterMentions`
- **AND** 不要求用户先手工填写完整人物名单

#### Scenario: 本地对齐 Character Memory
- **WHEN** 系统收到 `ExtractedCharacterMentions`
- **THEN** 本地 Agent 使用人物名、别名、称谓和上下文线索查询历史人物档案
- **AND** 输出 `CharacterMentionResolution`
- **AND** 将结果分为 `resolved / ambiguous / missing`

#### Scenario: 未匹配人物需要用户确认
- **WHEN** 某个人物提及在历史档案中没有匹配结果
- **THEN** 系统询问用户是否将其作为新增人物
- **AND** 只有用户确认新增后，系统才要求补充最小人物档案
- **AND** 未经确认的人物不得直接写入 `CharacterCastPlan` 或正式 Character Memory

#### Scenario: 模型提出 story_detail 查询
- **WHEN** 模型需要了解历史剧情细节
- **THEN** 模型返回 `story_detail` 语义请求
- **AND** 请求用自然语言描述想了解的故事细节、查询目的和优先级
- **AND** 本地 Agent 负责将该请求转换为 SQLite、Markdown 或 Memory 可执行查询

#### Scenario: 多轮 research
- **WHEN** 本地 Agent 返回 evidence 后
- **THEN** 模型可以继续提出下一轮 requests
- **AND** 每轮必须更新 `planning_notebook`
- **AND** 系统必须受 `ResearchBudget` 限制，避免无限检索

#### Scenario: 信息不足时询问用户
- **WHEN** 本地资料无法回答关键授权边界，或预算耗尽后仍存在阻塞缺口
- **THEN** 模型输出 `needs_user_input`
- **AND** 系统向用户提出少量具体问题，问题应能直接补齐大纲生成所需知识
- **AND** 不得对高风险剧情、终局秘密、关系跃迁或世界规则突破做静默假设

#### Scenario: 预算耗尽后继续生成草案
- **WHEN** ResearchBudget 已耗尽，但剩余不明确点均为低风险细节
- **THEN** 模型可以输出 `proceed_with_assumptions`
- **AND** 必须列出 `assumptions`、`optional_gaps` 和 `remaining_risks`
- **AND** 后续大纲必须标注这些假设，不得把它们写成已确认事实

#### Scenario: 预算耗尽后阻塞
- **WHEN** ResearchBudget 已耗尽，且缺少可用人物档案、历史大纲索引、当前续写起点或其他基础建模材料
- **THEN** 模型输出 `blocked`
- **AND** 返回 `required_actions`
- **AND** 系统不得继续生成正式大纲，只能生成低置信调试草案或引导用户先补建模

#### Scenario: 用户补充知识进入 research
- **WHEN** 用户回答 `needs_user_input` 中的问题
- **THEN** 系统将用户回答记录为 `user_authorized` evidence
- **AND** 将其加入 `planning_notebook`
- **AND** 系统 MAY 继续一小轮 research 或直接生成大纲

### Requirement: story_detail 必须通过本地 Resolver 解析

系统 SHALL 将 `story_detail.query` 视为语义请求，而不是数据库查询语言。

#### Scenario: 查询理解
- **WHEN** 本地 Agent 收到 `story_detail`
- **THEN** 系统使用 query understanding 流程解析人物、概念、事件意图、时间线提示和需要的事实侧面
- **AND** 输出结构化检索计划

#### Scenario: 历史大纲索引到源文档
- **WHEN** 系统从历史大纲中返回候选故事细节
- **THEN** 候选结果必须能追溯到 document、chapter 或 segment 位置
- **AND** 最低可用版本可以用章节摘要索引
- **AND** 完整版本 SHOULD 使用事件级 `HistoricalOutlineEventIndex`

#### Scenario: 候选事件 rerank
- **WHEN** 初步检索得到多个候选事件或章节摘要
- **THEN** 系统应根据原始 query、purpose 和候选卡片执行 rerank
- **AND** 返回最相关 evidence、覆盖的事实侧面、缺失侧面和来源引用

### Requirement: 人物补充必须先解析显式角色再检查隐式缺位

系统 SHALL 在 `Freeze A` 之前处理新增角色需求，并区分“用户已点名角色”和“剧情仍缺角色功能位”。

#### Scenario: 显式命名新角色
- **WHEN** `ExtractedCharacterMentions` 中出现一个当前 Memory 中不存在、且用户确认新增的人物，例如“大反派 X”
- **THEN** 系统先将其视为显式命名新角色，并进入最小人物档案补充
- **AND** 不得把这类角色仅作为“缺失角色槽位”推断结果处理

#### Scenario: 隐式角色缺位
- **WHEN** `BookContinuationPlan draft` 显示当前后续剧情需要某类角色承担功能，但尚未绑定到具体人物
- **THEN** 系统输出角色缺位报告
- **AND** 后续可进入 `Character Casting`

### Requirement: 计划角色不得直接污染正式 Character Memory

系统 SHALL 将“计划角色”与 Memory 层的正式人物档案分离管理。

#### Scenario: 计划角色状态
- **WHEN** 系统在人物补充层生成新角色
- **THEN** 角色先以 `PlannedCharacterProfile` 形式存在
- **AND** 默认状态处于 `planned` 或 `introduced`
- **AND** 不直接写入正式 `character_profiles`

#### Scenario: 新角色正式入档
- **WHEN** 某计划角色在正文中首次登场、通过连续性校验并完成回写
- **THEN** 系统才将其转为正式 Character Memory 可消费对象

### Requirement: Writer 层不得重定义已冻结跨层 contract

系统 SHALL 复用 [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md) 中已冻结的 `SceneBrief`、`ContextAssemblyPayload`、`WriterInputBundle` 等对象，不得在 Writer spec 中另起一套冲突命名和语义。

#### Scenario: 使用 SceneBrief
- **WHEN** Layer 3 需要把章节意图交给创作知识库层做检索
- **THEN** 必须输出 contract 兼容的 `SceneBrief`
- **AND** 不得用 `ChapterBrief` 直接替代 `SceneBrief`

#### Scenario: 保持正文层输入兼容
- **WHEN** Writer Agent 开始正文扩写
- **THEN** 当前分层执行输入必须能追溯到已冻结的 `ChapterBrief`、派生 `SceneBrief`、事实约束、风格参考和长度预算
- **AND** 若测试或跨层主链路需要构造 `WriterInputBundle`，不得改变 `WriterInputBundle` 与 `ContextAssemblyPayload` 的 contract 语义

### Requirement: 冻结梗概后必须生成章节长度计划

系统 SHALL 在 `Freeze C` 之后生成 `ChapterLengthPlan`，用于为当前批次提供默认章节长度，并允许对重点章节单独配置长度。

#### Scenario: 使用默认长度和重点章节 override
- **WHEN** 最近 N 章 `ChapterPackage` 已确认
- **THEN** 系统生成默认章节长度
- **AND** 允许用户指定重点章节或高潮章节
- **AND** 允许为这些章节单独指定 `target_chars / min_chars / max_chars`

#### Scenario: 交互式调整长度计划
- **WHEN** 用户选择调整 `ChapterLengthPlan`
- **THEN** 系统应支持用户保存默认长度覆盖值、单章 override 或修改后的 `chapter_length_plan.json`
- **AND** 修改后的长度计划必须重新保存并作为后续 `Freeze D` 输入
- **AND** 若长度计划变更影响当前章，系统必须重新生成或重新确认当前章执行输入

#### Scenario: 单章写作读取长度计划
- **WHEN** 系统加载某一章 `ChapterBrief`
- **THEN** 系统同时加载该章对应的长度预算
- **AND** Writer Agent 必须将其视为正文扩写的正式约束之一

### Requirement: Writer 规划必须消费结构模式以改善铺垫

系统 SHOULD 在 close-read 完成并完成 KB 结构沉淀后，消费 `NarrativeStructurePattern` / `ArcPatternCard`，用于学习长篇小说的谋篇布局、铺垫节奏、新人物登场、关系推进、篇章切换、高潮与收束方式。

#### Scenario: 使用结构模式规划批次
- **WHEN** `NarrativeStructurePattern` / `ArcPatternCard` 可用且用户进入 Writer Layer 1 / Layer 2
- **THEN** 系统应选择与当前续写目标相符的结构模式
- **AND** `BatchPlan` 应记录借鉴的 pattern id、节奏类型、铺垫目标、回收目标和过渡约束
- **AND** 不应把所有章节都规划为高强度主线推进

#### Scenario: 允许过渡章节
- **WHEN** 结构模式提示某些阶段需要过渡、日常、关系缓冲或内心活动章节
- **THEN** Writer 规划应允许生成低冲突章节
- **AND** 这类章节仍必须说明其人物状态、关系铺垫、设定缓释或后续回收功能

#### Scenario: SourceArcMap 只作为源作品定位参考
- **WHEN** `SourceArcMap` 与结构模式同时可用
- **THEN** Writer MAY 使用 `SourceArcMap` 理解源作品已经完成到哪个结构阶段、哪些伏笔或人物线尚未回收
- **AND** Writer SHALL 优先使用 `NarrativeStructurePattern` / `ArcPatternCard` 设计新的后续大纲与梗概
- **AND** 不得直接复制源作品 `SourceArcMap` 中的具体事件顺序作为续写内容

### Requirement: 用户确认点必须可恢复

系统 SHALL 将用户确认后的中间产物视为可恢复检查点。

该 requirement 的详细恢复语义已迁移到：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)

### Requirement: 章节生成后必须支持验收或重生成

系统 SHALL 在章节通过基础校验后提供一个显式验收节点，并输出结构化 `GenerationReviewDecision`。

本 requirement 的详细分支语义、场景与 accepted-only writeback 规则已迁移到：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
- [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)

### Requirement: 上游修改必须触发级联回滚

系统 SHALL 将分层规划产物视为带依赖关系的冻结节点；当上游节点被修改时，所有下游节点必须失效并回滚。

该 requirement 的详细失效传播与回滚语义已迁移到：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)

### Requirement: 章节生成基于批次而非全书一次性细纲

系统 SHALL 使用 `BatchPlan` 作为中间层，将全书后续内容拆成多个分批执行单元。

#### Scenario: 批次规划
- **WHEN** Layer 1 已确定全书方向
- **THEN** Layer 2 仅生成当前批次的章节包
- **AND** 后续批次可在不推翻全书方向的前提下重规划

### Requirement: Writer Agent 只消费冻结 brief

系统 SHALL 要求 Writer Agent 在正文扩写时只消费已经冻结的单章 brief 以及已确认的正文执行输入。

该 requirement 的详细输入边界已迁移到：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)

### Requirement: 世界观补全与剧情规划分离

系统 SHALL 将“剧情想怎么走”与“世界观允许怎么走”视为两个相关但独立的层。

#### Scenario: 新设定引入
- **WHEN** 后续剧情需要新增设定
- **THEN** 系统先在设定层生成最小补全
- **AND** 再将其注入批次与章节规划

### Requirement: 关系推进必须受状态约束

系统 SHALL 在章节梗概层和正文扩写层共同检查人物关系的当前状态与合法推进幅度。

#### Scenario: 关系弧线推进
- **WHEN** 一章涉及友情、爱情或亲情的重要变化
- **THEN** 系统读取当前关系状态
- **AND** 判断目标变化是否合法
- **AND** 如不合法，则先生成所需桥接事件，而不是直接跳跃

### Requirement: 风格参考与事实约束分离

系统 SHALL 将风格参考、范文模仿与事实型上下文分开存储、分开装配。

该 requirement 的详细语义已迁移到：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)

### Requirement: 章节终稿必须回写状态

系统 SHALL 在章节通过校验并完成正式验收后提取状态变化并回写到 Memory 层。

accepted-only writeback 的详细规则已迁移到：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)

### Requirement: 失败恢复必须基于冻结点

系统 SHALL 支持从最近冻结点重跑，而不是每次从零开始。

该 requirement 的详细重试与回退语义已迁移到：

- [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)

## Output Artifacts

Writer 层主要产物：

- `outline_seed_packet.json`
- `outline_research_trace.json`
- `memory_query_trace.json`（来自 BTree descent / Memory page query，可嵌入或引用在 `outline_research_trace.json` 中）
- `memory_query_decision_log.json`（Writer 模型对 Memory candidates 的结构化选择记录，可选独立落盘）
- `planning_notebook.json`
- `sufficiency_decision.json`
- `historical_outline_event_index.json`（来自 Memory / 大纲索引层，可选引用）
- `source_arc_map.json`（来自 Memory 层，可选引用）
- `narrative_structure_patterns.json` / `arc_pattern_cards.json`（来自 KB 层，可选引用）
- `book_continuation_plan.json`
- `world_expansion_pack.json`
- `character_requirement_report.json`
- `character_cast_request.json`
- `character_cast_plan.json`
- `planned_character_profiles.json`
- `character_introduction_plan.json`
- `batch_plan.json`
- `chapter_package.json`
- `chapter_brief.json`
- `chapter_length_plan.json`
- `chapter_length_budget.json`
- `style_reference_bundle.json`
- `chapter_execution_input.json`
- `draft.md`
- `generation_review_decision.json`
- `continuity_report.json`
- `state_delta.json`
- `memory_writeback.json`
- `planned_character_registry.json`

## Product Modes

产品模式的用户体验由核心 spec 定义。Writer 层只定义内部自动确认策略。

### Assist Mode

- 默认在全书规划、批次规划、章节梗概、本章写作材料和写回前等待用户确认
- 适合严肃续写、同人承接、已有大纲的长篇补完

### Batch Mode

- 默认在全书规划、批次规划和章节梗概处等待用户确认
- 后续执行可按策略自动推进，但应允许插入人工审阅
- Agent 自动完成最近一批章节

### Auto Novel Mode

- 策略层自动确认内部冻结点
- 仍必须写出冻结记录，便于回滚和审计

## Non-Goals

本 spec 当前不包含：

- UI 流程、视觉样式与前端组件实现细节
- 商业化计费设计
- 多书并行调度策略
- 模型训练或微调方案

## Success Criteria

- 能稳定生成“先规划、后写作、写后回写”的闭环
- 能在大纲生成前通过多轮 research 主动查询故事细节、人物档案和世界观概念
- 大纲与章节梗概具备足够高的信息密度，使正文层主要承担文笔和风格表达
- 能对最近 N 章做批次化生成而不是逐章无头扩写
- Writer Agent 不再频繁越权发明设定或跳过关系铺垫
- 失败时能从冻结点恢复
- 后续可平滑扩展到自动化长篇生成
