# Tasks

## Reading Rules

- 产品级流程、入口类型与用户可见状态文案，以 [`../spec.md`](../spec.md) 为准。
- 当前实现以 [`spec.md`](spec.md) 的 MVP Smoke Benchmark 与长文本 Writer-only Cached Benchmark 为准。
- 实现设计以 [`design.md`](design.md) 的 MVP-0、`longzu_96kb` / `longzu_120kb` cache 设计，以及 `Outline Research Author Brief Reconstruction Smoke` 为准。
- `SingleSampleSmokeRunner` 只作为旧 `--sample --db` 兼容路径保留，不再扩展为新的 agentic runner。

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

- [ ] 第一次运行 120KB benchmark 时用 `--prefix-min-chars 30000 --reference-min-chars 10000 --rebuild-modeling-cache` 建立真实 cache。
- [ ] 后续 120KB writer 层回归用 `--prefix-min-chars 30000 --reference-min-chars 10000 --reuse-modeling-cache`。
- [ ] 连续三章回归用同一组参数并加 `--sequence-chapter-count 3 --reuse-modeling-cache`。
- [ ] 每隔数次回归用 `--clear-modeling-cache` 或 `--rebuild-modeling-cache` 重新验证 close-read / Creative KB。
- [ ] 第一次运行 240KB author brief smoke 时用 `--outline-research-author-brief --rebuild-modeling-cache` 建立 prefix / future reference cache。
- [ ] 后续 Outline Research Loop 回归用 `--outline-research-author-brief --reuse-modeling-cache`，但每次都真实重跑 Writer research loop 和 Reviewer。
- [ ] BTree Memory Query 开发完成后，运行 OR-12 的真实模型 API smoke 命令作为最终验收；fake facade 通过只能说明协议测试通过，不能说明任务彻底完成。
