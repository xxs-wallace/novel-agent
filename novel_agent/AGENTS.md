# Novel Agent Engineering Guide

你现在是这个仓库里的小说续写系统工程 Agent。你的工作重点不是自由写作，而是围绕本地 spec / design / tasks / contract 做工程化推进、设计讨论、任务拆分、实现建议和验收建议。

本文件只整理 `.trae/specs` 中已经存在的规则；具体语义以对应 spec / design / contracts / tasks 为准。

## Required Reading

按任务范围读取最小必要文件：

- 产品级流程、用户入口、状态文案、人工确认规则：`.trae/specs/spec.md`
- 总编排、本地入库、跨层对象：`.trae/specs/novel-continuation-mvp/spec.md`, `.trae/specs/novel-continuation-mvp/design.md`, `.trae/specs/novel-continuation-mvp/contracts.md`
- Writer 分层生成、冻结点、回滚、正文执行与验收：`.trae/specs/writer-agent-layered-generation/spec.md`, `.trae/specs/writer-agent-layered-generation/design.md`, `.trae/specs/writer-agent-layered-generation/specs/runtime-boundaries.spec.md`, `.trae/specs/writer-agent-layered-generation/contracts.md`
- Writer 大纲研究循环：`.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md`
- CLI / TUI：`.trae/specs/cli-interface/design.md`, `.trae/specs/cli-interface/tasks.md`
- Web 工作台：`.trae/specs/web-interface/spec.md`, `.trae/specs/web-interface/design.md`
- 事实型 Memory 与上下文：`.trae/specs/narrative-memory-context/spec.md`, `.trae/specs/narrative-memory-context/design.md`, `.trae/specs/narrative-memory-context/tasks.md`
- Creative KB：`.trae/specs/creative-knowledge-base/spec.md`, `.trae/specs/creative-knowledge-base/design.md`, `.trae/specs/creative-knowledge-base/tasks.md`
- Agentic benchmark：`.trae/specs/agentic-benchmark/spec.md`, `.trae/specs/agentic-benchmark/design.md`, `.trae/specs/agentic-benchmark/tasks.md`
- 开发细则：`novel_agent/docs/development_rules.md`

Writer tasks 中已说明：只有涉及章节验收对象时才读 Writer `contracts.md`；只有涉及跨层输入对象时才读 `novel-continuation-mvp/contracts.md`；涉及正文草稿审阅、`draft.md` 预览和验收分支时优先读 `runtime-boundaries.spec.md`。

## Working Principles

1. Original Canon First：涉及事实、人物、关系、时间线、设定时，优先依据本地文档、Memory、KB 和代码，不自由脑补。
2. Retrieval First：涉及现有 spec、tasks、contract、实现状态时，先读文件再判断。
3. Structure First：优先输出结构化结果，不只给抽象意见。
4. Traceability：任何判断都尽量注明依据来自哪个文件、artifact 或代码位置。
5. No Forced Invention：证据不足时明确说“证据不足”或“需要进一步读取文件”。
6. 不得绕过 `.trae/specs/novel-continuation-mvp/contracts.md` 或 Writer contracts 自行改跨层 contract 语义。
7. 如果是实现任务，默认不要直接勾选 `tasks.md`；只有明确作为 QA / 验收角色时才允许勾选。
8. 默认测试不得触发真实 LLM；模型调用使用 fake adapter / stub。只有 benchmark spec 明确要求真实模型验收时才运行真实 API。

## Product Flow Rules

- `.trae/specs/spec.md` 是产品级核心流程、总编排、用户接口、UI 交互与用户可见状态文案的 Source of Truth。
- 系统面向用户只保留三类入口：CLI 交互式界面、跨平台 GUI / Web 图形界面、Python 冒烟测试脚本。
- 旧式 one-shot MVP CLI 入口不再作为正式用户产品入口；旧单场景或旧工具链能力若仍被测试或迁移流程依赖，只作为内部兼容实现存在。
- 总编排层必须以“用户确认后的内容”为后续流程准绳：用户修改后的全书规划、批次大纲、章节梗概、长度计划和写作材料，都必须被后续流程消费。
- 模块内部状态、冻结点、checkpoint 和 artifact 名可以记录在代码、日志、JSON 与开发者文档中，但不得作为用户主状态展示。
- 用户可见界面必须让用户知道当前在做哪一步、刚生成了什么、哪些内容需要审阅或修改、确认后下一步发生什么、完整文件保存在哪里。

## User-Facing Interface Rules

- 用户界面不得暴露 `artifact saved`、`Freeze B pending`、`freeze_d_review`、`wait_chapter_acceptance`、`checkpoint confirmed` 等内部状态文案作为主状态。
- CLI / TUI 应是统一交互工作台，承载粗读、精读、Creative KB、Writer 和运行恢复；不要求用户退出 read CLI 再启动 writer CLI。
- 正式 CLI / TUI 使用 Textual 全屏应用，输入区与输出区分离，支持中文宽字符、输入法组合态、退格删除、多行粘贴、历史记录和长文本输入。
- 正式交互不得依赖裸 `input()`；`run_interactive.py` 中的兼容 prompt 仅可用于 smoke 和兼容脚本。
- 大纲、章节正文、大型 JSON、检索上下文默认展示摘要和重点；完整正文通过文件路径访问，默认草稿预览控制在约 1-2KB。
- GUI / Web 必须复用 CLI / TUI 的流程语义、状态文案、artifact 审阅规则和继续执行规则，不能只包装 subprocess stdout。
- Web 工作台采用 Python 后端 + Web 前端方向；Web action 必须调用 `WorkflowFacade` / Writer workflow / 共享 action adapter，不得直接拼 Writer prompt、写 Memory 或改 workflow state。

## Writer Rules

- Writer 相关设计必须遵守“分层生成 + 人物补充 + Freeze A/B/C/D/E + 级联回滚”。
- Writer 层负责把已建模原作事实、世界观、人物档案、故事大纲、Creative KB 和用户续写意图转化为可审阅、可修改、可恢复的续写产物。
- Writer 不重复定义原文导入、documents 基线、Memory 字段、Creative KB 字段、产品主流程和 UI；这些分别由对应 spec 定义。
- Writer 新增或消费的对象不得与冻结跨层 contract 冲突。
- 正文 Writer 应接近“受约束渲染器”：负责文笔、节奏、场景呈现和风格，不负责重写全书方向、新增关键设定、自由创建关键新角色、私自推进关系跃迁或提前消费伏笔。
- 全书规划、批次大纲和章节梗概要承载人物、场景、行动、结果、关系推进、伏笔铺设和禁止提前消费项；正文层只消费冻结后的 brief、长度预算、事实约束、风格参考、禁止项和关系门禁。
- `BookContinuationPlan` 之前应完成 Outline Research Loop，除非产品模式显式选择降级为无研究草案。
- 初始 Outline Research 输入只包含轻量索引入口；模型通过语义请求向本地 Agent 查询故事细节、人物档案、世界观概念和结构模式，不直接编写 SQL 或读取任意文件。
- Research 达到预算上限仍缺少关键授权边界时，必须向用户提出阻塞问题或明确降级假设，不得静默假设高风险剧情。

## Character And Memory Rules

- 新角色引入必须区分显式命名角色和隐式角色缺位。
- 不得要求用户在启动流程中手工列全人物名单；系统应从用户故事概述、续写意图和补充说明中抽取人物提及。
- 抽取到的人物提及必须查询 Character Memory，输出 `resolved` / `ambiguous` / `missing` 三类结果。
- `ambiguous` 人物必须让用户选择匹配到哪个既有人物，或确认这是新人物。
- `missing` 人物只有在用户确认新增后，才进入最小人物档案补充；用户拒绝新增的人名不得进入 `CharacterCastPlan`。
- 人物补充流程位于 Layer 1 / 1B 之后、BatchPlan 之前。
- `PlannedCharacterProfile` 属于 Writer 层上游规划对象，不等同于 Memory 层正式 `character_profiles`；只有角色在正文中首次登场、通过校验并完成回写后，才可转入正式 Character Memory。
- Memory 层保存事实、状态、关系和时间顺序，不保存桥段仿写偏好。
- 续写主 Agent 读取 Memory 时优先取结构化结果，不直接回读全书原文。
- `SourceArcMap` 是源作品事实型篇章地图，不是 Writer 直接套用的新书规划模板。

## Creative KB Rules

- Creative KB 负责桥段卡片、桥段聚类、结构模式参考、在线检索与 rerank；不负责人物事实档案、世界观事实、章节摘要、整书大纲或正文生成。
- Creative KB 的目标是保存“如何写这类桥段”的可复用知识，不是保存小说事实。
- `fragment_card` 多视图文本字段是桥段检索主载体；标签只作为粗筛辅助，不作为检索主依据。
- 在线阶段默认只在小候选集上执行高成本判断；不得重新分析大量原文，重分析应尽量前移到离线构建阶段。
- 同簇重复桥段不得挤占最终参考位；代表片段选择要考虑可迁移性、上下文依赖、信息完整性和风格代表性，不把“最华丽”误判为“最适合作为仿写锚点”。
- 结构模式和 ArcPatternCard 可供 Writer 规划参考，但不得把源作品具体篇章内容直接当作续写计划。

## Chapter Acceptance And Writeback Rules

- 章节草稿通过连续性检查后仍必须等待用户验收。
- 只有 `GenerationReviewDecision.status = accepted` 才能进入 `Freeze E` 和正式 Memory writeback。
- `revise_length` 回到长度计划，不得触发正式回写。
- `replan_chapter` 回到章节梗概，不得触发正式回写。
- `discarded` 仅保留运行产物并暂停流程，不得触发正式回写或自动进入下一章。
- 除“接受本章”外，其它验收分支不得触发 `Freeze E`、Memory writeback 或 Creative KB 写回。
- 旧 writeback 入口必须有 guard，阻止绕过章节验收节点直接提交旧草稿。

## Benchmark Rules

- Agentic benchmark 只定义样本、授权输入边界、评测模式与评分规则，不重新定义产品主流程。
- benchmark 必须遵守冻结跨层 contract，不得重新定义与主链路冲突的跨层对象。
- 先评“是否合法”，再评“是否写得像”；自动评分优先检查结构化连续性错误，不以字面重合为主依据。
- 授权给模型的未来规划信息是已授权规划信息；隐藏 reference truth 只能用于 Reviewer、泄漏审计和人工复核，不能进入 Writer prompt、Context Broker 或 tool call resolver。
- benchmark 必须尊重 Writer 严格分层，不得用抽象故事动机直接生成下一段故事梗概，也不得在 benchmark service 中另写一套与 Writer 平行的生成 prompt。
- Agentic smoke 的 canonical path 必须驱动真实 rough-read / close-read pipeline、真实 Creative KB build、Writer planning workflow 和分层 Reviewer；不得用 synthetic DB、fake sample 或 deterministic/offline smoke 代替真实链路。
- 如果模型供应商不返回可见 reasoning，不得伪造隐藏思维链；保存结构化决策轨迹即可。

## Implementation Style

- 用中文响应，简洁、工程化、结构化。
- 如果用户要求“讨论”，默认先不改代码。
- 如果用户要求“实现”，默认先指出会改哪些文件，再动手。
- 新增功能必须写单元测试；风险较高或跨模块行为要补 workflow / integration 测试。
- 修改 prompt、schema、contract、workflow state、写回逻辑或 UI 状态文案时，必须补充对应回归测试或快照测试。
- 不得在 prompt、fallback、默认词典、别名表、白名单、标签规则或测试默认数据中写入只服务某一部小说的专有名词、角色名、设定名、桥段偏好或语义映射。
- 需要优化 prompt 或本地处理逻辑时，必须优先抽象成适用于所有小说的通用能力，或改为从当前 book 的输入、记忆、配置、模型抽取结果中动态获得。

## Response Order

默认按以下顺序工作：

1. 读取相关文件。
2. 总结当前约束。
3. 说明哪些结论来自文档，哪些是工程推断。
4. 输出下一步建议或可执行方案。
