# Reviewer Agent 独立评审模块设计

## Agent Reading Guide

先读 [`AGENT_CONTEXT.md`](AGENT_CONTEXT.md) 判断是否需要展开本文。Reviewer
设计按工作面切片阅读：

- Runtime / state machine / model loop：读第 2、3 节，并回查
  [`contracts.md`](contracts.md)。
- Memory / Narrative Index / evidence 查询：读第 4 节，并回查
  [`../narrative-indexer/spec.md`](../narrative-indexer/spec.md) 与
  [`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md)。
- Creative KB 风格和桥段评审：读第 5 节，并回查
  [`../creative-knowledge-base/spec.md`](../creative-knowledge-base/spec.md)。
- Artifact 读取、泄漏边界和 Writer / Benchmark 接入：读第 5.1、6、10 节。
- Reviewer 类型和 smoke：读第 7、8 节。
- 已入库原文章节的文学性 / 人物塑造诊断：读第 7.6 节，并参考
  [`../outline-analyzer/design.md`](../outline-analyzer/design.md) 的 seed、
  evidence triage 与 raw excerpt 升级策略。

## 1. Design Summary

Reviewer Agent 是一个模型驱动、只读、可插拔的评审运行时。

它把“评审能力”从 Writer 和 benchmark 中抽象出来，但第一阶段不改动既有 Writer / benchmark 流程。Reviewer Runtime 接收 `ReviewRequest`，解析 `ReviewTarget`，驱动指定 Reviewer 通过模型多轮查询 Memory / KB，最后输出 `ReviewReport`。

对于“已入库原文章节”的文学性、人物塑造和前文一致性诊断，Reviewer
应作为目标文本评审框架承载该能力；信息探索部分复用 Outline Analyzer
的轻量 seed、模型主导 research request、evidence triage 和受预算 raw
excerpt 读取策略。该能力不属于 close-read 建模链路，也不得把诊断结论写回
Memory、人物档案或 Writer artifact。

```text
ReviewRequest
  -> ReviewTargetResolver
  -> ReviewerRuntime
  -> Reviewer Agent Loop
       -> model planning
       -> ReviewerMemoryTool / ReviewerKBTool / ReviewerArtifactTool
       -> model judging
       -> model self-check
  -> ReviewReport
```

## 2. Runtime Components

### 2.1 ReviewTargetResolver

职责：

- 将 `ReviewTarget` 解析成 `resolved_text`。
- 保留来源引用，例如 document id、artifact path、chapter id、range hint。
- 校验目标类型是否被指定 Reviewer 支持。
- 对超长文本做输入裁剪，但必须记录裁剪策略。
- 对声明为必须完整阅读的目标类型，先执行硬性长度校验；若超过该 Reviewer
  的 hard limit，应返回 `skipped` / `failed` 并提示用户缩小章节范围，而不是
  静默裁剪后继续评审。

Resolver 不做语义评审，不判断文本质量。

### 2.2 BaseReviewer

Reviewer 插件只声明能力和 prompt 结构，不直接管理运行时循环。

推荐接口：

```python
class BaseReviewer(Protocol):
    reviewer_id: str
    reviewer_version: str
    supported_target_types: set[str]
    dimensions: list[str]

    def build_planning_prompt(self, request: ReviewRequest, resolved_target: ResolvedReviewTarget) -> ModelPrompt: ...
    def build_judging_prompt(self, state: ReviewerLoopState) -> ModelPrompt: ...
    def build_self_check_prompt(self, report: ReviewReport, state: ReviewerLoopState) -> ModelPrompt: ...
```

Reviewer 插件不得直接访问数据库、文件系统或 KB 存储。所有外部资料必须通过 runtime tool 注入。

### 2.3 ReviewerRuntime

职责：

- 校验 `ReviewRequest`。
- 调用 `ReviewTargetResolver`。
- 运行 Agent Loop。
- 执行模型请求的工具调用。
- 管理预算、重试、trace 和状态。
- 校验最终 `ReviewReport`。
- 将报告和原始模型响应落盘。

Runtime 不内置文学规则或角色规则。

### 2.4 ReviewerRegistry

职责：

- 注册正式 Reviewer。
- 按 `reviewer_id` 和 `target_type` 选择 Reviewer。
- 拒绝 fake / baseline reviewer 进入正式 registry。
- 暴露可用 Reviewer manifest。

### 2.5 ReviewerSuite

职责：

- 对同一 `ReviewTarget` 运行多个 Reviewer。
- 聚合分数、summary 和 findings。
- 保留每个 reviewer 的独立报告。
- 只做聚合，不覆盖单个 reviewer 的判断。

第一阶段 suite 可以串行运行；后续可并发运行。

## 3. Agent Loop Design

### 3.1 State Machine

```mermaid
flowchart TD
    A["initialized"] --> B["planning"]
    B --> C{"plan needs context?"}
    C -->|yes| D["querying_context"]
    D --> E["evidence_sufficiency_check"]
    E -->|need more and budget remains| D
    E -->|enough or budget exhausted| F["judging"]
    C -->|no| F
    F --> G["self_check"]
    G -->|valid| H["completed"]
    G -->|repairable| F
    B --> I["needs_model"]
    D --> J["failed"]
    F --> J
    G --> J
```

### 3.2 Planning

模型输入：

- `ReviewTarget` metadata。
- 解析后的目标文本。
- `ReviewContextPolicy`。
- Reviewer 的 rubric。
- 预算限制。

模型输出 `ReviewPlan`：

- 评审维度。
- 初步风险点。
- 是否需要 Memory / KB / artifact 证据。
- 工具调用请求。
- 预期证据类型。

Planning 失败或模型不可用时，runtime 返回 `needs_model` 或 `failed`。

### 3.3 Context Query

模型可以请求：

- `memory_query`
- `kb_retrieval`
- `artifact_read`

Runtime 执行工具调用，并把结果追加到 loop state。

工具调用必须受 `ReviewContextPolicy` 和 `ReviewBudget` 限制。任何未授权的查询必须被拒绝，并记录在 trace 中。

### 3.4 Evidence Sufficiency

模型判断当前证据是否足够：

- `sufficient`
- `needs_more_context`
- `blocked_by_missing_context`
- `budget_exhausted_proceed`

若 `blocked_by_missing_context` 且该维度不能可靠评审，最终 report 应降低 confidence 或返回 `skipped` / `failed`，不得用猜测补足。

### 3.5 Judging

模型基于目标文本和授权证据输出 `ReviewReport`。

Judging prompt 必须要求：

- 输出中文总评。
- 给出 0-100 分。
- 每个主要问题提供证据引用。
- 明确区分“文本中存在的问题”和“证据不足无法判断的问题”。
- 不把 Memory / KB 中的事实误写成目标文本事实。

### 3.6 Self Check

Self-check 由模型完成，用于确认：

- 报告是否符合 schema。
- 分数和 findings 是否一致。
- 每条强断言是否有目标文本或上下文证据。
- 是否使用了未授权 reference truth。
- 是否把建议当成事实。

Self-check 不改变核心语义；若只存在 JSON 结构问题，可触发一次语法修复。若存在语义矛盾，应返回 `failed` 或重新进入 judging，受 retry budget 限制。

## 4. Memory Query Integration

Reviewer 通过 `ReviewerMemoryTool` 使用 `NarrativeInquiryBroker`；Broker 再复用 `NarrativeIndexFacade` 与 `NarrativeMemoryQueryService`。

对 Reviewer 来说，公开工具名仍是 `memory_query`；实现路线是把 Reviewer 的自然语言核查意图转成 Broker 可理解的语义请求，而不是让 Reviewer Runtime 直接操作 Memory DB、`.memory` Markdown 或 Narrative Index 内部表。

Memory Query 已经定义为输入来源无关，可以由 user feedback、reviewer feedback 或 retry instruction 触发。Reviewer 应复用同一套协议和预算 / trace / 授权边界，而不是建立新的私有检索路径。

推荐工具接口：

```python
class ReviewerMemoryTool:
    def query(
        self,
        *,
        conn: sqlite3.Connection,
        book_id: str,
        intent: str,
        budget: MemoryQueryBudget,
        source: str = "reviewer_agent",
    ) -> MemoryEvidenceBundle: ...
```

内部流程：

1. 将一次 `memory_query` 转成 Broker 语义请求。
2. 优先调用 `narrative_scene_card_search`，返回 `NarrativeSceneCard` compact evidence，用于定位关键场景、局部高潮、结构转折和相关原文范围。
3. 同步发起 `story_detail(expected_depth=outline_segment)`，通过 outline root -> outline segment 查询返回连续剧情压缩证据。
4. 如 compact card 与 outline segment 不足，后续版本可继续经 Broker 请求 chapter summary 或 raw excerpt；raw excerpt 必须受预算和 read reason 约束。
5. 返回统一 `ReviewerToolResult`，其中 `evidence_items` 保留 inquiry request type、source、fact status 与 trace。

Evidence 约束：

- `NarrativeSceneCard` 适合帮助 Reviewer 定位场景、结构转折和相关原文范围，但不能单独替代人物档案、世界观规则或 chapter/outline factual memory。
- `story_detail(expected_depth=outline_segment)` 适合提供连续剧情压缩证据；若模型要判断对白、文风、动作细节或微妙情绪，必须显式申请更细粒度 evidence。
- raw excerpt 只能在 compact evidence 不足时升级读取，并且必须记录 `raw_read_reason`、来源范围和预算消耗。
- 每条 evidence 都应能生成 `EvidenceRef`，至少保留 source type、source id/path/range、summary 和 confidence/fact status。

Reviewer Runtime 不得直接扫描 Memory DB 或 `.memory` Markdown；Reviewer 插件也不得绕过 `ReviewerMemoryTool` 私自访问 Narrative Index 或 Memory。

## 5. KB Integration

Reviewer 通过 `ReviewerKBTool` 读取 Creative KB。

推荐工具接口：

```python
class ReviewerKBTool:
    def retrieve(
        self,
        *,
        book_id: str,
        intent: str,
        target_excerpt: str,
        budget: ReviewToolBudget,
    ) -> KBEvidenceBundle: ...
```

KB 查询可用于：

- 风格和氛围对照。
- 桥段执行质量参考。
- 结构模式一致性。
- 相似场景密度或节奏参考。

KB 工具只读，不写回，不更新权重，不修改 rerank 逻辑。

### 5.1 Artifact Read Integration

Reviewer 通过 `ReviewerArtifactTool` 读取授权 artifact。

Artifact 读取只用于评审目标上下文和证据补充，例如：

- Writer 当前 run 的章节梗概、批次计划、正文草稿、写回摘要。
- 调用方显式授权的 benchmark artifact。
- 用户上传或粘贴后保存的评审对象。

约束：

- `ReviewContextPolicy.allow_writer_artifacts` 为 false 时，不得读取 Writer artifact。
- `allowed_artifact_kinds` 是强约束；不在白名单内的 artifact 必须拒绝并记录 trace。
- benchmark held-out reference truth 只能在 `purpose = benchmark` 且调用方显式授权时读取。
- ArtifactTool 只读，不修改 Writer run state、workflow state、artifact 文件或 Memory / KB。
- Artifact id、path、checkpoint、stage 等内部信息只进入 `artifact_trace` 或 debug 视图，不作为用户主状态展示。

## 6. Context Policy And Leakage

Reviewer 有更高评审视角，但必须受场景约束。

### writer_assist

- 可读当前目标、prefix-authorized Memory、KB、当前 Writer artifacts。
- 不可读 benchmark held-out reference truth。
- 报告只作为用户反馈参考。

### user_review

- 可读用户授权的目标和上下文。
- 是否可读 Memory / KB 由 UI 或调用方显式指定。
- 不自动推进 Writer 流程。

### benchmark

- 可读 sample 明确授权的 reference truth。
- 必须在 report 中记录 reference truth 使用。
- 不得把 reference truth 反馈回 Writer。
- Reviewer 分数和意见只作为 benchmark 参考观察项，不直接作为 benchmark 通过标准。

### diagnostic

- 用于开发调试。
- 必须保留所有工具 trace。
- 若使用 fake / dry-run，必须在 report 中标记。

## 7. Reviewer Types

### 7.1 OutlinePlotDevelopmentReviewer

`reviewer_id`: `outline_plot_development`

支持目标：

- `outline`

关注：

- Writer 生成的大纲是否承接之前的剧情大纲。
- 剧情发展方向是否合理。
- 阶段推进是否有因果链。
- 主线、支线和人物线是否有可执行落点。
- 是否存在跳过关键转折、强行推进或长期结构失衡。

上下文策略：

- SHOULD 读取之前的剧情大纲或篇章地图。
- MAY 查询 Memory 中相关历史事件。
- 不关注正文文笔。

### 7.2 ChapterSynopsisPlotCharacterReviewer

`reviewer_id`: `chapter_synopsis_plot_character`

支持目标：

- `synopsis`
- `chapter_brief`

关注：

- Writer 生成的章节梗概是否承接之前的剧情大纲。
- 本章剧情目标、事件推进和人物动机是否合理。
- 梗概涉及的人物行动、语言倾向、关系状态是否与人物档案冲突。
- 是否存在人物能力、身份、阵营或情感状态的无依据跃迁。
- 梗概是否足以指导正文写作。

上下文策略：

- MUST 支持多轮 Memory Query。
- 模型先从梗概中抽取人物、行动、关系、状态变化和关键事件。
- Runtime 将模型查询意图交给 `ReviewerMemoryTool`。
- 模型基于查询结果判断证据是否足够；不足时可继续查询，直到预算耗尽。
- 若证据不足，报告必须明确标记“证据不足”，不得臆造人物档案。

### 7.3 LocalDraftContinuityReviewer

`reviewer_id`: `local_draft_continuity`

支持目标：

- `draft`

关注：

- 最新正文草稿和最近几段正文之间是否连续。
- 是否出现明显剧情错误。
- 是否出现剧情发展中断、场景衔接断裂或视角突然跳变。
- 文风切换是否过于生硬。
- 草稿局部节奏是否突然变松、变硬或脱离上一段叙事惯性。

上下文策略：

- SHOULD 读取最近几段正文和最新草稿。
- 默认不读取全文大纲，不做全局剧情方向裁决。
- MAY 不查询 Memory；若调用方允许，也只能查询与局部衔接直接相关的 evidence。

### 7.4 MemoryDraftConsistencyReviewer

`reviewer_id`: `memory_draft_consistency`

支持目标：

- `draft`

关注：

- 草稿中提及的事件、人物、地点、关系、设定和状态。
- 这些内容是否与历史正文、人物档案、世界观记录或上一次续写产物矛盾。
- 是否存在人物知道不该知道的信息、状态回滚、关系跳变、时间线冲突。
- 是否遗漏前文已经建立的关键限制。

上下文策略：

- MUST 支持多轮 Memory Query。
- 模型先抽取待核查 claims，再按 claim 生成 Memory Query intent。
- Runtime 必须记录 `MemoryQueryState` 和 `MemoryEvidenceBundle` trace。
- 重点是历史相关性，不评价整体文笔或全文大纲合理性。
- 必须严格区分“确认矛盾”和“证据不足”。

### 7.5 KBDraftStyleAtmosphereReviewer

`reviewer_id`: `kb_draft_style_atmosphere`

支持目标：

- `draft`
- `raw_text`

关注：

- 当前正文草稿的场景类型、叙事功能、情绪基调和文体特征。
- KB 中相似剧情或相似场景段落的文笔细节。
- 草稿与原作在句式密度、动作描写、心理描写、氛围推进和节奏上的一致性。
- 是否出现模板化、现代化突兀表达或氛围断裂。

上下文策略：

- 模型先总结目标草稿的剧情和场景特征。
- Runtime 使用这些特征调用 `ReviewerKBTool` 查询相似桥段或场景。
- 模型只比较文笔、文风、氛围和细节执行，不把 KB 相似段落当作剧情正确性标准。
- 通常不需要 Memory Query。

### 7.6 SourceChapterLiteraryDiagnosticReviewer

`reviewer_id`: `source_chapter_literary_diagnostic`

状态：

- Proposed extension，不属于第一阶段必须交付的五类正式 Reviewer。
- 需要新增或扩展 `ReviewTarget` contract 后才能作为冻结 API 暴露。

支持目标：

- `source_chapter`：已入库、可定位到 source document / chapter boundary 的原文章节或章节片段。
- `raw_text` MAY 作为 diagnostic fallback，但只有调用方同时提供 chapter / document
  source refs 时，才允许查询当前 book 的 Memory 证据并生成正式 evidence refs。

Web 入口：

- Web 右侧章节概要 / 章节内容面板中，用户选中一个章节或章节内范围后，右下角显示“分析原文”按钮。
- 点击后创建 `source_chapter_literary_diagnostic` review request。
- UI SHOULD 在创建任务前显示目标范围和大小；若目标原文超过 64KB，直接拒绝创建，并提示用户缩小选区或选择更短章节。
- 入口只启动只读诊断，不进入 Writer review gate，不自动把结论写入续写补充说明。

关注：

- 原作者该章节的文学性优点和短板，例如叙事功能、场景推进、节奏、冲突、情绪曲线、主题表达和语言执行。
- 本章人物的行动、对白、心理、关系互动是否符合此前人物档案、关系状态、历史行动和当前弧线。
- 是否存在与前文人物塑造相矛盾的内容，例如动机断裂、关系跃迁、信息知情越界、能力或价值观突变。
- 是否虽然不构成事实矛盾，但没有很好体现人物特点，例如人物功能化、语气失真、辨识度下降、关键关系张力被弱化。
- 原文中可能存在的合理文学解释，例如人物压抑、伪装、视角限制、阶段性变化或作者有意制造反差；不得把所有张力都直接判为“写崩”。

上下文策略：

- Target 章节原文是主材料。Runtime 在解析目标时必须完整读取用户选择的原文范围，且该范围不得超过 64KB。
- 首轮 seed 只包含目标章节 metadata、目标章节原文或分块索引、极短 story overview、chapter index、source arc hint、命中人物索引和可用 request types。
- 模型先阅读目标原文，抽取本章涉及的人物、关系、事件、情绪转折、文学观察点和待核查问题。
- 模型再生成 research plan，优先查询 `character_profile`、`character_state_card_search`、`story_detail`、`chapter_summary`、`theme_signal_card_search` 和必要的 `source_arc`。
- 只有当人物语气、关系张力、关键行动、伏笔措辞或前文铺垫无法通过摘要层判断时，才允许请求历史 `raw_excerpt`。
- Runtime MUST 复用 `ReviewerMemoryTool` 和 `NarrativeInquiryBroker`，不得直接扫描 documents、Memory SQLite、Markdown 或 Narrative Index 内部表。

Raw evidence budget：

- 创建任务前硬性校验：目标原文 `target_raw_text` 不得超过 64KB。
- 整个诊断过程中，目标章节原文与历史原文摘录之和不得超过 128KB。这里的“历史原文摘录”只包含真正注入模型判断 prompt 的早期 document 原文，不包含索引、摘要、人物档案摘要或 trace metadata。
- 历史原文读取必须是多轮、贡献导向的。模型请求某个历史 document / chapter 后，Broker SHOULD 先返回候选范围、摘要、source refs 和可裁剪片段说明；模型再判断哪些片段对目标章节判断有贡献。
- 对每个历史 document，进入 judging prompt 的 raw excerpt SHOULD 是“对目标章节分析有贡献”的局部截取，例如人物第一次表现同类特质的段落、关系转折段落、相似对话语气段落、关键承诺或冲突段落。
- 若累计贡献截取后仍会超过 128KB，Runtime SHALL 触发额外压缩轮：模型必须把低优先级片段压缩成带 evidence refs 的结论摘要，只保留最高相关、最需要逐字判断的原文片段。
- 若压缩后仍无法在 128KB 内覆盖关键证据，Runtime 应进入 `budget_exhausted_proceed` 或 `blocked_by_missing_context`，最终报告必须降低 confidence 并明确说明未能覆盖哪些历史原文。
- 模型不得请求“读取所有历史章节原文”；Broker 必须拒绝或拆分为带 read reason、expected confirmation 和 source refs 的有限 request。

Loop shape：

```text
resolve source chapter target
  -> hard limit check: selected target raw text <= 64KB
  -> seed with target text / target chunk map and lightweight book indexes
  -> model extracts target chapter literary and character questions
  -> model plans Memory / character / chapter-summary / card queries
  -> Broker returns compact evidence candidates
  -> model selects evidence and requests only necessary historical raw excerpts
  -> enforce target raw + selected historical raw <= 128KB
  -> optional compression round if selected historical raw exceeds budget
  -> model judges literary quality and character fit
  -> model self-checks evidence usage
  -> ReviewReport
```

Recommended report dimensions:

- `literary_execution`：章节功能、节奏、冲突、情绪曲线、主题表达和语言执行。
- `character_fit`：人物是否符合已有档案、目标、恐惧、关系状态和行动模式。
- `character_expression`：是否充分体现人物特点，而不是只判断是否矛盾。
- `continuity_and_causality`：本章事件、动机、信息流和前文铺垫是否连贯。
- `evidence_confidence`：目标原文、人物档案、历史摘要和历史原文证据是否足够。

Finding taxonomy SHOULD distinguish:

- `strength`：值得保留或学习的文学优点。
- `weakness`：文学执行不足，但不一定违反事实。
- `likely_contradiction`：较明确的人物、关系、事件或设定矛盾。
- `possible_tension`：需要解释的张力，可能是合理人物变化或叙事策略。
- `under_expressed_character_trait`：人物特点没有充分体现。
- `insufficient_evidence`：需要更多历史原文或人物档案才能判断。

### 7.7 Shared Output Rule

上述所有 Reviewer 都必须输出中文参考意见和 0-100 参考评分。评分字段只表示该 Reviewer 视角下的质量估计，不作为 Writer 或 Benchmark 的通过标准。

## 8. Reviewer Smoke Test Design

Reviewer smoke 的目标是验证五类 Reviewer 在真实模型、真实 Broker-backed Memory Query 和真实 KB 检索条件下，能够对偏离写作意图或存在明显错误的构造输入提出中文修改意见。

Smoke 不验证 Writer 是否生成了好文本，也不把 Reviewer 分数作为通过标准。Smoke 只验证 Reviewer 能否：

- 成功运行模型驱动 Agent Loop。
- 根据需要触发真实 Memory Query、Narrative Inquiry 或 KB Retrieval。
- 对构造文本中的明显问题提出中文审核意见。
- 产出 `score_usage = reference_only` 的参考评分。
- 保留 request、resolved target、tool trace、model responses 和 report。

### 8.1 Shared Real Modeling Task

五个 Reviewer smoke case MUST 共用一个真实建模任务，不得为五类 Reviewer 分别读取五本书或创建五个建模任务。

共享建模任务流程：

```text
one real source text
  -> document import / segmentation
  -> real rough read model calls
  -> real close read model calls
  -> real Narrative Memory artifacts, Narrative Index cards and pages
  -> real Creative KB build
  -> reviewer smoke case builder
  -> five constructed ReviewTargets
  -> five real Reviewer runs
```

约束：

- 粗读、精读、Memory 生成、Narrative Inquiry / Memory Query、KB 构建和 Reviewer 都必须是真实模型 prompt 请求。
- Memory / KB 不得使用 synthetic DB、fake markdown、规则式 fallback 或手写历史事实。
- 只有 Reviewer 的 `ReviewTarget.text` 可以是构造数据。
- 构造数据必须标记 `constructed_for_smoke = true`，不得写回 Memory / KB。
- 构造数据应从真实 Memory / KB 中动态选取人物、事件、场景或风格证据后生成，不得在代码、prompt fixture 或测试默认数据中写死某一部小说的专有名词、角色名或设定名。

### 8.2 Smoke Case Builder

Smoke runner SHOULD 使用一个 `ReviewerSmokeCaseBuilder` 生成五个 case。

Case builder 的职责：

- 读取共享建模任务输出的 Memory / KB index。
- 通过真实 Broker-backed Memory Query 选择少量可引用的历史事件、人物状态、章节梗概、NarrativeSceneCard 或场景特征。
- 构造带有明确缺陷的 `ReviewTarget.text`。
- 写入每个 case 的预期问题类型，但不写入 Reviewer 应输出的固定答案。

Case builder 可以使用真实模型生成构造文本，也可以使用通用模板拼装，但不得硬编码具体小说角色、设定、桥段映射或语义规则。构造文本只用于 smoke，不代表 Writer 产物。

推荐 artifact：

```text
runs/reviewer_smoke/<run_id>/
  modeling/
    source_manifest.json
    rough_read_summary.json
    close_read_summary.json
    memory_manifest.json
    kb_manifest.json
  cases/
    outline_plot_development/
      smoke_case.json
      review_request.json
      resolved_target.json
      report.json
      loop_trace.json
    chapter_synopsis_plot_character/
    local_draft_continuity/
    memory_draft_consistency/
    kb_draft_style_atmosphere/
  summary.json
```

### 8.3 Case A: Outline Plot Development

Reviewer:

- `outline_plot_development`

Shared context:

- 之前的剧情大纲、篇章地图或 Memory 中的事件线索。

Constructed target:

- 一个虚假的 event list / 大纲。
- 该大纲应有明显剧情发展问题，例如阶段推进跳跃、核心目标突然偏离、因果链缺失、主线和支线断裂。
- 构造内容应基于真实 Memory 中动态抽取的事件或人物标签，不硬编码专名。

Expected smoke evidence:

- Reviewer 成功读取目标大纲和授权历史大纲 / Memory evidence。
- Report 至少包含一个 `major` 或 `critical` finding，说明剧情发展或结构推进问题。
- `suggestion_zh` 或 `suggested_revision_focus` 非空。
- `score_usage = reference_only`。

### 8.4 Case B: Chapter Synopsis Plot And Character

Reviewer:

- `chapter_synopsis_plot_character`

Shared context:

- 之前的剧情大纲。
- 相关人物档案、人物关系、历史行动或状态记录。

Constructed target:

- 一个虚假的章节梗概或 `chapter_brief`。
- 该梗概应包含剧情合理性问题，以及至少一个人物设定或关系状态冲突，例如无铺垫的阵营切换、能力越界、关系跃迁或动机断裂。

Expected smoke evidence:

- Reviewer 触发真实 `ReviewerMemoryTool`。
- `memory_query_trace` 非空，并能看到 Broker request、card/outline evidence、预算消耗和至少一次模型驱动 evidence selection。
- Report 区分剧情问题和人物一致性问题。
- Findings 引用 Memory evidence 或明确标记证据不足。
- `score_usage = reference_only`。

### 8.5 Case C: Local Draft Continuity

Reviewer:

- `local_draft_continuity`

Shared context:

- 最近几段真实正文或从真实文档中截取的最近上下文。

Constructed target:

- 一个虚假的最新正文草稿。
- 草稿应包含局部承接问题，例如上一段场景未结束就突然切到新场景、叙事视角突变、剧情动作断裂、情绪和文风切换过硬。

Expected smoke evidence:

- Reviewer 重点引用最近上下文和最新草稿。
- 默认不需要 Memory Query；若发生查询，也必须只服务局部衔接判断。
- Report 不应把全文大纲合理性作为主要问题。
- Findings 至少指出一个局部连续性或文风突变问题。
- `score_usage = reference_only`。

### 8.6 Case D: Memory Draft Consistency

Reviewer:

- `memory_draft_consistency`

Shared context:

- 真实 Narrative Memory。
- 可选：上一次续写产物或最近历史正文。

Constructed target:

- 一个虚假的正文草稿。
- 草稿应提及从 Memory 中动态抽取的人物、事件、关系、地点或设定，并故意引入历史矛盾，例如状态回滚、人物知道不该知道的信息、关系反转、时间线错误或世界规则冲突。

Expected smoke evidence:

- Reviewer 先抽取待核查 claims。
- Reviewer 通过 `ReviewerMemoryTool` 发起真实多轮 Broker-backed Memory Query。
- Report 的 evidence refs 包含 Memory evidence。
- Report 明确判断确认矛盾或证据不足，不得凭空补事实。
- `score_usage = reference_only`。

### 8.7 Case E: KB Draft Style And Atmosphere

Reviewer:

- `kb_draft_style_atmosphere`

Shared context:

- 真实 Creative KB。
- KB 中与目标草稿剧情或场景特征相似的段落、桥段或风格参考。

Constructed target:

- 一个虚假的正文草稿。
- 草稿剧情可以简单，但文笔、风格或氛围应明显偏离原作，例如过度说明、现代化表达突兀、动作/心理描写密度不匹配、氛围推进断裂。

Expected smoke evidence:

- Reviewer 先用模型总结草稿的剧情和场景特征。
- Runtime 使用这些特征触发真实 `ReviewerKBTool`。
- `kb_query_trace` 非空。
- Report 主要评价文笔、文风、氛围和细节执行，不把 KB 相似段落当作剧情正确性标准。
- `score_usage = reference_only`。

### 8.8 Smoke Summary Criteria

Reviewer smoke run 成功标准：

- 五个 case 均调用真实 Reviewer 模型。
- 需要 Memory 的 case 有真实 `memory_query_trace`，其中保留 Broker / Narrative Inquiry trace。
- 需要 KB 的 case 有真实 `kb_query_trace`。
- 每个成功 report 都包含中文 `summary_zh`、参考 `score`、`score_usage = reference_only`、非空 `findings` 或 `suggested_revision_focus`。
- 每个 case 的 artifacts 可复现，包括构造输入、上下文 policy、模型响应、tool trace 和 report。
- 如果某个 case 因模型不可用或 JSON 解析失败而失败，必须返回 `failed` / `needs_model`，不得生成伪成功评分。

## 9. Report Persistence

Reviewer report SHOULD 落盘到调用方指定目录。

推荐结构：

```text
reviewer/
  review_request.json
  resolved_target.json
  loop_trace.json
  model_responses/
    planning.json
    judging.json
    self_check.json
  reports/
    local_draft_continuity.review.json
    memory_draft_consistency.review.json
    suite.review.json
```

报告路径不作为用户主状态展示，但可用于 debug drawer、benchmark summary 和开发验收。

## 10. Migration Strategy

第一阶段不迁移旧 Reviewer。

后续迁移顺序建议：

1. 将 `SmokeReviewerService` 的 prompt 迁移为 `local_draft_continuity` 或 `memory_draft_consistency` 的 benchmark profile。
2. 将 `OutlineResearchReviewer` 迁移为 `outline_plot_development` 或 `chapter_synopsis_plot_character` 的 benchmark reference policy。
3. 将 Creative KB reviewer 保持为 KB benchmark reviewer，必要时适配 `ReviewerReport` contract。
4. Writer 流程只读取 Reviewer report 作为辅助材料，不直接让 Reviewer 改写 Writer 状态机。

## 11. Implementation Notes

- Reviewer 相关代码建议放在 `novel_agent/app/reviewer/`。
- schema 可放在 `novel_agent/app/schemas/reviewer_schema.py`。
- prompts 可放在 `novel_agent/app/prompts/reviewer/`。
- tests 应覆盖模型失败、JSON 失败、未授权 reference truth、Memory Query trace、不同 target type。
- 正式 Reviewer tests 可以使用 fake model client，但 fake model 只能模拟模型输出，不得把本地规则注册成 reviewer。
