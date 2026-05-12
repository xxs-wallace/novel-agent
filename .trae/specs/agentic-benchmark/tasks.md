# Tasks

## Reading Rules

- 产品级流程、入口类型与用户可见状态文案，以 [`../spec.md`](../spec.md) 为准。
- 当前实现以 [`spec.md`](spec.md) 的 MVP Smoke Benchmark 与长文本 Writer-only Cached Benchmark 为准。
- 实现设计以 [`design.md`](design.md) 的 MVP-0 与 `longzu_96kb` cache 设计为准。
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

## Next Verification

- [x] 运行单元测试：`novel_agent/tests/test_smoke_benchmark_service.py`。
- [ ] 第一次运行 120KB benchmark 时用 `--prefix-min-chars 30000 --reference-min-chars 10000 --rebuild-modeling-cache` 建立真实 cache。
- [ ] 后续 120KB writer 层回归用 `--prefix-min-chars 30000 --reference-min-chars 10000 --reuse-modeling-cache`。
- [ ] 连续三章回归用同一组参数并加 `--sequence-chapter-count 3 --reuse-modeling-cache`。
- [ ] 每隔数次回归用 `--clear-modeling-cache` 或 `--rebuild-modeling-cache` 重新验证 close-read / Creative KB。
