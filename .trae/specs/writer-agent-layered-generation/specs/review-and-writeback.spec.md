# Review And Writeback Spec

## Purpose

该子 spec 负责承载章节验收、`GenerationReviewDecision`、`Freeze E` 与 accepted-only writeback 的产品语义。

## Scope

- 章节验收与重生成入口
- `GenerationReviewDecision` 的产品语义
- `Freeze E` 的进入条件
- 仅 accepted 才允许回写的规则
- review / writeback 相关运行产物
- 章节草稿审阅时的大体量正文展示策略

## Source Of Truth

- Parent overview: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md)
- Parent architecture: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
- Review contracts: [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)

## Review Goals

- 对正文执行连续性、人物、关系、时间线、设定一致性检查
- 在进入正式回写前提供显式章节验收节点
- 提取本章造成的真实状态变化并写回 Memory
- 保证下一章只消费“已验收且已回写”的 canon 状态

## Layer 5 Summary

典型输出：

- `ContinuityReport`
- `StateDelta`
- `MemoryWriteback`
- `BatchProgressUpdate`
- `GenerationReviewDecision`

要求：

- 未通过关键校验的正文不得直接进入下一章输入
- 未回写状态的正文不得视为“已成为 canon”
- 未被用户接受的正文不得写回人物档案、关系状态、时间线、世界状态或创作知识库
- 被用户作废或被后续版本替换的草稿只保留在 `runs` 等临时产物中，不进入正式 Memory / KB

`GenerationReviewDecision`、`LengthPlanUpdate` 与 `ChapterReplanRequest` 的正式字段、状态枚举、边界约束与 JSON Schema 草案，以 [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md) 为准。

## Acceptance Decision Semantics

在本 spec 中仅保留其产品语义：

- `GenerationReviewDecision.status = accepted`
  - 允许进入 `Freeze E`
  - 允许执行正式回写
  - 该版本可成为当前章 canon
- `GenerationReviewDecision.status = revise_length`
  - 退回长度规划层
  - 旧版本保留在运行产物中
  - 不触发正式回写
- `GenerationReviewDecision.status = replan_chapter`
  - 退回章节梗概层
  - 系统必须重新生成或确认对应的 `ChapterLengthPlan`
  - 不触发正式回写
- `GenerationReviewDecision.status = discarded`
  - 当前版本仅保留 `runs` 产物
  - 不触发正式回写
  - 不得被后续章节视为 canon

## Freeze E And Writeback Gate

`Freeze E` 代表“本章已验收终稿与状态变化冻结”。

规则：

- `Freeze E` 之前允许存在多个草稿版本
- 只有被用户接受的版本才可视为正式输入并触发回写
- `Freeze E` 前，用户可接受本章、调整长度后重生成、退回章节梗概重规划，或作废本次草稿
- `Freeze E` 后，系统回写状态，并决定是否自动进入下一章

## Review Display Policy

章节验收节点必须展示足够信息让用户判断是否接受，但不能把长正文完整刷入 terminal：

- `draft.md` SHOULD 只展示 artifact 路径、字数、目标字数、连续性状态和开头短预览
- 默认短预览不应超过约 1-2KB
- 完整正文应通过文件路径供用户打开或编辑
- `continuity_report.json`、`generation_review_decision.json` 等结构化审阅产物可完整展示

## Requirements

### Requirement: 章节生成后必须支持验收或重生成

系统 SHALL 在章节通过基础校验后提供一个显式验收节点，并输出结构化 `GenerationReviewDecision`，允许用户接受、调整长度后重生成、退回章节梗概重规划，或作废本次草稿。

#### Scenario: 展示草稿审阅信息
- **WHEN** 系统进入章节验收节点
- **THEN** 交互界面应展示 `draft.md` 路径、当前字数、目标字数、连续性状态与开头短预览
- **AND** 不应在 terminal 中输出完整草稿正文
- **AND** 应完整展示或提示 `generation_review_decision.json` 的可编辑位置

#### Scenario: 用户接受当前章
- **WHEN** 当前章草稿已通过关键连续性检查，且用户选择接受
- **THEN** 系统将 `GenerationReviewDecision.status` 记为 `accepted`
- **AND** 将该版本视为当前章正式终稿
- **AND** 才允许进入 `Freeze E` 与回写流程

#### Scenario: 用户要求调整长度重生成
- **WHEN** 当前章草稿已生成，但用户认为长度不合适
- **THEN** 系统将 `GenerationReviewDecision.status` 记为 `revise_length`
- **AND** 允许用户回退到 `ChapterLengthPlan` 审阅并更新该章长度参数后重新生成
- **AND** 旧版本保留在运行产物中，但不进入正式 Memory / KB

#### Scenario: 用户不接受当前章并退回章节梗概层
- **WHEN** 当前章草稿虽已生成，但用户认为本章方向、结构或展开方式不可接受
- **THEN** 系统将 `GenerationReviewDecision.status` 记为 `replan_chapter`
- **AND** 回退到章节梗概审阅层，允许用户修改当前部分 `ChapterPackage / ChapterBrief`
- **AND** 系统必须重新生成或确认该部分对应的 `ChapterLengthPlan`
- **AND** 旧版本仅保留在运行产物中，不得进入正式 Memory / KB

#### Scenario: 用户作废当前章
- **WHEN** 当前章草稿未被用户采纳
- **THEN** 系统将 `GenerationReviewDecision.status` 记为 `discarded`
- **AND** 将当前草稿标记为 `discarded` 或 `superseded`
- **AND** 不得回写人物档案、关系状态、时间线、世界状态或创作知识库

### Requirement: 章节终稿必须回写状态

系统 SHALL 在章节通过校验后提取状态变化并回写到 Memory 层。

#### Scenario: 写后回写
- **WHEN** 本章 `final` 确认
- **THEN** 系统至少回写人物状态、关系状态、时间线事件、世界状态变化和大纲进度

#### Scenario: 未验收草稿不得回写
- **WHEN** 某个草稿版本尚未被用户接受，或已被新版本替换
- **THEN** 系统不得将该版本产生的状态变化写回 Memory
- **AND** 不得让后续章节将该版本视为 canon

## Artifact Expectations

review / writeback 相关产物至少包括：

- `draft.md`
- `generation_review_decision.json`
- `continuity_report.json`
- `state_delta.json`
- `memory_writeback.json`

是否还需要落盘 `length_plan_update.json` 与 `chapter_replan_request.json`，以 [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md) 与对应实现任务为准。

## Non-Goals

- 不在本子 spec 中重新定义 `GenerationReviewDecision` 的字段结构
- 不在本子 spec 中展开全局 workflow 其他层的完整状态机
- 不在本子 spec 中定义 Layer 1 到 Layer 4 的详细规划逻辑
