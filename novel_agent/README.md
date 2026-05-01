# novel_agent（小说续写 MVP）

本目录是基于 `smolagents` 的“边车模块”式实现：MVP 以 `novel_agent/` 作为独立功能域落在同一仓库内，复用现有的 `CodeAgent/ToolCallingAgent`、`Tool` 体系与 `smolagents.cli.load_model` 模型加载能力；本次实现未修改 `src/smolagents`。

## 快速开始

### 1) 安装与运行前提

在仓库根目录下安装（任选其一）：

```bash
pip install -e ".[dev]"
```

如需接不同模型，按需安装额外依赖：

- LiteLLM：`pip install -e ".[litellm]"`
- OpenAI-compatible：`pip install -e ".[openai]"`
- 本地 Transformers：`pip install -e ".[transformers]"`

### 2) 准备语料目录（索引输入）

默认约定语料在仓库根目录的两个路径（可用参数覆盖）：

- `longzu_split/`：小说分片（Markdown，建议每段/每章一个 `.md`）
- `analysis/`：设定/考据/人物小传等（Markdown）

索引时会把文件路径写成相对 `repo_root` 的相对路径（例如 `longzu_split/seg_001.md`），后续 `--anchor-path` 也使用同样的相对路径。

## 如何 build 索引

### 默认构建

```bash
python -m novel_agent.indexes.build --rebuild
```

默认输出到：`novel_agent/indexes/novel.db`，默认扫描：`longzu_split/` 与 `analysis/`。

### 自定义输入/输出路径

```bash
python -m novel_agent.indexes.build \
  --repo-root /abs/path/to/your/repo_root \
  --db /abs/path/to/novel.db \
  --rebuild \
  --roots /abs/path/to/your/repo_root/longzu_split /abs/path/to/your/repo_root/analysis
```

## 如何 dry-run 跑 MVP（不接模型）

MVP 入口：`novel_agent/app/run_mvp.py`，流程为读锚点 -> 检索 -> 场景规划 -> 生成草稿 -> 一致性检查 -> 落盘。

dry-run 模式会跳过模型调用，使用确定性逻辑生成草稿（仍会跑检索、规划与一致性检查），用于验证索引、工具与落盘闭环。

```bash
python -m novel_agent.app.run_mvp \
  --dry-run \
  --rebuild-index \
  --anchor-path longzu_split/seg_001.md \
  --goal "承接锚点续写一场冲突升级的对话戏" \
  --runs-dir runs
```

输出产物在 `runs/<run_id>/`：

- `task.json`：本次运行参数与模型配置（即便 dry-run 也会记录）
- `reading_pack.json`：锚点读取结果与 sources
- `retrieval_bundle.json`：检索步骤与 sources 汇总
- `scene_plan.json`：场景规划结构化结果
- `draft.md`：草稿（dry-run 为确定性生成）
- `continuity_report.json`：一致性检查结果
- `final.md`：当前 MVP 下与 draft 相同（后续可扩展为“修订后终稿”）

## 如何实际接模型（真实生成）

`run_mvp` 在非 `--dry-run` 时使用 `smolagents.cli.load_model` 加载模型，并用 `CodeAgent` 或 `ToolCallingAgent` 发起一次生成调用（本阶段不把检索/规划工具挂到生成 Agent 上，生成仅消费 prompt）。

通用命令骨架：

```bash
python -m novel_agent.app.run_mvp \
  --anchor-path longzu_split/seg_001.md \
  --goal "承接锚点续写一场冲突升级的对话戏" \
  --model-type InferenceClientModel \
  --model-id Qwen/Qwen3-Next-80B-A3B-Thinking
```

### 选项 A：Hugging Face Inference（InferenceClientModel）

- 认证：`HF_API_KEY` 环境变量或 `--api-key`
- 可选：`--provider` 指定推理提供方

```bash
export HF_API_KEY="..."
python -m novel_agent.app.run_mvp \
  --anchor-path longzu_split/seg_001.md \
  --goal "承接锚点续写一场冲突升级的对话戏" \
  --model-type InferenceClientModel \
  --model-id Qwen/Qwen3-Next-80B-A3B-Thinking \
  --provider together
```

### 选项 B：OpenAI-compatible（OpenAIModel）

```bash
export OPENAI_API_KEY="..."
python -m novel_agent.app.run_mvp \
  --anchor-path longzu_split/seg_001.md \
  --goal "承接锚点续写一场冲突升级的对话戏" \
  --model-type OpenAIModel \
  --model-id gpt-4o \
  --api-base https://api.openai.com/v1 \
  --api-key "$OPENAI_API_KEY"
```

DeepSeek 思考模式示例（可选落盘 reasoning_content）：

```bash
export DEEPSEEK_API_KEY="..."
python -m novel_agent.app.run_mvp \
  --anchor-path longzu_split/seg_001.md \
  --goal "承接锚点续写一场冲突升级的对话戏" \
  --model-type OpenAIModel \
  --model-id deepseek-v4-pro \
  --api-base https://api.deepseek.com \
  --api-key "$DEEPSEEK_API_KEY" \
  --thinking enabled \
  --reasoning-effort high \
  --save-reasoning
```

### 选项 C：LiteLLM（LiteLLMModel）

```bash
export ANTHROPIC_API_KEY="..."
python -m novel_agent.app.run_mvp \
  --anchor-path longzu_split/seg_001.md \
  --goal "承接锚点续写一场冲突升级的对话戏" \
  --model-type LiteLLMModel \
  --model-id anthropic/claude-3-5-sonnet-latest \
  --api-key "$ANTHROPIC_API_KEY"
```

### 选项 D：本地 Transformers（TransformersModel）

```bash
python -m novel_agent.app.run_mvp \
  --anchor-path longzu_split/seg_001.md \
  --goal "承接锚点续写一场冲突升级的对话戏" \
  --model-type TransformersModel \
  --model-id HuggingFaceTB/SmolLM-135M-Instruct
```

## 复用清单（本 MVP 实际复用了什么）

- Agent：复用 `smolagents.CodeAgent` / `smolagents.ToolCallingAgent`
- Tool：复用 `smolagents.Tool` 基类与默认工具注册（`smolagents.default_tools.TOOL_MAPPING`），并在 `novel_agent/tools/` 内新增小说域工具集合
- Model：复用 `smolagents.cli.load_model` 的 model_type 分发逻辑（InferenceClient/LiteLLM/OpenAI/Transformers）
- 运行产物：复用“runs 目录 + current 指针”的落盘思路（由 `novel_agent/runs/` 负责）

同时满足：

- 未修改 `src/smolagents`：MVP 能力均通过新增 `novel_agent/` 实现
- 复用既有体系：Agent/Tool/Model 加载全部沿用仓库内现成实现，仅在 `novel_agent` 组合编排

## 结论：是否需要另建项目

结论：现阶段不需要另建项目，建议继续在本仓库内迭代 `novel_agent/`。

理由：

- 复用强：核心能力依赖 `smolagents` 的 Agent/Tool/Model 基建，同仓维护能降低 API 演进成本
- 测试与 CI 复用：可以直接接入本仓库 pytest 与质量门禁，减少重复工程化
- 交付形态明确：当前定位是“边车模块”，与 `src/smolagents` 解耦（不改核心），适合快速验证与迭代

何时再考虑拆分独立项目：

- 需要独立发布节奏（单独版本/依赖/部署），或要引入大量与 `smolagents` 无关的运行时组件（服务端、队列、存储、UI）
- 需要跨多仓协作、权限隔离或私有化交付时

## 已知缺口与后续迭代方向

- 状态机化编排：把“读->检索->计划->写->审->修订->保存”显式建模为状态机，支持可恢复、可跳步、可插拔策略
- 生成-审校闭环：把一致性报告反馈回写作环节，支持多轮修订（draft -> check -> revise -> final）
- 回写与增量索引：将产出的结构化信息（人物状态、时间线事件、设定条目）写回到长期存储，并支持增量更新索引
- 检索质量：更细粒度的 scope/layer、BM25/向量混检、rerank、证据片段去噪与引用格式统一
- 配置与可复现性：run_config 版本化、schema 兼容策略、可复用的“运行模板”（preset）
- 评测与可观测：离线基准集、自动一致性评分、检索命中率指标、run 级别 telemetry
- 交互形态：提供更友好的 CLI 参数组、或最小 Web/UI（查看 sources、plan、report、diff）
