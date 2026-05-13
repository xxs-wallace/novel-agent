# Writer Runtime Boundaries Spec

## Purpose

本 spec 收束 Writer 运行期边界：正文输入、冻结恢复、回滚、章节验收和 accepted-only writeback。

它不描述大纲 research 的 prompt / query 细节；相关内容见 [`../designs/outline-research-loop.design.md`](../designs/outline-research-loop.design.md)。

## Scope

- `chapter_execution_input.json` 的输入边界
- `ChapterBrief -> SceneBrief` 的跨层对齐
- facts / style / forbidden / relation / character / budget 的输入分类
- `Freeze A/B/C/D/E` 的运行语义
- 用户确认点、恢复点、失败重试和级联回滚
- 章节验收、`GenerationReviewDecision` 和 accepted-only writeback
- 大体量正文的审阅展示策略

正式字段结构以 [`../contracts.md`](../contracts.md) 和 [`../../novel-continuation-mvp/contracts.md`](../../novel-continuation-mvp/contracts.md) 为准。

## 1. Writer Input Boundary

正文 Writer 是受限执行器，不是自由规划器。

它只消费：

- 已冻结的 `ChapterBrief` 或兼容旧 `ScenePlan`
- 已确认的 `chapter_execution_input.json`
- 已冻结的 `chapter_length_budget`
- 事实约束 `fact_inputs`
- 风格参考 `style_reference_bundle`
- 禁止项 `forbidden_inputs`
- 关系推进门禁 `relation_state_gate`
- 计划角色约束 `planned_character_constraints`
- 由上游装配的 `WriterInputBundle` 兼容输入

它不得：

- 重写全书走向
- 擅自补大型世界观
- 自由创建关键新角色
- 跨章推进未经批准的关系跃迁
- 越过当前批次提前消费伏笔
- 私自确认终稿并写回 Memory
- 用风格参考覆盖事实约束

## 2. Input Categories

`chapter_execution_input.json` 中的输入应按职责分开：

- `facts`：已冻结的全书规划、世界观补充、批次计划、章节梗概、可用 Memory、最近窗口和来源记录。
- `style`：风格参考片段、叙述距离、句法密度、对话节奏和表达偏好。
- `forbidden`：不得提前揭露的秘密、禁止关系跃迁、未确认设定、不得消费的后续剧情。
- `relation`：当前关系状态、允许推进幅度、所需桥接事件。
- `character`：已冻结的 `PlannedCharacterProfile` / `CharacterIntroductionPlan`。
- `budget`：目标字数、最小/最大字数、重点章标记和 prompt token 预算。

`SourceArcMap` 只能作为源作品结构定位事实，用于理解当前结构阶段、未回收线索和人物线位置，不得被当作续写事件顺序。

`NarrativeStructurePattern` / `ArcPatternCard` 只能作为结构模式参考，用于铺垫、过渡、登场、升级、收束和节奏安排，不得覆盖事实约束。

## 3. Contract Alignment

`WriterInputBundle` 仍是跨层 contract 中的正文输入包。当前分层 Writer 可以直接消费 `chapter_execution_input.json`，但必须保持语义兼容：

- `WriterInputBundle.scene_brief` 对应派生后的 `SceneBrief`
- `WriterInputBundle.reference_fragments` 对应风格参考
- `WriterInputBundle.context_payload` 对应 Memory 事实型上下文与上游冻结事实
- `WriterInputBundle.sources` 对应来源记录

`ChapterBrief` 是 Writer 内部规划对象，不能替代 `SceneBrief`。

`ChapterBrief -> SceneBrief` 至少遵守：

- `ChapterBrief.goal -> SceneBrief.scene_objective`
- `ChapterBrief.emotional_goal -> SceneBrief.emotional_goal`
- `ChapterBrief.conflict_goal -> SceneBrief.conflict_goal`
- `ChapterBrief.plot_function -> SceneBrief.narrative_function`
- `ChapterBrief.relationship_targets -> SceneBrief.relationship_state`
- `ChapterBrief.forbidden -> SceneBrief.must_avoid`

若 `ChapterBrief` 缺少检索字段，允许结合兼容旧 `ScenePlan` 或批次约束补齐，但不得更改已冻结 contract 的语义。

## 4. Freeze Points

系统必须定义以下冻结点：

- `Freeze A`：全书续写方向、世界观补全和人物补充方案冻结。
- `Freeze B`：当前批次计划冻结。
- `Freeze C`：最近 N 章标题与高密度梗概冻结。
- `Freeze D`：单章写作材料、长度预算、事实和风格输入冻结。
- `Freeze E`：已验收终稿与状态变化冻结。

规则：

- 低层不得绕过高层冻结点直接篡改大纲。
- 每一层冻结后，其产物对下一层视为只读正式输入。
- 正文写作发现上游规划不可执行时，必须发起重规划请求，而不是自行改写。
- `Freeze E` 只能接收已通过关键校验且被用户 accepted 的草稿。

## 5. Recovery And Rollback

用户确认后的中间产物是可恢复检查点。

级联回滚规则：

- 修改 `Freeze D` 对应的当前章写作材料时，当前章正文、状态变化和回写候选失效。
- 修改当前章长度预算时，当前章正文失效，但不必自动作废后续章节。
- 修改 `Freeze C` 对应的 `ChapterPackage` / `ChapterBrief` 时，该章及其后续章节的长度计划、写作输入、正文和回写失效。
- 修改 `Freeze B` 对应的 `BatchPlan` 时，当前批次及后续批次下游产物失效。
- 修改 `Freeze A` 对应的 `BookContinuationPlan`、`WorldExpansionPack` 或 `CharacterCastPlan` 时，全部后续产物失效。
- 修改尚未正式登场的 `PlannedCharacterProfile` 时，所有引用该角色的批次、章节、写作输入和正文失效。
- 修改已进入 `canon_active` 的计划角色时，系统不得静默覆盖 Memory；必须让用户选择保留 canon、回滚首次登场章及之后内容，或分叉替代角色方案。

失败恢复规则：

- 正文失败可先在保持 `Freeze D` 不变的情况下重试。
- 连续失败时应回退到 `Freeze C` 请求章节重规划。
- 若失败根因来自批次目标或全书规划，才继续向 `Freeze B` 或 `Freeze A` 回退。

## 6. User Review Display

规划类 artifact 应完整展示，便于用户审阅：

- `BatchPlan`
- `ChapterPackage`
- `ChapterLengthPlan`

大体量 artifact 应使用短预览：

- `draft.md` 只展示路径、当前字数、目标字数、连续性状态和开头短预览
- 默认短预览不应超过约 1-2KB
- 完整正文通过文件路径供用户打开或编辑
- 完整检索上下文不应直接刷入 terminal

## 7. Chapter Acceptance

章节草稿通过基础校验后必须进入显式验收节点，并输出 `GenerationReviewDecision`。

状态语义：

- `accepted`：允许进入 `Freeze E`，允许正式回写，当前版本成为 canon。
- `revise_length`：回到长度规划层，更新或确认当前章长度预算后重写；不回写。
- `replan_chapter`：回到章节梗概层，重新确认章节规划和长度计划后重写；不回写。
- `discarded`：当前版本仅保留运行产物，进入暂停或等待用户下一步；不回写。

规则：

- 未通过关键校验的正文不得直接进入下一章输入。
- 未被用户接受的正文不得写回人物档案、关系状态、时间线、世界状态或 Creative KB。
- 被替换或作废的草稿只保留在 `runs` 等临时产物中。
- 后续章节只允许消费“已验收且已回写”的 canon 状态。

## 8. Writeback

accepted 后的写回至少包含：

- 人物状态变化
- 关系状态变化
- 时间线事件
- 世界状态变化
- 伏笔状态变化
- 批次 / 大纲进度

`StateDelta` 和 `MemoryWriteback` 必须能追溯到对应草稿版本、验收决策和来源。

## Requirements

### Requirement: Writer Agent 只消费已确认执行输入

系统 SHALL 要求 Writer Agent 在正文扩写时只消费已经冻结的单章 brief、长度预算和已确认的 `chapter_execution_input.json`。

### Requirement: 风格参考与事实约束分离

系统 SHALL 将风格参考、范文模仿与事实型上下文分开存储、分开装配；当二者冲突时事实优先。

### Requirement: 用户确认点必须可恢复

系统 SHALL 将用户确认后的中间产物视为可恢复检查点，并允许从最近冻结点继续。

### Requirement: 上游修改必须触发级联回滚

系统 SHALL 将分层规划产物视为带依赖关系的冻结节点；当上游节点被修改时，相关下游节点必须失效。

### Requirement: 章节生成后必须支持验收或重生成

系统 SHALL 在章节通过基础校验后提供显式验收节点，允许接受、调整长度后重生成、退回章节梗概重规划，或作废本次草稿。

### Requirement: 章节终稿必须 accepted 后才能回写

系统 SHALL 仅在 `GenerationReviewDecision.status = accepted` 后进入 `Freeze E` 并执行正式 Memory writeback。

## Non-Goals

- 不重新定义 `GenerationReviewDecision`、`LengthPlanUpdate` 或 `ChapterReplanRequest` 的字段结构。
- 不定义大纲 research 的 query prompt。
- 不定义 Memory / KB 的底层表结构。
