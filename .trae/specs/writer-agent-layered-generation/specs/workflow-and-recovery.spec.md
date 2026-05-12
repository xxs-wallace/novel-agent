# Workflow And Recovery Spec

## Purpose

该子 spec 负责承载工作流确认点、冻结点恢复、失败回退与级联回滚的产品语义。

## Scope

- 用户确认点与恢复点
- `Freeze A/B/C/D/E` 的工作流语义
- 失败恢复与重试边界
- 上游修改触发的级联回滚
- rejection path 对工作流的影响
- 交互式工作流中各类 artifact 的展示策略
- `ChapterLengthPlan` 的人工审阅与交互式调整

## Source Of Truth

- Parent overview: [spec.md](.trae/specs/writer-agent-layered-generation/spec.md)
- Parent architecture: [design.md](.trae/specs/writer-agent-layered-generation/design.md)
- Review contracts: [writer-agent-layered-generation/contracts.md](.trae/specs/writer-agent-layered-generation/contracts.md)

## Freeze Point Semantics

系统必须定义以下冻结点，避免上下层互相污染：

- `Freeze A`: 全书续写方向冻结
- `Freeze B`: 当前批次计划冻结
- `Freeze C`: 最近 N 章梗概冻结
- `Freeze D`: 单章写作 brief 冻结
- `Freeze E`: 本章已验收终稿与状态变化冻结

规则：

- 低层不得绕过高层冻结点直接篡改大纲
- 若正文写作发现上游规划不可执行，必须发起“重规划请求”，而不是自行改写
- 每一层冻结后，其产物对下一层来说视为只读正式输入，而不是可被下游局部修补的建议稿
- `Freeze C` 固定指向已确认的 `ChapterPackage` / 最近 N 章梗概，不等同于 `WriterInputBundle`
- `Freeze D` 固定指向当前待写章节的 `ChapterBrief` 及其派生检索意图，不等同于最终正文
- `Freeze D` 还应覆盖当前章已确认的长度预算与重点展开标记
- 若启用了人物补充流程，则 `Freeze A` 还应覆盖 `WorldExpansionPack` 与 `CharacterCastPlan`
- `Freeze E` 的详细门禁规则以 [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md) 为准

## Rollback And Invalidation Rules

级联回滚规则：

- 若修改 `Freeze D` 对应的单章 `ChapterBrief`，则该章的 `SceneBrief`、检索结果、`WriterInputBundle`、正文、`StateDelta` 与其后续章节产物全部失效并回滚
- 若修改 `Freeze C` 对应的 `ChapterPackage`，则该包内对应章节及其之后章节的所有下游产物全部失效并回滚
- 若修改 `Freeze B` 对应的 `BatchPlan`，则该批次的 `ChapterPackage`、`ChapterBrief`、正文与回写结果全部失效，并且后续批次产物一并回滚
- 若修改 `Freeze A` 对应的 `BookContinuationPlan`、`WorldExpansionPack` 或 `CharacterCastPlan`，则全部后续 `BatchPlan`、章节梗概、正文和回写结果全部失效并回滚
- 若修改某个尚未正式登场的 `PlannedCharacterProfile`，则所有引用该角色的 `BatchPlan`、`ChapterPackage`、`ChapterBrief`、`SceneBrief`、检索结果、`WriterInputBundle` 与正文草稿全部失效并回滚
- 若修改某个已经进入 `canon_active` 的计划角色设定，则系统不得静默覆盖 Memory；必须提示用户保留既有 canon、回滚首次登场章及之后章节，或分叉为替代角色方案

## Workflow Checkpoints

与用户交互的对应关系：

- `Freeze A` 前：用户确认续写方向、世界观补充与人物补充方案
- `Freeze B` 前：用户审阅并可修改批次剧情大纲；交互界面应完整展示 `BatchPlan`
- `Freeze C` 前：用户审阅并确认最近 N 章标题与梗概；交互界面应完整展示 `ChapterPackage`
- `Freeze D` 前：用户可选择单章开写前再做一次微调，并确认本章长度预算；交互界面应完整展示 `ChapterLengthPlan` 并询问是否调整长度
- `Freeze E` 前后的章节验收与回写流程，以 [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md) 为准

终端交互还应区分规划产物与大体量正文：

- 中间规划产物应完整展示，便于用户直接判断是否继续
- 大体量正文和完整检索上下文应只展示路径、元数据与短预览，避免 terminal 缓冲区被刷满

## Requirements

### Requirement: 用户确认点必须可恢复

系统 SHALL 将用户确认后的中间产物视为可恢复检查点。

#### Scenario: 从确认点恢复
- **WHEN** 用户已经确认世界观、全书续写方向、批次大纲或章节梗概
- **THEN** 系统可以从对应冻结点恢复
- **AND** 不要求用户重复走完整个流程

### Requirement: 交互式工作流必须展示可审阅规划产物

系统 SHALL 在等待用户确认的规划节点展示对应生成内容，而不是只展示文件路径。

#### Scenario: 展示批次与章节规划
- **WHEN** 工作流进入 `batch_review`、`chapter_review` 或 `wait_length_review`
- **THEN** 交互界面应完整展示对应的 `BatchPlan`、`ChapterPackage` 或 `ChapterLengthPlan`
- **AND** 同时展示 artifact 路径，允许用户编辑文件后继续

#### Scenario: 大体量 artifact 使用短预览
- **WHEN** 工作流需要提示用户审阅 `draft.md`、完整检索上下文或其他大体量 artifact
- **THEN** 交互界面应展示路径、字数/目标字数、状态摘要与开头短预览
- **AND** 不应把完整正文直接输出到 terminal

### Requirement: 长度计划必须支持交互式调整

系统 SHALL 在 `wait_length_review` 阶段询问用户是否需要调整章节长度，并支持修改后继续。

#### Scenario: 用户调整长度计划
- **WHEN** 用户在 `wait_length_review` 选择调整长度
- **THEN** 系统应支持用户输入默认长度覆盖值、单章 override，或修改 `chapter_length_plan.json`
- **AND** 修改后的 `ChapterLengthPlan` 必须重新保存
- **AND** 后续 `Freeze D` 必须消费修改后的长度预算

### Requirement: 上游修改必须触发级联回滚

系统 SHALL 将分层规划产物视为带依赖关系的冻结节点；当上游节点被修改时，所有下游节点必须失效并回滚。

#### Scenario: 修改章节梗概
- **WHEN** 用户修改某一章对应的 `ChapterBrief` 或其所在 `ChapterPackage`
- **THEN** 该章正文、状态回写以及其之后章节的全部下游产物失效
- **AND** 系统不得尝试保留旧正文继续写后续章节

#### Scenario: 修改批次规划
- **WHEN** 用户修改 `BatchPlan`
- **THEN** 当前批次及之后批次的章节梗概、正文、状态回写全部失效
- **AND** 系统必须从 `Freeze B` 重新向下生成

### Requirement: 失败恢复必须基于冻结点

系统 SHALL 支持从最近冻结点重跑，而不是每次从零开始。

#### Scenario: 正文失败重试
- **WHEN** Layer 4 生成结果连续性校验失败
- **THEN** 系统可在保持 `Freeze D` 不变的情况下重写正文
- **AND** 若持续失败，再回退到章节梗概层请求重规划

## Non-Goals

- 不在本子 spec 中重新定义 review 决策对象的字段结构
- 不在本子 spec 中展开 Layer 1 到 Layer 4 的规划内容
- 不在本子 spec 中定义 review / writeback 的详细门禁，详见 [review-and-writeback.spec.md](.trae/specs/writer-agent-layered-generation/specs/review-and-writeback.spec.md)
