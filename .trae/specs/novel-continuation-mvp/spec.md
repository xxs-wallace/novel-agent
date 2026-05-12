# 小说续写本地入库与运行基础 Spec

## Source Of Truth

- 产品级核心流程、总编排、用户接口、UI 交互与用户可见状态文案，以 [`../spec.md`](../spec.md) 为准。
- 本 spec 只定义本仓库内的本地运行基础：`novel_agent/` 模块、原文导入、`documents` 基线、粗读/分段运行器与运行产物存储。
- 旧 one-shot MVP 续写入口不再作为正式产品接口维护；正式入口只包括核心 spec 定义的 CLI 交互式界面、跨平台 GUI 界面和 Python 冒烟测试脚本。

## Purpose

本模块负责把原始小说稳定转换为后续 Memory、创作知识库和 Writer 分层生成都能消费的本地数据基线。

它不负责：

- 产品主流程编排
- 用户交互体验
- Writer 分层生成
- 创作知识库字段设计
- Memory 字段设计
- 跨层 contract 的完整定义

相关模块：

- 核心流程与总编排：[`../spec.md`](../spec.md)
- 跨层 contract：[`contracts.md`](contracts.md)
- Memory 层：[`../narrative-memory-context/spec.md`](../narrative-memory-context/spec.md)
- 创作知识库层：[`../creative-knowledge-base/spec.md`](../creative-knowledge-base/spec.md)
- Writer 层：[`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md)

## Module Boundary

### 本模块负责

- 在仓库内提供 `novel_agent/` 边车模块
- 解析用户指定的小说文件或目录
- 判断目录结构与读取策略
- 将原文切分并写入 SQLite `documents`
- 维护粗读/分段进度
- 为后续 Memory、KB、Writer 提供稳定的 document 基线
- 为 Python 冒烟测试脚本提供可重复执行的本地运行基础

### 本模块不负责

- 直接面向用户展示完整续写流程
- 决定 Writer 的全书规划、批次规划或章节梗概
- 维护人物档案、世界观、故事大纲或源作品篇章地图
- 构建桥段卡片、聚类或 rerank
- 生成正式续写正文
- 定义用户可见状态文案

## Requirements

### Requirement: Novel Agent 模块独立运行

系统 SHALL 在仓库内提供 `novel_agent/` 模块，且不依赖修改 `src/smolagents/*` 核心抽象即可运行。

#### Scenario: 初始化与导入

- **WHEN** 以本仓库 Python 环境运行 `novel_agent` 的入口脚本
- **THEN** 能成功 import `smolagents` 并构造所需运行器、服务和模型客户端

### Requirement: Document 基线

系统 SHALL 将原始小说转换为 SQLite 中的 `documents`，作为 Memory、KB 与 Writer 的统一输入基线。

#### Scenario: 构建索引

- **WHEN** 系统执行原文导入或分段流程
- **THEN** 默认生成或更新 `.indexes/<book_id>.db`
- **AND** 该数据库可被粗读、精读、检索、Writer 独立 memory 副本和冒烟测试复用

#### Scenario: Document 基础字段

- **WHEN** 一个 document 被写入 SQLite
- **THEN** 至少包含：
  - `doc_id`
  - `book_id`
  - `content`
  - `document_title`
  - `document_title_index`
  - `source_path`
  - `source_start_offset`
  - `source_end_offset`

### Requirement: 小说目录分析与读取策略

系统 SHALL 支持文件、单书目录、多章节文件和多书目录的基础读取策略判断。

#### Scenario: 目录结构分析

- **WHEN** 用户指定一个目标目录，目录中可能包含单文件、多章节文件或多书目录
- **THEN** 系统先分析目录结构
- **AND** 输出可复用的读取策略或等价配置

### Requirement: 本地预切与分段保护

系统 SHALL 在发送模型前先执行本地预切，降低模型直接处理超长原文的风险。

#### Scenario: 分段输入保护

- **WHEN** 粗读/分段流程准备处理一批原文
- **THEN** 系统 SHALL 先在本地预切 `segments`
- **AND** 模型主要返回 `segment_ids` 分组与结构化元信息
- **AND** 系统在 JSON 非法或分组失效时支持自动重试、批次减半重试与 deterministic fallback

### Requirement: 粗读阶段不做正式人物建档

系统 SHALL 将人物档案维护留给 Memory 层。

#### Scenario: 粗读入库

- **WHEN** 系统完成 document 切分
- **THEN** `documents.character_keywords_json` 在粗读入库时可以为空数组或轻量候选
- **AND** 正式人物抽取、人物证据判断与人物档案更新 SHALL 由 Memory 层负责

### Requirement: Python 冒烟测试支持

系统 SHALL 为测试和集成验证保留可脚本化运行能力。

#### Scenario: 冒烟测试脚本

- **WHEN** 测试脚本需要构建最小数据库、运行部分流程或验证产物
- **THEN** 可以直接调用本模块的运行器、服务或命令入口
- **AND** 冒烟测试脚本可以输出内部 JSON、检查点和 artifact 路径
- **AND** 这些脚本不被视为正式用户产品接口

## Storage Notes

- 默认用户任务数据库 SHOULD 使用 `.indexes/<book_id>.db`。
- Writer 独立 memory 副本 MAY 使用 `.indexes/writer/<book_id>.db`。
- 运行产物 SHOULD 写入 `runs/` 下的任务目录，并由核心总编排和 Writer 层决定具体 artifact 集合。

## Non-Goals

- 不保留旧 one-shot MVP 续写闭环作为正式产品需求。
- 不要求维护旧 `save_run_artifacts` 工具作为产品接口。
- 不在本文中重复 `SceneBrief`、`ContextAssemblyPayload`、`WriterInputBundle` 等跨层 contract。
- 不在本文中定义 CLI/TUI/GUI 的交互布局与状态文案。
