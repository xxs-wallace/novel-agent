# Reviewer Agent Tasks

本文只定义 Reviewer 独立模块的开发任务。第一阶段目标是让 Reviewer 框架能够产出正确、可审计、基于模型的评审意见；不接入 Writer 流程，不改用户交互，不迁移旧 Reviewer。

## Group A: Contracts And Schemas

- [ ] Task A1: 创建 Reviewer schema
  - `来源`: [`contracts.md`](contracts.md)
  - [ ] 实现 `ReviewTarget`
  - [ ] 实现 `ReviewContextPolicy`
  - [ ] 实现 `ReviewBudget`
  - [ ] 实现 `ReviewRequest`
  - [ ] 实现 `ResolvedReviewTarget`
  - [ ] 实现 `ReviewPlan`
  - [ ] 实现 `ReviewerToolCall`
  - [ ] 实现 `ReviewerToolResult`
  - [ ] 实现 `EvidenceRef`
  - [ ] 实现 `ReviewFinding`
  - [ ] 实现 `ReviewReport`
  - [ ] 实现 `ReviewSuiteReport`
  - [ ] 实现 `ReviewerManifest`

- [ ] Task A2: schema 校验规则
  - `来源`: [`contracts.md`](contracts.md) 的 required rules
  - [ ] `status != success` 时不得提供正式有效评分
  - [ ] `purpose != benchmark` 时禁止 `allow_reference_truth = true`
  - [ ] `score` 限制为 0-100 整数
  - [ ] `score_usage` 固定为 `reference_only`
  - [ ] `summary_zh` 必须是中文非空文本
  - [ ] fake / baseline reviewer 不得注册为正式 reviewer

## Group B: Core Runtime

- [ ] Task B1: 创建 Reviewer 模块目录
  - `建议路径`: `novel_agent/app/reviewer/`
  - [ ] `base.py`
  - [ ] `runtime.py`
  - [ ] `registry.py`
  - [ ] `target_resolver.py`
  - [ ] `suite.py`
  - [ ] `tools.py`

- [ ] Task B2: 实现 `ReviewTargetResolver`
  - `来源`: [`design.md`](design.md) 的 `ReviewTargetResolver`
  - [ ] 支持 `text`
  - [ ] 支持 `document_ids`
  - [ ] 支持 `artifact_path`
  - [ ] 支持 `draft`、`synopsis`、`outline`、`chapter_brief`、`raw_text`
  - [ ] 超长目标裁剪必须记录 `truncation`

- [ ] Task B3: 实现 `ReviewerRuntime`
  - `来源`: [`design.md`](design.md) 的 Agent Loop
  - [ ] `initialized`
  - [ ] `planning`
  - [ ] `querying_context`
  - [ ] `evidence_sufficiency_check`
  - [ ] `judging`
  - [ ] `self_check`
  - [ ] `completed`
  - [ ] `needs_model`
  - [ ] `failed`
  - [ ] `skipped`

- [ ] Task B4: 实现 report persistence
  - `来源`: [`design.md`](design.md) 的 Report Persistence
  - [ ] 写入 `review_request.json`
  - [ ] 写入 `resolved_target.json`
  - [ ] 写入 `loop_trace.json`
  - [ ] 写入模型原始响应
  - [ ] 写入 reviewer report
  - [ ] 写入 suite report

## Group C: Model-Only Reviewer Plugins

- [ ] Task C1: 实现 `BaseReviewer`
  - `来源`: [`design.md`](design.md) 的 `BaseReviewer`
  - [ ] reviewer manifest
  - [ ] supported target types
  - [ ] dimensions
  - [ ] planning prompt
  - [ ] judging prompt
  - [ ] self-check prompt

- [ ] Task C2: 实现 `OutlinePlotDevelopmentReviewer`
  - `reviewer_id`: `outline_plot_development`
  - `来源`: [`spec.md`](spec.md) 的 `outline_plot_development`
  - [ ] 支持 `outline`
  - [ ] 结合之前的剧情大纲或篇章地图
  - [ ] 判断剧情发展合理性、阶段推进和长期结构
  - [ ] 输出中文参考意见和 `reference_only` 评分
  - [ ] 不使用本地规则评分

- [ ] Task C3: 实现 `ChapterSynopsisPlotCharacterReviewer`
  - `reviewer_id`: `chapter_synopsis_plot_character`
  - `来源`: [`spec.md`](spec.md) 的 `chapter_synopsis_plot_character`
  - [ ] 支持 `synopsis`
  - [ ] 支持 `chapter_brief`
  - [ ] 结合之前剧情大纲和相关人物档案
  - [ ] 通过 Memory Query 多轮查询人物设定、关系状态和历史行动
  - [ ] 区分已知冲突和证据不足
  - [ ] 输出中文参考意见和 `reference_only` 评分

- [ ] Task C4: 实现 `LocalDraftContinuityReviewer`
  - `reviewer_id`: `local_draft_continuity`
  - `来源`: [`spec.md`](spec.md) 的 `local_draft_continuity`
  - [ ] 支持 `draft`
  - [ ] 结合最近几段正文
  - [ ] 判断明显剧情错误、剧情中断、局部承接断裂和文风生硬切换
  - [ ] 默认不做全文大纲剧情裁决
  - [ ] 输出中文参考意见和 `reference_only` 评分

- [ ] Task C5: 实现 `MemoryDraftConsistencyReviewer`
  - `reviewer_id`: `memory_draft_consistency`
  - `来源`: [`spec.md`](spec.md) 的 `memory_draft_consistency`
  - [ ] 支持 `draft`
  - [ ] 模型抽取草稿中的事件、人物、关系、设定和状态 claims
  - [ ] 通过 `ReviewerMemoryTool` 多轮查询相关历史正文或上一次续写产物
  - [ ] 判断是否与 Memory 中的历史记录矛盾
  - [ ] 重点关注历史相关性，不评价全文大纲或文笔
  - [ ] 输出中文参考意见和 `reference_only` 评分

- [ ] Task C6: 实现 `KBDraftStyleAtmosphereReviewer`
  - `reviewer_id`: `kb_draft_style_atmosphere`
  - `来源`: [`spec.md`](spec.md) 的 `kb_draft_style_atmosphere`
  - [ ] 支持 `draft`
  - [ ] 支持 `raw_text`
  - [ ] 模型总结当前草稿的剧情和场景特征
  - [ ] 通过 `ReviewerKBTool` 查询剧情或场景相似段落
  - [ ] 对比文笔细节、文风和氛围一致性
  - [ ] 不把 KB 相似段落当作剧情正确性标准
  - [ ] 输出中文参考意见和 `reference_only` 评分

## Group D: Reviewer Tools

- [ ] Task D1: 实现 `ReviewerMemoryTool`
  - `来源`: [`design.md`](design.md) 的 Memory Query Integration
  - [ ] 复用 `NarrativeMemoryQueryService`
  - [ ] 保留 `MemoryQueryState`
  - [ ] 保留 `MemoryEvidenceBundle`
  - [ ] 记录完整 memory query trace
  - [ ] 不直接扫描 Memory DB 或 Markdown

- [ ] Task D2: 实现 `ReviewerKBTool`
  - `来源`: [`design.md`](design.md) 的 KB Integration
  - [ ] 只读查询 Creative KB
  - [ ] 记录 query、命中、source refs 和裁剪策略
  - [ ] 不写回 KB

- [ ] Task D3: 实现 policy guard
  - `来源`: [`contracts.md`](contracts.md) 的 `ReviewContextPolicy`
  - [ ] 阻止未授权 reference truth
  - [ ] 阻止未授权 Memory 查询
  - [ ] 阻止未授权 KB 查询
  - [ ] 将拒绝原因写入 loop trace

## Group E: Tests And Acceptance

- [ ] Task E1: schema 单元测试
  - [ ] ReviewTarget 支持 text/document/artifact 三类来源
  - [ ] 非 benchmark 场景禁止 reference truth
  - [ ] failed report 不允许正式评分
  - [ ] success report 的 `score_usage` 必须为 `reference_only`
  - [ ] fake reviewer 不允许注册正式 registry

- [ ] Task E2: runtime 单元测试
  - [ ] 模型 planning 成功
  - [ ] 模型 judging 成功
  - [ ] self-check 成功
  - [ ] 模型不可用返回 `needs_model`
  - [ ] JSON 解析失败后有限修复，仍失败则 `failed`

- [ ] Task E3: Memory Query 集成测试
  - [ ] Reviewer 通过 `ReviewerMemoryTool` 触发 BTree Query
  - [ ] trace 中包含 query、selected ids、evidence ids
  - [ ] 证据不足时 report 明确说明

- [ ] Task E4: 实现 Reviewer smoke 共享真实建模基线
  - `来源`: [`design.md`](design.md) 的 `Reviewer Smoke Test Design`
  - [ ] 只创建一个真实建模任务
  - [ ] 运行真实 document import / segmentation
  - [ ] 运行真实 rough read model calls
  - [ ] 运行真实 close read model calls
  - [ ] 生成真实 Narrative Memory artifacts / pages
  - [ ] 生成真实 Creative KB
  - [ ] 写入 `modeling/source_manifest.json`
  - [ ] 写入 `modeling/memory_manifest.json`
  - [ ] 写入 `modeling/kb_manifest.json`
  - [ ] 禁止 synthetic DB、fake Memory、fake KB 或规则式 fallback 作为 smoke 基线

- [ ] Task E5: 实现 `ReviewerSmokeCaseBuilder`
  - `来源`: [`design.md`](design.md) 的 `Smoke Case Builder`
  - [ ] 从真实 Memory / KB 中动态选取人物、事件、场景或风格证据
  - [ ] 构造五个 `ReviewTarget.text`
  - [ ] 每个 constructed target 标记 `constructed_for_smoke = true`
  - [ ] 构造文本不得写回 Memory / KB
  - [ ] 不得在代码、prompt fixture 或测试默认数据中写死某一部小说的专有名词、角色名或设定名

- [ ] Task E6: Smoke `outline_plot_development`
  - [ ] 构造虚假的 event list / 大纲
  - [ ] 目标包含阶段推进跳跃、剧情方向偏离或因果链缺失
  - [ ] 调用真实 `OutlinePlotDevelopmentReviewer`
  - [ ] Report 包含中文参考意见和 `score_usage = reference_only`
  - [ ] Report 至少包含一个剧情发展或结构推进 finding

- [ ] Task E7: Smoke `chapter_synopsis_plot_character`
  - [ ] 构造虚假的章节梗概或 `chapter_brief`
  - [ ] 目标包含剧情合理性问题和人物设定 / 关系状态冲突
  - [ ] 调用真实 `ChapterSynopsisPlotCharacterReviewer`
  - [ ] 触发真实 `ReviewerMemoryTool`
  - [ ] `memory_query_trace` 非空
  - [ ] Report 区分剧情问题和人物一致性问题

- [ ] Task E8: Smoke `local_draft_continuity`
  - [ ] 从真实文档中截取最近几段正文作为局部上下文
  - [ ] 构造虚假的最新正文草稿
  - [ ] 目标包含局部承接断裂、剧情发展中断或文风突变
  - [ ] 调用真实 `LocalDraftContinuityReviewer`
  - [ ] Report 重点是局部连续性，不以全文大纲剧情作为主要问题

- [ ] Task E9: Smoke `memory_draft_consistency`
  - [ ] 构造虚假的正文草稿
  - [ ] 目标提及 Memory 中动态抽取的人物、事件、关系、地点或设定
  - [ ] 目标故意引入历史矛盾
  - [ ] 调用真实 `MemoryDraftConsistencyReviewer`
  - [ ] 触发真实多轮 Memory Query
  - [ ] Report 引用 Memory evidence 或明确标记证据不足

- [ ] Task E10: Smoke `kb_draft_style_atmosphere`
  - [ ] 构造虚假的正文草稿
  - [ ] 目标包含明显文笔、文风或氛围偏离
  - [ ] 调用真实 `KBDraftStyleAtmosphereReviewer`
  - [ ] 触发真实 `ReviewerKBTool`
  - [ ] `kb_query_trace` 非空
  - [ ] Report 主要评价文笔、文风、氛围和细节执行，不把 KB 相似段落当作剧情正确性标准

- [ ] Task E11: Reviewer smoke summary
  - [ ] 使用 `outline` 跑通 `OutlinePlotDevelopmentReviewer`
  - [ ] 使用 `synopsis` 跑通 `ChapterSynopsisPlotCharacterReviewer`
  - [ ] 使用 `draft` 跑通 `LocalDraftContinuityReviewer`
  - [ ] 使用 `draft` 跑通 `MemoryDraftConsistencyReviewer`
  - [ ] 使用 `draft` 或 `raw_text` 跑通 `KBDraftStyleAtmosphereReviewer`
  - [ ] 产物包含 request、resolved target、loop trace、report
  - [ ] 最终报告为中文，分数可读，`score_usage = reference_only`，findings 有证据引用
  - [ ] 任一模型失败时返回 `failed` / `needs_model`，不得伪造成功评分

## Group F: Future Integration

- [ ] Task F1: 接入 Writer 辅助评审
  - `前置`: Group A-E 完成
  - [ ] Writer 可请求 Reviewer report
  - [ ] Reviewer report 只作为用户参考
  - [ ] 不替代 `GenerationReviewDecision`
  - [ ] 不替代 Writeback Gate

- [ ] Task F2: 接入用户交互
  - `前置`: Writer 辅助评审完成
  - [ ] CLI / Web 可触发当前 artifact review
  - [ ] 用户可选择 reviewer suite
  - [ ] UI 显示中文总评、分数和 findings

- [ ] Task F3: 迁移旧 Reviewer
  - `前置`: Reviewer Runtime 稳定
  - [ ] 迁移 `SmokeReviewerService`
  - [ ] 迁移 `OutlineResearchReviewer`
  - [ ] 适配 Creative KB reviewer report
  - [ ] 保留 benchmark 专用 reference truth policy

## Group G: Agent Work Packages

本组用于把 Reviewer 第一阶段实现拆分给 2-3 个独立开发 Agent。各 Agent 必须遵守 [`spec.md`](spec.md)、[`design.md`](design.md)、[`contracts.md`](contracts.md) 和本文件的任务边界。

### Work Package 1: Reviewer Core Runtime And Contracts

覆盖任务：

- Group A
- Group B
- Group D
- Group E1-E3

建议所有权：

- `novel_agent/app/schemas/reviewer_schema.py`
- `novel_agent/app/reviewer/base.py`
- `novel_agent/app/reviewer/runtime.py`
- `novel_agent/app/reviewer/registry.py`
- `novel_agent/app/reviewer/target_resolver.py`
- `novel_agent/app/reviewer/suite.py`
- `novel_agent/app/reviewer/tools.py`
- `novel_agent/tests/test_reviewer_schema.py`
- `novel_agent/tests/test_reviewer_runtime.py`
- `novel_agent/tests/test_reviewer_tools.py`

验收要求：

- [ ] 所有 contract 对象可 JSON 序列化 / 反序列化
- [ ] `ReviewContextPolicy` 阻止未授权 Memory / KB / reference truth
- [ ] `ReviewerRegistry` 拒绝 fake / baseline reviewer
- [ ] `ReviewerRuntime` 支持 planning、tool call、judging、self-check 和失败状态
- [ ] `ReviewerMemoryTool` 复用 `NarrativeMemoryQueryService`
- [ ] `ReviewerKBTool` 只读查询 Creative KB
- [ ] 模型不可用或 JSON 失败时返回 `needs_model` / `failed`，不产出伪成功评分

### Work Package 2: Five Model-Only Reviewer Plugins

覆盖任务：

- Group C
- Group E2 的 reviewer prompt / model response 相关测试

建议所有权：

- `novel_agent/app/reviewer/reviewers/`
- `novel_agent/app/prompts/reviewer/`
- `novel_agent/tests/test_reviewer_plugins.py`
- `novel_agent/tests/test_reviewer_prompt_contracts.py`

验收要求：

- [ ] 实现 `outline_plot_development`
- [ ] 实现 `chapter_synopsis_plot_character`
- [ ] 实现 `local_draft_continuity`
- [ ] 实现 `memory_draft_consistency`
- [ ] 实现 `kb_draft_style_atmosphere`
- [ ] 每个 Reviewer 都声明 manifest、支持的 target type、allowed tools、dimensions 和默认预算
- [ ] 每个 Reviewer 都有 planning / judging / self-check prompt
- [ ] Prompt 明确要求中文参考意见、0-100 参考评分、`score_usage = reference_only`
- [ ] Prompt 不输出 Writer / Benchmark 质量裁决
- [ ] 不使用本地规则、关键词覆盖或硬编码角色 / 设定判断语义问题

### Work Package 3: Reviewer Real-Model Smoke Runner

覆盖任务：

- Group E4-E11

建议所有权：

- `novel_agent/app/services/reviewer_smoke_service.py`
- `novel_agent/app/run_reviewer_smoke.py`
- `novel_agent/tests/test_reviewer_smoke_service.py`
- Reviewer smoke 产物目录规范：`runs/reviewer_smoke/<run_id>/`

验收要求：

- [ ] 只创建一个真实粗读 / 精读 / KB 建模任务
- [ ] 五类 Reviewer 共用同一套真实 Memory / KB
- [ ] 只有 `ReviewTarget.text` 可以是构造数据
- [ ] 构造数据标记 `constructed_for_smoke = true`
- [ ] Reviewer 与 Memory Query / KB Retrieval 都使用真实模型 prompt 请求
- [ ] Smoke runner 生成五个 case 的 request、resolved target、loop trace、model responses、report 和 summary
- [ ] 每个成功 report 为中文，包含参考评分，且 `score_usage = reference_only`
- [ ] 任一模型失败时返回 `failed` / `needs_model`，不得伪造成功评分

## Group H: Delegation Prompts

以下 prompt 可直接复制给独立开发 Agent。每个 Agent 都必须先读取 `.trae/specs/reviewer-agent/` 下的 `spec.md`、`design.md`、`contracts.md`、`tasks.md`，再实现对应工作包。

### Prompt 1: Core Runtime And Contracts Agent

```text
你在 /Users/luliao/agent/reviewer 仓库中工作。请实现 Reviewer Agent 的核心 runtime 与 contract 层，只负责 .trae/specs/reviewer-agent/tasks.md 中 Work Package 1: Reviewer Core Runtime And Contracts。

开始前必须阅读：
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/spec.md
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/design.md
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/contracts.md
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/tasks.md
- 相关 Memory Query / KB 现有实现，尤其是 NarrativeMemoryQueryService 和 Creative KB retrieval facade

实现范围：
- novel_agent/app/schemas/reviewer_schema.py
- novel_agent/app/reviewer/base.py
- novel_agent/app/reviewer/runtime.py
- novel_agent/app/reviewer/registry.py
- novel_agent/app/reviewer/target_resolver.py
- novel_agent/app/reviewer/suite.py
- novel_agent/app/reviewer/tools.py
- 对应单元测试：test_reviewer_schema.py、test_reviewer_runtime.py、test_reviewer_tools.py

硬性要求：
- 正式 Reviewer 必须 model-only；runtime 不得用本地规则、关键词、硬编码角色名或 fallback 伪造语义评审。
- score 只能是 reference_only 参考评分；status 只表示运行状态，不表示文本质量通过。
- purpose != benchmark 时禁止 reference truth。
- ReviewerMemoryTool 必须复用 NarrativeMemoryQueryService，不得直接扫描 Memory DB 或 Markdown。
- ReviewerKBTool 只能只读查询 KB，不得写回 KB。
- 模型不可用、模型请求失败或 JSON 解析失败后有限重试仍失败时，必须返回 needs_model / failed，不得生成 success report。

交付：
- 完成上述文件实现和单元测试。
- 在最终回复中列出改动文件、测试命令和测试结果。
- 不接入 Writer 流程，不实现五个具体 Reviewer 插件，不实现真实模型 smoke runner。
```

### Prompt 2: Reviewer Plugins And Prompts Agent

```text
你在 /Users/luliao/agent/reviewer 仓库中工作。请实现 Reviewer Agent 的五个 model-only Reviewer 插件与 prompt，只负责 .trae/specs/reviewer-agent/tasks.md 中 Work Package 2: Five Model-Only Reviewer Plugins。

开始前必须阅读：
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/spec.md
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/design.md
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/contracts.md
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/tasks.md
- Work Package 1 已实现或正在实现的 reviewer base/runtime/registry 接口

实现范围：
- novel_agent/app/reviewer/reviewers/
- novel_agent/app/prompts/reviewer/
- novel_agent/tests/test_reviewer_plugins.py
- novel_agent/tests/test_reviewer_prompt_contracts.py

必须实现五个 reviewer_id：
- outline_plot_development
- chapter_synopsis_plot_character
- local_draft_continuity
- memory_draft_consistency
- kb_draft_style_atmosphere

硬性要求：
- 每个 Reviewer 必须声明 manifest、supported_target_types、allowed_tools、dimensions、default_budget。
- 每个 Reviewer 必须提供 planning / judging / self-check prompt。
- Prompt 必须要求中文参考意见、0-100 参考评分、score_usage = reference_only、findings、evidence_refs 和自检结果。
- Prompt 必须禁止输出 Writer / Benchmark 质量裁决，不得出现 approved/rejected/pass/fail 之类文本质量通过语义。
- 需要 Memory 的 Reviewer 只能通过 ReviewerMemoryTool；需要 KB 的 Reviewer 只能通过 ReviewerKBTool。
- 不得使用本地规则、关键词覆盖、硬编码角色名 / 设定名 / 小说专名来判断语义问题。

交付：
- 完成五个插件、prompt builder 和相关测试。
- 测试可使用 fake model client 模拟模型 JSON 输出，但 fake 只能模拟模型响应，不得实现规则式 reviewer。
- 在最终回复中列出改动文件、测试命令和测试结果。
- 不实现 core runtime，不实现真实模型 smoke runner，不接入 Writer 流程。
```

### Prompt 3: Real-Model Reviewer Smoke Agent

```text
你在 /Users/luliao/agent/reviewer 仓库中工作。请实现 Reviewer Agent 的真实模型 smoke runner，只负责 .trae/specs/reviewer-agent/tasks.md 中 Work Package 3: Reviewer Real-Model Smoke Runner。

开始前必须阅读：
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/spec.md
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/design.md
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/contracts.md
- /Users/luliao/agent/reviewer/.trae/specs/reviewer-agent/tasks.md
- 现有粗读、精读、Creative KB、Narrative Memory Query 和 smoke benchmark 相关服务
- Work Package 1/2 已实现或正在实现的 reviewer runtime、tools、plugins 接口

实现范围：
- novel_agent/app/services/reviewer_smoke_service.py
- novel_agent/app/run_reviewer_smoke.py
- novel_agent/tests/test_reviewer_smoke_service.py
- runs/reviewer_smoke/<run_id>/ 产物目录规范

Smoke 设计必须满足：
- 只创建一个真实建模任务：document import / segmentation -> real rough read -> real close read -> real Narrative Memory -> real Creative KB。
- 五个 Reviewer 共用同一套真实 Memory / KB，不得为五个 Reviewer 分别读取五本书或创建五个建模任务。
- 粗读、精读、Memory 生成、Memory Query、KB 构建、Reviewer 都必须是真实模型 prompt 请求。
- 只有 Reviewer 的 ReviewTarget.text 可以是构造数据。
- 构造数据必须标记 constructed_for_smoke = true，且不得写回 Memory / KB。
- 构造数据应从真实 Memory / KB 动态选取人物、事件、场景或风格证据后生成，不得硬编码某一部小说的专名、角色名、设定名或语义映射。

必须生成五个 case：
- outline_plot_development：虚假 event list / 大纲，包含阶段推进跳跃、剧情方向偏离或因果链缺失。
- chapter_synopsis_plot_character：虚假章节梗概或 chapter_brief，包含剧情合理性问题和人物设定 / 关系状态冲突，并触发真实 Memory Query。
- local_draft_continuity：结合最近几段真实正文的虚假最新草稿，包含局部承接断裂、剧情发展中断或文风突变。
- memory_draft_consistency：虚假草稿提及 Memory 动态抽取的人物、事件、关系、地点或设定，并故意引入历史矛盾，触发真实多轮 Memory Query。
- kb_draft_style_atmosphere：虚假草稿包含明显文笔、文风或氛围偏离，触发真实 KB 查询。

产物要求：
- runs/reviewer_smoke/<run_id>/modeling/source_manifest.json
- modeling/memory_manifest.json
- modeling/kb_manifest.json
- 每个 case 下写入 smoke_case.json、review_request.json、resolved_target.json、loop_trace.json、report.json、必要的 model responses
- summary.json 汇总五个 Reviewer 的 status、score_usage、score、summary_zh、主要 findings、Memory / KB trace 是否存在

硬性要求：
- Reviewer report 的 score_usage 必须为 reference_only。
- Reviewer 分数和意见只作为参考，不作为 Writer 或 Benchmark 通过标准。
- 任一模型失败、模型不可用或 JSON 失败时，必须返回 failed / needs_model，不得伪造 success report。

交付：
- 完成 smoke service、CLI runner 和测试。
- 在最终回复中列出改动文件、真实 smoke 命令、测试命令和测试结果。
- 不接入 Writer 流程，不实现规则式 reviewer。
```
