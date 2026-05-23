# Reviewer Agent 独立评审模块 Spec

## 1. Purpose

Reviewer Agent 是独立于 Writer、Narrative Memory 和 Creative KB 的只读评审模块。

它的职责是对一个可审阅目标执行模型驱动的多轮评审，输出 0-100 分评价、中文审核意见、结构化问题清单和证据引用。Reviewer 不负责创作、不修改 Writer artifact、不写入 Memory / KB，也不直接决定 Writer 流程是否通过。

本模块第一阶段目标是完善 Reviewer 抽象框架，直到它能够稳定产出正确、可审计、基于模型的 Review 意见。第一阶段不接入 Writer 流程、不接入用户交互界面，也不迁移既有 benchmark reviewer。

## 2. Module Boundary

Reviewer Agent 依赖但不替代以下模块：

- `writer-agent-layered-generation`：Writer 负责生成和修订创作 artifact；Reviewer 只读评审 Writer 或其他来源产物。
- `narrative-memory-context`：Memory 负责事实型上下文、BTree Query、预算、trace 和泄漏边界；Reviewer 只能通过 Memory Query 工具读取证据。
- `creative-knowledge-base`：KB 负责桥段、结构模式、风格参考和检索；Reviewer 只能通过 KB 只读检索工具读取证据。
- `agentic-benchmark`：benchmark 可以调用 Reviewer 生成参考评分和审核意见；Reviewer 分数不得直接作为 benchmark 通过标准，benchmark 自身的规则 baseline 不属于正式 Reviewer Agent。

Reviewer Agent SHALL NOT：

- 修改 Writer 状态机、artifact、草稿、规划或写回结果。
- 写入 Memory / KB 或创建正式事实。
- 使用本地规则、关键词、硬编码角色表或 deterministic fallback 代替模型语义判断。
- 在模型不可用、模型失败或 JSON 解析失败时伪造成功评审。
- 在 Writer 辅助评审场景读取 benchmark held-out reference truth。

Reviewer Agent MAY：

- 读取当前评审目标文本。
- 通过受控工具多轮查询 Memory 和 KB。
- 在 benchmark 场景读取显式授权的 reference truth。
- 运行多个不同维度 Reviewer，并聚合为一个 suite report。
- 将评审意见作为 Writer 后续人工反馈的参考材料。

## 3. Review Target

Reviewer 的输入不是固定 document id，而是 `ReviewTarget`。

`ReviewTarget` 表示一个可被评审的目标，可来自正文、梗概、大纲、章节 brief、规划 notes、用户粘贴文本或运行 artifact。

第一阶段 SHALL 支持以下目标类型：

- `draft`：正文草稿或连续正文片段。
- `synopsis`：故事梗概、章节梗概或批次梗概。
- `outline`：大纲、未来剧情规划或结构化篇章计划。
- `chapter_brief`：Writer 生成的章节写作材料。
- `raw_text`：用户或测试直接传入的一段文本。

`document_ids` 只是 `ReviewTarget` 的可选来源字段。Reviewer Runtime 需先通过 `ReviewTargetResolver` 将目标解析成可审阅文本、来源引用和 artifact metadata。

## 4. Reviewer Categories

Reviewer 是可插拔组件。不同 Reviewer 关注不同维度，但共享同一个运行时、模型调用、工具协议、报告 contract 和失败语义。

第一阶段 SHALL 至少定义以下正式 Reviewer 类型：

- `outline_plot_development`：结合之前的剧情大纲，对 Writer 生成的大纲进行 Review，判断剧情发展的合理性、阶段推进和长期结构是否成立。
- `chapter_synopsis_plot_character`：结合之前的剧情大纲和相关人物档案，对 Writer 生成的章节梗概进行 Review，判断剧情合理性，以及是否与人物既有设定、关系和行动记录冲突。该 Reviewer 需要查询 Memory 层，并且 MAY 进行多轮 Prompt 请求。
- `local_draft_continuity`：结合最近几段正文，对最新正文草稿进行 Review，判断是否存在明显剧情错误、剧情发展中断、局部承接断裂或文风切换过于生硬。该 Reviewer 重点关注草稿的局部性与连续性，不关注全文大纲剧情。
- `memory_draft_consistency`：结合 Memory，对最新正文草稿进行 Review。它需要抽取草稿中提及的事件、人物、关系、设定或状态，通过 Memory Query 查询相关历史正文或上一次续写产物，并判断是否存在历史矛盾。该 Reviewer 重点关注历史相关性。
- `kb_draft_style_atmosphere`：Review 当前正文草稿，先总结其剧情和场景特征，再查询 KB 中剧情或场景相似的段落，对比文笔细节、文风和氛围是否与原作保持一致。该 Reviewer 重点不是剧情正确性，而是文笔、文风和氛围。

具体 Reviewer MUST 声明支持的 `target_type`、允许的工具、评审维度和默认预算。后续可以继续增加其他 Reviewer，但不得弱化上述五类 Reviewer 的边界。

## 5. Model-Only Requirement

正式 Reviewer Agent MUST 基于模型运行。

以下内容必须由模型完成：

- 评审计划生成。
- 需要查询哪些 Memory / KB 证据。
- 语义判断、角色一致性判断、剧情逻辑判断和文风判断。
- 分数、中文意见、问题严重程度和修改建议。
- 最终报告自检。

本地代码只允许承担：

- schema 校验。
- 输入归一化。
- 上下文裁剪。
- 工具调用转发。
- 预算、trace、retry 和错误记录。
- JSON 语法修复，但不得改变语义。

benchmark 或单元测试可以使用 fake / rule baseline，但这些实现 MUST 放在 benchmark/test 边界内，MUST 显式标记 `fake`、`dry_run` 或 `baseline`，并且不得注册为正式 Reviewer。

## 6. Agent Loop

Reviewer 不是单次 prompt。重要 Reviewer SHOULD 使用多轮 Agent Loop。

标准状态：

- `initialized`
- `planning`
- `querying_context`
- `evidence_sufficiency_check`
- `judging`
- `self_check`
- `completed`
- `needs_model`
- `failed`
- `skipped`

标准循环：

1. 解析 `ReviewTarget`。
2. 模型生成 `ReviewPlan`，说明评审维度、风险点和需要查询的证据。
3. Reviewer Runtime 执行模型请求的 Memory / KB 只读工具调用。
4. 模型判断证据是否足够。
5. 若预算允许且证据不足，继续发起查询。
6. 模型生成 `ReviewReport`。
7. 模型执行 self-check，确认报告只基于目标文本和授权证据。
8. 通过 schema 校验后落盘。

## 7. Memory And KB Access

Reviewer 相对于 Writer 有更高的评审视角，但它仍然不能绕过 Memory / KB 的只读 facade。

Reviewer SHALL 通过工具访问上下文：

- `ReviewerMemoryTool`：封装 `NarrativeMemoryQueryService`。
- `ReviewerKBTool`：封装 Creative KB 检索和必要的结构模式查询。
- `ReviewerArtifactTool`：只读读取授权的 Writer artifacts 或 benchmark artifacts。

Memory Query MUST 复用 `NarrativeMemoryQueryService` 的预算、trace、prefix 授权和泄漏审计。Reviewer 不得直接扫描 SQLite、Markdown 或内部 artifact 来绕过 Memory facade。

KB 查询 MUST 保留 query、命中、裁剪、source ref 和预算 trace。Reviewer 不得把 KB 检索结果写回正式 KB。

## 8. Context Policy

每次评审 MUST 显式携带 `ReviewContextPolicy`。

`ReviewContextPolicy` 至少区分：

- `purpose`: `writer_assist` / `benchmark` / `user_review` / `diagnostic`
- `allow_memory`
- `allow_kb`
- `allow_writer_artifacts`
- `allow_reference_truth`
- `allowed_artifact_kinds`
- `leakage_guard`

当 `purpose != benchmark` 时，`allow_reference_truth` MUST 默认为 `false`。

当 `purpose = writer_assist` 时，Reviewer 输出只能作为辅助意见，不能直接替代 `GenerationReviewDecision` 或 Writeback Gate。

## 9. Review Report

Reviewer 输出 MUST 包含：

- `status`
- `score`：0-100 的整数，仅在 `status = success` 时必填，仅供参考。
- `score_usage`：固定为 `reference_only`。
- `summary_zh`：中文总评。
- `findings`：结构化问题列表。
- `dimension_scores`：分维度评分。
- `evidence_refs`：引用的目标文本、Memory、KB 或 artifact 证据。
- `memory_query_trace`
- `kb_query_trace`
- `reviewer_id`
- `reviewer_version`
- `model_id`

报告 MAY 包含：

- `confidence`
- `suggested_revision_focus`
- `raw_model_response_path`
- `self_check`

Reviewer report 是参考评审结果，不是流程决策。Reviewer 不得输出 `approved` / `rejected` / `pass` / `fail` 等质量裁决。`status` 只表示评审运行是否成功，不表示目标文本是否通过。Reviewer 分数和意见不作为 Writer 或 Benchmark 的通过标准；需要自动阻断或通过流程时，应由未来独立的 `ReviewPolicy` 层读取 report 后决策。

## 10. First Phase Acceptance

第一阶段完成标准：

- 定义 Reviewer 抽象、schema、registry、runtime 和 report writer。
- 定义首批五类正式 Reviewer manifest：`outline_plot_development`、`chapter_synopsis_plot_character`、`local_draft_continuity`、`memory_draft_consistency`、`kb_draft_style_atmosphere`。
- 支持 `ReviewTarget` 的 `draft`、`synopsis`、`outline`、`chapter_brief`、`raw_text` 输入。
- 支持 Reviewer Agent Loop 的 planning、querying、judging、self-check 和失败状态。
- 支持通过 Memory Query 工具读取证据，并记录 trace。
- 提供 Reviewer smoke 测试设计：一次真实粗读 / 精读 / KB 建模，五类 Reviewer 共用同一套真实 Memory / KB；仅 Reviewer 的目标文本允许使用构造数据。
- 模型失败时返回显式失败状态，不产出伪成功分数。
- 不接入 Writer 状态机、不修改用户交互、不迁移旧 Reviewer。
