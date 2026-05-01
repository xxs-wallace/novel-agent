# Novel Agent

Novel Agent 是一个面向作者的小说续写工作台，用于把长篇原文导入本地、完成粗读/精读建模、构建创作知识库，并在人工审阅确认的节奏下生成后续章节。

本项目基于 [huggingface/smolagents](https://github.com/huggingface/smolagents.git) 研发，继续复用其 Agent、Tool 与模型接入能力，并在此基础上扩展了小说续写相关的 `novel_agent` 模块和统一 CLI / TUI 工作台。

## 主要功能

- 原文导入与粗读：把小说原文切分并写入本地索引，形成后续建模的 `documents` 基线。
- 精读建模：抽取章节信息、人物档案、世界观摘要、故事大纲和事实型记忆。
- Creative KB：构建桥段卡片、结构模式与风格参考，用于续写时检索相似桥段。
- Writer 分层生成：按“全书规划 -> 批次大纲 -> 章节梗概 -> 长度计划 -> 写作材料 -> 正文草稿 -> 验收写回”的流程推进。
- 人工审阅与可恢复运行：每个关键产物都先展示摘要，用户可以修改、保存、确认，再进入下一步。
- 统一 CLI / TUI：粗读、精读、知识库和 Writer 不再分散在多个用户入口中，而是在同一个工作台里切换。

## 环境准备

需要 Python 3.10 及以上版本。推荐直接使用仓库根目录的启动脚本，它会自动创建或复用 `.venv` 并安装缺失依赖：

```bash
./novel-agent
```

如果希望手动安装：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[openai]"
```

本项目默认使用 DeepSeek 兼容 OpenAI 的接口能力。运行前请设置 `DEEPSEEK_API_KEY`：

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
```

也可以把 key 放在自己的 shell 配置或本地环境管理工具中，只要启动 `novel-agent` 时进程能读取到 `DEEPSEEK_API_KEY` 即可。

## 启动 CLI 工作台

开发者推荐入口：

```bash
./novel-agent
```

安装为 console script 后也可以使用：

```bash
novel-agent
```

等价的开发调试入口：

```bash
python -m novel_agent.app.cli_tui
```

启动后会进入 Textual 全屏 TUI。首屏会提供常用动作，例如选择或创建任务、继续上次会话、导入/粗读原文、运行精读建模、查看建模状态、构建 Creative KB、开始或恢复 Writer。

旧入口 `python -m novel_agent.app.run_interactive` 仅保留给 smoke、兼容测试和迁移期调试，不再作为正式用户入口。

## 基本使用流程

1. 设置 `DEEPSEEK_API_KEY`。
2. 运行 `./novel-agent` 进入工作台。
3. 使用 `/new-task <task_id> <source_path>` 创建任务，或用 `/tasks` 查看已有任务。
4. 使用 `/read` 导入并粗读原文。
5. 使用 `/close-read` 运行精读建模。
6. 使用 `/kb` 构建或查看 Creative KB。
7. 使用 `/writer` 开始或恢复分层续写。
8. 在每个审阅节点中修改、保存、确认产物，确认后系统才会进入下一步。

其中 `task_id` 对应同一本书在粗读、精读、Creative KB 和 Writer 中共用的 `book_id`。

## 主要命令

| 命令 | 用法 |
| --- | --- |
| `/status` | 查看当前项目的原文、精读记忆、人物档案、世界观、故事大纲、Creative KB 与 Writer 状态。 |
| `/tasks` | 列出所有任务，以及 documents、chapters、粗读进度和精读进度。 |
| `/task <task_id>` | 进入指定任务。 |
| `/new-task <task_id> <source_path>` | 创建新任务并记录原文路径。 |
| `/reset-close-read` | 清空当前任务的精读进度与派生产物，保留粗读 documents。 |
| `/read` | 进入原文导入/粗读流程。 |
| `/close-read` | 进入精读与记忆抽取流程。 |
| `/kb` | 构建或查看 Creative KB。 |
| `/writer` | 开始或恢复 Writer 分层生成。 |
| `/resume` | 恢复最近一次未完成流程。 |
| `/artifacts` | 查看当前会话产物。 |
| `/open` | 打开当前重点产物。 |
| `/save` | 保存当前 artifact 编辑内容。 |
| `/confirm` | 确认当前审阅步骤，并允许系统继续推进。 |
| `/back` | 在 Writer 审阅流程中返回上一层可修改节点。 |
| `/help` | 查看当前上下文可用操作。 |
| `/debug` | 查看内部 stage、run id、artifact path 等技术详情。 |

常用快捷键：

| 快捷键 | 行为 |
| --- | --- |
| `Enter` | 发送当前输入。 |
| `Shift+Enter` | 在输入框内换行。 |
| `Ctrl+P` | 打开命令面板。 |
| `Ctrl+S` | 保存当前 artifact。 |
| `Ctrl+Enter` | 确认当前审阅步骤。 |
| `Ctrl+O` | 打开当前重点 artifact。 |
| `Esc` | 关闭弹层；运行中可请求暂停。 |

## Writer 审阅节点

Writer 不会直接“一键吐出全文”，而是按可审阅、可修改、可恢复的方式推进：

1. 生成并审阅全书续写规划。
2. 生成并审阅本批剧情大纲。
3. 生成并审阅章节标题与故事梗概。
4. 规划并确认章节长度。
5. 整理并确认本章写作材料。
6. 生成正文草稿并进行连续性检查。
7. 用户接受、调整长度重生成、退回重规划或作废。
8. 接受后写回章节、记忆与运行产物。

用户在审阅节点修改后的内容，会作为后续流程的准绳。例如修改批次剧情大纲后，章节梗概会基于修改后的大纲继续生成。

## 运行产物

项目会在本地保存索引、记忆和运行产物，常见目录包括：

- `.indexes/`：每个任务对应的本地 SQLite 索引。
- `.memory/`：世界观、故事大纲、源作品篇章地图等长期记忆产物。
- `runs/`：Writer 运行过程中的规划、草稿、连续性检查和写回产物。

大体量正文默认在界面中只展示摘要和路径，完整内容通过 artifact 文件访问。

## 与 smolagents 的关系

本仓库保留并复用 [huggingface/smolagents](https://github.com/huggingface/smolagents.git) 的基础能力，包括：

- `CodeAgent` / `ToolCallingAgent`
- `Tool` 体系
- OpenAI-compatible、LiteLLM、InferenceClient、Transformers 等模型接入方式
- 原有 `smolagent`、`webagent` 命令

Novel Agent 是在这些能力之上扩展出的小说续写产品层。正式小说续写入口请使用 `./novel-agent` 或 `novel-agent`。

## 开发与测试

安装开发依赖：

```bash
pip install -e ".[dev,openai]"
```

运行测试：

```bash
python -m pytest novel_agent/tests tests
```

只验证 CLI / TUI 入口时可运行：

```bash
python -m pytest novel_agent/tests/test_cli_tui_entrypoint.py novel_agent/tests/test_cli_textual_components.py
```
