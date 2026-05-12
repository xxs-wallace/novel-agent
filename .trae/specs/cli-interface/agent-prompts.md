# CLI TUI Smoke Test Agent Prompt

下面是一条单 Agent 执行 prompt。该任务不计划拆给多个并发 Agent；请在一个独立 git worktree 中完成实现，完成后再由用户合并回当前分支。

```text
你负责继续完善 CLI TUI 冒烟 / 集成测试。

重要执行方式：
- 不要直接在当前主工作区 `/Users/luliao/agent/smolagents` 里实现代码改动。
- 请先基于当前 git 分支创建或切换到一个独立 git worktree，例如 `/Users/luliao/agent/smolagents-cli-tui-smoke`。
- 在新 worktree 中完成代码与测试修改，并在最终回复中汇报 worktree 路径、分支名、修改文件、测试命令和合并建议。
- `.trae` 目录当前没有加入 git 仓库，因此新 worktree 里通常不会有 `.trae` 文档。所有 spec / design / tasks 文档请从主工作区的绝对路径读取，不要假设它们存在于新 worktree。
- 代码文件请在新 worktree 内按仓库相对路径修改，例如 `novel_agent/tests/test_cli_textual_components.py`。

必须先阅读这些文档：
- `/Users/luliao/agent/smolagents/.trae/specs/cli-interface/design.md`
- `/Users/luliao/agent/smolagents/.trae/specs/cli-interface/tasks.md`
- `/Users/luliao/agent/smolagents/.trae/specs/agentic-benchmark/design.md`
- `/Users/luliao/agent/smolagents/.trae/specs/creative-knowledge-base/design.md`

建议再阅读这些代码和测试：
- `novel_agent/app/cli/textual_screens.py`
- `novel_agent/app/cli/textual_app.py`
- `novel_agent/app/cli/app.py`
- `novel_agent/app/cli/facade.py`
- `novel_agent/tests/test_cli_textual_components.py`
- `novel_agent/tests/test_cli_interface.py`
- `novel_agent/tests/test_run_creative_kb_benchmark.py`
- `novel_agent/tests/test_smoke_benchmark_service.py`
- `novel_agent/tests/test_creative_kb_benchmark_service.py`

目标：
在保留 Task 39 已有脚本化 TUI smoke 覆盖的基础上，继续完成 `/Users/luliao/agent/smolagents/.trae/specs/cli-interface/tasks.md` 中 Task 40-42：

1. Task 40：增强 CLI TUI benchmark 失败与恢复建议集成测试。
2. Task 41：增加可显式开启的真实 LLM CLI TUI 慢速 smoke。
3. Task 42：抽象可复用的 TUI smoke harness。

上下文：
- Task 39 已定义为当前 CLI TUI 的脚本化集成冒烟测试，覆盖 `/new-task`、`/read`、`/close-read`、`/query character`、`/query summary total`、`/benchmark`、`/creative-kb-benchmark`。
- 如果你在新 worktree 中看不到 Task 39 对应测试，说明当前主工作区的未提交改动尚未进入该 worktree。此时请优先根据上述文档和主工作区代码现状判断，必要时在最终回复中明确说明需要先同步 / 合并 Task 39 基线。

实现要求：
- 遵循 OOP 原则和 Pythonic 实现风格。
- 新增能力必须补测试。
- 默认测试不得触发真实 LLM；真实 LLM smoke 必须通过显式 marker 或环境变量启用。
- CLI / Textual 层只做交互、展示和调用 facade，不直接拼 Writer prompt，不直接修改 Memory / KB / workflow state。
- 冒烟测试应验证“用户打开 CLI 后基本可用”，优先覆盖用户可见消息、输入区稳定性、命令路由和 worker 结果回流。
- 不要重构无关模块，不要改动与当前任务无关的业务逻辑。

Task 40 细化要求：
- 使用 fake facade 或 monkeypatch，让 `/benchmark` 和 `/creative-kb-benchmark` 在 worker 中抛出可控异常。
- 覆盖未知 benchmark 目标、非法参数、缺少显式模型模式、artifact 写入失败、Reviewer 失败等至少 3 类场景。
- 断言消息流展示“错误”和“恢复建议”。
- 断言用户提交的原始命令仍以“你 · ...”形式保留。
- 断言 worker 失败后输入区仍可继续编辑，不被日志覆盖。
- 不要触发真实 LLM。

Task 41 细化要求：
- 新增一个显式开启的真实 LLM CLI TUI 慢速 smoke。
- 测试必须默认 skip，只有显式环境变量或 pytest marker 打开时才运行。
- 优先使用 `longzu-32kb` 或仓库已有小 fixture，不要引入大文件。
- 先覆盖真实 `/benchmark longzu-32kb`；如耗时可控，再增加 `/creative-kb-benchmark longzu-32kb --writer-ab`。
- 断言 Reviewer summary、decision / score、artifact_dir 或 run_dir 回流到消息流。
- 失败时输出最近 artifact 路径和恢复建议，便于定位。
- 必须限制 case_count / 运行预算，避免慢测变成质量回归套件。

Task 42 细化要求：
- 抽出 `submit_command` / `wait_for_worker` 或等价 helper，只放在测试文件或测试 helper 模块中。
- helper 必须通过 `PromptInput` + Textual pilot 提交命令，不能直接调用业务 facade。
- helper 应能断言提交后输入框清空，用户命令进入消息流。
- fake facade 的调用记录应更清楚地区分 `read:new`、`read:resume`、`benchmark`、`creative_kb_benchmark`，但不要破坏已有断言。
- 保持 helper 只服务测试，不进入生产代码。

测试要求：
- 至少运行 `.venv/bin/pytest novel_agent/tests/test_cli_textual_components.py -q`。
- 若修改了 CLI parser / facade，也运行 `.venv/bin/pytest novel_agent/tests/test_cli_interface.py novel_agent/tests/test_cli_tui_entrypoint.py -q`。
- 默认测试命令不得触发真实 LLM。
- 真实 LLM smoke 需要在最终回复中给出显式启用命令示例。

最终回复必须包含：
- worktree 路径和分支名。
- 修改文件列表。
- 已完成 Task 40-42 中哪些项，哪些仍未完成。
- 测试命令和结果。
- 合并回主工作区 / 当前分支前需要注意的事项。
```
