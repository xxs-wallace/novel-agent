# Tasks

## Reading Rules

- `spec.md` 与 `design.md` 现在主要作为总览和索引页使用；做具体任务时，优先只读任务下方标注的文档。
- 只有涉及章节验收对象时才读 [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)。
- 只有涉及跨层输入对象时才读 [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)。
- 当前尚未拆出的规划域与人物补充域，暂时继续以 [spec.md](.trae/specs/writer-agent-layered-generation/spec.md) 和 [design.md](.trae/specs/writer-agent-layered-generation/design.md) 为主。
- 涉及 terminal 展示、artifact review gate、章节验收与恢复时，优先读 [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)。
- 涉及正文草稿审阅、`draft.md` 预览和验收分支时，优先读 [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)。
- 涉及 `NarrativeStructurePattern` / `ArcPatternCard` 如何进入 Writer 输入，或 `SourceArcMap` 如何作为源作品定位事实可选进入上下文时，优先读 [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md) 与 [narrative-memory-context/spec.md](.trae/specs/narrative-memory-context/spec.md)。
- 本文件中部分已完成历史任务仍记录旧流程实现状态；新增实现必须以当前 `spec.md` / `design.md` / `contracts.md` 的 Agent Loop 与 artifact review gate 语义为准，旧式独立长度确认和写作材料确认由 Group L 负责迁移移除。

## Group A: 主总览 / 待拆分规划域

- [x] Task 1: 明确 Writer Agent 分层产物与冻结点
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [x] 定义 `ModelingStatus`
  - [x] 定义 `ContinuationIntent`
  - [x] 定义 `BookContinuationPlan`
  - [x] 定义 `WorldExpansionPack`
  - [x] 定义 `BatchPlan`
  - [x] 定义 `ChapterPackage`
  - [x] 定义 `ChapterBrief`
  - [x] 定义 `StateDelta`
  - [x] 定义 `Freeze A/B/C/D/E` 的持久化方式

- [ ] Task 2: 建立 Layer 1 全书续写规划链路（部分实现，待接入结构模式 KB）
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [x] 接收用户输入的简化续写方向
  - [x] 接收故事规模输入：目标章节数、目标总字数、默认单章字数
  - [x] 接收高潮输入：冲突高潮、情绪高潮、目标章节位置、必须铺垫、不得提前解决
  - [x] 读取已有故事大纲、终局线索、未决问题
  - [x] 生成后续发展方向与候选结局
  - [x] 将故事规模、节奏 profile 与高潮计划归并进 `BookContinuationPlan`，而不是只作为 prompt 附加备注
  - [x] 输出全书级 `chapter_outline_slots`，包含章节功能、目标字数、铺垫/回收职责与提前消费边界
  - [x] 输出阶段性高潮、角色弧与未决项
  - [x] 为每项规划写入来源与证据等级
  - [ ] 当 KB 层提供 `NarrativeStructurePattern` / `ArcPatternCard` 时，将续写目标映射到合适的结构模式或新建后续 `ArcRoadmap`，避免只按单章目标规划
  - [ ] 当 Memory 层提供 `SourceArcMap` 时，仅用于源作品结构位置、未回收伏笔和已有人物线定位，不直接套用为续写计划

- [ ] Task 3: 建立 Layer 1B 世界观补全链路
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [ ] 展示当前世界观摘要给用户
  - [x] 支持用户补充或修订世界观
  - [x] 识别剧情规划所需但当前缺失的设定
  - [x] 输出最小必要设定补全包
  - [ ] 建立“新增设定冲突检查”
  - [x] 建立“设定未决项”输出

- [x] Task 4: 建立 Layer 1C 人物补充链路
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [x] 实现显式角色解析，识别用户已点名但当前 Memory 中不存在的新角色
  - [x] 实现角色需求解析与缺位检查，区分显式新角色与隐式角色功能位
  - [x] 定义 `CharacterRequirementReport`
  - [x] 定义 `CharacterCastRequest`
  - [x] 定义 `CharacterSeedInput`
  - [x] 定义 `CharacterCastPlan`
  - [x] 定义 `PlannedCharacterProfile`
  - [x] 定义 `CharacterIntroductionPlan`
  - [x] 支持“用户提供角色雏形 -> 扩展为人物草案”
  - [x] 支持“用户提供模糊配额 -> 生成受约束候选 roster”
  - [x] 支持用户审阅、修改、删减人物补充方案后继续
  - [x] 明确计划角色与正式 Character Memory 的状态边界
  - [x] 为显式角色解析、候选生成和首次登场计划写入来源与约束

- [x] Task 5: 建立续写前建模状态检查链路
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [x] 检查是否已完成 Memory 建模
  - [x] 检查是否已完成知识库/索引建模
  - [x] 输出缺失项与下一步引导
  - [x] 阻止未建模完成时直接进入正式续写

- [ ] Task 6: 建立 Layer 2 批次剧情规划链路
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [ ] 设计批次切分策略（按 N 章 / 小篇章 / 目标字数）
  - [ ] 若存在 `NarrativeStructurePattern` / `ArcPatternCard`，支持按结构模式、篇章功能和铺垫/回收目标切分当前批次
  - [x] 输出 `batch_goal / emotional_arc / conflict_arc / exit_hook`
  - [x] 输出 `must_resolve / must_not_consume`
  - [ ] 输出当前批次借鉴的 `pattern_id`、结构功能、节奏类型、过渡功能、铺垫目标与回收目标
  - [x] 若存在 `CharacterCastPlan`，为首次登场角色预留批次级执行位置
  - [x] 支持批次级重规划
  - [x] 生成后暂停等待用户审阅批次大纲
  - [x] 支持用户修改批次大纲文件后继续
  - [ ] 在交互界面完整展示 `BatchPlan`，而不是只展示文件路径

- [ ] Task 7: 建立 Layer 3 章节包规划链路
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [story_structure_knowledge_base.md](novel_agent/docs/story_structure_knowledge_base.md), [relationship_arc_knowledge_base.md](novel_agent/docs/relationship_arc_knowledge_base.md)
  - [x] 基于 `BatchPlan` 生成最近 N 章标题与梗概
  - [x] 接入 [`story_structure_knowledge_base.md`](novel_agent/docs/story_structure_knowledge_base.md)
  - [x] 接入 [`relationship_arc_knowledge_base.md`](novel_agent/docs/relationship_arc_knowledge_base.md)
  - [x] 输出章节级关系目标、冲突目标、情绪目标与 ending hook
  - [ ] 若存在 `NarrativeStructurePattern` / `ArcPatternCard`，为每章标注结构功能：主线推进、过渡缓冲、日常关系、设定揭示、高潮或收束
  - [ ] 允许生成低冲突但有铺垫价值的日常/过渡章节，并要求说明人物状态、关系铺垫、设定缓释或后续回收功能
  - [x] 将计划角色的首次登场约束编入 `ChapterPackage` / `ChapterBrief`
  - [x] 生成后暂停等待用户审阅章节包
  - [x] 支持用户修改章节梗概文件后继续
  - [ ] 在交互界面完整展示 `ChapterPackage`
  - [ ] 支持退回批次层重规划

- [ ] Task 7A: 建立章节梗概通过后的 WritingGuidance 内部组装层
  - `来源`: 当前 `spec.md` / `design.md` 中 `ChapterPackage review -> supplement_text -> chapter writing guidance -> draft generation` 的 Agent Loop 要求
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
  - `建议只关注代码文件`: `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] 定义 `ChapterWritingGuidance` 与单章 `ChapterLengthBudget` 运行时 schema，明确其为内部派生产物而非独立用户确认节点
  - [ ] 在用户通过 `ChapterPackage` / `ChapterBrief` review gate 后，收集并落盘原始 `supplement_text`
  - [ ] 基于章节梗概、用户补充、上游规划、Memory / KB evidence 和风格参考生成 `chapter_writing_guidance.json`
  - [ ] 内部输出默认章节长度、重点展开段落、节奏偏好、风格要求与禁止项
  - [ ] 将 `chapter_writing_guidance.json` 与 `chapter_length_budget.json` 装配进 `chapter_execution_input.json`
  - [ ] 正文执行 prompt 消费已通过章节 brief、用户补充原文和派生写作指导，而不是临时猜测目标长度或风格
  - [ ] 不再在 Assist / Batch 模式下进入独立长度确认或写作材料确认主状态
  - [ ] 增加 `ChapterPackage approved + supplement_text -> writing guidance -> draft generation` 的最小流程测试
  - [ ] 增加用户在 `supplement_text` 中提出字数 / 风格要求后被写入 prompt 输入的回归测试

- [x] Task 13: 支持三种产品模式
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
  - [x] `Assist Mode`
  - [x] `Batch Mode`
  - [x] `Auto Novel Mode`
  - [x] 定义各模式的人类确认点

- [ ] Task 14: runs 目录扩展（部分实现，待记录结构模式与 SourceArcMap 引用）
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [x] 新增 `book_continuation_plan.*`
  - [x] 新增 `world_expansion_pack.*`
  - [x] 新增 `character_requirement_report.*`
  - [x] 新增 `character_cast_request.*`
  - [x] 新增 `character_cast_plan.*`
  - [x] 新增 `planned_character_profiles.*`
  - [x] 新增 `character_introduction_plan.*`
  - [ ] 读取并记录 KB 层提供的 `narrative_structure_patterns.*` / `arc_pattern_cards.*` 引用
  - [ ] 需要源作品定位时，读取并记录 Memory 层提供的 `source_arc_map.*` / `source_arc_context.*` 引用
  - [x] 新增 `batch_plan.*`
  - [x] 新增 `chapter_package.*`
  - [x] 新增 `state_delta.*`
  - [x] 新增 `memory_writeback.*`

## Group B: Writer Input / Execution

- [ ] Task 8: 扩展正文层输入 contract（部分实现，待接入结构模式 KB）
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)
  - [x] 在现有 `ScenePlan` 之上设计 `ChapterBrief`
  - [x] 定义 Writer Agent 的事实输入、风格输入、禁止输入
  - [x] 增加 style reference bundle 装配
  - [x] 增加 relation-state gate
  - [x] 增加计划角色约束输入，禁止正文层绕过上游自由创建关键新角色
  - [ ] 在 `WriterInputBundle` 或结构参考输入中装配相关 `NarrativeStructurePattern` / `ArcPatternCard` 片段，包含 `pattern_id`、结构功能、节奏类型、过渡功能、铺垫目标与回收目标
  - [ ] 在需要源作品定位时，可在事实上下文中装配相关 `SourceArcMap` 片段，包含 `source_arc_id`、`source_arc_role`、源作品阶段定位与未回收线索

- [x] Task 9: 重构 Writer Agent 为“受限执行器”
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)
  - [x] 将正文层改为只消费冻结 brief
  - [x] 禁止正文层直接补大型设定
  - [x] 禁止正文层跳过关系桥接
  - [x] 禁止正文层越过当前批次边界
  - [x] 禁止正文层在未冻结情况下自由发明关键新角色

## Group C: Review And Writeback

- [x] Task 10: 建立章节后校验与回写链路
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - [x] 复用并扩展 `ContinuityReport`
  - [x] 提取 `StateDelta`
  - [x] 回写人物状态、关系状态、时间线事件、世界状态
  - [x] 标记本章是否成为可继续消费的 canon
  - [x] 当计划角色首次正式登场并通过校验后，将其转写为正式 Character Memory

- [ ] Task 10A: 优化章节验收界面的 draft 展示策略
  - `来源`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md) 的 `User Review Display`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [ ] 在章节验收节点展示 `draft.md` 路径、当前字数、目标字数、连续性状态与开头短预览
  - [ ] 默认草稿预览限制在约 1-2KB，不把完整正文刷入 terminal
  - [ ] 完整展示或提示 `generation_review_decision.json` 的可编辑位置
  - [ ] 增加测试覆盖：长草稿只输出短预览、完整路径仍可见、结构化审阅产物可编辑

- [x] Task 14A: 旧代码结构改造 - 将写入流程重构为“验收后提交”
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - [x] 拆分旧的“生成后直接回写”路径，引入 `GenerationReviewDecision` 驱动的 accept-gated commit
  - [x] 仅当 `GenerationReviewDecision.status = accepted` 时允许进入 `Freeze E` 与正式 `MemoryWriteback`
  - [x] 当 `GenerationReviewDecision.status = revise_length` 时，消费 `LengthPlanUpdate` 并回退到 `wait_length_review`，不得触发正式回写
  - [x] 当 `GenerationReviewDecision.status = replan_chapter` 时，消费 `ChapterReplanRequest` 并回退到 `wait_chapter_review`，不得触发正式回写
  - [x] 当 `GenerationReviewDecision.status = discarded` 时，仅保留运行产物并暂停流程，不得触发正式回写或自动进入下一章
  - [x] 为旧 writeback 入口增加保护，阻止绕过章节验收节点直接提交旧草稿
  - [x] 将“是否成为 canon”的判定从“生成完成”改为“用户接受并完成回写”

- [x] Task 14C: 旧代码结构改造 - 重构 runs 产物与评审决策落盘
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - [x] 新增 `generation_review_decision.json`
  - [x] 新增 `length_plan_update.json`
  - [x] 新增 `chapter_replan_request.json`
  - [x] 明确旧草稿被 `superseded` 或 `discarded` 时的 runs 保留策略
  - [x] 确保评审决策产物与正式 `memory_writeback.*` 在目录结构上可追踪同一次章节执行

## Group D: Workflow And Recovery

- [ ] Task 11: 建立失败恢复与重规划机制
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [x] 正文失败时支持从 `Freeze D` 重试
  - [x] 连续失败时支持回退到 `Freeze C`
  - [x] 必要时回退到 `Freeze B`
  - [x] 为每次回退记录结构化原因
  - [x] 支持因 `CharacterCastPlan` 修改而触发的级联回滚
  - [ ] 支持已进入 `canon_active` 的计划角色修改时的冲突分支处理

- [x] Task 12: 建立交互式工作流控制器
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [x] 在建模检查、世界观确认、批次大纲审阅、章节包审阅处支持暂停
  - [x] 在建模状态中检查 `SourceArcMap` 是否存在；缺失时提示运行 post-close-read 源作品篇章地图生成或继续但降级
  - [x] 在建模状态中检查 `NarrativeStructurePattern` / `ArcPatternCard` 是否存在；缺失时提示运行 KB 结构模式沉淀或继续但降级
  - [x] 在交互界面展示源作品篇章地图面板，输出 `SourceArcMap` 摘要与 artifact 路径
  - [x] 在交互界面展示全局结构模式面板，输出 `NarrativeStructurePattern` / `ArcPatternCard` 摘要与 artifact 路径
  - [x] 在 `batch_review` 完整展示 `BatchPlan`
  - [x] 在 `chapter_review` 完整展示 `ChapterPackage`
  - [x] 在 `wait_length_review` 完整展示 `ChapterLengthPlan` 并询问是否调整长度
  - [x] 对 `draft.md` 只展示路径、字数、目标长度、校验状态和开头短预览，避免刷满 terminal
  - [x] 在人物补充确认处支持暂停
  - [x] 支持读取“用户修改后的文件”继续执行
  - [x] 支持从交互输入直接修改 `ChapterLengthPlan` 默认长度与单章 override 后继续
  - [x] 支持从最近确认点恢复
  - [x] 记录每次确认的时间与来源

- [x] Task 14B: 旧代码结构改造 - 重构工作流状态机以接入章节验收分支
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - [x] 在旧工作流控制器中补齐 `wait_chapter_acceptance`
  - [x] 在旧工作流控制器中补齐 `wait_length_review`
  - [x] 在旧工作流控制器中补齐 `halted`
  - [x] 区分“仅调整长度”和“退回章节梗概重规划”两条 rejection path
  - [x] 确保只有 `accepted` 才允许推进到下一章或下一批次
  - [x] 确保 `discarded` 不会污染后续状态恢复点

## Group E: Testing And Acceptance

- [ ] Task 15: 测试与验收
  - `建议只读`: 先读 [spec.md](.trae/specs/writer-agent-layered-generation/spec.md) 与 [design.md](.trae/specs/writer-agent-layered-generation/design.md) 获取总览，再按测试目标补读对应子文档，避免一次性通读全部文档。
  - [x] 增加“从 Layer 1 到 Layer 5”的集成测试
  - [x] 增加建模未完成时的阻断测试
  - [x] 增加显式角色解析测试，覆盖“用户点名新角色”和“命中既有角色”两类样例
  - [x] 增加角色缺位检查测试，覆盖“剧情需要角色功能位但未绑定具体人物”的样例
  - [ ] 增加 Character Casting 流程测试，覆盖“角色雏形扩展”和“模糊配额候选生成”两类路径
  - [ ] 增加 `NarrativeStructurePattern` / `ArcPatternCard` 可用时 Layer 1 / Layer 2 消费结构模式的测试
  - [ ] 增加过渡/日常缓冲结构模式能生成低冲突章节梗概的测试
  - [x] 增加世界观确认后再进入批次规划的流程测试
  - [x] 增加人物补充确认后再进入 `Freeze A` / 批次规划的流程测试
  - [x] 增加“用户修改批次大纲文件后继续”的测试
  - [x] 增加“用户修改章节梗概文件后继续”的测试
  - [x] 增加“用户修改人物补充方案后继续”的测试
  - [x] 增加关系推进非法时的阻断测试
  - [ ] 增加风格输入与事实输入冲突时的优先级测试
  - [x] 增加交互界面完整展示 `BatchPlan`、`ChapterPackage`、`ChapterLengthPlan` 的测试
  - [x] 增加 `draft.md` 只展示短预览且输出完整路径的测试
  - [x] 增加 `wait_length_review` 中直接输入长度 override 并写回 `chapter_length_plan.json` 的测试
  - [x] 增加冻结点回退测试
  - [x] 增加 `CharacterCastPlan` 触发的级联回滚测试
  - [ ] 增加批次级连续生成测试

- [x] Task 15A: 写入流程重构专项测试
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - [x] 增加 `accepted -> Freeze E -> MemoryWriteback` 的正向测试
  - [x] 增加 `revise_length -> wait_length_review -> 不回写` 的分支测试
  - [x] 增加 `replan_chapter -> wait_chapter_review -> 不回写` 的分支测试
  - [x] 增加 `discarded -> halted -> 不回写` 的分支测试
  - [x] 增加“旧 writeback 入口无法绕过验收节点”的回归测试
  - [x] 增加 `generation_review_decision.json / length_plan_update.json / chapter_replan_request.json` 落盘测试

## Group F: 14A / 14B / 14C / 15A 细粒度拆分

- [x] Task 14A-1: 运行时代码中引入 `GenerationReviewDecision` / `LengthPlanUpdate` / `ChapterReplanRequest`
  - `来源`: 拆自 `Task 14A`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/schemas/__init__.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 在运行时代码里增加 review 决策对象的最小数据结构
  - [x] 对齐 `accepted / revise_length / replan_chapter / discarded` 四种状态
  - [x] 对齐 `reason_code / feedback_text / next_action_checkpoint` 等核心字段
  - [x] 如有必要，导出到统一 schema 入口

- [x] Task 14A-2: 为 `RestrictedWriterExecutor` 增加 accept-gated writeback 门禁
  - `来源`: 拆自 `Task 14A`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/schemas/continuity.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 停止在 `execute_frozen_chapter()` 内基于 `canon_ready` 直接触发正式回写
  - [x] 将正式回写前置条件收紧为“continuity 通过 + review decision 已 accepted”
  - [x] 保持 continuity 校验与 state delta 提取逻辑可独立运行

- [x] Task 14A-3: 为旧 writeback 审批入口增加 guard，阻止绕过章节验收直接提交
  - `来源`: 拆自 `Task 14A`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] `approve_writeback()` 读取并校验 `generation_review_decision.json`
  - [x] 未提供 `accepted` 决策时拒绝正式回写
  - [x] 将“是否成为 canon”的最终判定收紧为“accepted 且 writeback 完成”

- [x] Task 14B-1: 扩展 workflow 状态枚举与 checkpoint，接入验收等待态
  - `来源`: 拆自 `Task 14B`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 在 workflow state 中补齐 `wait_chapter_acceptance`
  - [x] 在 workflow state 中补齐 `wait_length_review`
  - [x] 在 workflow state 中补齐 `halted`
  - [x] 明确这些状态如何写入 `workflow_state.json` 与 `workflow_checkpoints.json`

- [x] Task 14B-2: 在 `execute_current_chapter()` 后接入四态验收分流
  - `来源`: 拆自 `Task 14B`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] `accepted -> freeze_e / writeback_review`
  - [x] `revise_length -> wait_length_review`
  - [x] `replan_chapter -> wait_chapter_review`
  - [x] `discarded -> halted`
  - [x] 保证只有 `accepted` 才允许继续下一章或下一批次

- [x] Task 14B-3: 调整 resume / rollback 逻辑，兼容新的 rejection path
  - `来源`: 拆自 `Task 14B`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] `resume_from_latest_checkpoint()` 能正确返回新的等待态
  - [x] `discarded` 不污染恢复点
  - [x] `replan_chapter` 和 `revise_length` 不误触发 freeze 级联失效

- [x] Task 14C-1: 落盘 `generation_review_decision.json`
  - `来源`: 拆自 `Task 14C`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 在验收发生时稳定落盘 `generation_review_decision.json`
  - [x] 保证字段与 contract 对齐
  - [x] 保证同一 `run_id/chapter_id/draft_id` 可追踪

- [x] Task 14C-2: 落盘 `length_plan_update.json` 与 `chapter_replan_request.json`
  - `来源`: 拆自 `Task 14C`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] `revise_length` 分支落盘 `length_plan_update.json`
  - [x] `replan_chapter` 分支落盘 `chapter_replan_request.json`
  - [x] `accepted / discarded` 分支对这两个 artifact 的缺省策略保持一致

- [x] Task 14C-3: 增加 `superseded / discarded` 草稿保留策略
  - `来源`: 拆自 `Task 14C`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 明确废稿保留在 runs 内但不得进入正式回写链路
  - [x] 明确被新稿替代时旧稿的 `superseded` 策略
  - [x] 保证与 `memory_writeback.json` 的目录关联可追踪

- [x] Task 15A-1: 补 accepted-only writeback 的行为测试
  - `来源`: 拆自 `Task 15A`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`
  - [x] 覆盖 `accepted -> Freeze E -> MemoryWriteback`
  - [x] 覆盖旧入口在无 accepted 决策时被 guard
  - [x] 覆盖“未 accepted 不成为 canon”

- [x] Task 15A-2: 补 rejection path 的 workflow 分支测试
  - `来源`: 拆自 `Task 15A`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/app/orchestrators/writer_workflow.py`
  - [x] 覆盖 `revise_length -> wait_length_review -> 不回写`
  - [x] 覆盖 `replan_chapter -> wait_chapter_review -> 不回写`
  - [x] 覆盖 `discarded -> halted -> 不回写`

- [x] Task 15A-3: 补 review artifact 落盘测试
  - `来源`: 拆自 `Task 15A`
  - `建议只读`: [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`
  - [x] 覆盖 `generation_review_decision.json`
  - [x] 覆盖 `length_plan_update.json`
  - [x] 覆盖 `chapter_replan_request.json`

## Group G: Writer 用户可见状态重构

- [x] Task 16: 建立 Writer 状态翻译层（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/gui/main.py`, `novel_agent/app/gui/writer_cli.py`, `novel_agent/app/run_interactive.py`
  - [x] 定义 `WriterStatusPresenter` 或等价 presenter，将内部 stage / event 翻译为中文用户文案
  - [x] 覆盖 `artifact saved -> 已保存你的修改`
  - [x] 覆盖 `batch_review` / “Freeze B pending” -> “请审阅本批剧情大纲”
  - [x] 覆盖 `freeze_d_review -> 请确认本章写作材料`
  - [x] 覆盖 `wait_chapter_acceptance -> 请验收当前章节`
  - [x] 覆盖 `writeback_review -> 请确认写回续写记忆`
  - [x] 将内部 stage、freeze record、checkpoint path 放入技术详情，不作为主状态展示

- [x] Task 17: 替换 CLI / 交互输出中的内部状态文案（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
  - `建议只关注代码文件`: `novel_agent/app/run_interactive.py`, `novel_agent/app/gui/writer_cli.py`
  - [x] `_prompt_writer_review` 等交互提示显示中文状态、背景说明和下一步动作
  - [x] 保存 artifact 后显示“已保存你的修改”，并明确“保存不等于确认”
  - [x] 章节验收提示显示“接受本章 / 调整字数后重写 / 修改章节梗概后重写 / 作废草稿 / 稍后决定”
  - [x] `wait_length_review` 提示说明它既可能来自初次长度确认，也可能来自“调整字数后重写”
  - [x] 不再把 `freeze_d_review`、`wait_chapter_acceptance`、`checkpoint confirmed` 作为主输出给用户

- [x] Task 18: 替换 GUI Writer 面板中的内部状态文案（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [../cli-interface/design.md](.trae/specs/cli-interface/design.md)
  - `建议只关注代码文件`: `novel_agent/app/gui/main.py`
  - [x] `_refresh_writer_state_buttons` 使用中文状态和下一步说明
  - [x] `_writer_actions_for_stage` 的按钮文案去掉 `Freeze A/B/C/D/E` 主文案
  - [x] `batch_review` 按钮显示“确认本批剧情大纲”，而不是“确认 Freeze B”
  - [x] `freeze_d_review` 按钮显示“确认本章写作材料”，并说明不会立刻写回
  - [x] `wait_chapter_acceptance` 按钮显示完整验收动作
  - [x] 为 `wait_chapter_review` 补齐 GUI 动作入口，支持返回章节梗概调整后继续

- [x] Task 19: 对齐 Writer 模式确认点与状态机实现（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 核对 `MODE_CONFIRMATION_POINTS` 与实际 `prepare_planning()` 行为是否一致
  - [x] 明确 Batch 模式是否需要停在“请审阅全书续写规划”
  - [x] 若 Batch 需要确认 Freeze A 前置材料，则实现并补测试（不适用：已明确 Batch 不停留在该确认点）
  - [x] 若 Batch 不需要确认 Freeze A 前置材料，则更新模式定义，避免 spec / code 分歧
  - [x] 确认 `wait_chapter_review` 从验收分支进入后有可继续执行路径

- [x] Task 20: Writer 状态重构测试与快照验收（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_run_interactive_pipeline.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 增加状态翻译单测，覆盖所有 Writer 用户确认点
  - [x] 增加 CLI 输出测试，断言主输出不包含 `artifact saved`、`Freeze B pending`、`freeze_d_review`、`wait_chapter_acceptance`
  - [x] 增加 GUI 状态/按钮文案测试或 presenter 快照测试
  - [x] 增加 `wait_chapter_acceptance` 四分支中文文案测试
  - [x] 增加 `wait_chapter_review` 可继续路径测试
  - [x] 增加 Batch 模式 Freeze A 行为一致性测试

# Task Dependencies

- Task 2 depends on Task 1, Task 5
- Task 3 depends on Task 1, Task 5
- Task 4 depends on Task 1, Task 2, Task 3, Task 5
- Task 5 depends on Task 1
- Task 6 depends on Task 2, Task 3, Task 4
- Task 7 depends on Task 4, Task 6
- Task 7A depends on Task 7
- Task 8 depends on Task 1, Task 7, Task 7A
- Task 9 depends on Task 8
- Task 10 depends on Task 9
- Task 10A depends on Task 10, Task 12
- Task 11 depends on Task 4, Task 9, Task 10
- Task 12 depends on Task 5, Task 6, Task 7, Task 7A, Task 11
- Task 13 depends on Task 6, Task 7A, Task 9, Task 10, Task 11, Task 12
- Task 14 depends on Task 1, Task 4, Task 10, Task 12
- Task 14A depends on Task 10, Task 11, Task 12
- Task 14B depends on Task 11, Task 12, Task 14A
- Task 14C depends on Task 10, Task 14A, Task 14B
- Task 15 depends on Task 4, Task 9, Task 10, Task 10A, Task 11, Task 12, Task 13, Task 14
- Task 15A depends on Task 14A, Task 14B, Task 14C, Task 15
- Task 16 depends on Task 12, Task 14B, Task 14C
- Task 17 depends on Task 16
- Task 18 depends on Task 16
- Task 19 depends on Task 13, Task 14B, Task 16
- Task 20 depends on Task 16, Task 17, Task 18, Task 19

## Fine-Grained Dependencies

- Task 14A-1 depends on Task 10
- Task 14A-2 depends on Task 14A-1
- Task 14A-3 depends on Task 14A-1, Task 14A-2
- Task 14B-1 depends on Task 12
- Task 14B-2 depends on Task 14A-1, Task 14B-1
- Task 14B-3 depends on Task 14B-1, Task 14B-2
- Task 14C-1 depends on Task 14A-1, Task 14A-3
- Task 14C-2 depends on Task 14A-1, Task 14B-2, Task 14C-1
- Task 14C-3 depends on Task 14C-1, Task 14C-2
- Task 15A-1 depends on Task 14A-2, Task 14A-3
- Task 15A-2 depends on Task 14B-1, Task 14B-2, Task 14B-3
- Task 15A-3 depends on Task 14C-1, Task 14C-2, Task 14C-3

# External Dependencies

- 总编排层提供 `documents`、runs、主调度入口
- Memory 层提供人物档案、世界观、章节摘要、大纲与回写接口
- Memory 层提供 `SourceArcMap` 时，Writer 可将其作为源作品结构定位事实；缺失时可降级但应提示用户
- 创作知识库层提供结构理论、`NarrativeStructurePattern` / `ArcPatternCard`、范文参考、检索与 rerank

## Group H: JSON Contract 与正式 TUI 映射

- [x] Task 21: 定义 Writer 启动输入 ViewModel 与 JSON contract 映射
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [../cli-interface/design.md](.trae/specs/cli-interface/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/textual_widgets.py`, `novel_agent/app/cli/textual_screens.py`, `novel_agent/app/cli/facade.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] 定义 `WriterIntentForm` / `WriterIntentWizard` 或等价 ViewModel
  - [x] 将主要角色、续写目标、避免项、期望结果、补充说明映射到 `intent_payload`
  - [x] 将世界观补充映射到 `user_world_notes`
  - [x] 将批次数量、生成章节数映射到 `target_chapter_count` / `chapter_count`
  - [x] 将新角色开关映射到 `intent_payload.allow_character_cast`
  - [x] 保留 `WorkflowFacade.start_writer(intent_payload=...)` 的 JSON-compatible smoke 入口
  - [x] 增加测试覆盖 TUI 表单到 `intent_payload` 的映射

- [x] Task 21A: 扩展 Writer 启动向导以收集故事规模与高潮输入
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [../cli-interface/design.md](.trae/specs/cli-interface/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/forms.py`, `novel_agent/app/cli/textual_widgets.py`, `novel_agent/app/cli/textual_screens.py`, `novel_agent/app/cli/facade.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/tests/test_cli_textual_components.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 将 `target_total_chars`、`default_chapter_target_chars`、`pacing_profile`、`length_distribution_notes` 加入 Writer 启动表单
  - [x] 将 `conflict_climax`、`emotional_climax`、`target_chapter_index`、`must_foreshadow`、`must_not_resolve_before`、`payoff_expectation` 加入 Writer 启动表单
  - [x] 将故事规模字段映射到稳定 JSON 输入，供 smoke 和 workflow 恢复复用
  - [x] 将高潮字段映射到稳定 JSON 输入，供 `BookContinuationPlan` 生成消费
  - [x] 在用户只填写总字数和章节数时推导默认单章字数，并允许用户覆盖
  - [x] 增加测试覆盖 TUI 表单到故事规模 / 高潮 JSON 输入的映射

- [x] Task 22: 定义 Character Casting 表单与 JSON artifact 映射
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/artifacts.py`, `novel_agent/app/cli/textual_widgets.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] 将 `CharacterRequirementReport` 展示为已有人物、新角色候选、剧情缺位角色三类卡片
  - [x] 将 `CharacterSeedInput` 展示为角色雏形表单
  - [x] 将 `PlannedCharacterProfile` 展示为计划人物卡片
  - [x] 将 `CharacterCastPlan` 展示为角色方案审阅面板
  - [x] 内部 id 只放技术详情，不作为主界面文案
  - [x] 保留 JSON artifact 供 smoke 和恢复运行使用

- [x] Task 23: 定义 Writer 审阅 artifact 字段化编辑映射
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/artifacts.py`, `novel_agent/app/cli/textual_widgets.py`, `novel_agent/app/cli/textual_screens.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] `book_continuation_plan.json` 映射为全书目标、目标章节数、目标总字数、默认单章字数、节奏 profile、终局方向、阶段高潮、必须保留、未决问题
  - [x] 将 `climax_plan` 映射为冲突高潮、情绪高潮、目标章节位置、必须铺垫、不得提前解决、回收预期
  - [x] 将 `chapter_outline_slots` 映射为章节 slot 卡片，展示章节功能、目标字数、铺垫/回收职责与提前消费边界
  - [x] `batch_plan.json` 映射为本批目标、入口、冲突、中点、出口钩子、禁止提前消费
  - [x] `chapter_package.json` 映射为章节标题、章节目标、冲突目标、关系推进、必须出现、禁止项
  - [x] `chapter_length_plan.json` 映射为默认字数、重点章、高潮章、单章预算
  - [x] `chapter_execution_input.json` 映射为章节 brief、长度预算、事实约束、风格参考、人物门禁、禁止项
  - [x] 高级 JSON 编辑保留，但普通路径必须可通过字段化编辑或受控修订完成

- [x] Task 24: 定义章节验收 TUI 决策到 review contract 的映射
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/decisions.py`, `novel_agent/app/cli/textual_screens.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] “接受本章”映射到 `GenerationReviewDecision.status = accepted`
  - [x] “调整字数后重写”映射到 `LengthPlanUpdate`
  - [x] “修改章节梗概后重写”映射到 `ChapterReplanRequest`
  - [x] “作废本次草稿”映射到 `discarded`
  - [x] 技术字段由 workflow 补齐，不要求用户填写

- Task 21 depends on Task 12, Task 16, Task 17
- Task 21A depends on Task 21
- Task 22 depends on Task 4, Task 21
- Task 23 depends on Task 6, Task 7, Task 7A, Task 21, Task 21A
- Task 24 depends on Task 10, Task 14A, Task 21

## Group I: Outline Research Loop 落地

- [x] Task 47: 定义 Outline Research Loop 运行时 schema 与落盘结构
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [spec.md](.trae/specs/writer-agent-layered-generation/spec.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [spec.md](.trae/specs/writer-agent-layered-generation/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_writer_outline_research.py`
  - [x] 定义 `OutlineSeedPacket`
  - [x] 定义 `ExtractedCharacterMentions` / `CharacterMentionResolution`
  - [x] 定义 `ResearchRequest`，覆盖 `story_detail`、`character_profile`、`world_concept`、`structure_pattern`
  - [x] 定义 `ResearchBudget`
  - [x] 定义 `StoryDetailResult` / `ResearchResult`
  - [x] 定义 `PlanningNotebook`
  - [x] 定义 `SufficiencyDecision`，覆盖 `enough / needs_user_input / proceed_with_assumptions / blocked`
  - [x] 在 runs 中稳定落盘 `outline_seed_packet.json`、`outline_research_trace.json`、`planning_notebook.json`、`sufficiency_decision.json`
  - [x] 为 schema 序列化、缺字段、非法 status、路径关联补单元测试

- [x] Task 48: 实现用户概述人物提及抽取与 Character Memory 对齐
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md) 的 `Layer 0A.5`
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [narrative-memory-context/spec.md](.trae/specs/narrative-memory-context/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/services/`, `novel_agent/app/repos/`, `novel_agent/tests/test_writer_outline_research.py`
  - [x] 从用户故事概述、续写目标、避免项和补充说明中抽取人物姓名、称谓、别名和上下文片段
  - [x] 输出置信度、来源文本和 possible role hint
  - [x] 使用 Character Memory / alias / evidence 对抽取结果进行 `resolved / ambiguous / missing` 对齐
  - [x] 对 `resolved` 人物绑定既有 `character_id`
  - [x] 对 `ambiguous` 人物生成用户选择请求
  - [x] 对 `missing` 人物生成是否新增人物的确认请求
  - [x] 未经用户确认新增的人名不得进入 `CharacterCastPlan`
  - [x] 增加测试覆盖：命中既有人物、别名命中、多候选歧义、缺失人物、用户拒绝新增

- [x] Task 49: 实现 OutlineSeedPacket 装配
  - `来源`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md) 的 `Outline Seed Packet`
  - `建议只读`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [spec.md](.trae/specs/writer-agent-layered-generation/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/services/outline_service.py`, `novel_agent/tests/test_writer_outline_research.py`
  - [x] 汇总用户意图、故事规模、高潮输入和人物提及对齐结果
  - [x] 装配可查询人物索引，人物只包含姓名、别名和极短标签，不展开完整档案
  - [x] 装配世界观精炼梗概和世界观概念名词索引
  - [x] 装配历史故事精炼总览和当前续写起点
  - [x] 可选装配未决伏笔 / SourceArcMap / ArcPatternCard 的标题级索引
  - [x] 确保初始 prompt 不直接塞入完整 Memory、完整世界观或完整历史时间线
  - [x] 增加快照测试，断言 seed packet 信息密度和敏感字段边界

- [x] Task 50: 实现 Context Broker 与 research request resolver
  - `来源`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md) 的 `Context Broker`
  - `建议只读`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
  - `建议只关注代码文件`: `novel_agent/app/services/`, `novel_agent/app/repos/`, `novel_agent/tools/`, `novel_agent/tests/test_writer_outline_research.py`
  - [x] 实现 `character_profile` resolver，返回人物状态、能力边界、关系状态、最近变化和来源
  - [x] 实现 `world_concept` resolver，返回规则、限制、代价、例外、禁止突破点和来源
  - [x] 实现 `structure_pattern` resolver，调用 KB 层结构模式 / ArcPatternCard 检索
  - [x] 所有结果必须带 `fact_status` 和 sources
  - [x] 支持请求去重、低优先级降级、预算不足时只返回索引摘要
  - [x] 增加测试覆盖来源记录、结果裁剪、重复请求合并和不把 candidate 当 confirmed

- [x] Task 51: 实现 Story Detail Resolver 与历史大纲索引
  - `来源`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md) 的 `Story Detail Resolver`
  - `建议只读`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [narrative-memory-context/spec.md](.trae/specs/narrative-memory-context/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/services/outline_service.py`, `novel_agent/app/repos/`, `novel_agent/app/runner/close_read_runner.py`, `novel_agent/tests/test_writer_outline_research.py`
  - [x] 定义最低可用的 `ChapterSummaryIndex`，每条摘要保存人物、概念、事件概要、结果和 source document 位置
  - [x] 设计可升级的 `HistoricalOutlineEventIndex` 事件卡结构
  - [x] 实现 query understanding，将 `story_detail.query` 解析为人物、概念、事件意图、时间提示和 facts facets
  - [x] 使用章节摘要 / 事件卡检索候选
  - [x] 对候选事件执行 rerank，返回 matches、confidence、covered_facets、missing_facets
  - [x] 只展开高相关候选的详细材料
  - [x] 增加测试覆盖“最近一次信任冲突”“某伏笔来源”“某事件结果”等自然语言 query

- [x] Task 52: 实现 Outline Research Loop 控制器与预算门禁
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/services/`, `novel_agent/tests/test_writer_outline_research.py`
  - [x] 根据 `OutlineSeedPacket` 调用模型产生 research requests
  - [x] 逐轮调用 Context Broker 并把结果回传模型
  - [x] 维护 `planning_notebook`
  - [x] 执行 `ResearchBudget`：max_rounds、max_requests_per_round、max_total_requests、max_return_tokens_per_request
  - [x] 预算耗尽后必须进入 `Sufficiency Gate`
  - [x] 支持 `needs_user_input` 暂停，等待用户补充后继续一小轮 research 或生成大纲
  - [x] 支持 `proceed_with_assumptions`，并把假设标注到大纲来源
  - [x] 支持 `blocked`，返回 required_actions，不生成正式大纲
  - [x] 增加测试覆盖多轮请求、预算耗尽、用户补充、带假设继续和 blocked

- [x] Task 53: 将 Outline Research Loop 接入 Book / Batch / Chapter 规划
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/tests/test_writer_outline_research.py`
  - [x] 在生成 `BookContinuationPlan` 前执行 Outline Research Loop
  - [x] 将 `planning_notebook` 和 `SufficiencyDecision` 作为 Book Planner 输入
  - [x] `needs_user_input` 时进入可恢复等待态，不推进 Freeze A
  - [x] `proceed_with_assumptions` 时生成低风险草案，并在 `BookContinuationPlan` sources / assumptions 中标注
  - [x] `blocked` 时提示缺失建模步骤，不生成正式 `BookContinuationPlan`
  - [x] Batch / Chapter 规划可复用已有 notebook，必要时追加局部 research
  - [x] 增加端到端测试：用户概述 -> 人物抽取 -> research -> BookContinuationPlan -> batch_review

- [x] Task 54: Outline Research Loop 测试与 CLI 联动验收基线
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [../cli-interface/design.md](.trae/specs/cli-interface/design.md)
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [../cli-interface/design.md](.trae/specs/cli-interface/design.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_outline_research.py`, `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] 单元测试覆盖所有 schema、resolver 和 sufficiency status
  - [x] workflow 测试覆盖 `needs_user_input` 暂停与用户回答后继续
  - [x] workflow 测试覆盖 `proceed_with_assumptions` 的 assumptions 写入正式大纲
  - [x] workflow 测试覆盖 `blocked` 不生成正式大纲
  - [x] CLI fake facade 测试覆盖 research trace、用户补充问题和继续按钮
- [x] 默认测试不得触发真实 LLM；模型调用使用 fake adapter / stub

- Task 47 depends on Task 1, Task 2
- Task 48 depends on Task 47
- Task 49 depends on Task 47, Task 48
- Task 50 depends on Task 47, Task 49
- Task 51 depends on Task 47, Task 50
- Task 52 depends on Task 47, Task 50, Task 51
- Task 53 depends on Task 52
- Task 54 depends on Task 48, Task 52, Task 53

## Group J: Outline Research Loop BTree Memory Query 升级

- [ ] Task 55: 将 Story Detail Resolver 升级为 BTree Memory Query facade
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md)
  - `建议只读`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [`../narrative-memory-context/design.md`](.trae/specs/narrative-memory-context/design.md), [`../narrative-memory-context/tasks.md`](.trae/specs/narrative-memory-context/tasks.md)
  - `建议只关注代码文件`: `novel_agent/app/services/`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/repos/`, `novel_agent/tests/test_writer_outline_research.py`
  - [ ] `story_detail` 不再用一次性 historical outline rerank 作为主路径，而是调用 `NarrativeMemoryQueryService`
  - [ ] Context Broker 只做 facade、预算、去重和 evidence 归一化，不保存新的 canon Memory
  - [ ] 支持 event_summary -> event -> chapter -> document 的逐层候选返回
  - [ ] 返回 `StoryDetailResult` 时包含最终 evidence、source ids、status、`memory_query_trace`
  - [ ] 保留旧 resolver 作为缺少 BTree index 的兼容 fallback，并在 trace 中标记 fallback reason

- [ ] Task 56: 实现 Writer 模型驱动的 Memory candidate selection
  - `来源`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md) 的 `BTree descent chain`
  - `建议只读`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/services/`, `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/tests/test_writer_outline_research.py`
  - [ ] 给 Outline Research 模型新增 selection prompt，输入 `original_query`、`query_suffix_chain`、`path_context`、`current_level`、`current_candidates`
  - [ ] 模型结构化输出 `need_drill_down`、`selected_ids`、`query_suffix`、`reason`、`confidence`、`need_sibling_scan`
  - [ ] Agent 只根据 selected ids 调用 Memory 下钻，不替模型伪造选择理由
  - [ ] 累积 `query_suffix_chain`，并保证 suffix 只能基于当前层候选内容产生
  - [ ] 支持用户初次输入、用户反馈、reviewer feedback、retry instruction 都触发 Memory Query
  - [ ] 增加测试覆盖多层选择、query suffix 累积、feedback-triggered query、sibling scan 和预算耗尽

- [ ] Task 57: 扩展 Outline Research Loop artifacts 与 debug trace
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [`../agentic-benchmark/design.md`](.trae/specs/agentic-benchmark/design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [`../agentic-benchmark/design.md`](.trae/specs/agentic-benchmark/design.md)
  - `建议只关注代码文件`: `novel_agent/runs/writer.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/services/`, `novel_agent/tests/test_writer_outline_research.py`
  - [ ] 落盘 `memory_query_trace.json`
  - [ ] 落盘 `memory_query_decision_log.json`
  - [ ] 如果真实模型 API 返回可见 reasoning/debug 字段，落盘到 `model_reasoning_debug.json`
  - [ ] 如果 API 不返回可见 reasoning，不得伪造隐藏思维链；改为保存结构化决策轨迹
  - [ ] trace 仅用于 debug/reviewer，不得作为下一轮 Writer prompt 的隐藏知识注入
  - [ ] 测试覆盖 fake facade 的 trace 字段与真实模型字段缺失时的 fallback

- [ ] Task 58: 重构 Sufficiency Gate 与 feedback loop 集成
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md)
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [spec.md](.trae/specs/writer-agent-layered-generation/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_writer_outline_research.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] `needs_user_input` / `blocked` 不伪造用户答案
  - [ ] `proceed_with_assumptions` 必须把 assumptions 传给 Reviewer 和最终大纲 sources
  - [ ] 用户反馈进入下一轮 prompt loop 时，可触发新的 Memory Query
  - [ ] reviewer feedback 进入 retry 时，可触发新的 Memory Query
  - [ ] planning notebook 必须记录每轮查询理由、证据、缺口和未解决风险

- [ ] Task 59: Writer Outline Research Loop BTree 升级验收
  - `来源`: [tasks.md](.trae/specs/writer-agent-layered-generation/tasks.md), [`../agentic-benchmark/tasks.md`](.trae/specs/agentic-benchmark/tasks.md)
  - `建议只读`: [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md), [`../agentic-benchmark/design.md`](.trae/specs/agentic-benchmark/design.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_outline_research.py`, `novel_agent/tests/test_smoke_benchmark_service.py`, `novel_agent/app/run_single_sample_smoke.py`
  - [ ] 默认单元测试使用 fake model / fake reviewer，不触发真实 LLM
  - [ ] 单元测试覆盖 BTree Memory Query 正常完成、needs_user_input、blocked、proceed_with_assumptions
  - [ ] 单元测试覆盖 leakage audit 阻止 reference future outline、reference character set、future raw text 进入 Writer
  - [ ] 最终验收必须运行真实模型 API 的 author brief smoke benchmark
  - [ ] 真实 smoke 的 generated outline、planning notebook、memory query trace、reviewer summary 必须能证明流程没有依赖伪造模型返回

- Task 55 depends on Narrative Memory Task 15
- Task 56 depends on Task 55
- Task 57 depends on Task 56
- Task 58 depends on Task 56, Task 57
- Task 59 depends on Task 55, Task 56, Task 57, Task 58 and Agentic Benchmark OR-11 / OR-12

## Group K: Web Chat Question and Writer Workflow Bridge

- [ ] Task 60: 定义 Outline Research 问题集 contract 与落盘 / 恢复策略
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [`../web-interface/spec.md`](.trae/specs/web-interface/spec.md), [`../web-interface/design.md`](.trae/specs/web-interface/design.md)
  - `建议只读`: [contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md), [outline-research-loop.design.md](.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md)
  - `建议只关注代码文件`: `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_writer_outline_research.py`
  - [ ] 定义 `WriterQuestionSet` 或等价 schema，包含 `question_set_id`、`questions[]`、关联 gaps、必答状态、用户可见问题和恢复引用
  - [ ] 明确其与 `SufficiencyDecision.user_questions`、`outline_research_checkpoint.json`、`sufficiency_decision.json` 的关系
  - [ ] 支持 `outline_research_question_set.json` 独立落盘或在 sufficiency decision 中可追踪引用
  - [ ] 问题 id 必须稳定，便于 Web / CLI / TUI 用同一语义提交回答
  - [ ] 测试覆盖 `needs_user_input` 产物可恢复，且不需要解析自然语言日志

- [ ] Task 61: 实现 Web 结构化回答到 `continue_after_outline_research_input` 的桥接
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [`../web-interface/design.md`](.trae/specs/web-interface/design.md)
  - `依赖`: Task 60
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/run_interactive.py`, `novel_agent/app/web/services/web_action_service.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] 继续入口接受 `question_set_id`、可选 `source_message_id`、`answer_text`、`user_answers[]`
  - [ ] 保留用户原始回答文本，并把可映射内容作为 `user_authorized` evidence 写入 planning notebook
  - [ ] 若必答问题缺失，不得伪造用户回答；应保持等待态或返回用户可读补充提示
  - [ ] 普通聊天消息不得自动触发 workflow 继续
  - [ ] 保持 CLI / TUI 既有回答路径兼容，可映射为同一结构化入口

- [ ] Task 62: 对齐 WriterStatusPresenter 与 Web action / decision card 映射
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [`../web-interface/spec.md`](.trae/specs/web-interface/spec.md)
  - `依赖`: Task 60, Task 61
  - `建议只关注代码文件`: `novel_agent/app/presenters/`, `novel_agent/app/web/services/web_action_service.py`, `novel_agent/app/web/services/artifact_view_service.py`
  - [ ] `needs_user_input` 对外显示为用户可理解的问题消息与“提交回答并继续研究 / 稍后继续”动作
  - [ ] 普通用户视图不显示 `needs_user_input`、checkpoint id、workflow action 名或 artifact path
  - [ ] technical/debug 响应可以保留 raw decision、checkpoint 和 artifact path
  - [ ] Web action 结果能刷新右侧大纲研究 / planning notebook / 问题集视图

- [ ] Task 63: Web bridge 回归测试与验收
  - `来源`: [tasks.md](.trae/specs/writer-agent-layered-generation/tasks.md), [`../web-interface/tasks.md`](.trae/specs/web-interface/tasks.md)
  - `依赖`: Task 60, Task 61, Task 62
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_outline_research.py`, `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/tests/test_web_action_service.py`
  - [ ] 单元测试覆盖问题集生成、回答提交、回答原文保留、缺失必答问题处理
  - [ ] 工作流测试覆盖用户回答后继续一小轮 research 或直接生成大纲
  - [ ] Web action service 测试覆盖 `submit_outline_research_answers` 与 `defer_outline_research_answers`
  - [ ] 回归测试确认不会把普通聊天消息当作用户授权
  - [ ] 回归测试确认未回答问题不会被模型或后端伪造为 `user_authorized` evidence

- Task 60 depends on Task 47, Task 52, Task 53
- Task 61 depends on Task 60
- Task 62 depends on Task 60, Task 61 and Task 16
- Task 63 depends on Task 60, Task 61, Task 62

## Group L: Agent Loop Workflow Simplification

- [ ] Task 64: 重构 Writer workflow 小状态机
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
  - `依赖`: Task 7A, Task 60, Task 61
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/presenters/`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] 定义新旧状态映射表，明确哪些旧状态只作为恢复兼容存在
  - [ ] 将运行期主状态收敛为 `agent_running / reviewing_artifact / needs_user_input / generating_draft / reviewing_draft / writeback_review / completed / halted / error`
  - [ ] `workflow_state.json` 中保留可恢复的 technical stage，但用户可见 presenter 只输出自然语言 review gate
  - [ ] 移除普通用户必须处理的独立长度确认和写作材料确认主状态
  - [ ] 保留必要的旧状态恢复兼容映射，但普通 UI 不显示旧内部状态名
  - [ ] 增加恢复测试，覆盖旧 runs 仍可迁移到最近 review artifact

- [ ] Task 65: 实现 `ArtifactReviewDecision` 与通用 review action
  - `来源`: [contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `依赖`: Task 64
  - `建议只关注代码文件`: `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/runs/writer.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/web/services/web_action_service.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] 定义并导出 `ArtifactReviewDecision`
  - [ ] 支持 `approved + supplement_text`，原文落盘并进入后续模型输入
  - [ ] 支持 `revision_requested + revision_feedback`，驱动模型修订同一 artifact 并回到同一 review gate
  - [ ] 支持 `deferred`，保持可恢复暂停态
  - [ ] 每次 review action 都写入稳定 `artifact_review_decision.json` 或按 review id 归档的等价记录
  - [ ] downstream dependency invalidation 使用 artifact 版本依赖，不使用 Freeze 级联作为主语义
  - [ ] 测试覆盖 supplement 原文保留、revision feedback 原文保留、deferred 不推进 workflow

- [ ] Task 66: 重构章节梗概通过后的正文准备链路
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
  - `依赖`: Task 7A, Task 65
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] `ChapterPackage` / `ChapterBrief` 通过后直接组装 `chapter_writing_guidance.json` 与 `chapter_execution_input.json`
  - [ ] 字数、风格、节奏和重点展开要求从 `supplement_text` 进入正文 prompt
  - [ ] 不再要求用户单独审阅长度计划或写作材料后才生成正文
  - [ ] 测试覆盖通过章节梗概后直接进入正文生成准备

- [ ] Task 67: 重构章节草稿验收分支
  - `来源`: [contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md), [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
  - `依赖`: Task 64, Task 66
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/cli/decisions.py`, `novel_agent/app/web/services/web_action_service.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] 将 `GenerationReviewDecision` 分支对齐为 `accepted / rewrite_requested / replan_requested / discarded`
  - [ ] `rewrite_requested` 使用用户反馈和当前已通过 brief 重写正文，不正式回写
  - [ ] `replan_requested` 使用用户反馈修订章节梗概，并回到章节梗概 review gate
  - [ ] 字数不足、风格不符和节奏问题都通过 `feedback_text` 交给 Agent Loop，而不是进入独立长度分支
  - [ ] 测试覆盖不接受草稿不会写回、accepted-only writeback 仍成立

- [ ] Task 68: 更新 CLI / Web / GUI 用户提示与动作
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [`../web-interface/design.md`](.trae/specs/web-interface/design.md)
  - `依赖`: Task 65, Task 67
  - `建议只关注代码文件`: `novel_agent/app/run_interactive.py`, `novel_agent/app/gui/main.py`, `novel_agent/app/web/services/web_action_service.py`, `web/src/components/`
  - [ ] review gate 中提示用户审阅当前 artifact，并说明通过时可补充 prompt 信息
  - [ ] review gate 中提供“不通过并调整”动作，要求输入修订反馈
  - [ ] 普通 UI 不把 checkpoint id、artifact path、workflow stage/action 名当作主状态展示
  - [ ] 技术详情继续保留 raw stage、artifact path、run id 和 action payload

- [ ] Task 69: Agent Loop 简化流程验收测试
  - `来源`: Group L
  - `依赖`: Task 64, Task 65, Task 66, Task 67, Task 68, Task 70, Task 71, Task 72, Task 73, Task 74
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/tests/test_web_action_service.py`, `novel_agent/tests/test_run_interactive_pipeline.py`
  - [ ] 测试用户通过章节梗概并输入补充信息后，补充原文进入正文输入
  - [ ] 测试用户拒绝章节梗概后，模型修订 artifact 并回到同一 review gate
  - [ ] 测试用户不接受草稿时不会触发正式写回
  - [ ] 测试普通聊天消息不会绕过 `needs_user_input`
  - [ ] 测试 Web / CLI 主状态不展示内部技术字段

- [ ] Task 70: 定义 Writer Agent Loop 事件与执行步
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的核心流程
  - `依赖`: Task 64
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] 定义 `WriterLoopEvent` / `WriterLoopStep` 或等价内部对象，覆盖 local tool call、user question、artifact generated、artifact review、draft review、writeback review
  - [ ] Agent Loop 每一步都能落盘 trace，供恢复和 debug 使用
  - [ ] 模型返回信息不足时只允许走结构化 tool call：本地查询或 `WriterQuestionSet`
  - [ ] 普通用户消息只能成为下一轮 prompt 输入或 review feedback，不得直接改 workflow state
  - [ ] 测试覆盖 local query、user question、artifact ready 三类出口

- [ ] Task 71: 实现 review feedback 到模型 prompt 的组装边界
  - `来源`: [contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md), [runtime-boundaries.spec.md](.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md)
  - `依赖`: Task 65, Task 70
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/services/`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] `approved + supplement_text` 组装为下一阶段模型输入，包含 artifact 摘要、上游约束、planning notebook 和用户补充原文
  - [ ] `revision_requested + revision_feedback` 组装为 artifact 修订 prompt，要求模型输出同类型 artifact
  - [ ] 修订 prompt 不允许 Web / CLI 直接拼接；只能由 Writer 层统一装配
  - [ ] 模型修订后必须重新校验 schema、保存新版 artifact、回到同一 review gate
  - [ ] 测试覆盖用户补充进入下一阶段 prompt、用户反馈进入修订 prompt、修订后不自动继续

- [ ] Task 72: 移除旧长度确认 / 写作材料确认的主流程入口
  - `来源`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md) 的 `wait_length_review` / `freeze_d_review` 移除要求
  - `依赖`: Task 64, Task 66, Task 67
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/run_interactive.py`, `novel_agent/app/gui/main.py`, `novel_agent/app/web/services/web_action_service.py`, `novel_agent/tests/`
  - [ ] 移除新 runs 中进入 `wait_length_review` 和 `freeze_d_review` 的普通推进路径
  - [ ] 旧 runs 恢复时将相关状态迁移到最近章节梗概 review 或正文生成准备，不丢失已存在 artifact
  - [ ] CLI / GUI / Web 按钮不再暴露独立长度确认和写作材料确认
  - [ ] 保留 `chapter_length_budget` 作为内部派生产物和 technical artifact
  - [ ] 测试覆盖新流程不会生成旧主状态，旧状态仍可恢复

- [ ] Task 73: 对齐共享 action adapter 与 Web action 名
  - `来源`: [`../web-interface/tasks.md`](../web-interface/tasks.md) Group B / C
  - `依赖`: Task 65, Task 67, Task 72
  - `建议只关注代码文件`: `novel_agent/app/web/services/web_action_service.py`, `novel_agent/app/run_interactive.py`, `novel_agent/app/cli/decisions.py`, `novel_agent/tests/test_web_action_service.py`
  - [ ] 支持 `approve_writer_artifact / request_writer_artifact_revision / defer_writer_artifact_review`
  - [ ] 支持 `accept_chapter / rewrite_chapter / replan_chapter / discard_chapter / defer_chapter_acceptance`
  - [ ] 所有 action 都映射到 Writer contract，不暴露内部 stage/action 名给普通 UI
  - [ ] CLI / TUI 可复用同一 action adapter 或等价 contract mapping
  - [ ] 测试覆盖 Web action 与 Writer workflow 的 contract 对齐

- [ ] Task 74: 清理旧 contract 和 artifact 兼容层
  - `来源`: [contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `依赖`: Task 67, Task 72, Task 73
  - `建议只关注代码文件`: `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] 新 contract 不再要求 `LengthPlanUpdate` / `ChapterReplanRequest` 作为正式跨层对象
  - [ ] 如保留旧 schema，必须标记为 legacy / migration-only，不进入新流程主路径
  - [ ] runs 写入目标更新为 `artifact_review_decision.json`、`user_supplement.json`、`chapter_writing_guidance.json`
  - [ ] 测试覆盖旧 artifact 存在时不会被误当作新流程主决策

- Task 64 depends on Task 7A, Task 60, Task 61
- Task 65 depends on Task 64
- Task 66 depends on Task 7A, Task 65
- Task 67 depends on Task 64, Task 66
- Task 68 depends on Task 65, Task 67
- Task 69 depends on Task 64, Task 65, Task 66, Task 67, Task 68, Task 70, Task 71, Task 72, Task 73, Task 74
- Task 70 depends on Task 64
- Task 71 depends on Task 65, Task 70
- Task 72 depends on Task 64, Task 66, Task 67
- Task 73 depends on Task 65, Task 67, Task 72
- Task 74 depends on Task 67, Task 72, Task 73
