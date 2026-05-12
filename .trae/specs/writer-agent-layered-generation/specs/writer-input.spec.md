# Writer Input Spec

## Purpose

该子 spec 负责定义正文执行输入边界，以及它与跨层 `WriterInputBundle`、`SceneBrief`、事实约束、风格参考、禁止项和长度预算之间的关系。

## Scope

- 当前分层 Writer 的正文执行输入：`chapter_execution_input.json`
- 旧跨层主链路输入：`WriterInputBundle`
- `ChapterBrief` 与 `SceneBrief` 的关系
- facts / style / forbidden / relation / character / budget 输入分类
- 与 [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md) 的对齐方式
- `NarrativeStructurePattern` / `ArcPatternCard` 作为结构模式参考进入 Writer 规划与正文输入的方式
- `SourceArcMap` 作为源作品定位事实进入 Writer 输入的可选方式

## Source Of Truth

- Product flow and UI: [../../spec.md](../../spec.md)
- Parent overview: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md)
- Parent architecture: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
- Cross-layer contracts: [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)

## Layer 4 Summary

目标：

- 将单章梗概扩写为完整章节正文
- 严格受限于本章之前的 Memory、最近窗口、当前章梗概与风格参考
- 当前分层 Writer 通过 `chapter_execution_input.json` 进入正文执行器，而不是直接跨层拼接任意字段

典型输出：

- `draft.md`
- `chapter_execution_input.json`
- `chapter_length_budget.json`
- `style_reference_bundle.json`
- `generation_review_decision.json`

要求：

- Writer Agent 在本层 **不负责重新发明剧情大方向**
- Writer Agent 在本层 **不负责新增关键设定**
- Writer Agent 在本层 **不负责自由创建关键新角色**
- Writer Agent 在本层 **不负责跨章推进未经批准的关系跃迁**
- Writer Agent 在本层 **不负责私自确认终稿并写回 Memory**
- 风格参考只影响表达层，不得覆盖事实层

## Writer Boundary

Writer Agent 的核心职责不是“自由写作”，而是：

- 消费冻结后的章节 brief
- 消费已确认的 `chapter_execution_input.json`
- 消费本章之前的事实型 Memory
- 消费风格参考与结构提示
- 产出受约束的正文草稿
- 配合校验与修订

Writer Agent 明确不应直接负责：

- 重写全书走向
- 擅自补大型世界观
- 擅自发明关键新角色
- 擅自推进关键关系状态
- 擅自越过当前批次
- 用风格模板压过原作事实

## Input Categories

当前分层 Writer 的直接执行输入以 `chapter_execution_input.json` 为准，其中：

- 事实约束来自已冻结的全书规划、世界观补充、批次计划、章节梗概和可用 Memory
- 源作品结构定位事实 MAY 来自 Memory 层 post-close-read 生成的 `SourceArcMap` 片段
- 可迁移全书结构参考 SHOULD 来自 KB 层沉淀的 `NarrativeStructurePattern` / `ArcPatternCard`
- 检索意图由 `ChapterBrief -> SceneBrief` 派生
- 风格参考来自 `style_reference_bundle.references`
- 计划角色约束来自已冻结的 `PlannedCharacterProfile` / `CharacterIntroductionPlan`
- 关系推进约束来自 `relation_state_gate`
- 禁止项来自 `forbidden_inputs`
- 长度预算来自已冻结的 `ChapterLengthPlan` 或单章 `chapter_length_budget.json`

`SourceArcMap` 属于源作品事实型结构定位上下文，不是风格参考，也不是续写模板。它用于帮助 Writer 理解源作品已经完成到哪个结构阶段、哪些人物线和伏笔尚未回收。

`NarrativeStructurePattern` / `ArcPatternCard` 属于结构模式参考，不覆盖事实约束。它用于提示当前章节或批次可采用的铺垫、过渡、新人物登场、关系推进、冲突升级、设定揭示或收束方式，并帮助 Writer 避免把所有章节都写成高强度事件推进。

## WriterInputBundle Alignment

`WriterInputBundle` 仍是跨层 contract 中用于主层装配的对象，但当前 Writer 分层生成的直接执行对象是 `chapter_execution_input.json`。

系统 SHALL 保持二者语义兼容：

- `WriterInputBundle.scene_brief` 对应正文执行输入中的派生 `SceneBrief`
- `WriterInputBundle.reference_fragments` 对应 `style_reference_bundle.references`
- `WriterInputBundle.context_payload` 对应正文执行输入中的事实型 Memory 与上游冻结事实
- `WriterInputBundle.sources` 对应正文执行输入与风格参考中的来源记录

系统 MAY 在冒烟测试或旧主层链路中继续构造 `WriterInputBundle`，但正式 Writer 分层执行不得要求用户直接编辑或理解 `WriterInputBundle`。

## Chapter Brief Derivation Rules

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

## Requirements

### Requirement: Writer Agent 只消费已确认执行输入

系统 SHALL 要求 Writer Agent 在正文扩写时只消费已经冻结的单章 brief 以及已确认的 `chapter_execution_input.json`。

#### Scenario: 正文层边界
- **WHEN** Writer Agent 开始撰写本章
- **THEN** 输入中必须包含：
  - 供正文层本地使用的 `ChapterBrief` 或兼容旧 `ScenePlan`
  - `chapter_length_budget`
  - `fact_inputs`
  - `style_reference_bundle`
  - `forbidden_inputs`
  - `relation_state_gate`
  - `planned_character_constraints`
- **AND** 若本章涉及计划角色首次登场，还必须消费对应的已冻结角色约束
- **AND** 不得要求 Writer Agent 同时决定新的世界规则与最终走向

### Requirement: Writer 输入应包含相关结构模式参考

系统 SHOULD 在 `NarrativeStructurePattern` / `ArcPatternCard` 可用时，将与当前章节或批次相关的结构模式参考装配进 Writer 输入。

#### Scenario: 消费结构模式片段
- **WHEN** Writer Agent 准备当前章输入，且 KB 层存在相关 `NarrativeStructurePattern` / `ArcPatternCard`
- **THEN** `chapter_execution_input.json` 或其结构参考输入应包含相关 `pattern_id`、结构功能、节奏类型、铺垫目标与回收目标
- **AND** Writer Agent 应把这些内容视为谋篇布局参考，而不是源作品事实或必须照搬的事件顺序
- **AND** 不得用结构模式覆盖事实约束

#### Scenario: 可选消费 SourceArcMap 片段
- **WHEN** Writer Agent 准备当前章输入，且 Memory 层存在与当前续写位置相关的 `SourceArcMap`
- **THEN** 正文执行输入中的事实约束 MAY 包含相关 `source_arc_id`、`source_arc_role`、未回收线索与源作品阶段定位
- **AND** Writer Agent 只能将其用于源作品位置理解和连续性判断
- **AND** 不得把 `SourceArcMap` 中的具体事件顺序当作新章节梗概

### Requirement: 风格参考与事实约束分离

系统 SHALL 将风格参考、范文模仿与事实型上下文分开存储、分开装配。

#### Scenario: 风格与事实冲突
- **WHEN** 风格参考暗示某种写法，但与事实型 Memory 冲突
- **THEN** 事实优先
- **AND** Writer Agent 只能学习表达，不得学习错误事实

## Non-Goals

- 不在本子 spec 中重新定义跨层 contract 的字段结构
- 不在本子 spec 中展开 workflow / rollback 的恢复逻辑
- 不在本子 spec 中定义 review / writeback 的验收门禁
