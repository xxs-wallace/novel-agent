# 小说续写 Agentic Benchmark Spec

## Source Of Truth

- 产品级核心流程、UI 交互、用户可见状态文案，以 [`../spec.md`](../spec.md) 为准。
- 本 spec 只定义 benchmark 样本、授权输入边界、评测模式与评分规则。
- benchmark 可以复用核心流程驱动生成，但不重新定义产品主流程。

## Why

当前仓库已经分别定义了：

- 总编排层如何串起续写闭环
- 创作知识库层如何提供桥段型参考
- Memory 与上下文层如何提供事实型约束
- Writer 分层生成如何把规划、梗概与正文拆开

但仍缺少一个独立模块，专门回答以下评测问题：

- 在给定授权规划信息的前提下，系统能否写出“合法后继”
- 在最近 `m` 章窗口下，系统能否维持人物、关系、时间线和世界规则的一致
- 在不同授权边界下，系统质量会如何变化
- 自动评分应如何先发现高价值错误，再交给人工做最终判断

小说续写不是标准的唯一答案任务。  
本 spec 将 benchmark 的核心目标定义为：

- **在受控输入边界内，生成一个与原作前缀状态兼容、与当前章节目标一致、并具备原作风格约束的合法后继。**

## Relationship to Other Specs

- 产品核心流程与 UI 交互：[`../spec.md`](../spec.md)
- 总编排层：[`novel-continuation-mvp/spec.md`](.trae/specs/novel-continuation-mvp/spec.md)
- 总编排设计：[`novel-continuation-mvp/design.md`](.trae/specs/novel-continuation-mvp/design.md)
- 跨层 Contract：[`novel-continuation-mvp/contracts.md`](.trae/specs/novel-continuation-mvp/contracts.md)
- 创作知识库层：[`creative-knowledge-base/spec.md`](.trae/specs/creative-knowledge-base/spec.md)
- Memory 与上下文层：[`narrative-memory-context/spec.md`](.trae/specs/narrative-memory-context/spec.md)
- Writer 分层生成：[`writer-agent-layered-generation/spec.md`](.trae/specs/writer-agent-layered-generation/spec.md)

本 spec 不重复定义：

- `documents` 建库与粗读切分
- `fragment_card` / `fragment_cluster` 细节
- Character / World / Chapter / Outline 的字段级 schema
- Writer 的完整分层生成逻辑

本 spec 只定义：

- benchmark 样本结构
- 三种评测模式
- `forward_guidance` JSON schema
- 自动评分项
- 运行产物与通过标准

## Contract Alignment

本模块 SHALL 遵守 [`novel-continuation-mvp/contracts.md`](.trae/specs/novel-continuation-mvp/contracts.md) 中已冻结的跨层对象语义。

### Requirement: 复用冻结 Contract

benchmark 模块不得重新定义与主链路冲突的跨层对象。

#### Scenario: 检索与写作输入
- **WHEN** benchmark 驱动主续写链路
- **THEN** 检索意图必须复用 contract 兼容的 `SceneBrief`
- **AND** 事实型上下文必须复用 contract 兼容的 `ContextAssemblyPayload`
- **AND** 正文层跨层输入必须复用 contract 兼容的 `WriterInputBundle`
- **AND** 基础检索结果摘要应复用 contract 兼容的 `RetrievalContext`

#### Scenario: benchmark 内部对象边界
- **WHEN** benchmark 定义 `BenchmarkSampleConfig`、`AuthorizedInputs`、`AutoScoreReport` 等内部对象
- **THEN** 这些对象可以包装冻结 contract
- **AND** 不得改变冻结 contract 的字段名、字段类型或字段语义

## Core Principles

- 先评“是否合法”，再评“是否写得像”。
- 授权给模型的未来规划信息不视为信息泄漏，而视为 **已授权规划信息**。
- 原作目标章节是参考真值，不是唯一正确答案。
- 自动评分优先检查结构化连续性错误，不以字面重合为主依据。
- 单场景与单段样本优先于整章样本。
- 创作知识库层与 Memory 层必须分开统计贡献，不能混成一个黑箱输入。
- benchmark 必须尊重 Writer 的严格分层：故事动机/用户方向 -> 故事大纲 -> 故事梗概 -> 正文。
- 不得用抽象故事动机直接生成下一段故事梗概，也不得用章节级大目标直接评估短 document 的正文续写。
- 梗概层与正文层必须分开评测：先评“大纲 + 历史梗概 + 人物文档 -> 下一段梗概”，再评“梗概 + 长度 + KB/风格约束 -> 正文”。
- benchmark 只能驱动和评测正式 Writer 接口产物；不得在 benchmark service 中另写一套与 Writer 平行的故事梗概生成 prompt 或正文扩写 prompt。
- benchmark service 可以组装评测窗口、构造 reference synopsis、调用 Reviewer、落盘审计产物；但 generated synopsis 与 generated draft 的 canonical 产物必须来自 Writer 分层生成链路。

## MVP Smoke Benchmark

第一阶段 benchmark 的目标不是证明系统能达到满分文学质量，而是给用户一个低成本、可重复的能力边界判断：

- 粗读、精读、Creative KB、Writer 分层工作流能被真实 LLM 跑通
- 梗概层能发现“规划层剧情跳跃 / 粒度错位”
- 正文扩写层能验证“给定梗概与目标长度后，正文是否合理还原原文窗口”
- CLI 能给出可人工复核的分层 Reviewer 结论与产物路径

该 MVP SHALL 复用现有 smoke 相关代码与兼容入口，但 Agentic smoke 的 canonical path 是：

- `novel_agent/app/run_single_sample_smoke.py`
- `AgenticSmokeBenchmarkService`
- 真实 rough-read / close-read pipeline
- 真实 Creative KB build
- Writer planning workflow
- 分层 Reviewer：synopsis layer + expansion layer

`SingleSampleSmokeRunner` 必须保留，用于旧 `--sample --db` smoke sample 兼容测试；但端到端 Agentic benchmark 不得用 synthetic DB / fake sample 绕过真实粗读、精读与 Writer 分层流程。

### Requirement: 保留 Single Sample Smoke Runner 兼容性

系统 SHALL 保留 `run_single_sample_smoke.py` 与 `SingleSampleSmokeRunner`，并将其视为旧 sample/db smoke path 的 canonical runner。Agentic smoke path SHALL 通过 `AgenticSmokeBenchmarkService` 驱动真实全链路。

#### Scenario: 兼容现有入口
- **WHEN** 用户或测试仍调用 `python -m novel_agent.app.run_single_sample_smoke`
- **THEN** 现有参数与行为必须保持兼容
- **AND** `--sample`、`--db`、`--runs-dir`、`--use-real-model` 等参数不得被移除
- **AND** 新增 Reviewer 输出只能作为增量产物或增量摘要，不得破坏旧 summary 字段

#### Scenario: Runner 内部职责
- **WHEN** benchmark 执行单样本续写
- **THEN** 旧 sample/db 兼容路径仍由 `SingleSampleSmokeRunner` 负责：
  - 加载 smoke sample
  - 构建 prefix runtime snapshot
  - 裁剪 authorized inputs
  - 组装 retrieval result 与 `WriterInputBundle`
  - 生成正文
  - 保存 `prompt.txt`、`generated.txt`、`reference_truth.txt`、`smoke_compare_report.json`

#### Scenario: Agentic smoke 全链路职责
- **WHEN** 用户运行 `longzu-32kb` 或 `--source` Agentic benchmark
- **THEN** SHALL 使用真实 LLM 依次运行：
  - prefix source 粗读 / segmentation
  - prefix source 精读 / close-read
  - Creative KB build
  - Writer planning workflow
  - Writer 正式章节梗概产物抽取与 SynopsisReviewer
  - Writer 正式正文执行产物抽取与 ExpansionReviewer
- **AND** SHALL NOT 生成 synthetic `longzu_smoke.db` 代替粗读/精读产物
- **AND** SHALL NOT 使用 deterministic/offline smoke 代替真实 LLM 返回
- **AND** SHALL NOT 用 `AgenticSmokeBenchmarkService` 私有 prompt 代替 Writer 的 `plan_chapter_package` / `prepare_execution` / `execute_frozen_chapter` 等正式接口

### Requirement: longzu_32kb 作为真实冒烟样本

系统 SHALL 使用 `novel_agent/tests/longzu_32kb.txt` 作为 MVP 的真实冒烟测试 fixture。

该文件来自 `~/longzu.txt` 的前 32KB 以内片段，截取时必须回退到最后一个换行符，保证文件以完整行结尾。

#### Scenario: Fixture 文件位置
- **WHEN** 构造 MVP smoke sample
- **THEN** SHALL 使用 `novel_agent/tests/longzu_32kb.txt`
- **AND** 不再依赖已删除的 `novel_agent/tmp/longzu_real_sample`
- **AND** 该 fixture 应随测试代码一起维护，作为稳定回归输入

#### Scenario: Fixture 到 Agentic benchmark window 的适配
- **WHEN** 系统从 `longzu_32kb.txt` 构造 Agentic benchmark
- **THEN** SHOULD 切出：
  - `source_prefix.txt`: 只用于真实粗读、精读、Creative KB 和 Writer 前缀建模
  - `reference_truth.txt`: prefix 之后连续多个 document/chunk 组成的 held-out 原文窗口
  - `recent_window`: prefix 末尾最近若干段，用于梗概和正文的局部历史
- **AND** `reference_truth.txt` 不得进入 prefix 粗读、精读、Creative KB 或 Writer planning 输入
- **AND** `reference_truth.txt` 只能用于：
  - 生成 reference story synopsis
  - Reviewer 对照
  - 人工复核

### Requirement: 长文本 Writer-only Cached Benchmark

系统 SHALL 支持比 `longzu_32kb` 更长的真实文本回归样本，用于把评测窗口推进到更靠后的剧情位置。长文本样本包括：

- `novel_agent/tests/longzu_96kb.txt`
- `novel_agent/tests/longzu_120kb.txt`

这些 fixture SHALL 从 `/Users/luliao/longzu.txt` 按对应 KB 上限截取，截取时必须回退到最后一个换行符，保证 UTF-8 完整且以完整行结尾。

由于长文本的 rough-read / close-read / Creative KB token 成本显著更高，Agentic benchmark SHALL 支持 modeling cache：

- cache 内容只能包含真实 rough-read、close-read、Creative KB、reference close-read 以及由这些真实产物组装出的 benchmark story outline / reference story synopsis / writer planning input。
- cache 命中时，系统 SHOULD 跳过 prefix modeling 与 reference close-read，只重新运行 Writer planning、generated synopsis 抽取、reference-synopsis expansion、分层 Reviewer。
- cache key SHALL 至少包含 source hash、prefix/reference window hash、prefix window 参数、pipeline sizing 参数和 cache schema version。
- 长文本回归 SHOULD 通过 `reference_min_chars` 选择连续多个 held-out document/chunk，使 `reference_truth.txt` 与 Writer length budget 足够长，避免只测一个过短场景。
- 如果 source/window 参数无法同时满足 prefix 与 `reference_min_chars`，系统 SHALL 明确失败并提示调低 `prefix_min_chars` 或 `reference_min_chars`，不得静默生成过短 `reference_truth.txt`。
- `reference_story_synopsis.json` SHOULD 保留 `document_synopses`，并在 Expansion 层把这些连续 document 梗概按顺序合并进 Writer execution input。
- cache miss 或显式 rebuild 时，系统 SHALL 重新调用真实 LLM 建模，不得用 deterministic fallback、synthetic DB 或 fake sample 填充 cache。
- 用户 SHALL 能通过 CLI 显式要求 reuse、rebuild 或 clear 对应 cache entry；清理 cache 后的下一次运行必须重新验证 close-read / Creative KB 链路。

#### Scenario: 复用 modeling cache 只测试 Writer 层
- **WHEN** 用户运行长文本 `--source ... --reuse-modeling-cache`
- **AND** 对应 cache entry 已存在且 schema / key 匹配
- **THEN** benchmark SHALL 复用缓存的 prefix DB、story context、reference close-read、reference synopsis 和 benchmark story outline
- **AND** SHALL 重新运行 Writer planning workflow
- **AND** SHALL 重新生成 `generated_story_synopsis.json`
- **AND** expansion SHALL 继续使用 close-read 的 `reference_story_synopsis.json` 包装成 Writer execution input
- **AND** SHALL 重新运行 SynopsisReviewer 与 ExpansionReviewer

#### Scenario: 周期性清理 cache
- **WHEN** 用户传入 `--clear-modeling-cache` 或 `--rebuild-modeling-cache`
- **THEN** benchmark SHALL 删除或刷新当前 source/window 对应的 modeling cache entry
- **AND** 本次运行不得从旧 cache 读取 rough-read / close-read / Creative KB 产物
- **AND** 新 cache 仍必须由真实 DeepSeek LLM 产物构成

### Requirement: 连续多章 Writer Benchmark

系统 SHALL 支持一个小规模连续章节 smoke，用于验证 Writer 多轮生成、writeback 与 sliding-window 上下文是否有效。

- 默认仍为单章；连续模式通过 `sequence_chapter_count` 显式开启。
- 连续模式 SHOULD 使用同一份 prefix modeling cache 与同一份 held-out reference close-read。
- held-out reference close-read 的连续 summaries SHALL 被按顺序切分为多个目标章节窗口。
- 每一章都 SHALL 重新执行 Writer planning workflow 并生成本章 `generated_story_synopsis.json`，该产物只用于 SynopsisReviewer，不得进入 Expansion 生成输入。
- 每一章 Expansion 的输入 story synopsis SHALL 来自对应 close-read reference summary group，而不是 Writer 自己生成的 chapter brief。
- 每一章正文生成后 SHALL 走 Writer 正式执行链路，并在通过 continuity / acceptance 后写回 Writer memory DB。
- 下一章 planning / execution SHALL 从写回后的 Writer memory DB 读取最近章节摘要和人物/世界状态，形成类似 sliding-window attention 的连续上下文。

#### Scenario: 三章连续 smoke
- **WHEN** 用户传入 `--sequence-chapter-count 3`
- **THEN** benchmark SHALL 产生 `sequence/chapter_01`、`sequence/chapter_02`、`sequence/chapter_03`
- **AND** 每个 chapter 目录 SHALL 保存：
  - `reference_story_synopsis.json`
  - `generated_story_synopsis.json`
  - `writer_planning_input.json`
  - `expansion/writer_execution_input.json`
  - `expansion/draft.md`
  - `writeback_result.json`
  - 分层 Reviewer prompt/report
- **AND** 顶层 `reviewer_report.json` SHALL 汇总每章 synopsis layer 与 expansion layer 的 decision / score / summary

### Requirement: 分层 Writer Benchmark

系统 SHALL 将 Writer benchmark 拆成两个互相独立的层级，不得把故事梗概生成和正文扩写混成一个评分。

### Requirement: 复用正式 Writer 生成接口

Agentic benchmark SHALL 是正式 Writer 链路的评测器，而不是平行生成器。

#### Scenario: 生成产物来源
- **WHEN** benchmark 需要 `generated_story_synopsis.json`
- **THEN** SHALL 从 Writer 正式章节规划产物中抽取或规范化：
  - `chapter_package.json`
  - `chapter_brief.json`
  - 或等价的 Writer Freeze C / ChapterBrief 产物
- **AND** SHALL NOT 通过 benchmark service 自定义 prompt 直接生成一份替代性的 story synopsis

#### Scenario: 正文产物来源
- **WHEN** benchmark 需要 `expansion/draft.md`
- **THEN** SHALL 通过 Writer 正式正文执行路径生成：
  - `prepare_execution`
  - Freeze D / `chapter_execution_input.json`
  - `execute_frozen_chapter`
- **AND** SHALL NOT 通过 benchmark service 自定义 prompt 直接扩写正文

#### Scenario: benchmark service 职责边界
- **WHEN** `AgenticSmokeBenchmarkService` 运行 Agentic benchmark
- **THEN** 它可以负责：
  - 切分 prefix / held-out reference window
  - 运行真实 rough-read / close-read / Creative KB
  - 驱动 Writer workflow 到需要的 freeze / execution 阶段
  - 从 Writer 产物抽取 benchmark artifact
  - 从 held-out reference truth 构造 reference synopsis
  - 运行分层 LLM Reviewer
  - 保存 prompt / artifact / summary 用于复核
- **AND** 它不得重新实现 Writer 的 story synopsis generator 或 prose expansion executor
- **AND** 如需 teacher-forcing expansion 作为诊断实验，必须另命名为非 canonical 层（例如 `teacher_forced_expansion`），不得覆盖 `expansion/draft.md`

#### Scenario: 故事大纲到故事梗概
- **WHEN** benchmark 评估“下一段故事梗概”能力
- **THEN** 输入 SHOULD 包含：
  - 当前故事大纲，且至少包含目标梗概所在的 outline 节点
  - 最近一批已生成/已确认的故事梗概
  - 可用人物文档，用于约束可使用人物
  - 目标原文窗口长度或目标正文长度
- **AND** 输入 SHOULD NOT 包含：
  - reference truth 原文正文
  - 从 reference truth 直接抽出的 reference synopsis
  - 抽象故事动机或用户简述作为唯一剧情依据
- **AND** 输出 SHALL 落盘为 `generated_story_synopsis.json`
- **AND** `generated_story_synopsis.json` SHALL 是 Writer 章节梗概产物的规范化视图，而不是 benchmark service 自行生成的新梗概

#### Scenario: Reference synopsis 构造
- **WHEN** benchmark 需要评估梗概层
- **THEN** SHALL 从 held-out reference truth 的连续多个 document/chunk 总结出 `reference_story_synopsis.json`
- **AND** reference synopsis 应包含：
  - `source_chars`: 原文窗口字符数
  - `combined_synopsis`: 连续剧情梗概
  - `plot_beats`: 顺序剧情 beat
  - `tone_and_style`
  - `must_preserve`
  - `must_avoid`
- **AND** reference synopsis 只能用于 Reviewer 和正文扩写层 benchmark，不得作为梗概生成层的输入

#### Scenario: 故事梗概到正文
- **WHEN** benchmark 评估正文扩写能力
- **THEN** 输入 SHOULD 包含：
  - reference story synopsis 或当前层授权 story synopsis
  - 目标正文长度 / `source_chars`
  - recent window
  - KB / 风格约束
- **AND** 输入 SHOULD NOT 包含 reference truth 原文正文
- **AND** 输出 SHALL 落盘为 `expansion/draft.md`
- **AND** `expansion/draft.md` SHALL 是 Writer 正文执行器产物，而不是 benchmark service 自行扩写的新正文

#### Scenario: 分层 Reviewer
- **WHEN** benchmark 完成
- **THEN** SHALL 分别输出：
  - `synopsis_reviewer_report.json`: 比较 generated synopsis 与 reference synopsis
  - `expansion_reviewer_report.json`: 比较 expansion draft 与 reference truth/reference synopsis
  - `reviewer_report.json`: 汇总两个层级的综合结论
- **AND** CLI summary SHOULD 同时展示梗概层与扩写层 Reviewer 中文结论

### Requirement: 抽离可复用 Benchmark 组件

系统 SHALL 将 `SingleSampleSmokeRunner` 中可复用的 benchmark 能力抽离为服务，而不是把 CLI 逻辑写进 runner。

#### Scenario: 可复用组件边界
- **WHEN** CLI 或脚本需要运行 benchmark
- **THEN** SHOULD 复用以下服务或等价服务：
  - benchmark window adapter：负责从 `novel_agent/tests/longzu_32kb.txt` 切出 prefix source、recent window 与 held-out reference truth
  - agentic run service：负责运行真实粗读、精读、Creative KB、Writer planning、梗概生成、正文扩写与分层 Reviewer
  - compatibility run service：负责在旧 `--sample --db` 路径调用 `SingleSampleSmokeRunner`
  - reviewer service：负责生成分层 Reviewer reports 与顶层 `reviewer_report.json`
  - summary presenter：负责把结果转成人类可读 CLI 摘要
- **AND** `SingleSampleSmokeRunner` 不应依赖 Textual UI、slash command 或用户输入组件

### Requirement: 分层 LLM Reviewer 角色

系统 SHALL 新增 Reviewer 角色，并同时接入 `run_single_sample_smoke.py` 与统一 CLI。

Reviewer SHALL 由真实 LLM 执行评分，不得用 deterministic 轻量规则替代。  
第一期 Reviewer SHOULD 分成两个层级 prompt：

- `SynopsisReviewer`: 评估“故事大纲 + 最近梗概 + 人物文档 -> 下一段故事梗概”
- `ExpansionReviewer`: 评估“故事梗概 + 目标长度 + recent window + KB/风格约束 -> 正文”

后续可以引入更多 Reviewer，就像多头注意力一样，让不同 Reviewer 分别关注人物、关系、世界观、风格、检索使用等特征；但 MVP 阶段不得把这些职责都塞进同一个 prompt，避免注意力分散。

#### Scenario: SynopsisReviewer 输入
- **WHEN** Reviewer 检查梗概层
- **THEN** Reviewer SHOULD 读取：
  - 当前故事大纲或覆盖目标窗口的故事大纲节点
  - 最近一批已确认/已生成故事梗概
  - 可用人物约束
  - `generated_story_synopsis.json`
  - `reference_story_synopsis.json`
- **AND** Reviewer SHOULD 判断生成梗概是否承接最近梗概、符合故事大纲、与 reference synopsis 的核心剧情功能相似
- **AND** Reviewer 不得把 reference synopsis 暴露给梗概生成阶段

#### Scenario: ExpansionReviewer 输入
- **WHEN** Reviewer 检查正文扩写层
- **THEN** Reviewer SHOULD 读取：
  - 最近 `M` 段连续剧情或 `recent_window_summary`
  - 用于扩写的 authorized/reference story synopsis
  - 生成正文
  - held-out reference truth
- **AND** Reviewer SHOULD 把 generated draft 拼接到 recent window 后整体判断逻辑和剧情连续性
- **AND** Reviewer SHOULD 比较 generated draft 与原文窗口在核心事件、情绪功能、文本长度和叙事密度上的相似性
- **AND** reference truth 不得暴露给正文扩写阶段

#### Scenario: Reviewer 输出
- **WHEN** Reviewer 完成检查
- **THEN** SHALL 分别输出：
  - `synopsis_reviewer_report.json`
  - `expansion_reviewer_report.json`
  - 顶层 `reviewer_report.json`
- **AND** 每个 Reviewer report 至少包含：
  - `decision`: `pass | borderline | fail`
  - `score`: `0.0-1.0`
  - `summary`: 简短中文结论
  - `issues`: 明显问题列表
  - `checks`: Reviewer 检查项结果
  - `generated_chars`
  - `reference_truth_chars`

#### Scenario: Reviewer 最小检查项
- **WHEN** Reviewer 评分
- **THEN** SHOULD 至少检查：
  - 生成是否为空或过短
  - 梗概层是否能接上最近故事梗概
  - 梗概层是否符合故事大纲节点
  - 梗概层是否与 reference story synopsis 的核心剧情功能相似
  - 正文层是否能接上最近 `M` 段剧情
  - 正文层内部逻辑是否通顺
  - 正文层是否覆盖 authorized/reference story synopsis 的核心内容
- **AND** 第一阶段 SHOULD NOT 实现独立的人物档案、人物关系、世界观或检索使用专项 Reviewer

#### Scenario: Reviewer 与 SmokeCompareReport 的关系
- **WHEN** 系统同时产生 `smoke_compare_report.json` 与 `reviewer_report.json`
- **THEN** `smoke_compare_report.json` 保留为规则/轻量分项对比报告
- **AND** `reviewer_report.json` 作为面向用户的能力边界评语
- **AND** 两者不得互相覆盖
- **AND** CLI summary SHOULD 优先展示 Reviewer 的中文结论，再展示分数和产物路径

#### Scenario: MVP 决策
- **WHEN** Reviewer 综合评分
- **THEN** `score >= 0.60` SHOULD 视为达到最小回归目标
- **AND** `0.45 <= score < 0.60` SHOULD 视为 `borderline`
- **AND** `score < 0.45` 或空输出 SHOULD 视为 `fail`
- **AND** 分数只作为辅助信号，不作为文学质量的最终判断

### Requirement: MVP CLI Entry

系统 SHALL 将 single sample smoke benchmark 暴露给 CLI 用户。

#### Scenario: 独立命令入口
- **WHEN** 用户不想进入全屏 TUI
- **THEN** SHOULD 可以继续运行：

```bash
python -m novel_agent.app.run_single_sample_smoke \
  --source novel_agent/tests/longzu_32kb.txt \
  --runs-dir runs/benchmarks/longzu_32kb \
  --use-real-model \
  --api-key "$DEEPSEEK_API_KEY"
```

旧兼容路径仍可使用 `--sample <sample.json> --db <db_path>`，但该路径只用于 `SingleSampleSmokeRunner` 兼容测试，不代表 Agentic benchmark 全链路。

#### Scenario: 统一 CLI Slash Command
- **WHEN** 用户已经在统一 CLI / TUI 工作台
- **THEN** SHOULD 可以运行：

```text
/benchmark longzu-32kb
```

或显式指定 sample：

```text
/benchmark --source novel_agent/tests/longzu_32kb.txt
```

#### Scenario: MVP 产物落盘
- **WHEN** MVP benchmark 完成
- **THEN** SHOULD 保存：
  - `source_prefix.txt`
  - `reference_truth.txt`
  - `pipeline_result.json`
  - `writer_result.json`
  - `legacy_writer_chapter_brief.json`
  - `benchmark_story_outline.json`
  - `generated_story_synopsis_prompt.json`
  - `generated_story_synopsis.json`
  - `reference_story_synopsis_prompt.json`
  - `reference_story_synopsis.json`
  - `synopsis_reviewer_prompt.json`
  - `synopsis_reviewer_report.json`
  - `expansion/prompt.json`
  - `expansion/draft.md`
  - `expansion_reviewer_prompt.json`
  - `expansion_reviewer_report.json`
  - `reviewer_report.json`
  - `summary.json`
- **AND** 旧 sample/db 兼容路径仍 SHOULD 保存：
  - `smoke_sample.json`
  - `prefix_runtime_snapshot.json`
  - `authorized_inputs.json`
  - `retrieval_bundle.json`
  - `writer_input_bundle.json`
  - `prompt.txt`
  - `generated.txt`
  - `smoke_compare_report.json`
  - `smoke_run_summary.json`

## Benchmark Goals

本 benchmark SHALL 回答以下问题：

1. 给定前缀事实、桥段参考与授权规划信息，系统能否生成连续性正确的续写
2. 给定最近 `m` 章窗口，系统能否维持敌友关系、动机、冲突线与情绪余波
3. 给定当前章节授权纲要，系统能否完成本章应完成的叙事功能
4. 给定局部未来导向，系统能否在长场景拆段时维持逻辑连贯
5. 创作知识库、Memory、规划信息三类输入各自贡献了多少质量提升

## Evaluation Unit

### Requirement: Benchmark Sample

系统 SHALL 以“待生成场景”或“待生成段落组”作为默认评测单元。

#### Scenario: 最小样本结构
- **WHEN** 系统定义一个 benchmark sample
- **THEN** 样本至少包含如下字段或等价字段：

```json
{
  "sample_id": "string",
  "book_id": "string",
  "target_chapter_id": "string",
  "target_segment_id": "string | null",
  "mode": "blind_prefix | chapter_authorized | bounded_future_hint",
  "anchor_context_path": "string",
  "recent_window_refs": ["string"],
  "documents_cutoff": {
    "max_document_title_index": "string"
  },
  "allowed_outline_scope": {
    "chapter_range": ["string"],
    "allow_future_outline": false
  },
  "forward_guidance": null,
  "reference_truth_path": "string",
  "metadata": {
    "is_climax": false,
    "window_size": 3,
    "target_length_chars": 3000
  }
}
```

#### Scenario: Reference Truth 用途
- **WHEN** 样本包含 `reference_truth_path`
- **THEN** 原作文本仅用于：
  - 提取章节功能与关键状态变化
  - 辅助人工评审
  - 训练自动 judge 的弱监督样本
- **AND** 不得将字面相似度作为主评分依据

## Authorized Planning Boundary

### Requirement: 已授权规划信息定义

系统 SHALL 将生成时可见的未来信息统一归类为“已授权规划信息”。

#### Scenario: 规划信息分类
- **WHEN** benchmark 裁剪输入边界
- **THEN** 至少区分：
  - `prefix_facts`: 当前生成位置之前已经成为 canon 的事实
  - `current_unit_plan`: 当前待写章节或待写段落被授权暴露的规划信息
  - `bounded_future_hint`: 为拆段生成而暴露的局部未来导向

#### Scenario: 越界定义
- **WHEN** 系统读取未授权的后续剧情、终局秘密、身份反转或完整事件序列
- **THEN** 视为越界信息

## Benchmark Modes

### Requirement: Blind Prefix Mode

系统 SHALL 支持 `blind_prefix` 模式。

#### Scenario: Blind Prefix 输入边界
- **WHEN** 一个 sample 运行于 `blind_prefix`
- **THEN** 系统只可读取：
  - 前缀 `documents`
  - 当前点之前的章节摘要
  - 当前点之前的人物档案与世界观
  - 当前点之前可构建出的创作知识库
  - 锚点上下文与最近 `m` 章窗口
- **AND** 系统不得读取当前章节纲要
- **AND** 系统不得读取后续章节纲要
- **AND** `forward_guidance` 必须为 `null`

### Requirement: Chapter Authorized Mode

系统 SHALL 支持 `chapter_authorized` 模式。

#### Scenario: Chapter Authorized 输入边界
- **WHEN** 一个 sample 运行于 `chapter_authorized`
- **THEN** 系统可读取：
  - `blind_prefix` 允许的全部输入
  - 当前待写章节的章节目标与章节梗概
  - 当前章节允许暴露的关系推进目标、情绪目标与冲突目标
- **AND** 系统不得读取后续章节的详细纲要
- **AND** `forward_guidance` 默认应为 `null`

#### Scenario: 主 benchmark 模式
- **WHEN** 团队选择默认评测模式
- **THEN** SHOULD 使用 `chapter_authorized`
- **AND** 将其视为最接近作者真实写作条件的标准模式

### Requirement: Bounded Future Hint Mode

系统 SHALL 支持 `bounded_future_hint` 模式。

#### Scenario: Bounded Future Hint 输入边界
- **WHEN** 一个 sample 运行于 `bounded_future_hint`
- **THEN** 系统可读取：
  - `chapter_authorized` 允许的全部输入
  - 一个结构化 `forward_guidance`
- **AND** `forward_guidance` 只能表达局部导向
- **AND** 不得变相暴露完整后续章节剧情

#### Scenario: Bounded Future Hint 适用场景
- **WHEN** 待写内容属于高潮、长对峙、连续追逐或多段情绪升级场景
- **THEN** SHOULD 使用 `bounded_future_hint`

## Forward Guidance Schema

### Requirement: Forward Guidance 固定结构

系统 SHALL 为 `bounded_future_hint` 模式定义稳定的 `forward_guidance` JSON schema。

#### Scenario: Forward Guidance Frozen Fields
- **WHEN** 一个 sample 提供 `forward_guidance`
- **THEN** 其结构至少包含如下字段或等价字段：

```json
{
  "guidance_version": "v1",
  "segment_objective": "string",
  "required_emotional_direction": "string",
  "must_preserve_tension": true,
  "must_not_reveal": [
    "身份真相",
    "幕后势力",
    "感情明确表白"
  ],
  "next_turn_hint": "string",
  "allowed_future_scope": {
    "hint_level": "low | medium",
    "max_future_segments": 1
  },
  "continuity_watch_items": [
    "敌友关系不能混淆",
    "能力代价不能消失"
  ],
  "forbidden_shortcuts": [
    "禁止直接和解",
    "禁止无铺垫跳转到大战结束"
  ],
  "target_length_chars": 1500
}
```

#### Scenario: Forward Guidance 语义边界
- **WHEN** 系统使用 `forward_guidance`
- **THEN** 各字段最小语义为：
  - `segment_objective`: 当前段必须完成的局部叙事目标
  - `required_emotional_direction`: 当前段情绪走势
  - `must_preserve_tension`: 是否必须保留压力与悬念
  - `must_not_reveal`: 当前段不得提前揭露的信息
  - `next_turn_hint`: 下一转折的抽象导向
  - `allowed_future_scope`: 向前引用范围上限
  - `continuity_watch_items`: 当前段最容易写错的连续性项
  - `forbidden_shortcuts`: 禁止偷渡剧情的捷径
  - `target_length_chars`: 当前段目标长度

#### Scenario: Forward Guidance 约束
- **WHEN** 系统构造 `forward_guidance`
- **THEN** `next_turn_hint` SHOULD 保持抽象
- **AND** `allowed_future_scope.max_future_segments` SHOULD 保持在 `1-2`
- **AND** 不应直接给出完整后文事件序列

## Benchmark Runtime

### Requirement: 固定运行流程

系统 SHALL 为单样本运行提供稳定流程。

#### Scenario: 单样本运行顺序
- **WHEN** 系统执行一个 benchmark sample
- **THEN** SHOULD 按如下顺序运行：
  1. 读取 sample config
  2. 按 mode 裁剪授权输入边界
  3. 基于前缀 `documents` 构建或加载创作知识库与 Memory
  4. 组装 `recent_window`
  5. 读取 `current_unit_plan` 与可选 `forward_guidance`
  6. 派生 contract 兼容的 `SceneBrief`
  7. 执行桥段检索与事实上下文装配
  8. 组装 contract 兼容的 `WriterInputBundle`
  9. 生成 draft
  10. 执行自动评分
  11. 保存运行产物

#### Scenario: 产物落盘
- **WHEN** 系统完成一次 benchmark run
- **THEN** SHOULD 至少保存：
  - `sample_config.json`
  - `authorized_inputs.json`
  - `retrieval_bundle.json`
  - `scene_plan.json`
  - `draft.md`
  - `auto_score_report.json`
  - `continuity_report.json`
  - `judge_notes.json`

## Auto Scoring

### Requirement: 自动评分目标

系统 SHALL 将自动评分定义为“硬门槛 + 分项评分 + 综合结论”。

#### Scenario: 自动评分关注点
- **WHEN** 系统执行自动评分
- **THEN** 重点判断：
  - 是否违反已知事实
  - 是否完成当前授权目标
  - 是否承接最近窗口
  - 是否遵守 `forward_guidance`

### Requirement: Auto Score Report

系统 SHALL 输出稳定的 `auto_score_report`。

#### Scenario: Auto Score Report Frozen Fields
- **WHEN** 系统完成自动评分
- **THEN** 应输出如下结构或等价结构：

```json
{
  "sample_id": "string",
  "mode": "chapter_authorized",
  "hard_gate": {
    "passed": true,
    "fatal_issues": []
  },
  "scores": {
    "hard_consistency": 0.94,
    "recent_window_coherence": 0.88,
    "chapter_outline_fulfillment": 0.91,
    "forward_guidance_adherence": 1.0,
    "character_consistency": 0.90,
    "relationship_transition_legality": 0.93,
    "world_rule_compliance": 0.96,
    "style_alignment": 0.76,
    "retrieval_effectiveness": 0.72
  },
  "weighted_score": 0.88,
  "decision": "pass | borderline | fail",
  "explanations": [
    {
      "metric": "recent_window_coherence",
      "summary": "未解决冲突线得到延续，但一处敌友称谓存在轻微歧义"
    }
  ],
  "evidence_refs": [
    {
      "type": "chapter_summary",
      "ref": "string"
    }
  ]
}
```

## Hard Gate Metrics

### Requirement: Hard Consistency

系统 SHALL 将重大事实冲突视为硬失败。

#### Scenario: Hard Gate 覆盖范围
- **WHEN** 系统执行 `hard_consistency`
- **THEN** 至少检查：
  - 人物身份是否错乱
  - 敌友关系是否无因跳变
  - 时间顺序是否倒置
  - 地点连续性是否被破坏
  - 世界规则或能力代价是否被无依据改写
  - 未授权设定是否被引入

#### Scenario: Hard Gate 失败处理
- **WHEN** 出现重大事实冲突
- **THEN** `hard_gate.passed` SHALL 为 `false`
- **AND** `decision` SHOULD 直接为 `fail`

## Scored Metrics

### Requirement: Recent Window Coherence

系统 SHALL 评估生成结果与最近 `m` 章窗口的一致性。

#### Scenario: Recent Window Coherence 定义
- **WHEN** 计算 `recent_window_coherence`
- **THEN** 至少评估：
  - 最近章节未解决冲突是否被承接
  - 角色当前立场是否延续
  - 当前行动是否符合前一阶段动机
  - 近期情绪余波是否被保留

### Requirement: Chapter Outline Fulfillment

系统 SHALL 在存在当前章节授权纲要时评估章节目标完成度。

#### Scenario: Chapter Outline Fulfillment 定义
- **WHEN** sample mode 为 `chapter_authorized` 或 `bounded_future_hint`
- **THEN** 至少评估：
  - 是否完成指定叙事目标
  - 是否承接指定情绪目标
  - 是否推进指定冲突目标
  - 是否遵守必须避免项

### Requirement: Forward Guidance Adherence

系统 SHALL 在 `bounded_future_hint` 模式下单独评估 `forward_guidance` 服从度。

#### Scenario: Forward Guidance Adherence 定义
- **WHEN** sample 提供 `forward_guidance`
- **THEN** 至少评估：
  - 是否完成 `segment_objective`
  - 是否遵守 `must_not_reveal`
  - 是否维持 `must_preserve_tension`
  - 是否没有使用 `forbidden_shortcuts`
  - 是否只在允许范围内引用局部未来导向

### Requirement: Character Consistency

系统 SHALL 评估主要人物是否保持既有人设与行为风格。

#### Scenario: Character Consistency 定义
- **WHEN** 计算 `character_consistency`
- **THEN** 至少评估：
  - 对白是否符合角色气质
  - 决策是否符合已知动机
  - 心理与行为是否与近章状态兼容
  - 是否出现无铺垫的人格失真

### Requirement: Relationship Transition Legality

系统 SHALL 评估人物关系变化是否合法。

#### Scenario: Relationship Transition Legality 定义
- **WHEN** 生成内容涉及重要关系推进
- **THEN** 至少评估：
  - 当前关系状态识别是否正确
  - 目标变化是否在合法步长内
  - 是否存在必要桥接事件
  - 是否发生无铺垫的突然和解、表白、决裂或背叛

### Requirement: World Rule Compliance

系统 SHALL 评估生成内容是否符合世界观规则。

#### Scenario: World Rule Compliance 定义
- **WHEN** 计算 `world_rule_compliance`
- **THEN** 至少评估：
  - 设定规则是否被遵守
  - 能力使用是否符合代价与限制
  - 阵营、组织、地理与历史信息是否自洽
  - 是否引入未授权规则捷径

### Requirement: Style Alignment

系统 SHALL 以结构特征而非字面重合评估风格一致性。

#### Scenario: Style Alignment 定义
- **WHEN** 计算 `style_alignment`
- **THEN** SHOULD 优先比较：
  - 句子节奏
  - 对白密度
  - 内心描写密度
  - 情绪表达方式
  - 叙述克制度

### Requirement: Retrieval Effectiveness

系统 SHALL 单独评估创作知识库检索是否真正帮助写作。

#### Scenario: Retrieval Effectiveness 定义
- **WHEN** 计算 `retrieval_effectiveness`
- **THEN** 至少评估：
  - 被选参考片段是否匹配当前叙事功能
  - 参考片段是否帮助维持风格或桥段组织
  - 检索结果是否避免同簇重复占位
  - 写作是否实际使用了高分候选提供的有效特征

## Scoring Decision Rules

### Requirement: 综合决策规则

系统 SHALL 提供统一决策门槛。

#### Scenario: Pass
- **WHEN** `hard_gate.passed = true`
- **AND** `weighted_score >= 0.80`
- **THEN** `decision` SHOULD 为 `pass`

#### Scenario: Borderline
- **WHEN** `hard_gate.passed = true`
- **AND** `weighted_score >= 0.65`
- **AND** `weighted_score < 0.80`
- **THEN** `decision` SHOULD 为 `borderline`

#### Scenario: Fail
- **WHEN** `hard_gate.passed = false`
- **OR** `weighted_score < 0.65`
- **THEN** `decision` SHOULD 为 `fail`

#### Scenario: 指标缺失
- **WHEN** 某项评分因输入不足无法计算
- **THEN** 系统必须显式标记 `insufficient_evidence`

## Recommended Weighting

第一阶段推荐如下默认权重：

```json
{
  "recent_window_coherence": 0.20,
  "chapter_outline_fulfillment": 0.18,
  "forward_guidance_adherence": 0.10,
  "character_consistency": 0.16,
  "relationship_transition_legality": 0.12,
  "world_rule_compliance": 0.12,
  "style_alignment": 0.07,
  "retrieval_effectiveness": 0.05
}
```

说明：

- `hard_consistency` 属于门槛项，不纳入加权平均
- 在 `blind_prefix` 模式下，`chapter_outline_fulfillment` 与 `forward_guidance_adherence` 可标记为 `not_applicable`
- 在 `chapter_authorized` 模式下，`forward_guidance_adherence` 应为 `not_applicable`

## Ablation Expectations

### Requirement: Ablation Benchmark

系统 SHALL 支持关键输入源消融实验。

#### Scenario: 基础消融
- **WHEN** 团队需要判断系统质量来源
- **THEN** SHOULD 至少比较：
  - 完整输入
  - 去掉创作知识库
  - 去掉 Memory
  - 去掉章节授权纲要
  - 去掉 `forward_guidance`

## Human Evaluation

### Requirement: 自动评分之后的人审入口

系统 SHALL 保留人工评审接口。

#### Scenario: 人工复核
- **WHEN** 样本 `decision = borderline`
- **OR** 样本属于高潮、关系跃迁、重大设定揭示场景
- **THEN** SHOULD 进入人工复核
- **AND** 人工重点检查：
  - 是否像同一本书的自然后继
  - 是否存在模型 judge 难以发现的微妙 OOC
  - 是否在文风上过于模板化

## Success Criteria

- `chapter_authorized` 模式下，系统能稳定通过硬门槛，并在多数样本上达到 `pass`
- `bounded_future_hint` 模式下，系统能在长场景拆段时显著降低连续性错误
- 自动评分能稳定抓出敌友关系混淆、关系跳变、设定越界等高价值错误
- 消融结果能明确区分创作知识库、Memory 与规划信息的贡献
- benchmark 结果能直接指导检索、规划、写作与校验优化
