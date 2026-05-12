# Tasks

## 主任务（已完成）

- [x] Task 1: 复用评估与落地路径确认（不改 smolagents 核心）
  - [x] 盘点可复用点：Agent（MultiStep/Code/ToolCalling）、Tool（Tool/@tool）、Model、Memory、runs 导出
  - [x] 选择 MVP 默认 Agent 形态（优先 CodeAgent；ToolCallingAgent 作为可选）
  - [x] 明确 `novel_agent/` 目录与运行入口组织方式（作为本仓库内边车模块）

- [x] Task 2: 建立 novel_agent 工程骨架（目录/配置/入口）
  - [x] 创建 `novel_agent/` 目录结构（app/tools/schemas/memory/indexes/runs/tests）
  - [x] 提供最小运行入口（例如 `python -m novel_agent.app.run_continue_scene ...`）
  - [x] 约定 runs 产物命名与目录结构（run_id、current、history 等）

- [x] Task 3: 建立主数据基线（documents + SQLite/FTS5）
  - [x] 设计 `novel.db` 基础表结构（至少覆盖 `documents` 与 FTS）
  - [x] 实现索引构建脚本：扫描基础素材目录
  - [x] 支持全量构建模式
  - [x] 增加基础单测：建库后能查询到至少 1 条已知文档

- [x] Task 4: MVP 级读取、规划、续写闭环
  - [x] 实现 `read_anchor_context`
  - [x] 实现最小可用的 `search_by_character`、`search_lore`、`search_by_timeline`
  - [x] 实现 MVP 子集版 `ScenePlan`
  - [x] 实现 `check_continuity`
  - [x] 实现单轮续写 Runner 与 runs 落盘

- [x] Task 5: MVP 测试与项目结论
  - [x] 完成基础工具与集成测试
  - [x] 输出“继续本仓库内迭代”的结论

- [x] Task 6: 粗读 Agent 与 `documents` 基线落地
  - [x] 设计目录结构分析 prompt 与读取策略输出 schema
  - [x] 实现原始小说读取与断点续跑机制
  - [x] 扩展 `documents` 表字段：`doc_id`、`content`、`document_title`、`document_title_index`
  - [x] 增加源文件路径、offset 范围、章节序、轻量标签字段、人物关键字等元数据字段
  - [x] 增加进度状态表 / 游标表，维护当前精读进度与最近安全提交点
  - [x] 完成粗读基线：切分、标题、轻量标签、空人物关键字入库

- [x] Task 7: 建立分层后的主编排引用关系
  - [x] 将桥段知识库相关工作正式以下游依赖形式引用到 `creative-knowledge-base/tasks.md`
  - [x] 将人物档案、世界观、章节摘要、大纲、上下文装配相关工作正式以下游依赖形式引用到 `narrative-memory-context/tasks.md`
  - [x] 在主编排层明确：粗读 Agent 生产 `documents`，创作知识库层与 Memory 层分别消费 `documents`

- [x] Task 8: 统一跨层数据 contract
  - [x] 明确主编排层输出给创作知识库层的输入 contract：`documents`
  - [x] 明确主编排层输出给 Memory 层的输入 contract：`documents`
  - [x] 明确创作知识库层回传给续写主 Agent 的 contract：桥段候选、rerank 结果
  - [x] 明确 Memory 层回传给续写主 Agent 的 contract：章节摘要、人物档案、世界观概要、故事大纲
  - [x] 明确过渡期兼容 contract：允许旧 `ScenePlan` 子集、旧基础检索结果与新 `SceneBrief` / rerank 结果并存

- [x] Task 9: 重构续写主 Agent 的总装配逻辑
  - [x] 将当前“读 -> 检索 -> 计划 -> 写 -> 审 -> 保存”的 MVP 路径升级为“读 -> SceneBrief/ScenePlan -> 创作知识库检索 -> Memory 上下文装配 -> 写 -> 审 -> 保存”
  - [x] 已新增 `MainLayerOrchestrator`，把在线 Creative KB 检索主路径从主层显式接出
  - [x] 已将 `run_continue_scene.py` 的检索段接入 `MainLayerOrchestrator`，保留原有 CLI / Agent 外壳
  - [x] 已把 `scene_brief + reference_fragments + context_payload` 组装为 `WriterInputBundle`
  - [x] 已将 `scene_brief.json`、`retrieval_bundle.json`、`writer_input_bundle.json` 纳入当前 runs 落盘产物
  - [x] 保持与现有 CLI / runs 落盘能力兼容，或给出迁移策略
  - [x] 明确总装配层只编排，不重复实现子模块细节
  - [x] 保留现有 Runner 外壳与 runs 目录约定，仅重构内部编排顺序与依赖注入

- [x] Task 10: 跨层集成测试与验收
  - [x] 增加主编排层的跨层集成测试：`documents -> 创作知识库层 -> Memory 层 -> 续写主 Agent`
  - [x] 已增加主层在线接线测试，断言 `MainLayerOrchestrator -> RetrievalFacade` 主路径可用
  - [x] 已增加主层 `WriterInputBundle` 组装测试，断言 `scene_brief + reference_fragments + context_payload` 字段稳定
  - [x] 已增加 `run_continue_scene.py` 的 runs 落盘测试，覆盖 `scene_brief.json`、`retrieval_bundle.json`、`writer_input_bundle.json`
  - [x] 增加失败恢复测试，覆盖子模块缺失或未完成时的降级路径
  - [x] 增加总装配层验收说明，明确哪些能力来自主层、哪些来自子层
  - [x] 保留旧 MVP 直连路径测试作为回归基线，并新增新分层路径测试

- [x] Task 11: 已完成任务与新分层设计的冲突标注
  - [x] 标注当前 MVP 中已完成但仍基于旧检索路径的实现
  - [x] 标注当前 MVP 中已完成但仍基于旧 `ScenePlan` 子集的实现
  - [x] 标注当前测试中仍绑定旧路径的部分
  - [x] 为每项冲突给出“保留 / 兼容 / 重构”的候选决策
  - [x] 将已确认决策转写为主层与子层的具体重构任务，并在后续实施时逐项关闭

- [x] Task 12: 已确认决策的重构执行跟踪
  - [x] 决策项 A 落地：保留基础检索工具，但将续写主检索路径迁移到创作知识库层
  - [x] 决策项 B 落地：兼容保留旧 `ScenePlan` schema，并逐步引入扩展版 `ScenePlan` 与独立 `SceneBrief`
  - [x] 决策项 C 落地：保留 Runner 外壳与 CLI / runs 能力，重构内部总装配逻辑
  - [x] 决策项 D 落地：保留旧集成测试作为回归基线，并新增新分层集成测试
  - [x] 决策项 E 落地：保留粗读轻量标签入库，并在实现约束中明确其仅作粗筛与聚类辅助

## 冲突台账（保留追踪）

- 说明：以下条目用于记录“旧实现与新分层设计的关系与迁移策略”，属于历史冲突/兼容台账，不计入上方主任务完成度。

- [ ] 决策项 A: 当前 `Task 4` 中已完成的 `search_by_character` / `search_lore` / `search_by_timeline`
  - 现状：它们基于 MVP 早期检索路径实现
  - 与新设计的关系：未来创作知识库层会引入 `fragment_cards` / `fragment_clusters` 与 `SceneBrief -> 粗筛 -> rerank`
  - 建议：保留为基础检索工具，但续写主 Agent 的主检索路径应迁移到创作知识库层

- [ ] 决策项 B: 当前 `Task 4` / `Task 5` 中已完成的 MVP 子集版 `ScenePlan`
  - 现状：当前 `ScenePlan` 已落地，但仍是 MVP 子集
  - 与新设计的关系：新设计引入扩展版 `ScenePlan` 与独立 `SceneBrief`
  - 建议：兼容保留旧 schema，后续通过新 contract 渐进替换；如你倾向统一，可以重构

- [ ] 决策项 C: 当前 `Task 6` 中已完成的单轮续写 Runner
  - 现状：当前 Runner 仍按旧路径编排
  - 与新设计的关系：总装配层未来应改为显式消费创作知识库层与 Memory 层的结果
  - 建议：需要重构编排逻辑，但可保留 runs 落盘与 CLI 骨架

- [ ] 决策项 D: 当前 `Task 7` 中已完成的集成测试
  - 现状：测试覆盖的是旧的 MVP 直连路径
  - 与新设计的关系：未来需要补跨层集成测试
  - 建议：旧测试可暂时保留为回归基线；是否彻底替换为新分层测试，待确认

- [ ] 决策项 E: 当前 `Task 6` 中已完成的粗读轻量标签入库
  - 现状：轻量标签已进入 `documents`
  - 与新设计的关系：仍然兼容，但其作用已收缩为粗筛与聚类辅助
  - 建议：保留，不建议重构；只需在后续实现中避免把标签继续当作主检索依据

## 子模块任务引用

- 创作知识库层详见：
  - [`creative-knowledge-base/tasks.md`](.trae/specs/creative-knowledge-base/tasks.md)
- Memory 与上下文层详见：
  - [`narrative-memory-context/tasks.md`](.trae/specs/narrative-memory-context/tasks.md)

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2
- Task 4 depends on Task 3
- Task 5 depends on Task 3, Task 4
- Task 6 depends on Task 5
- Task 7 depends on Task 6
- Task 8 depends on Task 7
- Task 9 depends on Task 7, Task 8
- Task 10 depends on Task 8, Task 9
- Task 11 depends on Task 7, Task 8, Task 9, Task 10
- Task 12 depends on Task 11

# External Dependencies
- `creative-knowledge-base/tasks.md` 承接桥段知识库、去重、代表片段、`SceneBrief -> 粗筛 -> rerank`
- `narrative-memory-context/tasks.md` 承接人物档案、世界观、章节摘要、大纲、上下文装配
