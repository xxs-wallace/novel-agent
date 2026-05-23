# 小说续写系统核心流程与交互 Spec

## Purpose

本文是 `.trae/specs` 目录下所有小说续写相关 spec 的产品级 Source of Truth。

本 spec 只定义用户可见的核心流程、交互界面、状态文案与人工确认规则；各子模块只定义自己的内部能力与数据边界：

- 总编排与本地入库：[`novel-continuation-mvp/spec.md`](novel-continuation-mvp/spec.md)
- 统一 CLI / TUI 交互设计：[`cli-interface/design.md`](cli-interface/design.md)，开发任务：[`cli-interface/tasks.md`](cli-interface/tasks.md)
- 事实型 Memory 与上下文：[`narrative-memory-context/spec.md`](narrative-memory-context/spec.md)
- 统一叙事索引框架：[`narrative-indexer/spec.md`](narrative-indexer/spec.md)
- 创作知识库与桥段检索：[`creative-knowledge-base/spec.md`](creative-knowledge-base/spec.md)，作为 Narrative Indexer 下的创作参考索引族
- Writer 分层生成：[`writer-agent-layered-generation/spec.md`](writer-agent-layered-generation/spec.md)
- Outline Analyzer 只读剧情分析：[`outline-analyzer/spec.md`](outline-analyzer/spec.md)
- 评测与 benchmark：[`agentic-benchmark/spec.md`](agentic-benchmark/spec.md)

## Product Principle

小说续写产品的主界面不是开发者日志，也不是一次性命令输出，而是一个面向作者的“续写工作台”。

系统 SHALL 让用户始终知道：

- 当前在做哪一步
- 系统刚生成了什么
- 哪些内容需要用户审阅或修改
- 用户确认后下一步会发生什么
- 完整文件保存在哪里

系统 SHALL NOT 在用户界面中暴露只有开发者能理解的状态文案，例如：

- `artifact saved`
- `Freeze B pending`
- `freeze_d_review`
- `wait_chapter_acceptance`
- `checkpoint confirmed`

这些内部状态可以保留在代码、日志、JSON 与开发者文档中，但用户界面必须翻译成自然语言流程状态。

## Product Interfaces

系统面向用户只保留三类入口：

1. `CLI 交互式界面`
   - 面向作者和开发者日常使用。
   - 承载完整续写工作台、分层审阅、原地修改、保存与继续。
   - 必须遵守本文定义的用户可见流程和状态文案。
   - 详细交互结构见 [`cli-interface/design.md`](cli-interface/design.md)。

2. `跨平台 GUI 界面`
   - 面向不希望直接操作终端的用户。
   - 与 CLI 共享同一套流程语义、状态文案、artifact 审阅规则和继续执行规则。
   - 不得只把命令行日志包装成 GUI；必须提供结构化审阅与编辑界面。

3. `Python 冒烟测试脚本`
   - 仅用于自动化测试、集成验证、最小样例和 CI。
   - 可以暴露内部状态名和 JSON artifact。
   - 不作为正式用户产品接口，不承担完整交互体验。

系统 SHALL NOT 继续维护面向用户的旧式 one-shot MVP CLI 入口。旧单场景或旧工具链能力若仍被测试或迁移流程依赖，SHOULD 作为内部兼容实现存在，而不是产品入口。

## Core Orchestration

核心总编排层负责把所有模块串成可恢复、可审阅、可继续的产品流程。

系统 SHALL 在核心流程中调度：

- 原文导入与 `documents` 基线构建
- 精读、人物档案、世界观、故事大纲与源作品篇章地图
- Narrative Indexer 多维索引卡片
- 创作知识库、桥段卡片、结构模式与桥段参考检索
- Writer 分层生成：全书规划、设定补全、人物补充、批次规划、章节梗概、长度计划、正文执行、验收与写回
- 运行产物保存、检查点恢复、用户修改后的继续执行

总编排层 SHALL 以“用户确认后的内容”为后续流程的准绳：

- 用户修改全书续写规划后，后续批次规划必须使用修改后的规划。
- 用户修改批次剧情大纲后，章节梗概必须基于修改后的大纲生成。
- 用户修改章节梗概后，正文写作材料必须重新确认。
- 用户修改长度计划后，当前章正文生成必须使用新的长度预算。

总编排层 SHALL 将模块内部状态翻译为用户可理解的流程状态。内部对象名、冻结点、检查点和 artifact 名称可以记录在技术详情中，但不作为主状态展示。

## Core User Flow

### 1. 建模准备

目标：确认系统是否已经读懂原作，并提示缺失项。

用户可见界面 SHALL 展示：

- 原文是否已入库
- 精读记忆是否可用
- 人物档案是否可用
- 世界观摘要是否可用
- 故事大纲是否可用
- 桥段知识库是否可用
- 源作品篇章地图是否可用
- 结构模式参考是否可用

若缺失必要项，系统 SHALL 显示普通用户能执行的建议，例如：

- “还没有导入原文，请先运行粗读/精读。”
- “还没有人物档案，建议先完成精读建模。”
- “还没有桥段知识库，续写时会缺少风格与桥段参考。”

### 2. 输入续写方向

目标：让用户用自然语言给出后续剧情方向。

用户可见界面 SHALL 支持输入：

- 主要人物
- 想让人物做什么
- 希望避免什么
- 倾向结局或阶段目标
- 世界观补充或修订
- 其他备注

输入区 SHOULD 支持中文、多行编辑、粘贴长文本与干净回退。

### 3. 审阅全书续写规划

目标：在进入批次规划前，让用户确认后续大方向、世界观补充与人物补充。

系统 SHALL 展示：

- 全书续写规划
- 世界观补充方案
- 新角色或缺位角色检查结果
- 人物补充方案
- 未决问题

用户可见状态 SHOULD 使用：

- “正在生成全书续写规划”
- “请审阅全书续写规划”
- “全书续写规划已确认”

系统 SHALL 允许用户修改规划内容后保存，并以修改后的内容作为后续流程依据。

### 4. 审阅批次剧情大纲

目标：确认最近一批章节或小篇章的剧情走向。

系统 SHALL 展示当前批次的：

- 起点状态
- 阶段目标
- 主要冲突
- 情绪节奏
- 角色登场或推进安排
- 预计收束点
- 结构模式参考

用户可见状态 SHOULD 使用：

- “正在生成本批剧情大纲”
- “请审阅本批剧情大纲”
- “本批剧情大纲已确认”

系统 SHALL 允许用户原地修改、保存并继续。

### 5. 审阅章节标题与故事梗概

目标：确认每章写什么，而不是直接进入正文生成。

系统 SHALL 展示：

- 章节标题
- 每章目标
- 情绪目标
- 冲突目标
- 关系推进目标
- 本章结束时应改变什么
- 禁止写入的内容

用户可见状态 SHOULD 使用：

- “正在生成章节标题与梗概”
- “请审阅章节标题与梗概”
- “章节梗概已确认”

系统 SHALL 支持逐章确认，也 SHOULD 支持整批确认。

### 6. 审阅章节长度计划

目标：在正文生成前确认字数预算与重点章节。

系统 SHALL 展示：

- 默认目标字数
- 每章目标字数
- 每章最小/最大建议字数
- 重点章节
- 高潮章节
- 展开建议

用户可见状态 SHOULD 使用：

- “正在规划章节长度”
- “请确认章节长度”
- “章节长度已确认”

系统 SHALL 支持用户直接输入覆盖值，也 SHALL 支持用户修改长度计划文件后继续。

### 7. 准备本章写作输入

目标：让用户确认本章正文生成会使用哪些约束与参考。

系统 SHALL 展示：

- 当前章节梗概
- 本章长度预算
- 事实型上下文摘要
- 风格与桥段参考摘要
- 禁止项
- 计划登场角色约束

用户可见状态 SHOULD 使用：

- “正在整理本章写作材料”
- “请确认本章写作材料”
- “本章写作材料已确认”

### 8. 生成与校验正文

目标：生成正文草稿，并检查连续性。

系统 SHALL 对大体量正文采用摘要展示：

- 草稿文件路径
- 当前字数
- 目标字数
- 开头短预览
- 连续性检查结果
- 需要用户注意的问题

草稿预览默认 SHOULD 控制在 1-2KB，完整正文 SHALL 通过文件路径访问。

用户可见状态 SHOULD 使用：

- “正在生成正文草稿”
- “正在检查连续性”
- “正文草稿已生成”
- “发现需要确认的问题”

### 9. 验收当前章节

目标：让用户决定草稿是否进入正式结果。

系统 SHALL 提供以下用户动作：

- 接受本章
- 调整字数后重写
- 修改章节梗概后重写
- 作废本次草稿
- 暂不决定，稍后继续

用户可见状态 SHOULD 使用：

- “请验收当前章节”
- “本章已接受，等待确认写回”
- “将返回长度计划调整”
- “将返回章节梗概调整”
- “本次草稿已作废”

### 10. 确认写回

目标：在把草稿纳入后续记忆与已接受章节前，给用户最后确认。

系统 SHALL 展示：

- 本章最终草稿路径
- 将写回的章节摘要
- 将更新的人物状态
- 将更新的关系或世界观状态
- 已接受章节汇总路径

用户可见状态 SHOULD 使用：

- “请确认写回”
- “正在更新续写记忆”
- “本章已完成”

## User-Facing Status Vocabulary

系统内部 MAY 使用 `freeze_a`、`freeze_b`、`checkpoint`、`artifact` 等术语。

用户界面 SHALL 使用以下状态词汇：

| 内部概念 | 用户可见说法 |
|---|---|
| `modeling_status` | 建模准备情况 |
| `freeze_a_review` | 请审阅全书续写规划 |
| `freeze_a` | 全书续写规划已确认 |
| `batch_review` / `freeze_b_review` | 请审阅本批剧情大纲 |
| `freeze_b` | 本批剧情大纲已确认 |
| `chapter_review` / `freeze_c_review` | 请审阅章节标题与梗概 |
| `freeze_c` | 章节梗概已确认 |
| `wait_length_review` | 请确认章节长度 |
| `length_confirmed` | 章节长度已确认 |
| `freeze_d_review` | 请确认本章写作材料 |
| `freeze_d` | 本章写作材料已确认 |
| `execute_current_chapter` | 正在生成正文草稿 |
| `wait_chapter_acceptance` | 请验收当前章节 |
| `writeback_review` | 请确认写回 |
| `freeze_e` | 本章已完成 |
| `artifact saved` | 已保存你的修改 |
| `checkpoint confirmed` | 已确认，继续下一步 |
| `pending` | 等待你确认 |
| `halted` | 已暂停 |

界面文案 SHALL 避免把 “Freeze A/B/C/D/E” 作为主要状态显示。若需要提供开发者信息，可放在折叠的“技术详情”中。

## CLI / TUI Interaction Requirements

详细 CLI / TUI 信息架构、命令面板、状态侧栏、artifact 审阅、read pipeline 与 Writer 合并入口设计，见 [`cli-interface/design.md`](cli-interface/design.md)。

### Requirement: 中文友好的输入

系统 SHALL 使用能正确处理中文宽字符、输入法组合态、退格删除、多行粘贴与历史记录的输入组件。

#### Scenario: 中文回退

- **WHEN** 用户输入中文、英文、标点混排文本
- **THEN** 光标移动、退格删除、行内编辑都不应留下残影或半个字符

### Requirement: 输出与输入分离

系统 SHALL 将运行输出、审阅内容、状态栏与输入区分区展示。

#### Scenario: 模型运行时输出

- **WHEN** 系统正在生成规划、检索桥段或生成正文
- **THEN** 运行日志不得覆盖或插入到用户正在编辑的输入框中

### Requirement: 重点高亮

系统 SHALL 对关键信息进行高亮或结构化展示。

#### Scenario: 审阅规划产物

- **WHEN** 系统展示规划类产物
- **THEN** 至少高亮章节标题、目标、冲突、关系推进、禁止项、待确认问题、文件路径与下一步动作

### Requirement: 原地修改与保存

系统 SHALL 支持用户在交互界面中修改关键规划产物并保存。

#### Scenario: 修改批次剧情大纲

- **WHEN** 用户在“请审阅本批剧情大纲”阶段修改内容并保存
- **THEN** 后续章节梗概必须基于用户保存后的大纲生成
- **AND** 系统 SHALL 提示“已保存你的修改”

### Requirement: 大体量正文摘要展示

系统 SHALL 避免把完整正文、完整检索上下文或大型 JSON 直接刷满终端。

#### Scenario: 草稿展示

- **WHEN** 草稿生成完成
- **THEN** 终端默认只展示路径、字数、目标字数、校验状态与开头短预览

## GUI Interaction Requirements

若提供桌面 GUI，GUI SHALL 与 CLI/TUI 共享同一套流程语义和用户可见状态文案。

GUI SHOULD 至少包含：

- 左侧或主区域：运行消息与审阅内容
- 右侧或底部：当前步骤、可执行动作、参数输入
- 独立审阅编辑区：用于修改规划产物
- 状态区：显示用户可理解的当前流程状态

GUI SHALL NOT 只把 subprocess stdout 当作唯一界面。日志可以存在，但不能替代结构化审阅界面。

## Module Responsibilities

### 总编排层

负责把原文导入、Memory、创作知识库、Writer 和运行产物串成可恢复流程。

详见 [`novel-continuation-mvp/spec.md`](novel-continuation-mvp/spec.md)。

### Memory 层

负责事实、人物、世界观、章节摘要、故事大纲、源作品篇章地图和上下文装配。

详见 [`narrative-memory-context/spec.md`](narrative-memory-context/spec.md)。

### 创作知识库层

负责桥段卡片、桥段聚类、代表片段、结构模式参考与在线检索。

详见 [`creative-knowledge-base/spec.md`](creative-knowledge-base/spec.md)。

### Writer 层

负责全书规划、世界观补充、人物补充、批次规划、章节梗概、正文生成、章节验收与写回。

详见 [`writer-agent-layered-generation/spec.md`](writer-agent-layered-generation/spec.md)。

### Benchmark 层

负责验证系统在授权输入边界内能否生成连续性正确的合法后继。

详见 [`agentic-benchmark/spec.md`](agentic-benchmark/spec.md)。

## Non-Goals

本 spec 不定义：

- 数据库表字段细节
- prompt JSON schema 的完整字段
- 模型供应商配置
- 具体代码类名
- 具体 GUI 框架
- benchmark 打分细则

这些内容由各子模块 spec、design、contracts 或 tasks 文档定义。
