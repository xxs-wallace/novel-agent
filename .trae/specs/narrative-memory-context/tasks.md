# Tasks

这份清单已从历史实现账本压缩为当前仍需要跟踪的任务。已经落地且代码仍在仓库中的内容合并到“已落地能力”中，不再逐条保留旧任务编号。

## Status Legend

- `已落地`：当前仓库代码已具备主要能力，后续只作为背景能力引用
- `部分落地`：已有基础实现，但 contract、schema、测试或服务边界仍需收口
- `待处理`：设计明确，但当前仓库尚未形成稳定实现

## 已落地能力

- `Memory` 模块边界已明确：本层负责事实型长期上下文，不负责桥段去重、代表片段选择、SceneBrief 检索或 rerank。
- SQLite/Markdown 基础载体已存在：`documents`、`chapters`、`character_profiles`、`reading_progress`、`book_assets`，以及世界观、世界观概要、故事大纲 Markdown 资产。
- Close-read 主流程已落地：`CloseReadRunner` 读取 `documents`，使用 `ChapterAssemblerService` 按 `document_title_index` 组装章节批次，支持预算切批、fallback、debug 导出和 `reading_progress` 恢复。
- 人物档案更新链路已落地：`CharacterProfileService`、`CharacterProfilesRepo` 支持别名、发言状态、人物性证据、近期行动、关系、出现范围、重要性和事实型摘要合并。
- 世界观与大纲更新链路已落地：`WorldStateService`、`OutlineService` 支持世界观 section 合并、概要重压缩、大纲增量更新与长度裁剪。
- Character Evidence 链路已落地但当前实现按单 document 运行：`CharacterEvidenceBatchAssemblerService` 保留 batch 输入结构，`CloseReadRunner` 对章节批次内每个 document 单独运行 `character_evidence`，再汇合给 `MemoryCandidateService` 和 character reduce。
- Memory Candidate / Reduce 链路已落地：`MemoryCandidateService` 汇合章节摘要、人物证据和世界观证据，过滤低置信伪人物，并生成人物/世界观更新候选。
- 上下文装配已落地：`ContextAssemblyService` 输出章节摘要、世界观概要、相关人物档案、故事大纲、缺失信号，并可按预算加入 `SourceArcMap` 片段。
- Writer 边界已对齐：Writer 常规输入消费已沉淀的 Memory 资产，不直接消费 Character Evidence 原始输出。
- `SourceArcMap` 已落地：`SourceArcMappingService`、`PlotSummaryUnitCompressionService`、`build_source_arc_map` 支持 close-read 后生成 `.memory/arcs/<book_id>.source_arc_map.json` 与 Markdown debug 导出；上下文装配可选择相关 source arc 片段。
- 已有测试覆盖人物档案合并、上下文装配 contract、Character Evidence 汇合、章节调度、SourceArcMap 生成/压缩/查询、Writer 对 Memory 资产的消费。

## 当前有效任务

- [ ] Task 1: 收口章节摘要与故事大纲的稳定 schema（部分落地）
  - [x] 当前 `chapters` 已保存 `summary_md`、`summary_short`、`summary_intermediate_json`、`importance_score`、`related_chapters_json`、`mentioned_characters_json`、`world_update_json`、`outline_update_json`
  - [x] 当前故事大纲 Markdown 已可增量更新并做长度裁剪
  - [x] `spec.md` / `design.md` 已明确需要区分 `provisional` 与 `committed`
  - [ ] 设计并实现 `summary_status`、`summary_evidence_window`、`summary_target_range` 的持久化方案
  - [ ] 设计并实现 `outline_status`、`outline_evidence_window`、`outline_target_range` 的持久化方案
  - [ ] 兼容旧数据：缺失状态字段的旧章节摘要和旧大纲片段默认视为 `provisional`
  - [ ] 固化章节摘要、整书大纲的长度约束、压缩边界和主线优先淘汰规则
  - [ ] 强化 `related_chapters`、章节重要性、弱支线淘汰的后处理规则

- [ ] Task 2: 拆分 Close-read 持久化边界（部分落地）
  - [x] 当前 `CloseReadRunner` 已完成章节摘要、人物档案、世界观、大纲、进度的完整写回
  - [ ] 将 `_persist_batch()` 中的持久化逻辑拆为独立 Memory Update service，降低 runner 体积
  - [ ] 定义 Chapter Summary、Character Evidence、Memory Candidate、Global Memory、Memory Update 之间的运行顺序与失败恢复策略
  - [ ] 保持现有 dry-run、fallback、debug markdown 和旧数据兼容读取

- [ ] Task 3: 明确 SQLite 与 Markdown 资产职责边界（部分落地）
  - [x] 当前 SQLite 保存结构化运行结果，Markdown 保存世界观、概要、大纲和 SourceArcMap debug 资产
  - [ ] 在文档与接口中固化 SQLite / Markdown 的读写职责、source of truth 和重建策略
  - [ ] 评估是否需要 alias、关系、证据级别、source arc 的辅助表
  - [ ] 若新增证据或调试记录，不保存 offset、原文连续子串或 doc 级人物证据索引

- [ ] Task 4: 强化超长章节拆批与恢复测试（部分落地）
  - [x] 当前 `ChapterAssemblerService` 支持整章优先、超预算切批、从 `reading_progress` 继续处理
  - [x] 当前 `_persist_batch()` 支持 `summary_intermediate_json` 与完整章节二次合并
  - [ ] 明确整章输入、跨章合批、超长章节拆批的稳定阈值 contract
  - [ ] 增加覆盖整章输入、跨章预算合批、超长章节拆批、中间摘要合并的单元测试
  - [ ] 增加 `reading_progress` 恢复测试，覆盖 checkpoint token 与 `last_completed_doc_id`

- [ ] Task 5: 对齐 Character Evidence contract 与当前实现（部分落地）
  - [x] 当前代码按单 document 运行 Character Evidence，并将多个 document 结果汇合为 `character_evidence_batches`
  - [x] 当前输出包含 `is_speaking_character`、`personhood_evidence`、`activity_or_state_evidence`、`relationship_evidence`、`source_doc_ids`、`source_title_indexes`
  - [ ] 清理 spec/design 中仍暗示“多 document batch 直接由模型一次处理”的旧描述，改成当前 per-document evidence + batch 汇合语义，或重新实现真正的多 document batch
  - [ ] 将 `prompt_io_schema.py` 中 Character Evidence dataclass 与 prompt / runner 实际输出保持一致
  - [ ] 保持不输出 offset、原文连续子串和逐 doc_id 人物列表的约束

- [ ] Task 6: 补齐 SourceArcMap 与 Writer/KB 的后续边界（部分落地）
  - [x] `SourceArcMap` JSON/Markdown 生成、压缩窗口、上下文装配片段选择已实现
  - [x] Writer 能识别可选 `memory.source_arc_map` 缺失与就绪状态
  - [ ] 明确 `SourceArcMap` 是否继续只存文件，还是补充 `source_arc_maps` 表或 `book_assets.source_arc_map_path`
  - [ ] 明确哪些 source arc 信息可进入 Writer factual context，哪些只交给创作知识库沉淀结构模式
  - [ ] 增加端到端验收：`documents -> close-read -> SourceArcMap -> context assembly -> writer readiness`

- [ ] Task 7: 补齐端到端测试与文档验收（部分落地）
  - [x] 已有人物档案、上下文装配、SourceArcMap、Character Evidence 汇合等局部测试
  - [ ] 增加端到端测试：`documents -> chapter summaries -> memory updates -> context assembly`
  - [ ] 增加世界观 schema / 概要压缩测试
  - [ ] 增加章节摘要与整书大纲 schema 测试
  - [ ] 更新 `spec.md` / `design.md`，删除与当前代码不一致的旧任务痕迹

- [ ] Task 8: 引入 Summary / Outline 状态模型（待处理）
  - [ ] 新增状态值 contract：`provisional` 表示顺序 close-read 的即时判断，`committed` 表示已结合后续窗口或 `SourceArcMap` 复核
  - [ ] Chapter Summary Agent 写入的 `summary_md` / `summary_short` 默认标记为 `summary_status = provisional`
  - [ ] Memory Candidate Agent 或 Global Memory 生成的即时 `outline_update` 默认标记为 `outline_status = provisional`
  - [ ] 章节摘要中的“结构功能/节奏”只作为 `provisional` 结构判断，不能被 Writer 当作最终篇章功能
  - [ ] 对同一章节或同一 `target_range`，`committed` 结果应优先于旧的 `provisional` 结果

- [ ] Task 9: 实现窗口级 Summary / Outline 定稿流程（待处理）
  - [ ] 设计 `SummaryOutlineCommitService` 或等价服务，输入较大的 `evidence_window` 与较小的 `target_range`
  - [ ] 支持用后续窗口复核目标范围，例如基于第 10 到第 20 个 `document_title_index` 的梗概、人物档案和世界观概要，定稿第 14 到第 18 个 `document_title_index`
  - [ ] 定稿流程应重算目标范围的大纲片段和结构功能 / 节奏判断，而不是简单复制即时 `outline_update`
  - [ ] 定稿完成后写入或导出 `committed` 状态，并保留 `evidence_window` / `target_range`
  - [ ] 定稿失败时不得覆盖已有 `committed` 结果；可保留旧 `provisional` 并输出缺失或失败原因

- [ ] Task 10: 将 SourceArcMap 接入 committed 结构信息（待处理）
  - [ ] 明确 `SourceArcMap` 的篇章功能、节奏和 `chapter_role_map` 属于 `committed` 级结构信息
  - [ ] 支持 `SourceArcMap` 生成后反向更新或辅助定稿相关章节摘要 / 大纲片段
  - [ ] 若同一范围同时存在窗口定稿与 `SourceArcMap` 判断，定义冲突处理和优先级策略
  - [ ] 更新 `SourceArcMap` JSON/Markdown 输出或上下文装配 payload，使其携带必要的状态和参考窗口信息

- [ ] Task 11: 更新 Context Assembly 的状态感知策略（待处理）
  - [ ] `ContextAssemblyService` 优先选择 `committed` 章节摘要和故事大纲
  - [ ] 当目标范围没有 `committed` 结果时，可回退到 `provisional`，但必须在 payload 中显式标注状态
  - [ ] 增加 `memory_status` 或等价字段，说明 `chapter_context`、`story_outline`、`source_arc_context` 是 `committed`、`provisional` 还是 `mixed`
  - [ ] Writer 输入侧不得把 `provisional` 的结构功能 / 节奏判断当作稳定事实

- [ ] Task 12: 补齐状态模型测试与迁移验收（待处理）
  - [ ] 增加 schema / repo 测试：新字段能写入、读取、默认值兼容旧数据
  - [ ] 增加 close-read 写回测试：新摘要和即时大纲默认是 `provisional`
  - [ ] 增加窗口定稿测试：较大 `evidence_window` 可将较小 `target_range` 标记为 `committed`
  - [ ] 增加优先级测试：同范围 `committed` 优先于 `provisional`
  - [ ] 增加 Context Assembly 测试：输出状态标记，并在缺少 `committed` 时正确回退
  - [ ] 增加 SourceArcMap 集成测试：篇章功能和节奏判断可作为 `committed` 级结构信息进入上下文装配

## BTree Narrative Memory Query 重构

- [ ] Task 13: 定义并迁移 BTree Page schema
  - `来源`: [spec.md](spec.md) 的 `BTree-like Narrative Memory`、[design.md](design.md) 的 `BTree Descent Query`
  - `建议只读`: [spec.md](spec.md), [design.md](design.md), [`../writer-agent-layered-generation/designs/outline-research-loop.design.md`](../writer-agent-layered-generation/designs/outline-research-loop.design.md)
  - `建议只关注代码文件`: `novel_agent/app/schemas/`, `novel_agent/app/repos/`, `novel_agent/app/services/`, `novel_agent/tests/test_*memory*.py`
  - [ ] 定义 `document -> chapter summary -> event list -> event summary` 四层 Page 数据结构
  - [ ] `event_summary` Page MUST 只保存对应 event id 起止范围、source doc range、<= 200 字摘要和状态
  - [ ] `chapter summary` Page MUST 记录 `source_doc_start_id` / `source_doc_end_id`，且 `summary_md` 不超过原文 1/10
  - [ ] `event` MUST 包含 `event_id`、`label`、`summary`、`participants`、`source_chapter_range`、`source_doc_range`、`status`
  - [ ] 支持旧数据兼容读取；缺失 BTree Page 时可由现有 chapters / outline assets 重建
  - [ ] 增加 schema / repo / migration 测试

- [ ] Task 14: 重构 close-read 索引构建
  - `来源`: [spec.md](spec.md) 的 `Story Outline Memory` 与 `Character Memory`
  - `建议只读`: [spec.md](spec.md), [design.md](design.md)
  - `建议只关注代码文件`: `novel_agent/app/runner/close_read_runner.py`, `novel_agent/app/services/outline_service.py`, `novel_agent/app/services/character_profile_service.py`, `novel_agent/app/repos/`, `novel_agent/tests/`
  - [ ] close-read 每个章节批次生成或更新 chapter summary Page，并保留 doc range
  - [ ] 从 chapter summaries 压缩生成 `event list`，事件粒度高于 document，通常覆盖多个 document 或一个章节关键推进
  - [ ] 实现 `event summary` 压缩服务：在存在 N 个未压缩 events 时，让模型选择关联性强的一段压缩，并返回尾部未压缩 event index
  - [ ] 支持多 `event_summary` Page；每个 Page 目标覆盖 10-20 万字原文，摘要 <= 200 字
  - [ ] 人物档案新增人物维度 `story_events`，每条事件携带 event id、chapter refs、doc refs、participants
  - [ ] `mentioned_doc_ids` / `speaking_doc_ids` 只作为底层倒排索引，不作为 Writer 理解人物过往的主要入口
  - [ ] 增加 close-read 索引构建测试，覆盖 event doc range、event summary range、人物事件时间线和旧数据回退

- [ ] Task 15: 实现 `NarrativeMemoryQueryService`
  - `来源`: [design.md](design.md) 的 `NarrativeMemoryQueryService`
  - `建议只读`: [design.md](design.md), [spec.md](spec.md)
  - `建议只关注代码文件`: `novel_agent/app/services/`, `novel_agent/app/repos/`, `novel_agent/app/schemas/`, `novel_agent/tests/test_narrative_memory_query*.py`
  - [ ] 实现 `root_scan(query, budget)`，返回 event_summary root candidates
  - [ ] 实现 `drill_down(state, selected_ids)`，支持 event_summary -> event -> chapter -> document
  - [ ] 实现 `resolve_event_ids`、`resolve_chapter_refs`、`resolve_document_refs`
  - [ ] 每层输出 `MemoryQueryState`，包含 `original_query`、`query_suffix_chain`、`path_context`、`current_level`、`current_candidates`、预算消耗和 trace
  - [ ] 实现 `Path Context + Current Candidates` 裁剪策略；进入下一层后默认裁剪未选 sibling
  - [ ] 支持 `need_sibling_scan`、空选择、低置信度的相邻 Page 扩展
  - [ ] 输出 `MemoryEvidenceBundle` 时保留 sources、状态、doc ids、chapter refs 和必要 excerpt
  - [ ] 单元测试覆盖 root scan、逐层下钻、sibling scan、预算裁剪、空选择、旧数据兼容

- [ ] Task 16: 接入泄漏边界与状态标注
  - `来源`: [`../agentic-benchmark/design.md`](../agentic-benchmark/design.md) 的 `Input Boundary`
  - `建议只读`: [spec.md](spec.md), [design.md](design.md), [`../agentic-benchmark/design.md`](../agentic-benchmark/design.md)
  - `建议只关注代码文件`: `novel_agent/app/services/`, `novel_agent/app/benchmarks/`, `novel_agent/tests/`
  - [ ] Memory Query MUST 只查询 prefix-authorized Memory，不得读取 reference future raw text、future outline、reference character set
  - [ ] 每个 candidate / evidence MUST 标注 `provisional` / `committed` / `mixed`
  - [ ] trace 中记录所有 source ids、状态、预算消耗和裁剪原因
  - [ ] 增加故意注入 reference-only data 的失败测试

- [ ] Task 17: Narrative Memory Query 端到端验收
  - `来源`: [spec.md](spec.md), [design.md](design.md)
  - `建议只读`: [spec.md](spec.md), [design.md](design.md), [`../agentic-benchmark/tasks.md`](../agentic-benchmark/tasks.md)
  - `建议只关注代码文件`: `novel_agent/tests/`, `novel_agent/app/run_single_sample_smoke.py`
  - [ ] 增加端到端测试：`documents -> close-read -> BTree Pages -> NarrativeMemoryQueryService -> evidence bundle`
  - [ ] 测试能从 event summary 定位到 event，再定位到 chapter summary，再定位到 document ids
  - [ ] 测试人物档案能从人物事件时间线定位到相关 event / document
  - [ ] 默认单元测试使用 fake model，不调用真实 LLM
  - [ ] 最终验收必须通过显式真实模型 API 的 smoke benchmark；不得用 fake 返回值替代

## 任务依赖

- Task 1 是 Task 2、Task 4、Task 7 的前置
- Task 2 依赖现有 close-read 主流程稳定运行
- Task 3 可与 Task 1、Task 2 并行推进
- Task 5 应先于继续扩展 Character Evidence 相关测试
- Task 6 依赖现有 `SourceArcMap` 文件实现与上下文装配能力
- Task 7 依赖 Task 1、Task 2、Task 4、Task 5 的 contract 收口
- Task 8 依赖 Task 1 的 schema 决策，并应先于 Task 9、Task 11、Task 12
- Task 9 依赖 Task 8，并可在 Task 10 前先实现独立窗口定稿
- Task 10 依赖 Task 6 与 Task 8
- Task 11 依赖 Task 8，并可在 Task 9 / Task 10 未完全完成时先支持状态透传与回退
- Task 12 依赖 Task 8、Task 9、Task 10、Task 11 的实现结果
- Task 13 是 Task 14、Task 15、Task 16、Task 17 的前置
- Task 14 依赖 Task 13，并应与现有 close-read 主流程兼容
- Task 15 依赖 Task 13、Task 14
- Task 16 依赖 Task 15，并应与 benchmark leakage audit 对齐
- Task 17 依赖 Task 14、Task 15、Task 16

## 外部依赖

- 依赖 `novel-continuation-mvp/spec.md` 提供的 `documents` 基线、粗读入库能力与主运行入口。
- 可与 `creative-knowledge-base/spec.md` 的检索结果装配接口集成，但 Memory 层不阻塞于 KB 层完成。
- Writer 可在缺少 `SourceArcMap` 时继续运行，但源作品结构定位能力会下降。

## 独立 Worktree 执行注意

- 建议将 Task 8 到 Task 12 放到独立 git worktree 中执行，完成后再合并回当前分支。
- 当前 `.trae/` 目录未添加进 git 仓库；独立 worktree 中可能无法通过相对路径读取这些 spec 文档。
- 新 Agent 执行时应显式使用绝对路径读取设计文档：
  - `/Users/luliao/agent/smolagents/.trae/specs/narrative-memory-context/spec.md`
  - `/Users/luliao/agent/smolagents/.trae/specs/narrative-memory-context/design.md`
  - `/Users/luliao/agent/smolagents/.trae/specs/narrative-memory-context/tasks.md`
