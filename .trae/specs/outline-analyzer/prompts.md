# Outline Analyzer Implementation Prompts

本文提供可直接交给实现 agent 的独立 prompt。执行前必须重新读取相关 spec / design / tasks；实现完成后不要自动勾选 `tasks.md`，除非明确执行对应 QA / 验收。

## Prompt 1: Shared Narrative Inquiry And Analyzer Core

```text
你在 /Users/luliao/agent/smolagents 仓库中工作。请实现 Outline Analyzer 的共享 Narrative Inquiry 与 Analyzer Core 最小闭环。

必须先读取：
- .trae/specs/spec.md
- .trae/specs/outline-analyzer/spec.md
- .trae/specs/outline-analyzer/design.md
- .trae/specs/outline-analyzer/tasks.md
- .trae/specs/narrative-memory-context/spec.md
- .trae/specs/narrative-memory-context/design.md 中 BTree Descent Query 相关章节

实现目标：
1. 不要为 Analyzer 实现私有检索系统。新增或整理共享的 NarrativeInquiryBroker / EvidenceBundle / request schema，使 Analyzer、Writer Research、未来 Reviewer 都能复用。
2. 事实型请求必须优先复用现有 NarrativeMemoryQueryService，而不是直接扫描 SQLite、Markdown 或 documents。
3. 实现 AnalyzerSeedPacket / AnalyzerSeedBuilder / AnalyzerNotebook 的最小 schema 与 service。
4. 实现 Analyzer Research Loop 的最小版本：
   - 初始只给模型 seed，不喂整本书。
   - 模型返回结构化 requests。
   - requests 交给 NarrativeInquiryBroker。
   - evidence 进入 AnalyzerNotebook。
   - 模型最终输出用户可读分析。
5. 实现 budget 限制，尤其是 raw_excerpt 限制；不得允许“读取整本原文”。
6. 无模型、模型不可用、JSON 解析失败时，必须显式返回 needs_model / failed / blocked，不得使用本地 heuristic 伪装语义分析成功。

范围建议：
- 优先覆盖 tasks.md 的 A1-A5、B1-B5、C1-C4、D1-D3 的最小可运行子集。
- 可以保留后续扩展点，但不要把 Writer handoff、Web UI 改动混入本 prompt，除非为了测试服务入口所必需。

验收测试：
- 增加 service-level 单元测试，覆盖 EvidenceBundle contract。
- 增加 Analyzer Research Loop 测试，至少覆盖 need_more_info -> ready_to_answer。
- 增加 raw_excerpt budget 测试。
- 增加 no model / model JSON failure 测试。
- 增加边界测试：Analyzer 不直接扫描 SQLite / Markdown / documents，事实查询通过 NarrativeInquiryBroker / NarrativeMemoryQueryService。

实现约束：
- 遵守 AGENTS.md：涉及跨层对象先查 contracts / specs，不得改变已冻结字段语义。
- 不得在 prompt、测试数据、fallback 或默认词典中写入只服务某一部小说的专有角色名或设定名。
- 新功能需要单元测试。
- 不要回滚用户已有改动。

完成后请说明：
- 新增/修改的文件。
- 哪些 tasks 被实现到可测试程度，但不要自动勾选 tasks.md。
- 运行过的测试命令和结果。
- 仍未实现的后续项。
```

## Prompt 2: Analyzer Chat Integration And Smoke Test

```text
你在 /Users/luliao/agent/smolagents 仓库中工作。请实现 Outline Analyzer 的 Web / CLI 聊天接入与最小冒烟测试。

必须先读取：
- .trae/specs/spec.md
- .trae/specs/outline-analyzer/spec.md
- .trae/specs/outline-analyzer/design.md
- .trae/specs/outline-analyzer/tasks.md
- .trae/specs/web-interface/spec.md
- 如涉及 Writer handoff 或 Writer gate，先读 .trae/specs/writer-agent-layered-generation/contracts.md

前置假设：
- 已有或将复用 Prompt 1 产出的 Analyzer service facade。
- 本 prompt 不要求实现完整 Narrative Inquiry 深层 loop；若底层尚未完成，可只接入最小服务入口，并保持失败状态显式可见。

实现目标：
1. Web 顶部提供“小说专家意见”入口，启用后同一个聊天输入框进入 Analyzer mode。
2. Analyzer mode 发送消息时必须带 payload.channel = outline_analyzer。
3. 后端收到 outline_analyzer 消息后调用 Analyzer service，并把 Analyzer 回复追加为 assistant message。
4. Analyzer 回复不得自动成为 Writer supplement_text、revision_feedback 或 Writer 问题回答。
5. CLI / TUI 提供 /analyze <question> 或等价命令入口，只输出 Analyzer 回答，不推进 Writer。
6. 实现最小冒烟测试：
   - 复用已经构建好的 Memory，不重新跑完整续写。
   - 向 Analyzer 提出宏观问题，例如“当前未解之谜哪条最适合下一阶段回收？”
   - 验证回答是进一步分析结论，而不是只回显 Memory 摘要。
   - 验证回答包含事实依据或来源标签。
   - 验证回答包含至少一个风险、缺口或需要用户确认的问题。
   - 验证不写 Memory、不创建 Writer artifact、不推进 Writer workflow。

范围建议：
- 优先覆盖 tasks.md 的 E1-E3、F1、F6。
- 如果 Prompt 1 尚未完成，不要用 heuristic 冒充 Analyzer；应返回 needs_model / blocked / missing_core_service 等显式状态。
- Writer handoff 属于 E4，除非用户明确要求，本轮不要实现。

前端要求：
- UI 文案面向用户，不展示内部 stage、checkpoint、artifact id 作为主状态。
- 输入框应清楚显示当前正在和小说专家讨论剧情，并可退出该模式。
- Writer gate 存在时，Analyzer 只是讨论辅助，不自动触发任何 Writer action。

测试要求：
- 后端测试覆盖 outline_analyzer message -> Analyzer service -> assistant message。
- 前端测试覆盖点击“小说专家意见”后发送消息 payload.channel = outline_analyzer。
- CLI 测试覆盖 /analyze 路由到 facade，且不走 slash command 兼容路径以外的 Writer action。
- 冒烟测试覆盖基于已有 Memory 的进一步分析结论。

实现约束：
- 遵守 AGENTS.md：不得用本地 deterministic fallback 伪装模型完成语义分析。
- 不要修改 Writer workflow 继续执行语义。
- 不要回滚用户已有改动。

完成后请说明：
- 新增/修改的文件。
- 运行过的测试命令和结果。
- Analyzer 是否已经能用真实模型运行；若缺少模型配置，请说明如何返回 needs_model。
- 哪些 tasks 仍未实现。
```
