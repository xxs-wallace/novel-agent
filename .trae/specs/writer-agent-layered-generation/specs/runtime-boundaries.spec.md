# Writer Runtime Boundaries Spec

## Purpose

本 spec 收束 Writer 运行期边界：Draft Research Loop、Draft Prose Executor、正文输入、review artifact 恢复、回滚、用户草稿决策和 accepted-only writeback。

它不描述大纲 research 的 prompt / query 细节；相关内容见 [`../designs/outline-research-loop.design.md`](../designs/outline-research-loop.design.md)。

## Scope

- `draft_seed_packet.json`、`draft_context_notebook.json` 和 `chapter_execution_input.json` 的输入边界
- `ChapterBrief -> SceneBrief` 的跨层对齐
- facts / style / forbidden / relation / character / budget 的输入分类
- Draft Research Loop 的查询、摘取、阻塞与重写边界
- Draft Prose Executor 的受限执行边界
- artifact review gate 的运行语义
- 用户确认点、恢复点、失败重试和级联回滚
- 用户草稿决策、`GenerationReviewDecision` 和 accepted-only writeback
- 大体量正文的审阅展示策略

正式字段结构以 [`../contracts.md`](../contracts.md) 和 [`../../novel-continuation-mvp/contracts.md`](../../novel-continuation-mvp/contracts.md) 为准。

## 1. Writer Input Boundary

旧的固定 prompt 正文 Writer 不再是目标运行边界。正文 writer 分为 `Draft Research Loop` 和 `Draft Prose Executor`。

Draft Research Loop 从轻量 `draft_seed_packet.json` 开始，负责判断正文前信息是否足够。它可以请求本地资料或用户补充，但不得修改上游 artifact 或写入正式 Memory / KB。

Draft Prose Executor 是受限执行器，不是自由规划器。它只消费：

- 已通过 review 的 `ChapterBrief` 或兼容旧 `ScenePlan`
- 用户通过章节梗概时输入的 `supplement_text`
- `draft_context_notebook.json`
- 已装配的 `chapter_execution_input.json`
- 内部派生的 `chapter_length_budget`
- 事实约束 `fact_inputs`
- 风格参考 `style_reference_bundle`
- 禁止项 `forbidden_inputs`
- 关系推进门禁 `relation_state_gate`
- 计划角色约束 `planned_character_constraints`
- 可选的 `draft_rewrite_plan.json`
- 由上游装配的 `WriterInputBundle` 兼容输入

它不得：

- 重写全书走向
- 擅自补大型世界观
- 自由创建关键新角色
- 跨章推进未经批准的关系跃迁
- 越过当前批次提前消费伏笔
- 私自确认终稿并写回 Memory
- 用风格参考覆盖事实约束
- 主动查询 Memory / KB 或向用户提问
- 把 Draft Research Loop 标注为低置信、未解决或需要用户授权的内容写成 confirmed fact

若 Draft Prose Executor 发现上游规划或研究笔记不可执行，应返回结构化 retry / replan request，由 Agent Loop 回到 Draft Research Loop 或对应 review artifact。

## 2. Draft Research Loop

Draft Research Loop SHALL 使用 `draft_seed_packet.json` 作为初始输入。该 seed packet SHOULD 只包含：

- 已通过的 `ChapterBrief`
- 用户 `supplement_text`
- 全书规划、批次计划和当前长度预算的压缩摘要
- 最近几章梗概、当前续写锚点和必要 planning notebook 摘要
- 本章人物索引、关系门禁、禁止项和计划角色约束
- 可查询资源目录，而不是完整 Memory、完整人物档案或完整原文

Draft Research Loop 可发起以下结构化请求：

- `text_search`
- `character_profile`
- `character_experience`
- `story_detail`
- `chapter_excerpt`
- `scene_card`
- `world_concept`
- `structure_pattern`
- `WriterQuestionSet`

本地 Agent / Context Broker SHALL 负责查询执行、预算裁剪、来源标注、泄漏审计和 trace 落盘。模型负责选择需要查看的候选、判断信息是否足够，以及输出下一步状态。

当 Draft Research Loop 使用 `character_profile` 或 `character_experience` 查询人物经历时，SHOULD 支持 `metadata.story_events_offset` / `metadata.story_events_char_budget` 分页读取 `story_events_json`，单页不超过 4096 字符，并返回 `story_events_page` 供后续继续读取。

Draft Research Loop 的出口只有：

- `ready_for_draft`：可以构建正文执行输入并调用 Draft Prose Executor。
- `needs_user_input`：需要用户补充或授权，必须输出结构化问题集。
- `replan_requested`：当前 `ChapterBrief` / 上游 artifact 与 canon 或用户目标冲突，应回到对应 review gate。
- `blocked`：缺少建模基础、Memory 不可用或关键事实不可确认，不能生成正式草稿。

Draft Research Loop SHALL 落盘 `draft_context_notebook.json` 或等价 artifact。该 notebook 至少应表达：

- `character_notes`
- `story_continuity_notes`
- `scene_notes`
- `world_notes`
- `style_notes`
- `unresolved_risks`
- `evidence_trace`

`draft_context_notebook.json` 是当前草稿的临时上下文，不是正式 Memory / KB。它可以被连续性检查和重写复用，但不得直接写回 canon。

## 3. Input Categories

`chapter_execution_input.json` 中的输入应按职责分开：

- `facts`：已通过的全书规划、世界观补充、批次计划、章节梗概、可用 Memory、最近窗口和来源记录。
- `user_supplement`：用户通过当前 artifact 时输入的原文补充，包括字数、风格、节奏、重点描写、必须保留项和禁止项。
- `draft_context`：Draft Research Loop 摘取的当前草稿事实笔记、人物约束、场景索引和 unresolved risks。
- `style`：风格参考片段、叙述距离、句法密度、对话节奏和表达偏好。
- `forbidden`：不得提前揭露的秘密、禁止关系跃迁、未确认设定、不得消费的后续剧情。
- `relation`：当前关系状态、允许推进幅度、所需桥接事件。
- `character`：已通过的人物规划 / 登场计划。
- `budget`：目标字数、最小/最大字数、重点章标记和 prompt token 预算。
- `rewrite`：用户草稿反馈归类、保留项、修正项、删除项和重写模式。

`SourceArcMap` 只能作为源作品结构定位事实，用于理解当前结构阶段、未回收线索和人物线位置，不得被当作续写事件顺序。

`NarrativeStructurePattern` / `ArcPatternCard` 只能作为结构模式参考，用于铺垫、过渡、登场、升级、收束和节奏安排，不得覆盖事实约束。

## 4. Contract Alignment

`WriterInputBundle` 仍是跨层 contract 中的正文输入包。当前分层 Writer 可以直接消费 `chapter_execution_input.json`，但必须保持语义兼容：

- `WriterInputBundle.scene_brief` 对应派生后的 `SceneBrief`
- `WriterInputBundle.reference_fragments` 对应风格参考
- `WriterInputBundle.context_payload` 对应 Memory 事实型上下文与上游已通过事实
- `WriterInputBundle.sources` 对应来源记录

`ChapterBrief` 是 Writer 内部规划对象，不能替代 `SceneBrief`。

`ChapterBrief -> SceneBrief` 至少遵守：

- `ChapterBrief.goal -> SceneBrief.scene_objective`
- `ChapterBrief.emotional_goal -> SceneBrief.emotional_goal`
- `ChapterBrief.conflict_goal -> SceneBrief.conflict_goal`
- `ChapterBrief.plot_function -> SceneBrief.narrative_function`
- `ChapterBrief.relationship_targets -> SceneBrief.relationship_state`
- `ChapterBrief.forbidden -> SceneBrief.must_avoid`

若 `ChapterBrief` 缺少检索字段，允许结合兼容旧 `ScenePlan` 或批次约束补齐，但不得更改已稳定 contract 的语义。

## 5. Artifact Review Gates

系统必须支持以下 review artifact：

- `BookContinuationPlan`：全书续写方向、规模、高潮、角色弧和未决问题。
- `BatchPlan`：当前批次计划。
- `ChapterPackage` / `ChapterBrief`：最近 N 章标题与高密度梗概。
- `draft.md`：章节草稿。
- `memory_writeback.json` 或写回摘要：已验收终稿与状态变化。

规则：

- 低层不得绕过上游已通过 artifact 直接篡改大纲。
- 每一层 artifact 通过后，其版本对下一层视为正式输入。
- 用户通过 artifact 时的 `supplement_text` 必须原文保存并进入后续模型 prompt。
- 用户不通过 artifact 时的 `revision_feedback` 必须原文保存，并驱动模型修订同一 artifact。
- 修订完成后必须回到同一个 review gate，不得自动越过用户审阅。
- 章节梗概通过后可以内部派生长度预算和写作输入，但不再需要独立的长度计划确认或写作材料确认作为用户主流程。
- Draft Research Loop 或 Draft Prose Executor 发现上游规划不可执行时，必须发起重规划请求，而不是自行改写。

## 6. Recovery And Rollback

用户通过后的中间产物是可恢复 review artifact。

级联回滚规则：

- 修改 `ChapterPackage` / `ChapterBrief` 时，该章及其后续章节的写作输入、正文和回写候选失效。
- 修改当前章内部派生长度预算时，当前章正文失效，但不必自动作废后续章节。
- 修改 `BatchPlan` 时，当前批次及后续批次下游产物失效。
- 修改 `BookContinuationPlan`、`WorldExpansionPack` 或 `CharacterCastPlan` 时，全部后续产物失效。
- 修改尚未正式登场的 `PlannedCharacterProfile` 时，所有引用该角色的批次、章节、写作输入和正文失效。
- 修改已进入 `canon_active` 的计划角色时，系统不得静默覆盖 Memory；必须让用户选择保留 canon、回滚首次登场章及之后内容，或分叉替代角色方案。

失败恢复规则：

- 正文失败可先回到 Draft Research Loop 复核 `draft_context_notebook.json`、查询缺口和执行输入，再决定是否保持同一 `ChapterBrief` 重试。
- 连续失败、用户反馈指向章节因果或 reviewer 指出上游约束不可执行时，应回到章节梗概 review gate。
- 若失败根因来自批次目标或全书规划，才继续回到批次或全书 artifact review gate。

## 7. User Review Display

规划类 artifact 应完整展示，便于用户审阅：

- `BookContinuationPlan`
- `BatchPlan`
- `ChapterPackage`
- `ChapterBrief`

review gate 应显示自然语言下一步提示：

- 通过时可补充字数、风格、节奏、重点描写对象、必须保留或禁止出现的内容。
- 不通过时应说明需要调整的标题、因果、人物动机、场景顺序、关系推进或伏笔安排。

大体量 artifact 应使用短预览：

- `draft.md` 只展示路径、当前字数、目标字数、连续性状态和开头短预览
- 默认短预览不应超过约 1-2KB
- 完整正文通过文件路径供用户打开或编辑
- 完整检索上下文不应直接刷入 terminal

内部 stage、run id、artifact path 和 action 名只放技术详情、debug drawer 或日志，不作为普通用户主状态。

## 8. User Draft Decision

章节草稿生成后必须进入显式用户草稿决策节点，并输出 `GenerationReviewDecision`。

状态语义：

- `accepted`：允许进入写回摘要审阅；用户确认写回后，当前版本才会成为后续可消费的 canon。
- `rewrite_requested`：用户反馈先进入 Draft Research Loop；Loop 归类反馈、必要时补查 Memory / KB / 用户授权，并输出 `draft_rewrite_plan.json` 后再重写；不回写。
- `replan_requested`：回到章节梗概层，修订 `ChapterPackage` / `ChapterBrief` 后再生成新稿；不回写。
- `discarded`：当前版本仅保留运行产物，进入暂停或等待用户下一步；不回写。

规则：

- `continuity_report.canon_ready` 只表示连续性风险等级，不得作为自动回滚、自动拒绝或写回硬 gate。
- Reviewer 报告与连续性报告只能作为用户决策参考，不得替代 `GenerationReviewDecision`。
- 未被用户接受的正文不得写回人物档案、关系状态、时间线、世界状态或 Creative KB。
- 被替换或作废的草稿只保留在 `runs` 等临时产物中。
- 后续章节只允许消费“已被用户接受且已确认写回”的 canon 状态。

### 8.1 Rewrite Loop

`GenerationReviewDecision.status = rewrite_requested` SHALL NOT directly call Draft Prose Executor with only the old prompt plus user feedback.

Workflow SHALL:

1. Preserve `feedback_text` verbatim.
2. Load the current approved `ChapterBrief`, previous `draft.md`, `continuity_report.json`, `draft_context_notebook.json`, and execution input.
3. Run Draft Research Loop to classify feedback as `prose_only`, `scene_emphasis`, `continuity_fix`, `character_voice_fix`, `structure_fix`, or `upstream_conflict`.
4. Query Memory / KB / user input when the feedback requires additional facts.
5. Write `draft_rewrite_plan.json`.
6. Call Draft Prose Executor only when the rewrite can be completed under the current approved brief.

`draft_rewrite_plan.json` SHOULD include:

- `rewrite_mode`: `full_rewrite`, `targeted_rewrite`, `regenerate_from_brief`, or `replan_required`
- `preserve`
- `remove_or_change`
- `new_memory_notes`
- `character_constraints`
- `style_constraints`
- `must_not_change`
- `requires_replan`

If `requires_replan = true`, workflow SHALL return to the chapter artifact review gate or `needs_user_input`.

## 9. Writeback

accepted 后的写回至少包含：

- 人物状态变化
- 关系状态变化
- 剧情时间线 / 关键经历更新
- 世界状态变化
- 伏笔状态变化
- 批次 / 大纲进度

`StateDelta` 和 `MemoryWriteback` 必须能追溯到对应草稿版本、用户草稿决策和来源。写回摘要本身应作为 review artifact；用户确认后才执行正式 Memory / KB 更新。

## Requirements

### Requirement: Draft Prose Executor 只消费已确认执行输入

系统 SHALL 要求 Draft Prose Executor 在正文扩写时只消费已经通过 review 的单章 brief、用户补充、长度预算、`draft_context_notebook.json` 和已装配的 `chapter_execution_input.json`。

### Requirement: Draft Research Loop 支持正文前主动查询

系统 SHALL 在正文生成前支持 Draft Research Loop，让模型基于轻量 seed 主动请求人物档案、人物经历、故事细节、章节摘录、场景索引、世界观概念、结构参考或用户补充。

### Requirement: 草稿重写必须经过 Draft Research Loop

系统 SHALL 在用户请求重写草稿时先运行 Draft Research Loop，生成 `draft_rewrite_plan.json`，再决定是否调用 Draft Prose Executor 或回到上游 review gate。

### Requirement: 风格参考与事实约束分离

系统 SHALL 将风格参考、范文模仿与事实型上下文分开存储、分开装配；当二者冲突时事实优先。

### Requirement: 用户确认点必须可恢复

系统 SHALL 将用户通过后的中间产物视为可恢复 review artifact，并允许从最近通过版本继续。

### Requirement: 上游修改必须触发级联回滚

系统 SHALL 将分层规划产物视为带依赖关系的 review artifact；当上游 artifact 修改并重新通过时，相关下游节点必须失效。

### Requirement: 章节生成后必须支持用户决策或重生成

系统 SHALL 在章节生成后提供显式用户草稿决策节点，允许接受、基于反馈重写、退回章节梗概重规划，或作废本次草稿。

### Requirement: 章节终稿必须 accepted 后才能回写

系统 SHALL 仅在 `GenerationReviewDecision.status = accepted` 后进入写回摘要审阅或正式 Memory writeback。

## Non-Goals

- 不重新定义 `ArtifactReviewDecision`、`GenerationReviewDecision`、`DraftResearchDecision`、`DraftRewritePlan` 或 `OutlineResearchQuestionSet` 的字段结构。
- 不定义大纲 research 的 query prompt。
- 不定义 Memory / KB 的底层表结构。
