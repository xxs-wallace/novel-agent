# CLI TUI Agentic Smoke 集成测试设计

## 1. 目标

本设计定义一组面向 `novel_agent.app.cli_tui` 的集成冒烟测试，用来回答：

- 用户打开统一 CLI / TUI 后，是否能通过脚本化交互完成基本工作流。
- CLI 是否能从任务创建、原文入库、精读建模、人物档案查询、剧情梗概查询，一路走到 `/benchmark longzu-32kb`。
- CLI 是否把 Agentic benchmark 的分层 Reviewer 结论、分数和关键产物路径展示给用户。
- 这些测试是否能在普通 CI 中稳定运行，不依赖人工反馈、不依赖终端截图识别，也不把普通 PR 测试绑定到真实 LLM 成本与波动上。

本设计不替代 `.trae/specs/agentic-benchmark/design.md` 中定义的真实 LLM Agentic smoke benchmark。  
它只验证 **CLI / TUI 交互外壳、命令路由、facade 调用和用户可见输出** 是否能稳定串起来。

## 2. 相关设计边界

### 2.1 来自 agentic-benchmark 的约束

Agentic benchmark 的 canonical path 是：

```text
longzu_32kb.txt
  -> prefix source 粗读 / segmentation
  -> prefix source 精读 / close-read
  -> Creative KB build
  -> Writer planning workflow
  -> Writer ChapterBrief -> generated_story_synopsis.json
  -> held-out reference truth -> reference_story_synopsis.json
  -> SynopsisReviewer
  -> Writer prepare_execution / execute_frozen_chapter
  -> expansion/draft.md
  -> ExpansionReviewer
  -> reviewer_report.json
  -> CLI summary
```

该真实链路必须使用真实 LLM，不得用 synthetic DB、fake sample 或 deterministic fallback 伪装端到端 benchmark 成功。

### 2.2 来自 cli-interface 的约束

统一 CLI / TUI 是正式用户入口。CLI 层职责是：

- 解析 slash command。
- 调用 `WorkflowFacade` 或等价 facade。
- 展示运行进度、artifact 摘要、状态侧栏、错误恢复建议和 Reviewer summary。

CLI 层不得：

- 直接拼 Writer prompt。
- 直接生成故事梗概或正文。
- 直接运行 Reviewer prompt。
- 绕过 facade / workflow 写业务状态。

因此，CLI 集成冒烟测试的断言重点应放在 **交互是否可达、命令是否调用正确 facade、输出是否包含用户需要的信息**。

## 3. 测试分层

### 3.1 普通 CI：Textual scripted smoke

普通 CI 运行一条稳定、快速、不访问真实 LLM 的 Textual scripted smoke。

该测试使用 Textual 官方 `run_test()` / Pilot 驱动 `TextualNovelAgentApp`，而不是用 `pexpect` 操作全屏终端。原因：

- Textual `run_test()` 可以直接访问 widget、消息流和 app 状态，避免 ANSI 控制序列导致的脆弱断言。
- 可以稳定发送 `Enter`、`Shift+Enter`、输入 slash command、等待 worker 完成。
- 可以注入 facade test double，验证 CLI 和 facade 边界，而不把模型调用放进普通 CI。

该测试不是 Agentic benchmark 的真实质量评测，不声称模型通过了 60 分目标。

### 3.2 Nightly / Release：真实 LLM CLI smoke

真实 LLM Agentic benchmark 应作为 env-gated 测试或 release 前手动/自动验收运行。

触发条件建议：

```text
DEEPSEEK_API_KEY 存在
RUN_REAL_AGENTIC_SMOKE=1
```

真实测试可以走：

```text
python -m novel_agent.app.run_single_sample_smoke --source novel_agent/tests/longzu_32kb.txt --runs-dir runs/benchmarks/longzu_32kb --use-real-model --api-key "$DEEPSEEK_API_KEY"
```

也可以后续扩展为 CLI/TUI 的 `/benchmark longzu-32kb` 黑盒脚本测试，但不应作为普通 PR 必跑。

## 4. 普通 CI scripted smoke 场景

### 4.1 测试名称

建议新增测试：

```text
test_cli_tui_agentic_smoke_script_covers_read_close_read_queries_and_benchmark
```

可放置在：

```text
novel_agent/tests/test_cli_tui_agentic_smoke.py
```

或并入现有：

```text
novel_agent/tests/test_cli_textual_components.py
```

考虑到该测试语义横跨 read pipeline、close-read query 和 benchmark，建议单独建文件。

### 4.2 测试入口

测试实例化：

```text
TextualNovelAgentApp(repo_root=tmp_path, session=TuiApp(..., facade=CliTuiAgenticSmokeFacadeDouble))
```

然后使用：

```text
async with app.run_test(size=(120, 40)) as pilot:
    ...
```

测试通过 `PromptInput` 写入命令并按 `Enter`，优先模拟用户真实路径，而不是直接调用 `screen.handle_command()`。

### 4.3 命令 transcript

推荐 transcript：

```text
/new-task longzu-cli-smoke novel_agent/tests/longzu_32kb.txt
/read novel_agent/tests/longzu_32kb.txt
/close-read --batches 1
/query character 路明非
/query summary total
/benchmark longzu-32kb
```

可选补充：

```text
/tasks
/status
```

### 4.4 必须验证的用户可见行为

测试应断言消息流中出现：

- 任务创建成功：`已创建并进入任务 longzu-cli-smoke`
- 原文入库进度：`正在运行粗读/精读` 或 `粗读/精读本轮已完成`
- 精读进度：`本轮 /close-read 将处理最多 1 个精读 batch`
- 人物档案：`# 人物档案：longzu-cli-smoke` 和 `路明非`
- 剧情梗概总览：`# 当前精读总览：longzu-cli-smoke`
- benchmark 启动：`正在运行MVP smoke benchmark`
- benchmark 完成：`MVP smoke benchmark本轮已完成`
- 分层 Reviewer summary：
  - `梗概层 Reviewer`
  - `扩写层 Reviewer`
  - `综合 Reviewer`
- 关键产物路径：
  - `generated_story_synopsis.json`
  - `reference_story_synopsis.json`
  - `expansion/draft.md`
  - `reviewer_report.json`
  - `summary.json`

同时应断言：

- prompt 提交后被清空。
- 后台事件不会覆盖输入区。
- `/benchmark` 调用的是 facade，不在 CLI 层直接生成正文。
- fake facade 记录的调用序列至少包含：

```text
ensure_task
start_read_pipeline
start_read_pipeline(close_only=True)
query_close_read(character)
query_close_read(summary total)
run_smoke_benchmark(target=longzu-32kb)
```

## 5. Facade Test Double 设计

### 5.1 设计原则

普通 CI 的 test double 只模拟 facade 返回值和最小可查询产物，不模拟模型能力。

它必须清楚命名为 test double，例如：

```text
CliTuiAgenticSmokeFacadeDouble
```

不得命名为 `AgenticSmokeBenchmarkService` 的真实替代品，也不得进入生产代码路径。

### 5.2 行为要求

`ensure_task(...)`：

- 记录 task id 和 source path。
- 返回 task snapshot，显示 documents、chapters、精读状态。

`start_read_pipeline(..., run_mode="new")`：

- 记录 `book_id`、`source_path`、`db_path`。
- 返回含 `inserted_documents`、`segmentation_batches`、`close_read_batches` 的 payload。
- 可选：在 tmp repo 下写入一个最小 SQLite / memory fixture，供 query 测试使用。

`start_read_pipeline(..., run_mode="resume", max_read_kb=0)`：

- 代表 `/close-read --batches 1`。
- 返回 close-read 完成 payload。
- 产物语义上应包含：
  - 至少 1 个章节梗概。
  - 至少 1 个人物档案。
  - 世界观 / 大纲路径可选。

`query_close_read(..., query_type="character")`：

- 返回 Markdown 人物档案。
- 内容包含 `路明非`，用于证明 CLI 可以展示人物档案。

`query_close_read(..., query_type="summary", summary_scope="total")`：

- 返回 Markdown 剧情梗概总览。
- 内容包含 close-read 总结，例如 `路明非在日常压抑中等待命运转折`。

`run_smoke_benchmark(target="longzu-32kb", use_real_model=True, ...)`：

- 在测试目录下创建或返回一组代表性产物路径：

```text
runs/benchmarks/longzu-cli-smoke-run/
  source_prefix.txt
  reference_truth.txt
  pipeline_result.json
  writer_result.json
  generated_story_synopsis.json
  reference_story_synopsis.json
  synopsis_reviewer_report.json
  expansion/draft.md
  expansion_reviewer_report.json
  reviewer_report.json
  summary.json
```

- 返回 `summary_text`，格式与真实 `WorkflowFacade.run_smoke_benchmark()` 保持一致：

```text
梗概层 Reviewer：...
扩写层 Reviewer：...
综合 Reviewer：...
run_id：...
产物目录：...
生成梗概：...
原文梗概：...
Writer 草稿：...
Reference truth：...
生成字数：...
reference truth 字数：...
```

注意：这里的 `use_real_model=True` 只验证 CLI 是否按当前默认参数传递给 facade。test double 不应真的调用模型。

## 6. 真实 LLM smoke 设计

### 6.1 测试名称

建议新增 env-gated 测试：

```text
test_cli_tui_real_agentic_benchmark_longzu_32kb
```

该测试默认 skip。

### 6.2 触发条件

```text
pytest.mark.skipif(
    not os.getenv("RUN_REAL_AGENTIC_SMOKE") or not os.getenv("DEEPSEEK_API_KEY"),
    reason="requires RUN_REAL_AGENTIC_SMOKE=1 and DEEPSEEK_API_KEY"
)
```

### 6.3 推荐运行方式

第一阶段建议不通过 Textual 全屏交互跑真实 LLM，而是直接验证 canonical runner：

```text
WorkflowFacade(repo_root).run_smoke_benchmark(target="longzu-32kb", api_key=os.getenv("DEEPSEEK_API_KEY"))
```

或者：

```text
python -m novel_agent.app.run_single_sample_smoke ...
```

等普通 CI 的 Textual scripted smoke 稳定后，再增加真正通过 `/benchmark longzu-32kb` 的 TUI real smoke。

### 6.4 必须验证的真实产物

真实 LLM smoke 应断言：

- `source_prefix.txt` 存在且非空。
- `reference_truth.txt` 存在且非空。
- `pipeline_result.json` 存在。
- `generated_story_synopsis.json` 存在。
- `reference_story_synopsis.json` 存在。
- `expansion/draft.md` 存在且非空。
- `synopsis_reviewer_report.json` 存在。
- `expansion_reviewer_report.json` 存在。
- `reviewer_report.json` 存在。
- `summary.json` 存在。
- `reviewer_report.json.decision` 属于 `pass | borderline | fail`。
- `reviewer_report.json.score` 是 `0.0-1.0`。

真实 smoke 不应强制 `score >= 0.60` 作为普通测试硬失败。  
若要作为 release gate，可单独配置阈值。

## 7. 为什么不直接用 pexpect

`pexpect` 可以作为最后一层黑盒测试，但不适合作为主要集成冒烟：

- Textual 是全屏 TUI，会输出 ANSI 控制序列和 alternate screen 内容。
- 焦点、窗口尺寸和刷新时机容易导致 flake。
- 对中文 Rich/Textual 输出做正则断言成本高。
- 失败时很难定位是业务失败、UI 渲染失败还是终端 transcript 解析失败。

因此主测试使用 Textual `run_test()`。  
后续如果要补 `pexpect`，只建议覆盖：

```text
启动 ./novel-agent -> 输入 /help -> 看到 /benchmark -> 退出
```

不要让 `pexpect` 承担真实 benchmark 链路。

## 8. 与现有测试的关系

已有测试已经覆盖：

- `CommandRouter` 能解析 `/benchmark longzu-32kb`。
- `TuiApp.dispatch_command("/benchmark longzu-32kb")` 能渲染 Reviewer summary。
- Textual prompt 能提交、清空并进入消息流。
- fake worker 能覆盖 `/read -> /kb -> /writer` 的最小路径。

本测试补齐的是一条更贴近用户路径的连续 transcript：

```text
创建任务
-> 原文入库
-> close-read
-> 查询人物档案
-> 查询剧情梗概
-> CLI 中执行 Agentic benchmark
-> 查看分层 Reviewer summary 与产物路径
```

它不是单元测试的替代，而是验证这些能力在同一个 Textual session 中不会互相打断。

## 9. 后续实现任务建议

1. 新增 `novel_agent/tests/test_cli_tui_agentic_smoke.py`。
2. 新增测试内专用 `CliTuiAgenticSmokeFacadeDouble`。
3. 编写 helper：`submit_prompt(screen, text, pilot)`，通过 `PromptInput` + `Enter` 模拟用户输入。
4. 覆盖 transcript：
   - `/new-task longzu-cli-smoke novel_agent/tests/longzu_32kb.txt`
   - `/read novel_agent/tests/longzu_32kb.txt`
   - `/close-read --batches 1`
   - `/query character 路明非`
   - `/query summary total`
   - `/benchmark longzu-32kb`
5. 断言消息流、facade 调用序列和 benchmark summary。
6. 增加 env-gated 真实 LLM smoke，但默认 skip。
7. 后续如需黑盒测试，再补极薄的 `pexpect` `/help` smoke。

## 10. 验收标准

普通 CI scripted smoke 通过时，应证明：

- `novel_agent.app.cli_tui` 可以启动 Textual app。
- 用户可以通过输入区提交 slash command。
- 创建任务、入库、精读、查询人物档案、查询剧情梗概、运行 benchmark 这些命令在同一 session 内可连续执行。
- CLI 输出包含 Agentic benchmark 的分层 Reviewer summary 和关键产物路径。
- CLI 交互过程中无需人工选择、无需 Codex 代操作、无需真实 LLM。

真实 LLM smoke 通过时，应证明：

- `longzu_32kb` 的真实粗读、精读、Creative KB、Writer、Reviewer 链路能跑通。
- 关键 benchmark 产物全部落盘。
- CLI 或 runner 能给出可人工复核的 Reviewer 结论。
