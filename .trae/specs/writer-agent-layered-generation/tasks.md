# Tasks

## Reading Rules

- `spec.md` 与 `design.md` 现在主要作为总览和索引页使用；做具体任务时，优先只读任务下方标注的文档。
- 只有涉及章节验收对象时才读 [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)。
- 只有涉及跨层输入对象时才读 [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)。
- 当前尚未拆出的规划域与人物补充域，暂时继续以 [spec.md](.trae/specs/writer-agent-layered-generation/spec.md) 和 [design.md](.trae/specs/writer-agent-layered-generation/design.md) 为主。
- 涉及 terminal 展示、确认点、长度计划交互与恢复时，优先读 [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md)。
- 涉及正文草稿审阅、`draft.md` 预览和验收分支时，优先读 [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md)。
- 涉及 `NarrativeStructurePattern` / `ArcPatternCard` 如何进入 Writer 输入，或 `SourceArcMap` 如何作为源作品定位事实可选进入上下文时，优先读 [writer-input.spec.md](.trae/specs/writer-agent-layered-generation/specs/writer-input.spec.md) 与 [narrative-memory-context/spec.md](.trae/specs/narrative-memory-context/spec.md)。

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

- [ ] Task 7A: 建立 ChapterLengthPlan 章节长度规划层
  - `来源`: 拆自 `spec.md` / `design.md` 中 `Freeze C -> ChapterLengthPlan -> Freeze D` 的正式预算层要求
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md), [writer-input.spec.md](.trae/specs/writer-agent-layered-generation/specs/writer-input.spec.md)
  - `建议只关注代码文件`: `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [ ] 定义 `ChapterLengthPlan` 与单章 `ChapterLengthBudget` 运行时 schema
  - [ ] 在 `Freeze C` 后基于 `ChapterPackage` 生成 `chapter_length_plan.json`
  - [ ] 输出默认章节长度、重点章节、高潮章节与单章 `target/min/max` override
  - [ ] 在 Assist / Batch 模式下进入 `wait_length_review`，允许用户修改长度计划文件后继续
  - [ ] 在交互界面完整展示 `ChapterLengthPlan`
  - [ ] 在 `wait_length_review` 明确询问用户是否需要调整章节长度
  - [ ] 支持用户直接输入默认长度覆盖值或单章 override，并写回 `chapter_length_plan.json`
  - [ ] 确认长度计划后，将 `chapter_length_plan.json` 作为进入 `Freeze D` 的前置输入
  - [ ] `prepare_execution` / `Freeze D` 加载并冻结当前章对应长度预算与重点展开标记
  - [ ] 正文执行 prompt 消费已确认的长度预算，而不是临时猜测目标长度
  - [ ] `revise_length` 分支能基于 `length_plan_update.json` 更新或重新确认 `ChapterLengthPlan` 后重写当前章
  - [ ] 增加从 `Freeze C -> wait_length_review -> Freeze D` 的最小流程测试
  - [ ] 增加 `revise_length -> wait_length_review -> 更新长度预算 -> 重写当前章` 的回归测试

- [x] Task 13: 支持三种产品模式
  - `建议只读`: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md), [design.md](.trae/specs/writer-agent-layered-generation/design.md), [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md)
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
  - `建议只读`: [writer-input.spec.md](.trae/specs/writer-agent-layered-generation/specs/writer-input.spec.md), [writer-execution.design.md](.trae/specs/writer-agent-layered-generation/designs/writer-execution.design.md), [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)
  - [x] 在现有 `ScenePlan` 之上设计 `ChapterBrief`
  - [x] 定义 Writer Agent 的事实输入、风格输入、禁止输入
  - [x] 增加 style reference bundle 装配
  - [x] 增加 relation-state gate
  - [x] 增加计划角色约束输入，禁止正文层绕过上游自由创建关键新角色
  - [ ] 在 `WriterInputBundle` 或结构参考输入中装配相关 `NarrativeStructurePattern` / `ArcPatternCard` 片段，包含 `pattern_id`、结构功能、节奏类型、过渡功能、铺垫目标与回收目标
  - [ ] 在需要源作品定位时，可在事实上下文中装配相关 `SourceArcMap` 片段，包含 `source_arc_id`、`source_arc_role`、源作品阶段定位与未回收线索

- [x] Task 9: 重构 Writer Agent 为“受限执行器”
  - `建议只读`: [writer-input.spec.md](.trae/specs/writer-agent-layered-generation/specs/writer-input.spec.md), [writer-execution.design.md](.trae/specs/writer-agent-layered-generation/designs/writer-execution.design.md), [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)
  - [x] 将正文层改为只消费冻结 brief
  - [x] 禁止正文层直接补大型设定
  - [x] 禁止正文层跳过关系桥接
  - [x] 禁止正文层越过当前批次边界
  - [x] 禁止正文层在未冻结情况下自由发明关键新角色

## Group C: Review And Writeback

- [x] Task 10: 建立章节后校验与回写链路
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - [x] 复用并扩展 `ContinuityReport`
  - [x] 提取 `StateDelta`
  - [x] 回写人物状态、关系状态、时间线事件、世界状态
  - [x] 标记本章是否成为可继续消费的 canon
  - [x] 当计划角色首次正式登场并通过校验后，将其转写为正式 Character Memory

- [ ] Task 10A: 优化章节验收界面的 draft 展示策略
  - `来源`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md) 的 `Review Display Policy`
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md)
  - [ ] 在章节验收节点展示 `draft.md` 路径、当前字数、目标字数、连续性状态与开头短预览
  - [ ] 默认草稿预览限制在约 1-2KB，不把完整正文刷入 terminal
  - [ ] 完整展示或提示 `generation_review_decision.json` 的可编辑位置
  - [ ] 增加测试覆盖：长草稿只输出短预览、完整路径仍可见、结构化审阅产物可编辑

- [x] Task 14A: 旧代码结构改造 - 将写入流程重构为“验收后提交”
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - [x] 拆分旧的“生成后直接回写”路径，引入 `GenerationReviewDecision` 驱动的 accept-gated commit
  - [x] 仅当 `GenerationReviewDecision.status = accepted` 时允许进入 `Freeze E` 与正式 `MemoryWriteback`
  - [x] 当 `GenerationReviewDecision.status = revise_length` 时，消费 `LengthPlanUpdate` 并回退到 `wait_length_review`，不得触发正式回写
  - [x] 当 `GenerationReviewDecision.status = replan_chapter` 时，消费 `ChapterReplanRequest` 并回退到 `wait_chapter_review`，不得触发正式回写
  - [x] 当 `GenerationReviewDecision.status = discarded` 时，仅保留运行产物并暂停流程，不得触发正式回写或自动进入下一章
  - [x] 为旧 writeback 入口增加保护，阻止绕过章节验收节点直接提交旧草稿
  - [x] 将“是否成为 canon”的判定从“生成完成”改为“用户接受并完成回写”

- [x] Task 14C: 旧代码结构改造 - 重构 runs 产物与评审决策落盘
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - [x] 新增 `generation_review_decision.json`
  - [x] 新增 `length_plan_update.json`
  - [x] 新增 `chapter_replan_request.json`
  - [x] 明确旧草稿被 `superseded` 或 `discarded` 时的 runs 保留策略
  - [x] 确保评审决策产物与正式 `memory_writeback.*` 在目录结构上可追踪同一次章节执行

## Group D: Workflow And Recovery

- [ ] Task 11: 建立失败恢复与重规划机制
  - `建议只读`: [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md), [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md)
  - [x] 正文失败时支持从 `Freeze D` 重试
  - [x] 连续失败时支持回退到 `Freeze C`
  - [x] 必要时回退到 `Freeze B`
  - [x] 为每次回退记录结构化原因
  - [x] 支持因 `CharacterCastPlan` 修改而触发的级联回滚
  - [ ] 支持已进入 `canon_active` 的计划角色修改时的冲突分支处理

- [x] Task 12: 建立交互式工作流控制器
  - `建议只读`: [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md)
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
  - `建议只读`: [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md)
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
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - [x] 增加 `accepted -> Freeze E -> MemoryWriteback` 的正向测试
  - [x] 增加 `revise_length -> wait_length_review -> 不回写` 的分支测试
  - [x] 增加 `replan_chapter -> wait_chapter_review -> 不回写` 的分支测试
  - [x] 增加 `discarded -> halted -> 不回写` 的分支测试
  - [x] 增加“旧 writeback 入口无法绕过验收节点”的回归测试
  - [x] 增加 `generation_review_decision.json / length_plan_update.json / chapter_replan_request.json` 落盘测试

## Group F: 14A / 14B / 14C / 15A 细粒度拆分

- [x] Task 14A-1: 运行时代码中引入 `GenerationReviewDecision` / `LengthPlanUpdate` / `ChapterReplanRequest`
  - `来源`: 拆自 `Task 14A`
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/schemas/orchestration_schema.py`, `novel_agent/schemas/__init__.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 在运行时代码里增加 review 决策对象的最小数据结构
  - [x] 对齐 `accepted / revise_length / replan_chapter / discarded` 四种状态
  - [x] 对齐 `reason_code / feedback_text / next_action_checkpoint` 等核心字段
  - [x] 如有必要，导出到统一 schema 入口

- [x] Task 14A-2: 为 `RestrictedWriterExecutor` 增加 accept-gated writeback 门禁
  - `来源`: 拆自 `Task 14A`
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/schemas/continuity.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 停止在 `execute_frozen_chapter()` 内基于 `canon_ready` 直接触发正式回写
  - [x] 将正式回写前置条件收紧为“continuity 通过 + review decision 已 accepted”
  - [x] 保持 continuity 校验与 state delta 提取逻辑可独立运行

- [x] Task 14A-3: 为旧 writeback 审批入口增加 guard，阻止绕过章节验收直接提交
  - `来源`: 拆自 `Task 14A`
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] `approve_writeback()` 读取并校验 `generation_review_decision.json`
  - [x] 未提供 `accepted` 决策时拒绝正式回写
  - [x] 将“是否成为 canon”的最终判定收紧为“accepted 且 writeback 完成”

- [x] Task 14B-1: 扩展 workflow 状态枚举与 checkpoint，接入验收等待态
  - `来源`: 拆自 `Task 14B`
  - `建议只读`: [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 在 workflow state 中补齐 `wait_chapter_acceptance`
  - [x] 在 workflow state 中补齐 `wait_length_review`
  - [x] 在 workflow state 中补齐 `halted`
  - [x] 明确这些状态如何写入 `workflow_state.json` 与 `workflow_checkpoints.json`

- [x] Task 14B-2: 在 `execute_current_chapter()` 后接入四态验收分流
  - `来源`: 拆自 `Task 14B`
  - `建议只读`: [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] `accepted -> freeze_e / writeback_review`
  - [x] `revise_length -> wait_length_review`
  - [x] `replan_chapter -> wait_chapter_review`
  - [x] `discarded -> halted`
  - [x] 保证只有 `accepted` 才允许继续下一章或下一批次

- [x] Task 14B-3: 调整 resume / rollback 逻辑，兼容新的 rejection path
  - `来源`: 拆自 `Task 14B`
  - `建议只读`: [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] `resume_from_latest_checkpoint()` 能正确返回新的等待态
  - [x] `discarded` 不污染恢复点
  - [x] `replan_chapter` 和 `revise_length` 不误触发 freeze 级联失效

- [x] Task 14C-1: 落盘 `generation_review_decision.json`
  - `来源`: 拆自 `Task 14C`
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 在验收发生时稳定落盘 `generation_review_decision.json`
  - [x] 保证字段与 contract 对齐
  - [x] 保证同一 `run_id/chapter_id/draft_id` 可追踪

- [x] Task 14C-2: 落盘 `length_plan_update.json` 与 `chapter_replan_request.json`
  - `来源`: 拆自 `Task 14C`
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] `revise_length` 分支落盘 `length_plan_update.json`
  - [x] `replan_chapter` 分支落盘 `chapter_replan_request.json`
  - [x] `accepted / discarded` 分支对这两个 artifact 的缺省策略保持一致

- [x] Task 14C-3: 增加 `superseded / discarded` 草稿保留策略
  - `来源`: 拆自 `Task 14C`
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 明确废稿保留在 runs 内但不得进入正式回写链路
  - [x] 明确被新稿替代时旧稿的 `superseded` 策略
  - [x] 保证与 `memory_writeback.json` 的目录关联可追踪

- [x] Task 15A-1: 补 accepted-only writeback 的行为测试
  - `来源`: 拆自 `Task 15A`
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/orchestrators/writer_execution.py`
  - [x] 覆盖 `accepted -> Freeze E -> MemoryWriteback`
  - [x] 覆盖旧入口在无 accepted 决策时被 guard
  - [x] 覆盖“未 accepted 不成为 canon”

- [x] Task 15A-2: 补 rejection path 的 workflow 分支测试
  - `来源`: 拆自 `Task 15A`
  - `建议只读`: [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/app/orchestrators/writer_workflow.py`
  - [x] 覆盖 `revise_length -> wait_length_review -> 不回写`
  - [x] 覆盖 `replan_chapter -> wait_chapter_review -> 不回写`
  - [x] 覆盖 `discarded -> halted -> 不回写`

- [x] Task 15A-3: 补 review artifact 落盘测试
  - `来源`: 拆自 `Task 15A`
  - `建议只读`: [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md), [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)
  - `建议只关注代码文件`: `novel_agent/tests/test_writer_execution_workflow.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/runs/writer.py`
  - [x] 覆盖 `generation_review_decision.json`
  - [x] 覆盖 `length_plan_update.json`
  - [x] 覆盖 `chapter_replan_request.json`

## Group G: Writer 用户可见状态重构

- [x] Task 16: 建立 Writer 状态翻译层（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `Writer 用户可见状态词典`
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md), [review-writeback.design.md](.trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/app/gui/main.py`, `novel_agent/app/gui/writer_cli.py`, `novel_agent/app/run_interactive.py`
  - [x] 定义 `WriterStatusPresenter` 或等价 presenter，将内部 stage / event 翻译为中文用户文案
  - [x] 覆盖 `artifact saved -> 已保存你的修改`
  - [x] 覆盖 `batch_review` / “Freeze B pending” -> “请审阅本批剧情大纲”
  - [x] 覆盖 `freeze_d_review -> 请确认本章写作材料`
  - [x] 覆盖 `wait_chapter_acceptance -> 请验收当前章节`
  - [x] 覆盖 `writeback_review -> 请确认写回续写记忆`
  - [x] 将内部 stage、freeze record、checkpoint path 放入技术详情，不作为主状态展示

- [x] Task 17: 替换 CLI / 交互输出中的内部状态文案（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `状态展示与跳转`
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md)
  - `建议只关注代码文件`: `novel_agent/app/run_interactive.py`, `novel_agent/app/gui/writer_cli.py`
  - [x] `_prompt_writer_review` 等交互提示显示中文状态、背景说明和下一步动作
  - [x] 保存 artifact 后显示“已保存你的修改”，并明确“保存不等于确认”
  - [x] 章节验收提示显示“接受本章 / 调整字数后重写 / 修改章节梗概后重写 / 作废草稿 / 稍后决定”
  - [x] `wait_length_review` 提示说明它既可能来自初次长度确认，也可能来自“调整字数后重写”
  - [x] 不再把 `freeze_d_review`、`wait_chapter_acceptance`、`checkpoint confirmed` 作为主输出给用户

- [x] Task 18: 替换 GUI Writer 面板中的内部状态文案（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `当前实现需要对齐的点`
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [../cli-interface/design.md](.trae/specs/cli-interface/design.md)
  - `建议只关注代码文件`: `novel_agent/app/gui/main.py`
  - [x] `_refresh_writer_state_buttons` 使用中文状态和下一步说明
  - [x] `_writer_actions_for_stage` 的按钮文案去掉 `Freeze A/B/C/D/E` 主文案
  - [x] `batch_review` 按钮显示“确认本批剧情大纲”，而不是“确认 Freeze B”
  - [x] `freeze_d_review` 按钮显示“确认本章写作材料”，并说明不会立刻写回
  - [x] `wait_chapter_acceptance` 按钮显示完整验收动作
  - [x] 为 `wait_chapter_review` 补齐 GUI 动作入口，支持返回章节梗概调整后继续

- [x] Task 19: 对齐 Writer 模式确认点与状态机实现（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `当前实现需要对齐的点`
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md)
  - `建议只关注代码文件`: `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 核对 `MODE_CONFIRMATION_POINTS` 与实际 `prepare_planning()` 行为是否一致
  - [x] 明确 Batch 模式是否需要停在“请审阅全书续写规划”
  - [x] 若 Batch 需要确认 Freeze A 前置材料，则实现并补测试（不适用：已明确 Batch 不停留在该确认点）
  - [x] 若 Batch 不需要确认 Freeze A 前置材料，则更新模式定义，避免 spec / code 分歧
  - [x] 确认 `wait_chapter_review` 从验收分支进入后有可继续执行路径

- [x] Task 20: Writer 状态重构测试与快照验收（待新增）
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `Writer 用户可见状态词典`
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md), [workflow-and-recovery.spec.md](.trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md)
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
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `JSON Contract 与 TUI 步骤映射`
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
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `故事规模 / 高潮输入映射`
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [../cli-interface/design.md](.trae/specs/cli-interface/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/forms.py`, `novel_agent/app/cli/textual_widgets.py`, `novel_agent/app/cli/textual_screens.py`, `novel_agent/app/cli/facade.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/tests/test_cli_textual_components.py`, `novel_agent/tests/test_writer_execution_workflow.py`
  - [x] 将 `target_total_chars`、`default_chapter_target_chars`、`pacing_profile`、`length_distribution_notes` 加入 Writer 启动表单
  - [x] 将 `conflict_climax`、`emotional_climax`、`target_chapter_index`、`must_foreshadow`、`must_not_resolve_before`、`payoff_expectation` 加入 Writer 启动表单
  - [x] 将故事规模字段映射到稳定 JSON 输入，供 smoke 和 workflow 恢复复用
  - [x] 将高潮字段映射到稳定 JSON 输入，供 `BookContinuationPlan` 生成消费
  - [x] 在用户只填写总字数和章节数时推导默认单章字数，并允许用户覆盖
  - [x] 增加测试覆盖 TUI 表单到故事规模 / 高潮 JSON 输入的映射

- [x] Task 22: 定义 Character Casting 表单与 JSON artifact 映射
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `人物补充输入映射`
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
  - `建议只关注代码文件`: `novel_agent/app/cli/artifacts.py`, `novel_agent/app/cli/textual_widgets.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] 将 `CharacterRequirementReport` 展示为已有人物、新角色候选、剧情缺位角色三类卡片
  - [x] 将 `CharacterSeedInput` 展示为角色雏形表单
  - [x] 将 `PlannedCharacterProfile` 展示为计划人物卡片
  - [x] 将 `CharacterCastPlan` 展示为角色方案审阅面板
  - [x] 内部 id 只放技术详情，不作为主界面文案
  - [x] 保留 JSON artifact 供 smoke 和恢复运行使用

- [x] Task 23: 定义 Writer 审阅 artifact 字段化编辑映射
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `审阅类 artifact 映射`
  - `建议只读`: [design.md](.trae/specs/writer-agent-layered-generation/design.md), [workflow-state-machine.design.md](.trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md)
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
  - `来源`: [design.md](.trae/specs/writer-agent-layered-generation/design.md) 的 `章节验收 contract 映射`
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
