# Agent 派工清单

## 1. 目的

本文件用于整理当前小说续写系统多层 spec 的并行开发派工方案，明确：

- 执行顺序
- 每个 Agent 的负责范围
- 每一批可并行执行的 Agent Plan
- 每个 Agent 可直接使用的 prompt 指令
- 哪个验收 Agent 负责最终勾选 `tasks.md`

本派工清单以以下文档为边界约束：

- [spec.md](.trae/specs/novel-continuation-mvp/spec.md)
- [design.md](.trae/specs/novel-continuation-mvp/design.md)
- [tasks.md](.trae/specs/novel-continuation-mvp/tasks.md)
- [contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)
- [creative-knowledge-base/tasks.md](.trae/specs/creative-knowledge-base/tasks.md)
- [narrative-memory-context/tasks.md](.trae/specs/narrative-memory-context/tasks.md)
- [writer-agent-layered-generation/tasks.md](.trae/specs/writer-agent-layered-generation/tasks.md)

## 2. 当前前置状态与不一致点

### 2.1 已知前置完成项

- `K1` 已完成
- `M1` 已完成
- `M2` 已完成

说明：

- 这里的“已完成”表示已知前置实现已交付，可作为派工输入。
- 是否可以正式勾选 `tasks.md`，仍以独立 QA Agent 的代码与测试验收为准。

### 2.2 已确认的不一致点

- `M2` 的“已完成”与 [narrative-memory-context/tasks.md](.trae/specs/narrative-memory-context/tasks.md) 不完全一致：
  - `Task 3`、`Task 9` 当前仍标为“部分实现”
  - 因此 `QA-Memory` 必须先核对 `M2` 是否已达到可验收状态，再决定是否允许把它视为后续任务的稳定前置
- 原派工把 `W1` 设为负责 Writer `Task 1` 和完整 `Task 14`，这一点与 [writer-agent-layered-generation/tasks.md](.trae/specs/writer-agent-layered-generation/tasks.md) 的依赖关系不一致：
  - `Task 14` 依赖 `Task 1`、`Task 4`、`Task 10`、`Task 12`
  - 因此 `W1` 只能负责 `Task 14` 的基础约定与 runs 命名底座，不能单独承担完整 `Task 14`
- 原派工把 `K2` 与 `K3` 放在同一轮无条件并行，这与 [creative-knowledge-base/tasks.md](.trae/specs/creative-knowledge-base/tasks.md) 的依赖关系不完全一致：
  - `Task 12` 依赖 `Task 11`
  - `Task 11` 依赖 `Task 7`
  - 因此 `K3` 必须在 `K2` 冻结好 cluster / representative 相关结果后再进入主实现
- Writer 层当前没有完全独立的 `writer/` 代码目录，多个任务天然会收敛到共享文件：
  - `novel_agent/app/schemas/orchestration_schema.py`
  - `novel_agent/runs/layout.py`
  - `novel_agent/runs/writer.py`
  - `novel_agent/app/run_interactive.py`
  - 因此必须先确定单一 owner，再发车

## 3. 派工原则

- 所有实现 Agent 都以 [contracts.md](.trae/specs/novel-continuation-mvp/contracts.md) 为冻结边界，不得主动修改它。
- 不允许建议多个 Agent 同时修改 `contracts.md`。
- 不允许建议多个 Agent 同时修改共享 schema 文件。
- 实现 Agent 只改自己负责模块下的代码、测试和必要文档，不直接勾选 `tasks.md`。
- `tasks.md` 的勾选由独立验收 Agent 完成，避免“自己实现自己验收”。
- 主编排层 [tasks.md](.trae/specs/novel-continuation-mvp/tasks.md) 默认最后做，只由 `Integrator` 收口。
- 如果文档与 `tasks.md` 不一致，先记录不一致点，再决定是否发车。
- Writer 层若任务边界变化，优先同步 `W1 / W2 / W3` 的职责边界，再下发 prompt。

## 4. 冻结共享边界与单一 Owner

### 4.1 冻结文件

- 禁止任何实现 Agent 修改 [contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)
- `novel_agent/app/schemas/creative_kb_schema.py`
  - 当前轮默认冻结
  - 如必须修改，需暂停并由你或 `Integrator` 重新裁边界
- `novel_agent/app/schemas/context_assembly_schema.py`
  - 当前轮默认冻结
  - 如必须修改，需暂停并由你或 `Integrator` 重新裁边界

### 4.2 单一 Owner 文件

- `novel_agent/app/schemas/orchestration_schema.py`
  - 单一 owner：`W1`
- `novel_agent/runs/layout.py`
  - 单一 owner：`W1`
- `novel_agent/runs/writer.py`
  - Phase 1-2 由 `W1` 维护 runs 底座
  - Phase 3 仅在 `W1` 合并完成后允许 `W3` 接手补执行层产物
- `novel_agent/app/run_interactive.py`
  - 单一 owner：`W3`
- `novel_agent/app/run_continue_scene.py`
  - 单一 owner：`Integrator`

### 4.3 通用越界规则

- 禁止在 `Batch 1-4` 提前大改主 Runner、主 CLI、总装配入口
- 若某个 Agent 发现需要修改共享 schema、主入口或 contract，必须停止并上报
- 每个实现 Agent 只允许修改自己 prompt 中明确授权的文件范围

## 5. 分批执行 Plan

### Batch 0: 基线冻结

目标：

- 冻结当前 [contracts.md](.trae/specs/novel-continuation-mvp/contracts.md) 与四份 `tasks.md`
- 记录不一致点
- 写死共享文件 owner

并行情况：

- 无代码实现 Agent 发车

完成标准：

- 你确认本文件为当前派工基线

### Batch 1: 低冲突基础件

可并行 Agent：

- `W1`
- `K2`
- `QA-Memory` 预核对 `M2`

Plan：

- `W1`
  - 只做 Writer `Task 1`
  - 只做 Writer 共享 schema、Freeze 持久化基础与 runs 命名底座
  - 不宣称完成完整 `Task 14`
- `K2`
  - 做 Creative KB `Task 6`、`Task 7`
  - 先把 dedupe / representative 规则与落库接口稳定下来
- `QA-Memory`
  - 不勾选
  - 先核对 `M2` 的代码、测试与任务表状态是否一致
  - 产出“可继续依赖 / 不可继续依赖”的判断

禁止冲突：

- `W1` 不碰 `run_interactive.py`、`run_continue_scene.py`
- `K2` 不碰 `scene_brief_service.py`、`rerank_service.py`
- 本批不得改 `creative_kb_schema.py`、`context_assembly_schema.py`

本批输出：

- Writer 共享底座
- Creative KB dedupe / representative 稳定接口
- `M2` 状态核对结果

### Batch 2: 中层能力

启动条件：

- `W1` 已合并
- `K2` 已冻结 cluster / representative 接口
- `QA-Memory` 已确认 `M2` 可以作为稳定前置；若未确认，则 `M3` 暂缓

可并行 Agent：

- `W2`
- `K3`
- `M3`

Plan：

- `W2`
  - 负责 Writer `Task 2-7`
  - 承担 `Task 14` 中规划层产物落盘：
    - `book_continuation_plan.*`
    - `world_expansion_pack.*`
    - `character_requirement_report.*`
    - `character_cast_request.*`
    - `character_cast_plan.*`
    - `planned_character_profiles.*`
    - `character_introduction_plan.*`
    - `batch_plan.*`
    - `chapter_package.*`
- `K3`
  - 负责 `Task 8` 未完成项、`Task 12` 未完成项、`Task 15` 剩余测试
  - 重点做 `SceneBrief` prompt 化与 rerank prompt 化
- `M3`
  - 负责 `Task 4`、`Task 7` 未完成项、`Task 13`
  - 重点做章节摘要 schema、调度、`reading_progress` 恢复、Memory 端到端测试

禁止冲突：

- `W2` 不碰 `orchestration_schema.py`
- `W2` 不碰正文执行器、回写、工作流控制器
- `K3` 不碰 `K2` 的聚类核心实现
- `M3` 不碰人物档案规则实现

本批输出：

- Writer Layer 1-3 规划链路
- Creative KB 在线检索 prompt 化升级
- Memory 调度与端到端测试能力

### Batch 3: Writer 正文执行与恢复控制

启动条件：

- `W2` 已完成并冻结对 `W3` 的输入边界

可并行 Agent：

- `W3`

Plan：

- `W3`
  - 负责 Writer `Task 8-13`、`Task 15`
  - 承担 `Task 14` 中执行与回写层产物落盘：
    - `state_delta.*`
    - `memory_writeback.*`
    - Freeze D/E 相关运行产物
    - workflow / rollback 相关记录
  - 负责受限执行器、回写、回滚、确认点恢复与产品模式

禁止冲突：

- 不碰 `orchestration_schema.py`
- 不碰主编排层总装配入口
- 不重定义 Layer 1-3 核心 schema

本批输出：

- Writer 受限执行器
- Freeze D/C/B/A 回退能力
- CharacterCastPlan 级联回滚
- 交互式 workflow controller

### Batch 4: 模块验收与勾选

启动条件：

- `K2/K3`、`M3`、`W1/W2/W3` 均已完成各自交付

可并行 Agent：

- `QA-KB`
- `QA-Memory`
- `QA-Writer`

Plan：

- `QA-KB`
  - 验收 Creative KB 模块
  - 勾选 [creative-knowledge-base/tasks.md](.trae/specs/creative-knowledge-base/tasks.md)
- `QA-Memory`
  - 验收 Memory 模块
  - 同时最终裁定 `M2` 是否达到“已实现”
  - 勾选 [narrative-memory-context/tasks.md](.trae/specs/narrative-memory-context/tasks.md)
- `QA-Writer`
  - 验收 Writer 模块
  - 最终判定 `Task 14` 是否可勾选
  - 勾选 [writer-agent-layered-generation/tasks.md](.trae/specs/writer-agent-layered-generation/tasks.md)

禁止冲突：

- QA 只在对应 `tasks.md` 中勾选
- QA 不回头做大规模生产实现

本批输出：

- 三个模块的正式验收结果
- 正式勾选后的子模块 `tasks.md`

### Batch 5: 主编排层总装配

启动条件：

- `QA-KB`、`QA-Memory`、`QA-Writer` 全部完成

可并行 Agent：

- `Integrator`

Plan：

- `Integrator`
  - 负责 [novel-continuation-mvp/tasks.md](.trae/specs/novel-continuation-mvp/tasks.md) 的 `Task 7-12`
  - 只做编排、依赖注入、降级路径、失败恢复、跨层集成测试
  - 保留旧 CLI / runs 外壳，只改内部 orchestration

禁止冲突：

- 不改子模块内部稳定 contract
- 不做无必要的大规模 schema 重写

本批输出：

- 主编排层新分层总装配
- 跨层集成测试

### Batch 6: 主编排层验收

启动条件：

- `Integrator` 已完成

可并行 Agent：

- `QA-Integrator`

Plan：

- `QA-Integrator`
  - 验收主编排层
  - 勾选 [novel-continuation-mvp/tasks.md](.trae/specs/novel-continuation-mvp/tasks.md) 的 `Task 7-12`

完成标准：

- 确认主层只编排，不重复实现子层细节
- 确认旧路径可回归，新分层路径可运行

## 6. 角色分工

### 6.1 Creative Knowledge Base

- `K1`
  - 负责 [creative-knowledge-base/tasks.md](.trae/specs/creative-knowledge-base/tasks.md) 的 `Task 4`、`Task 5`
  - 当前作为已知完成前置处理
- `K2`
  - 负责 `Task 6`、`Task 7`
  - 独占 dedupe / cluster / representative 主实现
- `K3`
  - 负责 `Task 8` 未完成项、`Task 12` 未完成项、`Task 15` 剩余测试
  - 在 `K2` 冻结接口后发车

### 6.2 Narrative Memory Context

- `M1`
  - 负责 [narrative-memory-context/tasks.md](.trae/specs/narrative-memory-context/tasks.md) 的 `Task 2`、`Task 8`
  - 当前作为已知完成前置处理
- `M2`
  - 负责 `Task 3`、`Task 9`
  - 当前按“已知完成前置”处理，但必须由 `QA-Memory` 最终裁定
- `M3`
  - 负责 `Task 4`、`Task 7` 未完成项、`Task 13`

### 6.3 Writer Agent

- `W1`
  - 负责 [writer-agent-layered-generation/tasks.md](.trae/specs/writer-agent-layered-generation/tasks.md) 的 `Task 1`
  - 负责 Writer 共享 schema / Freeze 持久化基础 / runs 命名底座
  - 仅承担 `Task 14` 的基础约定，不单独对完整 `Task 14` 负责
- `W2`
  - 负责 `Task 2`、`Task 3`、`Task 4`、`Task 5`、`Task 6`、`Task 7`
  - 负责 `Task 14` 中规划层产物落盘
  - 负责 Layer 1 / 1B / 1C 到 Layer 3 的完整规划链路
- `W3`
  - 负责 `Task 8`、`Task 9`、`Task 10`、`Task 11`、`Task 12`、`Task 13`、`Task 15`
  - 负责 `Task 14` 中执行 / 回写层产物落盘
  - 负责正文层受限执行、回写、回滚、交互恢复
- `QA-Writer`
  - 负责最终验收 Writer `Task 1-15`
  - 尤其负责最终判定 `Task 14` 是否可勾选

### 6.4 QA 与集成

- `QA-KB`
  - 负责 Creative KB 模块验收并勾选
- `QA-Memory`
  - 负责 Memory 模块验收并勾选
  - 同时负责裁定 `M2` 的“已完成”是否与代码状态一致
- `QA-Writer`
  - 负责 Writer 模块验收并勾选
- `Integrator`
  - 负责最后推进 [tasks.md](.trae/specs/novel-continuation-mvp/tasks.md) 的 `Task 7-12`
- `QA-Integrator`
  - 负责主编排层验收并勾选

## 7. 通用 Prompt 模板

所有实现 Agent 开工前，统一使用以下开头：

```text
你负责本仓库小说续写系统的一个子模块实现任务。
必须遵守以下规则：
1. 以 .trae/specs/novel-continuation-mvp/contracts.md 为冻结 contract，不得主动修改。
2. 只修改本次明确授权的文件范围；不要碰主编排层总装配入口。
3. 优先补齐 schema、service、repo、tests，并保持与 tasks.md 对齐。
4. 完成后不要勾选 tasks.md；只输出“已完成内容 / 变更文件 / 建议勾选项 / 未完成项 / 风险”。
5. 如发现需要修改共享 schema 或 contract，停止并报告，不要自行扩边界。
```

## 8. Agent Prompt 指令

### 8.1 K2

```text
你的角色：K2，负责创作知识库近重复检测与代表片段选择。

任务来源：
- .trae/specs/creative-knowledge-base/tasks.md
- 负责 Task 6 和 Task 7

允许修改：
- novel_agent/app/repos/fragment_cards_repo.py
- novel_agent/app/repos/fragment_clusters_repo.py
- novel_agent/app/repos/creative_kb_storage.py
- novel_agent/app/services/*cluster* 相关实现
- novel_agent/app/services/*dedupe* 相关实现
- novel_agent/tests/**

禁止修改：
- .trae/specs/novel-continuation-mvp/contracts.md
- novel_agent/app/services/scene_brief_service.py
- novel_agent/app/services/rerank_service.py
- novel_agent/app/schemas/creative_kb_schema.py
- 主编排层入口

目标：
1. 实现近重复候选生成与归并规则。
2. 明确“可合并 / 不可合并”的边界，避免误合并事件相似但功能不同的桥段。
3. 实现 representative fragment 选择规则。
4. 回填 cluster_id 与 is_cluster_representative。
5. 补充聚类与代表片段测试。
```

### 8.2 K3

```text
你的角色：K3，负责创作知识库在线检索的 prompt 化升级。

任务来源：
- .trae/specs/creative-knowledge-base/tasks.md
- 负责 Task 8 未完成项、Task 12 未完成项、Task 15 剩余测试

前置条件：
- K2 已完成 cluster / representative 相关接口冻结

允许修改：
- novel_agent/app/services/scene_brief_service.py
- novel_agent/app/services/rerank_service.py
- novel_agent/app/services/coarse_retrieval_service.py
- novel_agent/app/prompts/** 中 SceneBrief / rerank 相关文件
- novel_agent/tests/**

禁止修改：
- .trae/specs/novel-continuation-mvp/contracts.md
- novel_agent/app/schemas/creative_kb_schema.py
- K2 的聚类核心实现
- 主编排层入口

目标：
1. 为 SceneBrief 设计 prompt 生成与 schema 校验。
2. 将当前 rerank 升级为固定 rubric 的 prompt-based rerank。
3. 保持 selected_fragment_ids 数量 1-4，且默认同簇不重复。
4. 增加 SceneBrief prompt、rerank prompt、辅助标签非主排序依据的测试。
```

### 8.3 M3

```text
你的角色：M3，负责章节摘要 / 调度 / Memory 端到端测试。

任务来源：
- .trae/specs/narrative-memory-context/tasks.md
- 负责 Task 4、Task 7 未完成项、Task 13

前置条件：
- QA-Memory 已确认 M2 可作为稳定前置；否则先报告阻塞

允许修改：
- novel_agent/app/services/chapter_assembler_service.py
- novel_agent/app/services/context_assembly_service.py
- novel_agent/app/services/outline_service.py
- novel_agent/app/services/world_state_service.py
- novel_agent/app/runner/close_read_runner.py
- novel_agent/app/repos/chapters_repo.py
- novel_agent/app/repos/reading_progress_repo.py
- novel_agent/tests/**

禁止修改：
- .trae/specs/novel-continuation-mvp/contracts.md
- novel_agent/app/schemas/context_assembly_schema.py
- 人物档案规则实现
- creative kb
- writer layer

目标：
1. 固化 chapter schema 与 outline schema。
2. 明确长度约束、压缩边界、整章输入与拆批阈值。
3. 强化超长章节拆批后的中间摘要保存与二次汇总。
4. 增加 reading_progress 恢复测试。
5. 增加 Memory 端到端测试：documents -> chapter summaries -> memory updates -> context assembly。
```

### 8.4 W1

```text
你的角色：W1，负责 Writer 层共享 schema、Freeze 持久化基础与 runs 命名底座。

任务来源：
- .trae/specs/writer-agent-layered-generation/tasks.md
- 负责 Task 1
- 负责 Task 14 的基础约定，不单独承担完整 Task 14

允许修改：
- novel_agent/app/schemas/orchestration_schema.py
- novel_agent/runs/layout.py
- novel_agent/runs/writer.py
- novel_agent/app/orchestrators/** 中与 schema / persistence 基础强相关的文件
- novel_agent/tests/**

禁止修改：
- .trae/specs/novel-continuation-mvp/contracts.md
- novel_agent/app/schemas/creative_kb_schema.py
- novel_agent/app/schemas/context_assembly_schema.py
- novel_agent/app/run_interactive.py
- novel_agent/app/run_continue_scene.py

目标：
1. 定义 ModelingStatus、ContinuationIntent、BookContinuationPlan、WorldExpansionPack、BatchPlan、ChapterPackage、ChapterBrief、StateDelta。
2. 定义 Freeze A/B/C/D/E 的持久化方式。
3. 扩展 runs 目录命名与产物约定。
4. 为人物补充流程新增 runs 产物命名与落盘底座。
5. 补充最小 schema / serialization / 持久化测试。

特别要求：
- 必须与 writer spec/design 中的 Freeze A-E 和级联回滚语义一致。
- Freeze A 必须兼容 BookContinuationPlan + WorldExpansionPack + CharacterCastPlan。
- 不得改动 contracts.md 中已冻结的 WriterInputBundle 语义。
```

### 8.5 W2

```text
你的角色：W2，负责 Layer 1 到 Layer 3 的规划链路，以及人物补充流程。

任务来源：
- .trae/specs/writer-agent-layered-generation/tasks.md
- 负责 Task 2、Task 3、Task 4、Task 5、Task 6、Task 7
- 负责 Task 14 中规划层产物落盘

前置条件：
- W1 已完成共享 schema / Freeze / runs 底座

允许修改：
- novel_agent/app/orchestrators/** 中 Layer 1-3 规划链路实现
- novel_agent/app/prompts/** 中 Writer 规划 prompt
- novel_agent/tests/**

禁止修改：
- .trae/specs/novel-continuation-mvp/contracts.md
- novel_agent/app/schemas/orchestration_schema.py
- novel_agent/app/run_interactive.py
- novel_agent/app/run_continue_scene.py
- 正文层执行器
- Memory 写回实现
- 主编排层总装配

目标：
1. 建立续写前建模检查。
2. 建立全书续写规划链路和世界观补全链路。
3. 建立 Layer 1C 人物补充链路。
4. 建立 BatchPlan 生成、暂停审阅、继续执行流程。
5. 建立 ChapterPackage / ChapterBrief 规划链路。
6. 明确 BookContinuationPlan + WorldExpansionPack + CharacterCastPlan -> Freeze A -> BatchPlan -> Freeze B -> ChapterPackage -> Freeze C。
```

### 8.6 W3

```text
你的角色：W3，负责 Writer 正文层受限执行、回写、回滚、产品模式与交互工作流。

任务来源：
- .trae/specs/writer-agent-layered-generation/tasks.md
- 负责 Task 8、Task 9、Task 10、Task 11、Task 12、Task 13、Task 15
- 负责 Task 14 中执行 / 回写层产物落盘

前置条件：
- W2 已完成 Layer 1-3 规划链路并冻结交接边界

允许修改：
- novel_agent/app/run_interactive.py
- novel_agent/app/orchestrators/** 中执行器 / rollback / workflow 相关文件
- novel_agent/runs/writer.py
- novel_agent/schemas/continuity.py
- novel_agent/tests/**

禁止修改：
- .trae/specs/novel-continuation-mvp/contracts.md
- novel_agent/app/schemas/orchestration_schema.py
- novel_agent/app/run_continue_scene.py
- Layer 1-3 核心 schema 定义
- 主编排层总装配

目标：
1. 扩展 ChapterBrief 到正文层输入 contract。
2. 将 Writer Agent 改为只消费冻结 brief 的受限执行器。
3. 将计划角色约束接入正文层，禁止正文层绕过上游自由创建关键新角色。
4. 建立 ContinuityReport 扩展、StateDelta 提取、memory writeback。
5. 支持计划角色首次正式登场后转写为正式 Character Memory。
6. 建立 Freeze D / C / B 逐级回退机制，并支持 CharacterCastPlan 修改触发的级联回滚。
7. 建立交互式工作流控制器、人物补充确认点恢复与三种产品模式。
```

### 8.7 QA-KB

```text
你的角色：QA-KB，负责创作知识库模块验收与勾选 tasks。

验收对象：
- .trae/specs/creative-knowledge-base/tasks.md
- K2、K3 的提交结果

规则：
1. 逐项核对 Task 6-15 的已实现情况，不看 agent 自述，只看代码、测试、必要文档。
2. 能跑则优先跑对应测试；必要时补最小验收测试。
3. 只在“代码 + 测试 + 行为”都满足时勾选 tasks.md。
4. 如需勾选，直接更新 creative-knowledge-base/tasks.md。
```

### 8.8 QA-Memory

```text
你的角色：QA-Memory，负责 Memory 模块验收与勾选 tasks。

验收对象：
- .trae/specs/narrative-memory-context/tasks.md
- M1、M2、M3 的提交结果

规则：
1. 先核对 M2“已完成”与 Task 3 / Task 9“部分实现”的不一致。
2. 只有在代码、测试与 contract 都满足时，才把 M2 视为已实现并勾选。
3. 核对 Task 2-13 对应代码与测试覆盖。
4. 勾选动作只在 narrative-memory-context/tasks.md 中进行。
```

### 8.9 QA-Writer

```text
你的角色：QA-Writer，负责 Writer 模块验收与勾选 tasks。

验收对象：
- .trae/specs/writer-agent-layered-generation/tasks.md
- W1、W2、W3 的提交结果

规则：
1. 重点检查 Freeze A-E、级联回滚、只消费冻结输入、失败恢复、确认点恢复。
2. 重点检查人物补充流程是否真正进入 Freeze / Rollback 体系。
3. 重点检查 Task 14 是否由 W1 / W2 / W3 分段落地后形成完整闭环。
4. 不接受“文档写了但代码未落地”的完成声明。
5. 勾选动作只在 writer-agent-layered-generation/tasks.md 中进行。
```

### 8.10 Integrator

```text
你的角色：Integrator，负责主编排层最后收口。

任务来源：
- .trae/specs/novel-continuation-mvp/tasks.md
- 负责 Task 7-12

前置条件：
- QA-KB、QA-Memory、QA-Writer 已完成各自模块验收

允许修改：
- novel_agent/app/run_continue_scene.py
- novel_agent/app/run_mvp.py
- novel_agent/app/orchestrators/**
- novel_agent/tools/**
- 跨层集成测试

禁止修改：
- contracts.md
- creative_kb_schema.py
- context_assembly_schema.py
- orchestration_schema.py
- 子模块内部已稳定 contract

目标：
1. 把 documents -> Creative KB -> Memory -> Writer 的总装配顺序真正接起来。
2. 保留旧 CLI / runs 外壳，只重构内部编排。
3. 支持降级路径与失败恢复。
4. 补跨层集成测试。
5. 不改子模块内部已稳定实现，优先做依赖注入与 orchestration。
```

### 8.11 QA-Integrator

```text
你的角色：QA-Integrator，负责主编排层验收与勾选 tasks。

验收对象：
- .trae/specs/novel-continuation-mvp/tasks.md
- Integrator 的提交结果

规则：
1. 确认主层只编排，不重复实现子层细节。
2. 确认旧路径仍可作为回归基线，新分层路径已可运行。
3. 确认跨层 bundle 与 contracts.md 一致。
4. 验收通过后勾选 novel-continuation-mvp/tasks.md 的 Task 7-12 对应项。
```

## 9. 谁负责勾选

- `creative-knowledge-base/tasks.md`
  - 由 `QA-KB` 勾选
- `narrative-memory-context/tasks.md`
  - 由 `QA-Memory` 勾选
- `writer-agent-layered-generation/tasks.md`
  - 由 `QA-Writer` 勾选
- `novel-continuation-mvp/tasks.md`
  - 由 `QA-Integrator` 勾选
- 所有实现 Agent
  - 一律不直接勾选，只能在交付说明中写“建议勾选项”

## 10. 勾选标准

- `已实现`
  - 代码已落地，测试覆盖主要路径，契约未破坏
- `部分实现`
  - 核心路径已存在，但仍缺子项、边界规则或关键测试
- `待新增`
  - 只有文档或只有占位代码，不勾选
- `live smoke`
  - 可作为增强证据，但不能替代本地可重复测试

## 11. 建议的实际发车顺序

- 第 0 轮
  - 冻结共享边界
- 第 1 轮
  - `W1`
  - `K2`
  - `QA-Memory` 预核对 `M2`
- 第 2 轮
  - `W2`
  - `K3`
  - `M3`
- 第 3 轮
  - `W3`
- 第 4 轮
  - `QA-KB`
  - `QA-Memory`
  - `QA-Writer`
- 第 5 轮
  - `Integrator`
- 第 6 轮
  - `QA-Integrator`

## 12. 补充建议

- 每个 Agent 开工前，把自己的“允许修改文件列表”写死到 prompt 里，能显著减少冲突。
- 如果在多个对话框里同时派发，建议直接复制本文件中的 prompt 原文，不要再临场改动边界。
- 如果某个 Agent 发现必须修改共享 schema，应立即停下并转交你或 `Integrator` 决策。
- 如果 `M2` 最终被 `QA-Memory` 判定为“部分实现”，则应暂停 `M3` 的正式完工宣称，并把缺口回流为新的前置阻塞项。
- 如果 Writer 层任务发生变化，先更新 `W1 / W2 / W3` 的职责边界，再改发车顺序与 prompt，不要反过来操作。

## 13. 主编排层任务卡模板

说明：

- 以下任务卡用于主编排层剩余缺口的继续派工。
- 默认执行角色为 `Integrator`，除非你后续再细拆给别的实现 Agent。
- 所有任务卡都以 [contracts.md](.trae/specs/novel-continuation-mvp/contracts.md) 为冻结边界。
- 所有任务卡都不得重复实现 Creative KB、Memory、Writer 子层已经稳定的内部细节。

### 13.1 任务卡 A：主编排总装配 Service

目标：

- 新增主编排总装配 service，形成单一主链路入口。
- 把 `SceneBrief/ScenePlan -> Creative KB -> Memory -> WriterInputBundle` 串成可调用流程。
- 保持主层只负责 orchestration，不下沉实现子层细节。

输入（prompt 词）：

```text
你的角色：Integrator-Assembly。

任务目标：
1. 新增主编排总装配 service。
2. 把 SceneBrief/ScenePlan -> Creative KB -> Memory -> WriterInputBundle 串成单一主链路。
3. 主层只做 orchestration，不重复实现 SceneBrief 生成、粗筛、rerank、上下文裁剪、Writer Freeze 细节。

必须遵守：
1. 以 .trae/specs/novel-continuation-mvp/contracts.md 为冻结 contract，不得主动修改。
2. 只修改本卡明确授权的文件范围。
3. 优先补 service、tests 和必要文档。
4. 完成后不要勾选 tasks.md，只输出“已完成内容 / 变更文件 / 建议勾选项 / 未完成项 / 风险”。
5. 如发现需要修改 creative_kb_schema.py、context_assembly_schema.py 或子层稳定 contract，立即停止并报告。
```

输出：

- 新增主编排 service
- 可调用的总装配方法
- 产出真实 `WriterInputBundle`

修改文件：

- 新增 `novel_agent/app/orchestrators/main_layer_orchestrator.py`
- 可更新 `novel_agent/app/orchestrators/__init__.py`
- 可更新 `novel_agent/app/schemas/orchestration_schema.py`
- 可更新 `novel_agent/tests/**`

验收标准：

- 主层存在单一 orchestration service，而不是把逻辑散在 CLI 中。
- service 只调用子层能力，不在主层重写 `SceneBriefService`、`CoarseRetrievalService`、`RerankService`、`ContextAssemblyService`、Writer workflow 的内部实现。
- service 能产出符合 contract 的 `WriterInputBundle`。

### 13.2 任务卡 B：Creative KB 接线与兼容映射

目标：

- 在主编排层完成旧 `ScenePlan` 到 `SceneBrief` 的兼容映射。
- 接入 Creative KB 检索链，输出标准参考片段集合。

输入（prompt 词）：

```text
你的角色：Integrator-CreativeBridge。

任务目标：
1. 在主编排层实现 ScenePlan -> SceneBrief 的兼容映射。
2. 接入 SceneBriefService、CoarseRetrievalService、RerankService。
3. 产出可直接用于 WriterInputBundle 的 reference_fragments。

边界要求：
1. 不修改 creative_kb_schema.py。
2. 不重写 SceneBrief、粗筛、rerank 的业务规则。
3. 可以为 orchestration_schema.py 增加与冻结 contract 兼容的辅助字段，但不得破坏既有字段语义。
```

输出：

- 主编排层对 Creative KB 的稳定调用路径
- 兼容旧 `ScenePlan` 的映射逻辑
- `reference_fragments` 组装结果

修改文件：

- `novel_agent/app/orchestrators/main_layer_orchestrator.py`
- `novel_agent/app/schemas/orchestration_schema.py`
- `novel_agent/tests/**`

验收标准：

- 有 `SceneBrief` 时优先使用 `SceneBrief`。
- 无 `SceneBrief` 时可从旧 `ScenePlan` 映射生成。
- `reference_fragments` 来自 rerank 选中的片段，而不是主层自行伪造。
- 不重复实现 Creative KB 内部排序逻辑。

### 13.3 任务卡 C：Memory 上下文装配接线

目标：

- 在主编排层接入 Memory 层上下文装配。
- 产出符合 `ContextAssemblyPayload` contract 的 `context_payload`。

输入（prompt 词）：

```text
你的角色：Integrator-MemoryBridge。

任务目标：
1. 在主编排层接入 MemoryAssemblyInput 与 ContextAssemblyService。
2. 组装符合 contract 的 context_payload。
3. 保持缺失上下文信号显式返回，不允许静默丢失。

边界要求：
1. 不修改 context_assembly_schema.py。
2. 不重写 Memory 层上下文裁剪逻辑。
3. 主层只负责准备输入、调用 service、承接输出。
```

输出：

- `MemoryAssemblyInput` 的主层构造逻辑
- `ContextAssemblyPayload` 的接线结果

修改文件：

- `novel_agent/app/orchestrators/main_layer_orchestrator.py`
- `novel_agent/app/schemas/orchestration_schema.py`
- `novel_agent/tests/**`

验收标准：

- 主层调用 `ContextAssemblyService`，不在主层重复拼接章节摘要/人物摘要/世界观摘要。
- `context_payload` 满足冻结 contract。
- `missing_context` 在缺失时显式存在。

### 13.4 任务卡 D：CLI 接入新总装配且保留旧路径

目标：

- 在现有 CLI 外壳中接入新分层总装配入口。
- 保留旧路径，作为回归基线和回退方案。

输入（prompt 词）：

```text
你的角色：Integrator-CLI。

任务目标：
1. 在不破坏旧 pipeline / 旧 Runner 的前提下，接入新的主编排总装配入口。
2. 保留旧 CLI / runs 外壳。
3. 明确新旧路径切换方式。

边界要求：
1. 不大改现有 segmentation / close_read 基线逻辑。
2. 不移除旧入口。
3. 只改主层入口和 orchestration 调用方式。
```

输出：

- 可运行的新总装配入口
- 新旧路径切换开关或明确入口

修改文件：

- `novel_agent/app/run_interactive.py`
- 可新增 `novel_agent/app/run_layered_continue.py`
- `novel_agent/tests/**`

验收标准：

- 旧 pipeline 相关测试仍通过。
- 新入口可构建并运行主装配链。
- CLI 层主要做参数收集与依赖注入，不把编排逻辑重新写回入口函数。

### 13.5 任务卡 E：主编排层成功链路集成测试

目标：

- 补主层视角的端到端成功链路测试。
- 覆盖 `documents -> Creative KB -> Memory -> WriterInputBundle`。

输入（prompt 词）：

```text
你的角色：Integrator-TestE2E。

任务目标：
1. 新增主编排层成功链路集成测试。
2. 测试必须从主层入口或主层 orchestration service 出发。
3. 不接受只测 Creative KB、Memory、Writer 子层各自 service 的拼盘测试。
```

输出：

- 主层成功链路测试

修改文件：

- 新增 `tests/test_main_layer_orchestration.py`
- 可复用 `tests/fixtures/**`

验收标准：

- 测试从主层 orchestration 入口发起。
- 测试断言至少覆盖：
  - 读入主层输入
  - 生成 `SceneBrief` 或兼容旧 `ScenePlan`
  - 获取 `reference_fragments`
  - 获取 `context_payload`
  - 产出 `WriterInputBundle`

### 13.6 任务卡 F：主编排层降级路径测试

目标：

- 补主层对子模块缺失或未就绪时的降级测试。

输入（prompt 词）：

```text
你的角色：Integrator-TestDegrade。

任务目标：
1. 为主编排层增加降级路径测试。
2. 覆盖 Creative KB 未命中、Memory 缺上下文、仅旧 ScenePlan 可用等场景。
3. 确保主层的降级是显式的、可观察的，而不是静默吞掉问题。
```

输出：

- 主层降级路径测试
- 必要时新增降级原因落盘或结构化返回

修改文件：

- `tests/test_main_layer_orchestration.py`
- 可更新 `novel_agent/app/orchestrators/main_layer_orchestrator.py`

验收标准：

- 至少覆盖 2 类降级场景。
- 主层会返回或落盘降级原因。
- 不因为子模块部分缺失就直接崩掉整条链路，除非 contract 明确要求阻断。

### 13.7 任务卡 G：runs 观测面补齐

目标：

- 为主编排层新增关键中间产物落盘，便于跨层排查。

输入（prompt 词）：

```text
你的角色：Integrator-Runs。

任务目标：
1. 为主编排总装配增加 runs 落盘。
2. 重点落盘 creative_kb_input、scene_brief、rerank_result、memory_assembly_input、writer_input_bundle、degrade_reason。
3. 不改变现有 runs 基础约定，只做兼容扩展。
```

输出：

- 主层关键中间产物 runs 文件

修改文件：

- `novel_agent/runs/writer.py`
- `novel_agent/app/orchestrators/main_layer_orchestrator.py`
- `novel_agent/tests/**`

验收标准：

- runs 中能看到主层关键跨层 bundle。
- 产物命名稳定、JSON 可读。
- 不破坏旧 runs 目录约定。

### 13.8 任务卡 H：主层/子层责任说明与迁移说明

目标：

- 补主编排层验收说明、责任边界与迁移说明。

输入（prompt 词）：

```text
你的角色：Integrator-Docs。

任务目标：
1. 写一份主层与子层责任说明。
2. 写清旧路径保留原因、新路径目标形态、迁移中的兼容策略。
3. 让 QA-Integrator 能直接依据该文档进行验收。
```

输出：

- 主层验收说明
- 迁移与责任边界文档

修改文件：

- 新增 `novel_agent/docs/main_layer_integration_notes.md`
- 可新增 `novel_agent/docs/main_layer_migration_plan.md`
- 可更新 [tasks.md](.trae/specs/novel-continuation-mvp/tasks.md) 的说明性文字，但不要提前勾选

验收标准：

- 文档明确列出主层负责的内容与不负责的内容。
- 文档明确旧路径是回归基线，新路径是未来主路径。
- 文档能支撑 `Task 10` 第三子项与 `Task 11` 最后一子项的后续关闭。

### 13.9 任务卡 I：冲突标注转实施任务

目标：

- 把 `Task 11` 中的冲突标注正式转成可关闭的实施项。

输入（prompt 词）：

```text
你的角色：Integrator-MigrationTasks。

任务目标：
1. 将 Task 11 当前的“保留 / 兼容 / 重构”建议转写为明确的主层与子层实施任务。
2. 每项都要能映射回 tasks.md 的后续关闭动作。
3. 不要只写讨论性说明，必须写成可执行项。
```

输出：

- 冲突标注到实施项的转写结果

修改文件：

- [tasks.md](.trae/specs/novel-continuation-mvp/tasks.md)
- `novel_agent/docs/main_layer_migration_plan.md`

验收标准：

- `Task 11` 最后一子项对应的实施任务明确可追踪。
- 每一项冲突都至少有一个明确动作：保留、兼容、迁移或废弃。

### 13.10 任务卡 J：决策项 A/B 收口

目标：

- 完成 `Task 12` 中尚未关闭的决策项 A、B。

输入（prompt 词）：

```text
你的角色：Integrator-DecisionAB。

任务目标：
1. 落实决策项 A：保留基础检索工具，但主续写检索路径迁移到 Creative KB。
2. 落实决策项 B：兼容保留旧 ScenePlan schema，并逐步引入独立 SceneBrief。
3. 确保主层优先级明确：SceneBrief > ScenePlan。
```

输出：

- 决策项 A/B 的代码与测试落地

修改文件：

- `novel_agent/app/orchestrators/main_layer_orchestrator.py`
- `novel_agent/app/run_interactive.py`
- `novel_agent/app/run_continue_scene.py`
- `novel_agent/tests/**`

验收标准：

- 主路径不再以旧基础检索工具为核心检索链。
- 旧 `ScenePlan` 仍可兼容输入。
- `SceneBrief` 优先级高于 `ScenePlan`。

### 13.11 主编排层任务卡建议发车顺序

- 第 1 张卡：A
- 第 2 张卡：B
- 第 3 张卡：C
- 第 4 张卡：D
- 第 5 张卡：E
- 第 6 张卡：F
- 第 7 张卡：G
- 第 8 张卡：H
- 第 9 张卡：I
- 第 10 张卡：J

### 13.12 推荐组合发车方式

- `组合 1`
  - A + B + C
  - 适合一个 Agent 一次性打通主链路
- `组合 2`
  - D + G
  - 适合在主链路稳定后补入口和观测面
- `组合 3`
  - E + F
  - 适合专门补主层测试
- `组合 4`
  - H + I + J
  - 适合最后收口文档、迁移任务与未完成决策项
