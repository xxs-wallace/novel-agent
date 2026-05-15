# Tasks

## Reading Rules

- 产品级流程、入口类型与用户可见状态文案，以 [`../spec.md`](../spec.md) 为准。
- 当前实现以 [`spec.md`](spec.md) 的 MVP Smoke Benchmark 与长文本 Writer-only Cached Benchmark 为准。
- 实现设计以 [`design.md`](design.md) 的 MVP-0、`longzu_96kb` / `longzu_120kb` cache 设计，以及 `Outline Research Author Brief Reconstruction Smoke` 为准。
- `SingleSampleSmokeRunner` 只作为旧 `--sample --db` 兼容路径保留，不再扩展为新的 agentic runner。

## Current Baseline

已完成并保留：

- `longzu_32kb.txt` 真实 LLM smoke fixture。
- `AgenticSmokeBenchmarkService` canonical agentic path。
- prefix source 切分、真实 rough-read / close-read / Creative KB。
- reference truth close-read -> `reference_story_synopsis.json`。
- close-read artifacts -> `benchmark_story_outline.json` / `writer_planning_input.json`。
- Writer planning workflow -> `generated_story_synopsis.json`。
- close-read reference synopsis -> Writer execution input -> `expansion/draft.md`。
- SynopsisReviewer / ExpansionReviewer / combined `reviewer_report.json`。
- Writer expansion 复用正式 Writer execution interface。
- `SingleSampleSmokeRunner` 旧兼容路径。

已删除的过期任务：

- synthetic DB / offline deterministic smoke 作为 agentic benchmark 目标。
- benchmark-owned synopsis / expansion parallel prompt builder。
- 过早的多 split dataset / manifest / ablation / 多头专项 Reviewer 任务矩阵。
- 已与当前分层 Writer benchmark 冲突的旧 `forward_guidance` MVP 分解。

## Active Tasks

- [x] 固化 `novel_agent/tests/longzu_96kb.txt`
  - [x] 从 `/Users/luliao/longzu.txt` 截取 96KB 以内内容。
  - [x] 回退到最后一个换行符，确保 UTF-8 与完整行。
  - [x] 增加 fixture 稳定性单测。

- [x] 固化 `novel_agent/tests/longzu_120kb.txt`
  - [x] 从 `/Users/luliao/longzu.txt` 截取 120KB 以内内容。
  - [x] 回退到最后一个换行符，确保 UTF-8 与完整行。
  - [x] 增加 fixture 稳定性和长 reference window 单测。

- [x] 扩展 `AgenticSmokeBenchmarkService` 支持 modeling cache
  - [x] cache key 纳入 source/window hash、prefix 参数、pipeline sizing 参数和 schema version。
  - [x] cache miss / rebuild 时运行真实 rough-read、close-read、Creative KB、reference close-read。
  - [x] cache hit 时复用 prefix DB、story context、reference close-read、reference synopsis、benchmark story outline 与 writer planning input。
  - [x] cache hit 后仍重新运行 Writer planning、expansion 与分层 Reviewer。
  - [x] 支持 clear / rebuild 当前 cache entry。

- [x] 扩展 `run_single_sample_smoke.py`
  - [x] 增加 `--prefix-count`、`--prefix-min-chars`、`--recent-window-size`。
  - [x] 增加 `--reference-min-chars`，让长文本 benchmark 能选择连续多个 held-out document/chunk。
  - [x] 增加 `--benchmark-cache-dir`、`--reuse-modeling-cache`、`--rebuild-modeling-cache`、`--clear-modeling-cache`。
  - [x] 增加 pipeline sizing 参数：`--max-read-kb`、`--max-close-batches`、`--segment-step-kb`、`--close-step-batches`。

- [x] 调整长文本 Expansion 输入
  - [x] `reference_story_synopsis.json` 保留连续 `document_synopses`。
  - [x] `expansion/writer_execution_input.json` 将 `document_synopses` 写入 `chapter_brief.reference_document_synopses`。
  - [x] Writer execution prompt 明确要求按 `order` 合并扩写连续 document 梗概。

- [x] 支持连续多章 smoke
  - [x] 增加 `--sequence-chapter-count`。
  - [x] 将 held-out reference close-read summaries 按顺序切分为多个章节目标。
  - [x] 每章重新运行 Writer planning，generated synopsis 仅用于 Reviewer。
  - [x] 每章 expansion 使用 close-read reference synopsis 覆盖 Freeze D。
  - [x] 每章正文走 Writer `execute_current_chapter`，通过后执行 acceptance/writeback。
  - [x] 下一章从写回后的 writer DB 重新读取最近上下文。

- [x] 更新文档
  - [x] `spec.md` 记录 `longzu_96kb` 与 Writer-only cached benchmark 规则。
  - [x] `design.md` 记录 cache 边界、命令示例与不绕过 Writer 层的约束。
  - [x] 压缩 `tasks.md`，移除已失效的旧任务矩阵。

## Outline Research Author Brief Reconstruction Smoke

- [ ] Task OR-1: 固化 `novel_agent/tests/longzu_240kb.txt`
  - `来源`: [`design.md`](design.md) 的 `Longer Fixtures and Modeling Cache`、`Outline Research Author Brief Reconstruction Smoke`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/designs/outline-research-loop.design.md`](../writer-agent-layered-generation/designs/outline-research-loop.design.md)
  - `建议只关注代码文件`: `novel_agent/tests/`, `novel_agent/tests/test_smoke_benchmark_service.py`
  - [ ] 从 `/Users/luliao/longzu.txt` 截取 240KB 以内内容。
  - [ ] 回退到最后一个换行符，确保 UTF-8 完整且不截断半行。
  - [ ] 增加 fixture 稳定性测试，断言文件存在、大小上限、换行结尾和可切分为前 120KB / 后 120KB。
  - [ ] 不要把 240KB fixture 放入默认快速 smoke；只用于显式开启的真实模型 benchmark。

- [ ] Task OR-2: 实现 240KB author brief 窗口切分与缓存键
  - `来源`: [`design.md`](design.md) 的 `Input Boundary`、`Modeling Cache`
  - `建议只读`: [`design.md`](design.md)
  - `建议只关注代码文件`: `novel_agent/app/run_single_sample_smoke.py`, `novel_agent/app/benchmarks/`, `novel_agent/tests/test_smoke_benchmark_service.py`
  - [ ] 扩展 benchmark window adapter，使 `--outline-research-author-brief` 使用 `prefix_120kb + future_120kb` 的固定语义。
  - [ ] cache key 纳入 source hash、`prefix_chars=120KB`、`future_chars=120KB`、rough-read / close-read 参数、Creative KB 参数、author brief summarizer prompt version。
  - [ ] cache 结构区分 `prefix_modeling_cache` 与 `future_reference_cache`。
  - [ ] cache hit 后仍强制重跑 Writer Outline Research Loop、CharacterMentionResolution、generated outline 和 OutlineResearchReviewer。
  - [ ] 测试覆盖 cache key 稳定性、cache hit / rebuild / clear，以及不会把 future reference cache 传给 Writer。

- [ ] Task OR-3: 构建 prefix modeling snapshot 与历史大纲索引导出
  - `来源`: [`design.md`](design.md) 的 `prefix_120kb` 流程
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/designs/outline-research-loop.design.md`](../writer-agent-layered-generation/designs/outline-research-loop.design.md), [`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/benchmarks/`, `novel_agent/app/runner/close_read_runner.py`, `novel_agent/app/services/outline_service.py`, `novel_agent/tests/test_smoke_benchmark_service.py`
  - [ ] 对前 120KB 执行真实 rough-read、close-read、Creative KB / Memory 建模。
  - [ ] 保存 `prefix_modeling_snapshot.json`，包含 prefix story outline、人物快照、世界观摘要和可追踪来源。
  - [ ] 导出 `chapter_summary_index.json` 与 `historical_outline_event_index.json`，供 Writer Context Broker 查询。
  - [ ] 明确这些 prefix artifacts 是 `prefix_facts`，可以进入 Writer research。
  - [ ] 测试覆盖 artifact 落盘、source 引用完整性，以及不读取 future_120kb。

- [ ] Task OR-4: 构建 future reference cache 与 500-1000 字 `user_story_overview`
  - `来源`: [`design.md`](design.md) 的 `future_120kb` 流程、`Input Boundary`
  - `建议只读`: [`design.md`](design.md)
  - `建议只关注代码文件`: `novel_agent/app/benchmarks/`, `novel_agent/tests/test_smoke_benchmark_service.py`
  - [ ] 对后 120KB 执行真实 close-read，保存 `future_source.txt` 与 `future_close_read` 审计信息。
  - [ ] 从 future close-read 分章梗概生成 `reference_future_outline.json`，仅供 Reviewer 使用。
  - [ ] 将 future close-read 分章梗概浓缩为 500-1000 字 `user_story_overview.txt`，作为 `authorized_user_input` 传给 Writer。
  - [ ] 保存 summarizer prompt / 参数版本，纳入 cache key。
  - [ ] 测试覆盖 `user_story_overview` 长度、来源、可重复落盘，以及 detailed reference outline 不进入 Writer 输入。

- [ ] Task OR-5: 构建 `reference_character_set.json`
  - `来源`: [`design.md`](design.md) 的 `Character Evaluation`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md)
  - `建议只关注代码文件`: `novel_agent/app/benchmarks/`, `novel_agent/app/services/`, `novel_agent/tests/test_smoke_benchmark_service.py`
  - [ ] 从 prefix_120kb 与 future_120kb close-read artifacts 中抽取人物集合。
  - [ ] 将人物区分为 `existing_characters` 与 `new_characters`。
  - [ ] 每个人物记录 prefix / future evidence source ids。
  - [ ] 该 reference set 只能进入 Reviewer 和 leakage audit，不能进入 Writer research prompt、Context Broker 或 resolver。
  - [ ] 测试覆盖已有角色、新角色、同名/别名边界和 reference-only 输入隔离。

- [x] Task OR-6: 将 Author Brief smoke 接入正式 Writer Outline Research Loop
  - `来源`: [`design.md`](design.md) 的 `Writer smoke`、[`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md), [`../writer-agent-layered-generation/designs/outline-research-loop.design.md`](../writer-agent-layered-generation/designs/outline-research-loop.design.md)
  - `建议只关注代码文件`: `novel_agent/app/benchmarks/`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/test_smoke_benchmark_service.py`, `novel_agent/tests/test_writer_outline_research.py`
  - [x] 使用 `user_story_overview.txt` 和 prefix modeling snapshot 构造 Writer 输入。
  - [x] 通过正式 Writer Outline Research Loop 生成 `outline_seed_packet.json`、`extracted_character_mentions.json`、`character_resolution.json`、`outline_research_trace.json`、`planning_notebook.json`、`sufficiency_decision.json`、`generated_outline.json`。
  - [x] 不得在 benchmark service 中另写一套大纲生成 prompt。
  - [x] 如果 Writer 返回 `needs_user_input`，benchmark 记录 blocking gaps；若没有 scripted answer，不伪造用户答案。
  - [x] 如果 Writer 返回 `proceed_with_assumptions`，Reviewer 必须能看到 assumptions。
  - [x] 测试覆盖正常完成、needs_user_input、blocked、proceed_with_assumptions 四种路径的 artifact 落盘。

- [x] Task OR-7: 实现 `OutlineResearchReviewer`
  - `来源`: [`design.md`](design.md) 的 `OutlineResearchReviewer`
  - `建议只读`: [`design.md`](design.md)
  - `建议只关注代码文件`: `novel_agent/app/benchmarks/`, `novel_agent/tests/test_smoke_benchmark_service.py`
  - [x] 新增 JSON-only Reviewer prompt，读取 prefix story outline、user_story_overview、research trace、planning notebook、generated outline、reference future outline、reference character set。
  - [x] 输出 decision、score、summary、checks、scores、major_failures。
  - [x] 分项覆盖 outline_similarity、plot_node_coverage、character_extraction、existing_character_resolution、new_character_detection、research_tool_usefulness、leakage_boundary。
  - [x] Reviewer 可以读取 reference-only 材料，但不得反馈给 Writer。
  - [x] 默认单元测试使用 fake reviewer；真实 LLM reviewer 只在显式 smoke 中启用。

- [x] Task OR-8: 增加 leakage audit 与 reference-only 防线
  - `来源`: [`design.md`](design.md) 的 `Input Boundary`、`Artifacts`
  - `建议只读`: [`design.md`](design.md)
  - `建议只关注代码文件`: `novel_agent/app/benchmarks/`, `novel_agent/tests/test_smoke_benchmark_service.py`
  - [x] 保存 `leakage_audit.json`，记录每类输入属于 prefix_facts、authorized_user_input 还是 reference_only。
  - [x] 断言 Writer 输入、OutlineSeedPacket、Context Broker 请求和 planning notebook 不包含 future detailed outline、reference character set 或 future raw text。
  - [x] 若 audit 发现 reference-only 材料进入 Writer 阶段，benchmark 必须失败。
  - [x] 测试覆盖正常隔离、故意注入 reference-only 的失败路径。

- [x] Task OR-9: 扩展 CLI / script 入口
  - `来源`: [`design.md`](design.md) 的 `Entrypoints`
  - `建议只读`: [`design.md`](design.md), [`../cli-interface/design.md`](../cli-interface/design.md)
  - `建议只关注代码文件`: `novel_agent/app/run_single_sample_smoke.py`, `novel_agent/app/cli/`, `novel_agent/tests/test_cli_interface.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] `run_single_sample_smoke.py` 支持 `--enable-outline-research-loop`。
  - [x] `run_single_sample_smoke.py` 支持 `--outline-research-author-brief`。
  - [x] CLI / TUI 支持 `/benchmark longzu-240kb --outline-research --author-brief`。
  - [x] 命令解析必须要求显式真实模型授权，不得默认触发真实 LLM。
  - [x] 输出 summary 时展示 OutlineResearchReviewer 分数、artifact 路径和 leakage audit 结果。
  - [x] 测试覆盖参数解析、dry-run / fake facade、错误提示和结果回流。

- [x] Task OR-10: 增加显式开启的真实 LLM smoke 验收
  - `来源`: [`design.md`](design.md) 的 `Entrypoints`
  - `建议只读`: [`design.md`](design.md), [`../cli-interface/tasks.md`](../cli-interface/tasks.md) 的真实 LLM 慢速 smoke 规则
  - `建议只关注代码文件`: `novel_agent/tests/test_smoke_benchmark_service.py`, `novel_agent/tests/test_cli_textual_components.py`
  - [x] 增加 `real_llm_outline_research` marker 或环境变量开关，默认 CI / 本地单元测试跳过。
  - [x] 提供真实命令示例：
    `PYTHONUNBUFFERED=1 .venv/bin/python -m novel_agent.app.run_single_sample_smoke --source novel_agent/tests/longzu_240kb.txt --runs-dir runs/benchmarks/outline_research_longzu_240kb --use-real-model --api-key "$DEEPSEEK_API_KEY" --prefix-min-chars 120000 --reference-min-chars 120000 --max-read-kb 240 --max-close-batches 48 --enable-outline-research-loop --outline-research-author-brief --reuse-modeling-cache`
  - [x] smoke 完成后必须保存 `outline_research_author_brief/summary.json`。
  - [x] 若真实模型返回 needs_user_input / blocked，也应算作流程可观测完成，但 summary 必须标记不能生成正式大纲的原因。
  - [x] 最终报告展示 artifact_dir、Reviewer summary、主要失败项和下一步建议。

- [ ] Task OR-11: 将 Author Brief smoke 升级为 BTree Memory Query 多轮研究
  - `来源`: [`design.md`](design.md) 的 `Multi-round Memory Query`、[`../writer-agent-layered-generation/designs/outline-research-loop.design.md`](../writer-agent-layered-generation/designs/outline-research-loop.design.md)
  - `建议只读`: [`design.md`](design.md), [`../narrative-memory-context/design.md`](../narrative-memory-context/design.md), [`../writer-agent-layered-generation/tasks.md`](../writer-agent-layered-generation/tasks.md)
  - `建议只关注代码文件`: `novel_agent/app/benchmarks/`, `novel_agent/app/run_single_sample_smoke.py`, `novel_agent/app/orchestrators/writer_layered_generation.py`, `novel_agent/tests/test_smoke_benchmark_service.py`
  - [ ] Author Brief smoke 继续遮住后 120KB reference window，不改变评分目标
  - [ ] Writer 输入仍只来自 `user_story_overview.txt`、prefix modeling snapshot 和授权 prefix Memory
  - [ ] Outline Research Loop MUST 通过 `NarrativeMemoryQueryService` 多轮查询 prefix Memory
  - [ ] benchmark artifacts MUST 保存 `memory_query_trace.json`、`memory_query_decision_log.json`、`model_reasoning_debug.json`
  - [ ] `leakage_audit.json` MUST 验证 future raw text、reference future outline、reference character set 没有进入 Writer / Context Broker / Memory resolver
  - [ ] summary MUST 标记流程状态、Memory Query 轮数、最终 evidence ids、Reviewer score 和主要失败项
  - [ ] 默认测试使用 fake facade；fake 只能模拟结构化协议，不能作为最终质量验收

- [ ] Task OR-12: 真实模型 API smoke benchmark 作为最终完成标准
  - `来源`: [`design.md`](design.md) 的 `Entrypoints` 与 `Reasoning / Decision Debug Logs`
  - `建议只读`: [`design.md`](design.md), [`../writer-agent-layered-generation/tasks.md`](../writer-agent-layered-generation/tasks.md), [`../narrative-memory-context/tasks.md`](../narrative-memory-context/tasks.md)
  - `建议只关注代码文件`: `novel_agent/app/run_single_sample_smoke.py`, `novel_agent/app/benchmarks/`, `novel_agent/tests/test_smoke_benchmark_service.py`
  - [ ] 真实 smoke 必须显式使用 `--use-real-model` 和真实 API key；默认单元测试不得触发真实 LLM
  - [ ] 真实 smoke MUST 真实调用 Writer model 与 Reviewer model，不得读取、硬编码或伪造模型返回
  - [ ] 若 provider 返回可见 reasoning/debug 字段，保存到 `model_reasoning_debug.json`
  - [ ] 若 provider 不返回可见 reasoning/debug 字段，保存结构化决策轨迹，不得伪造隐藏思维链
  - [ ] 真实 smoke 通过标准包括：流程完成、leakage audit 通过、Reviewer 可读、Memory Query trace 可审计、生成大纲质量达到可接受阈值或失败原因明确
  - [ ] 最终验收命令：
    `PYTHONUNBUFFERED=1 .venv/bin/python -m novel_agent.app.run_single_sample_smoke --source novel_agent/tests/longzu_240kb.txt --runs-dir runs/benchmarks/outline_research_longzu_240kb --use-real-model --api-key "$DEEPSEEK_API_KEY" --prefix-min-chars 120000 --reference-min-chars 120000 --max-read-kb 240 --max-close-batches 48 --enable-outline-research-loop --outline-research-author-brief --reuse-modeling-cache`
  - [ ] 开发 Agent 最终报告必须列出 artifact_dir、summary.json、Reviewer summary、leakage audit 结果、Memory Query trace 摘要和真实 API 调用证据

## Next Verification

- [x] 运行单元测试：`novel_agent/tests/test_smoke_benchmark_service.py`。
- [ ] 第一次运行 120KB benchmark 时用 `--prefix-min-chars 30000 --reference-min-chars 10000 --rebuild-modeling-cache` 建立真实 cache。
- [ ] 后续 120KB writer 层回归用 `--prefix-min-chars 30000 --reference-min-chars 10000 --reuse-modeling-cache`。
- [ ] 连续三章回归用同一组参数并加 `--sequence-chapter-count 3 --reuse-modeling-cache`。
- [ ] 每隔数次回归用 `--clear-modeling-cache` 或 `--rebuild-modeling-cache` 重新验证 close-read / Creative KB。
- [ ] 第一次运行 240KB author brief smoke 时用 `--outline-research-author-brief --rebuild-modeling-cache` 建立 prefix / future reference cache。
- [ ] 后续 Outline Research Loop 回归用 `--outline-research-author-brief --reuse-modeling-cache`，但每次都真实重跑 Writer research loop 和 Reviewer。
- [ ] BTree Memory Query 开发完成后，运行 OR-12 的真实模型 API smoke 命令作为最终验收；fake facade 通过只能说明协议测试通过，不能说明任务彻底完成。
