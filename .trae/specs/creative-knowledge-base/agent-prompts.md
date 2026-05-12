# Creative KB Benchmark Agent Prompts

这些 prompt 用于把 Creative KB Benchmark 的实现拆给其他 Agent 执行。每个 Agent 接手前都应先阅读：

- `.trae/specs/creative-knowledge-base/spec.md`
- `.trae/specs/creative-knowledge-base/design.md`
- `.trae/specs/creative-knowledge-base/tasks.md`
- `novel_agent/app/services/creative_kb_facade.py`
- `novel_agent/app/services/retrieval_facade.py`
- `novel_agent/app/services/smoke_benchmark_service.py`
- `novel_agent/tests/test_creative_kb_facade.py`
- `novel_agent/tests/test_retrieval_facade.py`
- `novel_agent/tests/test_smoke_benchmark_service.py`

通用约束：

- 遵循 OOP 原则和 Pythonic 实现风格。
- 新能力必须补单元测试；真实 LLM smoke 必须通过显式 marker 或环境变量启用，普通单元测试使用 fake LLM / stub Reviewer。
- 不要把 `AgenticSmokeBenchmarkService` 当前默认行为当作 no-KB baseline；它更接近 `kb_enabled`。
- Benchmark 只能编排 `CreativeKnowledgeBaseFacade` 与 `RetrievalFacade`，不得绕过 `fragment_cards` / `fragment_clusters` 直接返回最终参考桥段。
- Reviewer 只评价，不得把 Reviewer 结论回写到 KB 构建、检索或 rerank 输入。
- 产物目录按 `runs/creative_kb_benchmarks/<run_id>/` 组织，关键 JSON 产物需要可复盘。
- 不要重构无关模块，不要修改与本任务无关的行为。

## Prompt 1: Benchmark Service 与 Case 构造

```text
你是负责实现 Creative KB Benchmark 编排入口的 Agent。

目标：
实现 Task 17 和 Task 18：新增 `CreativeKBBenchmarkService` 或等价服务，负责从真实 source / fixture 构造 benchmark run，并生成 `KBBenchmarkCase`。

请先阅读：
- `.trae/specs/creative-knowledge-base/spec.md` 的 Creative KB Benchmark 章节
- `.trae/specs/creative-knowledge-base/design.md` 第 11 章
- `.trae/specs/creative-knowledge-base/tasks.md` Task 17、Task 18
- `novel_agent/app/services/creative_kb_facade.py`
- `novel_agent/app/services/retrieval_facade.py`
- `novel_agent/app/services/smoke_benchmark_service.py`

交付物：
- 新增 benchmark service，建议路径为 `novel_agent/app/services/creative_kb_benchmark_service.py`，若仓库已有更合适模式则遵循现有模式。
- 新增必要 schema，建议集中在 `novel_agent/app/schemas/creative_kb_benchmark_schema.py` 或现有 schema 模块中。
- 服务输入 contract 至少包含：source / fixture、run_id、case_count、artifact_dir、enable_writer_ab、model config、seed。
- 服务输出 contract 至少包含：run_id、artifact_dir、build summary、case summary、retrieval review summary 占位、可选 writer_ab summary 占位。
- 构造 `3-5` 个 `KBBenchmarkCase`，覆盖情绪停顿 / 关系收束、冲突升级 / 行动推进、信息揭示 / 设定承接。
- 保存 `source_prefix.txt`、`reference_truth.txt` 或等价产物、`kb_build_result.json`、`scene_brief_cases.json`。

关键边界：
- 只做 benchmark 编排，不替代 `CreativeKnowledgeBaseFacade` 或 `RetrievalFacade`。
- 若暂时没有真实 Reviewer，可先保留清晰接口和 pending summary，但产物 shape 要稳定。
- 空 KB、空 documents、case 构造失败必须返回可读失败结果，而不是静默成功。

测试要求：
- 增加 `KBBenchmarkCase` 构造测试。
- 增加 artifact shape 测试，验证关键 JSON 可解析。
- 普通测试不要真实请求 LLM；使用 fake pipeline / fake facade。

完成后请在最终回复中列出修改文件、测试命令和仍未接入的下游 Task。
```

## Prompt 2: 建卡与聚类质量 Reviewer

```text
你是负责实现 Creative KB 建库质量 Reviewer 的 Agent。

目标：
实现 Task 19：为 Creative KB Benchmark 增加 fragment card 与 fragment cluster 的抽样评测能力。

请先阅读：
- `.trae/specs/creative-knowledge-base/spec.md` 的“建卡质量评测”和“聚类与代表片段评测”
- `.trae/specs/creative-knowledge-base/design.md` 第 11.1、11.2、11.6、11.8 节
- `.trae/specs/creative-knowledge-base/tasks.md` Task 19
- `novel_agent/app/schemas/creative_kb_schema.py`
- `novel_agent/app/repos/creative_kb_storage.py`

交付物：
- 定义 `KBFragmentCardReviewReport` 与 `KBClusterReviewReport` schema。
- 实现 prompt builder / reviewer service，输入为原始 document excerpt、fragment card、cluster members、representative card、dedup_reason。
- Reviewer 检查 fragment card：忠实度、可检索性、叙事功能、情绪机制、关系事实、风格可迁移性、上下文依赖风险。
- Reviewer 检查 cluster：近重复合理性、误合并风险、representative 选择质量。
- 将建卡 / 聚类 Reviewer report 汇总到顶层 `kb_reviewer_report.json` 的对应字段中。
- 保存 Reviewer prompt 与 report，便于人工复盘。

关键边界：
- Reviewer 只评价，不得修改 card、cluster 或 rerank 输入。
- 抽样逻辑要稳定可复现，支持 seed。
- 如果 KB 样本不足，要给出明确 warning 和降级评分，而不是抛出不可理解异常。

测试要求：
- schema round-trip 测试。
- fake LLM Reviewer 输出解析测试。
- 样本不足时的 warning / fail 或 borderline 行为测试。

完成后请在最终回复中列出修改文件、测试命令和 report JSON 示例字段。
```

## Prompt 3: Retrieval Audit、Decoy 与 KBRetrievalReviewer

```text
你是负责实现 Creative KB 检索 / rerank 主评测层的 Agent。

目标：
实现 Task 20 和 Task 21：为每个 benchmark case 保存 retrieval audit artifacts，构造 decoy references，并通过 `KBRetrievalReviewer` 评价 rerank 质量。

请先阅读：
- `.trae/specs/creative-knowledge-base/spec.md` 的“检索 / rerank 质量评测”和“Creative KB benchmark 通过标准”
- `.trae/specs/creative-knowledge-base/design.md` 第 11.3 到 11.6 节
- `.trae/specs/creative-knowledge-base/tasks.md` Task 20、Task 21
- `novel_agent/app/services/retrieval_facade.py`
- `novel_agent/app/services/coarse_retrieval_service.py`
- `novel_agent/app/repos/creative_kb_storage.py`

交付物：
- 对每个 `KBBenchmarkCase` 调用正式 `RetrievalFacade`，启用 `include_coarse_result=True` 与 `expand_reference_fragments=True` 或等价调试模式。
- 保存：
  - `retrieval_cases/<case_id>/scene_brief.json`
  - `retrieval_cases/<case_id>/coarse_result.json`
  - `retrieval_cases/<case_id>/rerank_result.json`
  - `retrieval_cases/<case_id>/selected_reference_fragments.json`
  - `retrieval_cases/<case_id>/decoy_fragments.json`
  - `retrieval_cases/<case_id>/kb_retrieval_reviewer_prompt.json`
  - `retrieval_cases/<case_id>/kb_retrieval_reviewer_report.json`
- 构造 decoy：`random_decoy`、`same_cluster_decoy`、`tag_similar_decoy`、`high_dependency_decoy`、`rejected_high_score`；不存在时记录原因。
- 定义 `KBRetrievalReviewReport` schema，包含 `decision`、`score`、`summary`、固定 `checks`、`selected_fragment_ids`、`decoy_fragment_ids`、`issues`。
- 固化 checks：
  `top1_beats_decoys`、`selected_fragments_match_scene_brief`、`scene_function_fit`、`emotion_mechanism_fit`、`relationship_state_fit`、`style_reference_value`、`transferability`、`cluster_diversity`、`context_dependency_risk`、`negative_transfer_risk`。
- 聚合多个 case report，生成顶层 `kb_reviewer_report.json`。

关键边界：
- Rerank 质量不是“文学性绝对评分”，Reviewer 必须基于 SceneBrief、selected references、decoy / rejected references 做相对排序判断。
- selected references 与 decoy references 必须能回源到 `fragment_cards` / `fragment_clusters`。
- 空 KB、空 selected references、无法回源 references 直接 fail。

测试要求：
- decoy 构造测试，覆盖每类 decoy 的正常与缺失场景。
- `KBRetrievalReviewer` schema 与 fake LLM 输出解析测试。
- 聚合评分测试：pass / borderline / fail，尤其覆盖 top1 输给 decoy 与高上下文依赖误排。
- artifact shape 测试。

完成后请在最终回复中列出修改文件、测试命令和一个单 case report 的最小 JSON 示例。
```

## Prompt 4: Writer A/B 增益诊断 Variants

```text
你是负责实现 Creative KB Writer A/B 诊断层的 Agent。

目标：
实现 Task 22：复用现有 Writer smoke benchmark 能力，增加显式 KB variants，用于判断 KB references 对 Writer 是否有可观测增益。

请先阅读：
- `.trae/specs/creative-knowledge-base/spec.md` 的“Writer A/B 增益诊断”
- `.trae/specs/creative-knowledge-base/design.md` 第 11.7、11.8 节
- `.trae/specs/creative-knowledge-base/tasks.md` Task 22
- `novel_agent/app/services/smoke_benchmark_service.py`
- `novel_agent/tests/test_smoke_benchmark_service.py`

交付物：
- 在 Creative KB Benchmark 中增加可选 Writer A/B runner 或 adapter。
- 支持 variants：
  - `kb_enabled`: 保持现有 Agentic smoke / Writer 执行中可使用 KB references 的行为。
  - `kb_disabled`: 禁用 KB 构建，或在 Writer execution input 中清空 `style_reference_bundle.references` 与 `selected_fragment_ids`。
  - `kb_random`: 构建 KB，但注入随机 / decoy references，并标记来源。
  - `kb_oracle`: 可选，只作为诊断上限，不进入 canonical pass/fail。
- 保存每个 variant 的 `writer_execution_input.json`、`draft.md`、`reviewer_report.json`。
- 定义 `KBWriterABReport`，包含 `decision`、`score`、`winner`、`variant_scores`、`negative_transfer_issues`。
- 顶层 summary 中只把 Writer A/B 作为诊断字段，不覆盖 retrieval / rerank 主分。

关键边界：
- 当前 `AgenticSmokeBenchmarkService` 默认会构建 KB 并携带 style references，因此它不是 no-KB baseline。
- 不要复制一套新的 Writer 主流程；优先复用现有 window split、prefix close-read、reference synopsis、Writer execution 与 ExpansionReviewer。
- 不要让 `kb_random` 的 references 污染后续 variants；每个 variant 的输入要隔离。

测试要求：
- variant input 构造测试，明确 `kb_enabled`、`kb_disabled`、`kb_random` 的区别。
- 测试当前默认 smoke 路径不会被标记为 `kb_disabled`。
- fake Writer / fake Reviewer 下的 A/B summary 聚合测试。

完成后请在最终回复中列出修改文件、测试命令和每个 variant 的输入差异说明。
```

## Prompt 5: CLI Summary 与验收测试

```text
你是负责把 Creative KB Benchmark 接入 CLI / runner 并补齐验收测试的 Agent。

目标：
实现 Task 23 和 Task 24：让 CLI 能触发 Creative KB Benchmark，并以用户可读 summary 展示结果；补齐关键测试。

请先阅读：
- `.trae/specs/creative-knowledge-base/design.md` 第 11.8、11.9、13 节
- `.trae/specs/creative-knowledge-base/tasks.md` Task 23、Task 24
- `novel_agent/app/cli_tui.py`
- `novel_agent/tests/test_cli_tui_entrypoint.py`
- Creative KB Benchmark service / reviewer / writer A/B 的已实现代码

交付物：
- 提供可被 CLI 调用的 Creative KB benchmark runner。
- CLI summary 至少展示：
  - Creative KB Benchmark 标题
  - 建卡质量 decision / score
  - 检索与 rerank decision / score
  - 主要问题摘要
  - Writer A/B 简述，如果启用
  - artifact_dir
- CLI 只展示结果，不直接生成 Reviewer prompt，不直接修改 KB。
- 失败时展示明确原因：空 KB、空 references、Reviewer 失败、真实 LLM 调用失败、产物写入失败。
- 长耗时真实 LLM benchmark 要有阶段日志或进度事件，便于 TUI 暴露当前阶段。

测试要求：
- CLI entrypoint / runner 参数解析测试。
- summary formatting 测试。
- 空 KB / 空 selected references / 无法回源 references 的失败展示测试。
- artifact shape 测试，校验 `runs/creative_kb_benchmarks/<run_id>/` 下关键文件存在。
- 真实 LLM smoke 使用显式环境变量或 marker，默认测试套件不触发真实请求。

完成后请在最终回复中列出修改文件、测试命令和 CLI 使用示例。
```
