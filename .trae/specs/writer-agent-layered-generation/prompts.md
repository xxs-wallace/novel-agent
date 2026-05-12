# Writer Status Refactor Prompts

本文为 [`tasks.md`](tasks.md) 中 `Group G: Writer 用户可见状态重构` 生成可交给独立 agent 执行的 prompt。默认使用“总执行 prompt”；若需要分批派工，再使用后续阶段 prompt。

## Prompt 0: 顺序完成 Writer 状态重构全部任务

```text
你的角色：Writer-Status-Refactor-Agent。

工作目录：/Users/luliao/agent/smolagents

任务目标：
按顺序完成 .trae/specs/writer-agent-layered-generation/tasks.md 中 Group G 的 Task 16、Task 17、Task 18、Task 19、Task 20。不要只改文案，要把状态翻译层、CLI 输出、GUI 输出、状态机不一致点和测试一起完成。

必须先阅读：
1. AGENTS.md
2. .trae/specs/spec.md
3. .trae/specs/writer-agent-layered-generation/design.md 的 “Writer 用户可见状态词典”
4. .trae/specs/writer-agent-layered-generation/tasks.md 的 Group G
5. .trae/specs/writer-agent-layered-generation/designs/workflow-state-machine.design.md
6. .trae/specs/writer-agent-layered-generation/designs/review-writeback.design.md
7. .trae/specs/writer-agent-layered-generation/specs/workflow-and-recovery.spec.md
8. .trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md

建议重点阅读代码：
1. novel_agent/app/orchestrators/writer_workflow.py
2. novel_agent/app/orchestrators/writer_layered_generation.py
3. novel_agent/app/orchestrators/writer_execution.py
4. novel_agent/app/run_interactive.py
5. novel_agent/app/gui/main.py
6. novel_agent/app/gui/writer_cli.py
7. novel_agent/tests/test_run_interactive_pipeline.py
8. novel_agent/tests/test_writer_execution_workflow.py

实现边界：
1. 内部状态名可以继续存在于 workflow_state.json、checkpoint、日志和技术详情中。
2. CLI / GUI 主界面必须展示中文用户流程状态，不得把 artifact saved、Freeze B pending、freeze_d_review、wait_chapter_acceptance、checkpoint confirmed 作为主文案。
3. 保存 artifact 只显示“已保存你的修改”，不能自动推进流程。
4. WriterStatusPresenter 应尽量独立，供 CLI 和 GUI 共用。
5. 不要破坏现有 Writer workflow、Freeze record、review decision、writeback gate 的语义。
6. 遵守 OOP 原则，Pythonic，新增功能必须补测试。
7. 不要删除用户已有改动，不要做无关重构。

执行顺序：
1. 完成 Task 16：建立 WriterStatusPresenter 或等价状态翻译层。
2. 完成 Task 17：替换 CLI / run_interactive / writer_cli 中的内部状态主文案。
3. 完成 Task 18：替换 GUI Writer 面板状态和按钮文案，补齐 wait_chapter_review GUI 入口。
4. 完成 Task 19：核对 MODE_CONFIRMATION_POINTS 与 prepare_planning 等实际行为，修复 Batch 模式 Freeze A 确认点不一致，或更新模式定义并补测试。
5. 完成 Task 20：补状态翻译、CLI 输出、GUI 文案、wait_chapter_acceptance 四分支、wait_chapter_review 可继续路径、Batch 模式行为测试。
6. 每完成一个任务，更新 .trae/specs/writer-agent-layered-generation/tasks.md 中对应 checkbox。只有实现与测试都满足时才能勾选。

必须覆盖的用户文案：
- artifact saved -> 已保存你的修改
- batch_review / Freeze B pending -> 请审阅本批剧情大纲
- freeze_d_review -> 请确认本章写作材料
- wait_chapter_acceptance -> 请验收当前章节
- writeback_review -> 请确认写回续写记忆
- wait_chapter_review -> 请调整章节规划后重写
- checkpoint confirmed -> 已确认，继续下一步
- pending -> 等待你确认

验收标准：
1. CLI 主输出不包含 artifact saved、Freeze B pending、freeze_d_review、wait_chapter_acceptance、checkpoint confirmed。
2. GUI Writer 状态栏和按钮不把 Freeze A/B/C/D/E 作为主文案。
3. 技术详情仍可查看内部 stage、run id、freeze record、checkpoint path。
4. wait_chapter_acceptance 展示四个主要分支：接受本章、调整字数后重写、修改章节梗概后重写、作废草稿，并说明后续状态。
5. wait_chapter_review 有可继续路径。
6. Batch 模式 Freeze A 行为与 spec / mode definition 一致。
7. 新增/修改测试通过。至少运行 Writer workflow、run_interactive、GUI/presenter 相关测试；如果无法跑全量测试，说明原因。

交付要求：
1. 输出修改文件列表。
2. 输出已完成任务编号和未完成/阻塞项。
3. 输出测试命令与结果。
```

## Prompt 1: Task 16 状态翻译层

```text
你的角色：Writer-StatusPresenter-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 16。

重点：
1. 定义 WriterStatusPresenter 或等价 presenter。
2. 将内部 stage / event 翻译为中文用户文案。
3. 输出结构应包含：用户主状态、背景说明、下一步动作、技术详情。
4. CLI 和 GUI 都应能复用，不要把映射散落在多个界面函数里。

必须覆盖：
- artifact saved -> 已保存你的修改
- batch_review / Freeze B pending -> 请审阅本批剧情大纲
- freeze_d_review -> 请确认本章写作材料
- wait_chapter_acceptance -> 请验收当前章节
- writeback_review -> 请确认写回续写记忆
- wait_chapter_review -> 请调整章节规划后重写
- completed / halted / pending / confirmed / needs_review

建议关注代码：
- novel_agent/app/orchestrators/writer_workflow.py
- novel_agent/app/run_interactive.py
- novel_agent/app/gui/main.py
- novel_agent/app/gui/writer_cli.py
- novel_agent/tests/test_writer_execution_workflow.py

验收：
- 有状态翻译单测，覆盖所有 Writer 用户确认点。
- 内部状态仍可作为 technical detail 返回。
- 完成后勾选 Task 16。
```

## Prompt 2: Task 17 CLI / 交互输出替换

```text
你的角色：Writer-CLI-Copy-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 17。

重点：
1. 将 run_interactive.py、writer_cli.py 中展示给用户的内部状态替换为 WriterStatusPresenter 输出。
2. _prompt_writer_review 等交互提示显示中文状态、背景说明和下一步动作。
3. 保存 artifact 后显示“已保存你的修改”，并明确“保存不等于确认”。
4. 章节验收提示显示：接受本章、调整字数后重写、修改章节梗概后重写、作废草稿、稍后决定。
5. wait_length_review 说明它可能来自初次长度确认，也可能来自“调整字数后重写”。

禁止：
- 不得在主输出中展示 freeze_d_review、wait_chapter_acceptance、checkpoint confirmed、Freeze B pending。
- 不得改变 Writer workflow 的业务语义。

验收：
- CLI 输出测试断言主输出不包含内部状态码。
- 章节验收和长度重修路径有中文提示测试。
- 完成后勾选 Task 17。
```

## Prompt 3: Task 18 GUI Writer 面板替换

```text
你的角色：Writer-GUI-Copy-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 18。

重点：
1. _refresh_writer_state_buttons 使用中文状态和下一步说明。
2. _writer_actions_for_stage 的按钮文案去掉 Freeze A/B/C/D/E 主文案。
3. batch_review 按钮显示“确认本批剧情大纲”。
4. freeze_d_review 按钮显示“确认本章写作材料”，并说明不会立刻写回。
5. wait_chapter_acceptance 显示完整验收动作。
6. 为 wait_chapter_review 补齐 GUI 动作入口，支持返回章节梗概调整后继续。

建议关注代码：
- novel_agent/app/gui/main.py
- novel_agent/app/orchestrators/writer_workflow.py
- novel_agent/tests/**

验收：
- GUI 状态/按钮文案测试或 presenter 快照测试通过。
- 主界面不把 Freeze A/B/C/D/E 作为主要状态展示。
- 技术详情仍能显示内部 stage。
- 完成后勾选 Task 18。
```

## Prompt 4: Task 19 模式确认点与状态机对齐

```text
你的角色：Writer-StateMachine-Alignment-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 19。

重点：
1. 核对 MODE_CONFIRMATION_POINTS 与 prepare_planning()、prepare_batch_plan()、prepare_chapter_package()、prepare_execution() 的实际行为。
2. 解决 Batch 模式是否需要停在“请审阅全书续写规划”的不一致。
3. 确认 wait_chapter_review 从验收分支进入后有可继续执行路径。

决策规则：
1. 如果 design/spec 明确 Batch 模式应确认全书规划，则实现 Batch 在 Freeze A 前停留并补测试。
2. 如果现有产品意图是 Batch 跳过 Freeze A 人工确认，则更新 mode definition / tasks 注释，并补测试证明行为一致。
3. 不允许保留“文档说 A、代码做 B”的状态。

验收：
- Batch 模式 Freeze A 行为一致性测试通过。
- wait_chapter_review 可继续路径测试通过。
- 没有破坏 Assist / Auto 模式现有测试。
- 完成后勾选 Task 19。
```

## Prompt 5: Task 20 测试与快照验收

```text
你的角色：Writer-Status-Test-Agent。

目标：
完成 .trae/specs/writer-agent-layered-generation/tasks.md 的 Task 20。

测试必须覆盖：
1. 状态翻译单测，覆盖所有 Writer 用户确认点。
2. CLI 输出测试，断言主输出不包含 artifact saved、Freeze B pending、freeze_d_review、wait_chapter_acceptance。
3. GUI 状态/按钮文案测试或 presenter 快照测试。
4. wait_chapter_acceptance 四分支中文文案测试：
   - accepted -> 请确认写回 / 本章已完成路径
   - revise_length -> 请确认章节长度与节奏
   - replan_chapter -> 请调整章节规划后重写
   - discarded -> 流程已暂停
5. wait_chapter_review 可继续路径测试。
6. Batch 模式 Freeze A 行为一致性测试。

建议关注测试文件：
- novel_agent/tests/test_run_interactive_pipeline.py
- novel_agent/tests/test_writer_execution_workflow.py
- 可新增专门的 presenter 测试文件

验收：
- 目标测试通过。
- 若全量测试过慢，可运行相关测试子集并说明。
- 完成后勾选 Task 20。
```
