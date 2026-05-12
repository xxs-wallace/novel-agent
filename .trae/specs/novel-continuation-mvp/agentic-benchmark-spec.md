# 小说续写 Agentic Benchmark Spec

## Why

当前 `novel-continuation-mvp` 已明确总编排层、创作知识库层、Memory 与上下文层的职责边界，但仍缺少一份专门用于回答以下问题的评测规范：

- 系统是否能在给定授权规划信息的前提下，稳定写出“合法后继”而不是仅做表面续写
- 系统是否能同时利用事实型 Memory 与桥段型参考，而不混淆两者职责
- 系统是否能在不同授权边界下表现稳定，例如盲续写、本章授权续写、局部未来导向续写
- 系统是否能在自动评测中先发现明显连续性错误，再交给人工做更高层的主观质量判断

小说续写不是标准的 token-level reconstruction 任务，也不是唯一答案问题。  
本 spec 将评测对象定义为：

- **在受控输入边界内，生成一个与原作前缀状态兼容、与当前章节目标一致、并具备原作风格约束的合法后继。**

## Relationship to Other Specs

- 总编排层：[`spec.md`](.trae/specs/novel-continuation-mvp/spec.md)
- 总编排设计：[`design.md`](.trae/specs/novel-continuation-mvp/design.md)
- 跨层 Contract：[`contracts.md`](.trae/specs/novel-continuation-mvp/contracts.md)
- 创作知识库层：[`creative-knowledge-base/spec.md`](.trae/specs/creative-knowledge-base/spec.md)
- Memory 与上下文层：[`narrative-memory-context/spec.md`](.trae/specs/narrative-memory-context/spec.md)
- Writer 分层生成：[`writer-agent-layered-generation/spec.md`](.trae/specs/writer-agent-layered-generation/spec.md)

本 spec 不重复定义以下实现细节：

- `documents` 建库与粗读切分
- `fragment_card` / `fragment_cluster` 的字段级细节
- 人物档案、世界观、章节摘要、大纲的字段级细节
- Writer Agent 的全部分层生成逻辑

本 spec 只定义：

- Benchmark 样本如何构造
- 三种评测模式的授权边界
- `forward_guidance` 的 JSON schema
- 自动评分项与通过规则
- 运行产物与评测记录结构

## Core Principles

- 评测首先验证“是否写得合法”，其次才验证“是否写得像”。
- 授权给模型的规划信息不视为信息泄漏，而视为 **已授权规划信息**。
- 不同 benchmark mode 的区别不在于“能不能看未来”，而在于“被授权看到多少、以什么结构看到”。
- 原作对应章节是参考真值，不是唯一正确答案。
- 自动评测优先识别结构化连续性错误，不直接用表面文本相似度代表质量。
- 单场景与单段评测优先于整章评测；整章评测应建立在可用的分段评测能力之上。
- 创作知识库层负责“怎么写类似桥段”，Memory 层负责“当前事实状态是什么”，两者在评测中必须分开统计。

## Benchmark Goals

本 benchmark 应同时回答以下问题：

1. 给定前缀事实、桥段参考与授权规划信息，系统能否写出连续性正确的续写
2. 给定最近 `m` 章窗口，系统能否保持人物、关系、冲突与时间顺序的一致
3. 给定当前章节纲要，系统能否完成本章应完成的叙事功能
4. 给定少量局部未来导向，系统能否在长场景或高潮场景中维持拆段生成的一致性
5. 创作知识库、Memory、规划信息三者中，哪一类输入对最终质量贡献最大

## Evaluation Unit

### Benchmark Sample

一个 benchmark sample 的最小单位 SHOULD 为：

- 一个待生成场景
- 或一个待生成段落组
- 或在能力成熟后，扩展到一个完整章节

每个 sample 至少包含：

```json
{
  "sample_id": "string",
  "book_id": "string",
  "target_chapter_id": "string",
  "target_segment_id": "string | null",
  "mode": "blind_prefix | chapter_authorized | bounded_future_hint",
  "anchor_context_path": "string",
  "recent_window_refs": ["string"],
  "documents_cutoff": {
    "max_document_title_index": "string"
  },
  "allowed_outline_scope": {
    "chapter_range": ["string"],
    "allow_future_outline": false
  },
  "forward_guidance": null,
  "reference_truth_path": "string",
  "metadata": {
    "is_climax": false,
    "window_size": 3,
    "target_length_chars": 3000
  }
}
```

### Reference Truth

`reference_truth_path` 对应的原作文本在 benchmark 中仅用于：

- 提取章节功能与关键状态变化
- 辅助人工评审
- 训练自动 judge 的弱监督样本

系统 SHALL NOT 以字面相似度作为主评分依据。

## Authorized Planning Boundary

### 定义

本 spec 将“生成时可见的未来信息”统一称为 **已授权规划信息**，并分为三类：

- `prefix_facts`: 截至当前生成位置之前，已经成为 canon 的事实型信息
- `current_unit_plan`: 当前待写章节或待写段落已被授权暴露的规划信息
- `bounded_future_hint`: 为了维持拆段逻辑而允许暴露的极少量后续导向信息

### 基本规则

- `prefix_facts` 始终允许使用
- `current_unit_plan` 是否允许使用，由 benchmark mode 决定
- `bounded_future_hint` 仅允许在对应 mode 中使用，且必须符合固定 schema
- 任意未授权的后续剧情、终局秘密、反转机制、身份揭示 SHALL 视为越界信息

## Benchmark Modes

### Requirement: Blind Prefix Mode

系统 SHALL 支持 `blind_prefix` 模式，用于测试“仅依赖前缀事实与风格参考”的基础续写能力。

#### Scenario: Blind Prefix 输入边界
- **WHEN** 一个 sample 运行于 `blind_prefix`
- **THEN** 系统只可读取：
  - 前缀 `documents`
  - 截止当前点之前的章节摘要
  - 截止当前点之前的人物档案与世界观
  - 截止当前点之前可构建出的创作知识库
  - 锚点上下文与最近 `m` 章窗口
- **AND** 系统不得读取当前章节纲要
- **AND** 系统不得读取后续章节纲要
- **AND** `forward_guidance` 必须为 `null`

#### Scenario: Blind Prefix 适用目标
- **WHEN** 团队需要测试系统的纯前缀承接能力
- **THEN** 优先使用 `blind_prefix`
- **AND** 将其作为 benchmark 下界

### Requirement: Chapter Authorized Mode

系统 SHALL 支持 `chapter_authorized` 模式，用于测试“给定当前章节授权纲要后的受控生成能力”。

#### Scenario: Chapter Authorized 输入边界
- **WHEN** 一个 sample 运行于 `chapter_authorized`
- **THEN** 系统可读取：
  - `blind_prefix` 模式允许的全部输入
  - 当前待写章节的章节目标与章节梗概
  - 当前章节允许暴露的关系推进目标、情绪目标与冲突目标
- **AND** 系统不得读取后续章节的详细纲要
- **AND** `forward_guidance` 默认应为 `null`

#### Scenario: Chapter Authorized 作为主 benchmark
- **WHEN** 团队需要一个最接近作者真实写作条件的默认评测模式
- **THEN** SHOULD 将 `chapter_authorized` 作为主 benchmark
- **AND** 将“已看到本章纲要但未看到更后续纲要”视为标准授权边界

### Requirement: Bounded Future Hint Mode

系统 SHALL 支持 `bounded_future_hint` 模式，用于测试长场景拆段生成时对局部未来导向的服从能力。

#### Scenario: Bounded Future Hint 输入边界
- **WHEN** 一个 sample 运行于 `bounded_future_hint`
- **THEN** 系统可读取：
  - `chapter_authorized` 模式允许的全部输入
  - 一个结构化的 `forward_guidance`
- **AND** `forward_guidance` 只能表达局部导向
- **AND** 不得变相暴露完整后续章节剧情

#### Scenario: Bounded Future Hint 适用目标
- **WHEN** 待写内容属于高潮场景、长对峙场景、多段追逐场景或连续情绪升级场景
- **THEN** SHOULD 使用 `bounded_future_hint`
- **AND** 以验证模型能否在不直接知道全部后文细节的情况下维持分段一致性

## Forward Guidance Schema

### Requirement: Forward Guidance 固定结构

系统 SHALL 为 `bounded_future_hint` 模式定义稳定的 `forward_guidance` JSON schema。

#### Scenario: Forward Guidance Frozen Fields
- **WHEN** 一个 sample 提供 `forward_guidance`
- **THEN** 其结构至少包含如下字段或等价字段：

```json
{
  "guidance_version": "v1",
  "segment_objective": "string",
  "required_emotional_direction": "string",
  "must_preserve_tension": true,
  "must_not_reveal": [
    "身份真相",
    "幕后势力",
    "感情明确表白"
  ],
  "next_turn_hint": "string",
  "allowed_future_scope": {
    "hint_level": "low | medium",
    "max_future_segments": 1
  },
  "continuity_watch_items": [
    "敌友关系不能混淆",
    "能力代价不能消失"
  ],
  "forbidden_shortcuts": [
    "禁止直接和解",
    "禁止无铺垫跳转到大战结束"
  ],
  "target_length_chars": 1500
}
```

#### Scenario: Forward Guidance 字段语义
- **WHEN** 系统消费 `forward_guidance`
- **THEN** 各字段的最小语义为：
  - `segment_objective`: 当前段必须完成的局部叙事目标
  - `required_emotional_direction`: 当前段的情绪走势要求
  - `must_preserve_tension`: 是否必须维持悬念或冲突压力
  - `must_not_reveal`: 当前段不得提前揭露的信息
  - `next_turn_hint`: 下一段或下一转折的抽象导向
  - `allowed_future_scope`: 允许向前引用的范围上限
  - `continuity_watch_items`: 当前段最容易写错的连续性项
  - `forbidden_shortcuts`: 禁止用来偷渡剧情的捷径
  - `target_length_chars`: 当前段目标长度

#### Scenario: Forward Guidance 边界约束
- **WHEN** 系统构造或使用 `forward_guidance`
- **THEN** `next_turn_hint` SHOULD 保持抽象
- **AND** 不应直接给出完整后文事件序列
- **AND** `must_not_reveal` 应优先表达“不能提前消费什么”
- **AND** `allowed_future_scope.max_future_segments` SHOULD 保持在 `1-2`

## Benchmark Runtime Flow

### Requirement: 固定运行流程

系统 SHALL 为 benchmark 运行提供稳定、可复现的执行顺序。

#### Scenario: 单样本运行
- **WHEN** 系统执行一个 benchmark sample
- **THEN** SHOULD 按如下顺序运行：
  1. 读取 sample config
  2. 按 mode 裁剪可见输入边界
  3. 基于前缀 `documents` 构建或加载创作知识库与 Memory
  4. 组装 `recent_window`
  5. 读取 `current_unit_plan` 与可选 `forward_guidance`
  6. 生成 `ScenePlan` 或兼容 `SceneBrief`
  7. 执行桥段检索与事实上下文装配
  8. 生成 draft
  9. 执行自动评分
  10. 保存运行产物

#### Scenario: 产物落盘
- **WHEN** 系统完成一次 benchmark run
- **THEN** SHOULD 至少保存：
  - `sample_config.json`
  - `authorized_inputs.json`
  - `retrieval_bundle.json`
  - `scene_plan.json`
  - `draft.md`
  - `auto_score_report.json`
  - `continuity_report.json`
  - `judge_notes.json`

## Auto Scoring Model

### Core Position

自动评分的目标不是判定“是否复现原作文本”，而是判定：

- 是否违反已知事实
- 是否完成当前授权目标
- 是否承接最近窗口
- 是否遵守 `forward_guidance`

自动评分 SHALL 采用“硬门槛 + 分项分数 + 综合结论”的结构。

## Auto Scoring Schema

### Requirement: Auto Score Report 固定结构

系统 SHALL 输出稳定的 `auto_score_report`。

#### Scenario: Auto Score Report Frozen Fields
- **WHEN** 系统完成自动评分
- **THEN** 应输出如下结构或等价结构：

```json
{
  "sample_id": "string",
  "mode": "chapter_authorized",
  "hard_gate": {
    "passed": true,
    "fatal_issues": []
  },
  "scores": {
    "hard_consistency": 0.94,
    "recent_window_coherence": 0.88,
    "chapter_outline_fulfillment": 0.91,
    "forward_guidance_adherence": 1.0,
    "character_consistency": 0.90,
    "relationship_transition_legality": 0.93,
    "world_rule_compliance": 0.96,
    "style_alignment": 0.76,
    "retrieval_effectiveness": 0.72
  },
  "weighted_score": 0.88,
  "decision": "pass | borderline | fail",
  "explanations": [
    {
      "metric": "recent_window_coherence",
      "summary": "未解决冲突线得到延续，但一处敌友称谓存在轻微歧义"
    }
  ],
  "evidence_refs": [
    {
      "type": "chapter_summary",
      "ref": "string"
    }
  ]
}
```

## Hard Gate Metrics

### Requirement: Hard Consistency

系统 SHALL 将以下项目视为硬门槛检查项。

#### Scenario: Hard Gate 覆盖范围
- **WHEN** 系统执行 `hard_consistency`
- **THEN** 至少检查：
  - 人物身份是否错乱
  - 敌友关系是否无因跳变
  - 时间顺序是否倒置
  - 地点连续性是否被破坏
  - 世界规则或能力代价是否被无依据改写
  - 未授权设定是否被引入

#### Scenario: Hard Gate 失败处理
- **WHEN** 出现重大事实冲突
- **THEN** `hard_gate.passed` SHALL 为 `false`
- **AND** `decision` SHOULD 直接为 `fail`
- **AND** 软性分数不得掩盖硬失败

## Scored Metrics

### Requirement: Recent Window Coherence

系统 SHALL 检查生成结果与最近 `m` 章窗口的一致性。

#### Scenario: Recent Window Coherence 定义
- **WHEN** 计算 `recent_window_coherence`
- **THEN** 至少评估：
  - 最近章节未解决冲突是否被承接
  - 角色当前立场是否延续
  - 当前行动是否符合前一阶段动机
  - 近期情绪余波是否被保留

### Requirement: Chapter Outline Fulfillment

系统 SHALL 在存在本章授权纲要时评估章节目标完成度。

#### Scenario: Chapter Outline Fulfillment 定义
- **WHEN** sample mode 为 `chapter_authorized` 或 `bounded_future_hint`
- **THEN** 至少评估：
  - 本段或本场景是否完成指定叙事目标
  - 是否承接指定情绪目标
  - 是否推进指定冲突目标
  - 是否遵守必须避免项

### Requirement: Forward Guidance Adherence

系统 SHALL 在 `bounded_future_hint` 模式下单独评估对 `forward_guidance` 的服从度。

#### Scenario: Forward Guidance Adherence 定义
- **WHEN** sample 提供 `forward_guidance`
- **THEN** 至少评估：
  - 是否完成 `segment_objective`
  - 是否遵守 `must_not_reveal`
  - 是否维持 `must_preserve_tension`
  - 是否没有使用 `forbidden_shortcuts`
  - 是否只在允许范围内引用局部未来导向

### Requirement: Character Consistency

系统 SHALL 评估主要人物是否保持既有人设与行为风格。

#### Scenario: Character Consistency 定义
- **WHEN** 计算 `character_consistency`
- **THEN** 至少评估：
  - 对白是否符合角色气质
  - 决策是否符合已知动机
  - 心理与行为是否与近章状态兼容
  - 是否出现无铺垫的人格失真

### Requirement: Relationship Transition Legality

系统 SHALL 评估人物关系变化是否合法。

#### Scenario: Relationship Transition Legality 定义
- **WHEN** 生成内容涉及友情、爱情、亲情、师徒、敌对等关系推进
- **THEN** 至少评估：
  - 当前关系状态识别是否正确
  - 目标关系变化是否在合法步长内
  - 是否存在必要桥接事件
  - 是否发生无铺垫的突然和解、表白、决裂或背叛

### Requirement: World Rule Compliance

系统 SHALL 评估生成内容是否符合世界观规则。

#### Scenario: World Rule Compliance 定义
- **WHEN** 计算 `world_rule_compliance`
- **THEN** 至少评估：
  - 设定规则是否被遵守
  - 能力使用是否符合代价与限制
  - 阵营、组织、地理与历史信息是否自洽
  - 是否引入未授权规则捷径

### Requirement: Style Alignment

系统 SHALL 以结构特征而非字面重合评估风格一致性。

#### Scenario: Style Alignment 定义
- **WHEN** 计算 `style_alignment`
- **THEN** SHOULD 优先比较：
  - 句子节奏
  - 对白密度
  - 内心描写密度
  - 情绪表达方式
  - 叙述克制度
- **AND** 不将 n-gram 相似度作为主依据

### Requirement: Retrieval Effectiveness

系统 SHALL 单独评估创作知识库检索是否真正帮助写作。

#### Scenario: Retrieval Effectiveness 定义
- **WHEN** 计算 `retrieval_effectiveness`
- **THEN** 至少评估：
  - 被选参考片段是否匹配当前叙事功能
  - 参考片段是否帮助维持风格或桥段组织
  - 检索结果是否避免了同簇重复占位
  - 写作是否实际使用了高分候选提供的有效特征

## Scoring Decision Rules

### Requirement: 综合决策规则

系统 SHALL 为自动评分提供统一决策门槛。

#### Scenario: Pass
- **WHEN** `hard_gate.passed = true`
- **AND** `weighted_score >= 0.80`
- **THEN** `decision` SHOULD 为 `pass`

#### Scenario: Borderline
- **WHEN** `hard_gate.passed = true`
- **AND** `weighted_score >= 0.65`
- **AND** `weighted_score < 0.80`
- **THEN** `decision` SHOULD 为 `borderline`

#### Scenario: Fail
- **WHEN** `hard_gate.passed = false`
- **OR** `weighted_score < 0.65`
- **THEN** `decision` SHOULD 为 `fail`

#### Scenario: 指标缺失
- **WHEN** 某项评分因输入不足无法计算
- **THEN** 系统必须显式标记 `insufficient_evidence`
- **AND** 不得默默用默认高分补齐

## Recommended Weighting

### 默认权重

第一阶段推荐如下默认权重：

```json
{
  "recent_window_coherence": 0.20,
  "chapter_outline_fulfillment": 0.18,
  "forward_guidance_adherence": 0.10,
  "character_consistency": 0.16,
  "relationship_transition_legality": 0.12,
  "world_rule_compliance": 0.12,
  "style_alignment": 0.07,
  "retrieval_effectiveness": 0.05
}
```

说明：

- `hard_consistency` 属于门槛项，不纳入加权平均
- 在 `blind_prefix` 模式下，`chapter_outline_fulfillment` 与 `forward_guidance_adherence` 可标记为 `not_applicable`
- 在 `chapter_authorized` 模式下，`forward_guidance_adherence` 应为 `not_applicable`

## Benchmark Splits

### Requirement: 样本分层切分

系统 SHALL 对 benchmark 样本进行分层切分，以避免单一类型样本主导结果。

#### Scenario: 推荐分层维度
- **WHEN** 构建 benchmark dataset
- **THEN** SHOULD 按至少以下维度分层：
  - 日常过渡场景
  - 冲突升级场景
  - 关系推进场景
  - 设定解释场景
  - 高潮拆段场景
  - 收束与回钩场景

#### Scenario: 长度分层
- **WHEN** 构建 benchmark dataset
- **THEN** SHOULD 同时记录：
  - 单段短样本
  - 多段连续样本
  - 单章样本

## Ablation Expectations

### Requirement: Ablation Benchmark

系统 SHALL 支持对关键输入源做消融实验。

#### Scenario: 基础消融
- **WHEN** 团队需要判断系统质量来源
- **THEN** SHOULD 至少比较：
  - 完整输入
  - 去掉创作知识库
  - 去掉 Memory
  - 去掉章节授权纲要
  - 去掉 `forward_guidance`

#### Scenario: 消融结果用途
- **WHEN** 消融运行结束
- **THEN** 应输出每项指标掉分情况
- **AND** 用于判断后续优化优先级

## Human Evaluation Interface

### Requirement: 自动评分之后的人审入口

系统 SHALL 保留人工评审接口，且自动评分不应替代最终质量判断。

#### Scenario: 人工复核
- **WHEN** 一个样本的 `decision = borderline`
- **OR** 样本属于高潮、关系跃迁、重大设定揭示场景
- **THEN** SHOULD 进入人工复核
- **AND** 人工重点检查：
  - 是否像同一本书的自然后继
  - 是否存在模型 judge 难以发现的微妙 OOC
  - 是否在文风上过于模板化

## Non-Goals

本 spec 当前不要求：

- 直接产出训练 loss 或 token-level accuracy
- 用单一模型 judge 完全取代人工评审
- 以 BLEU、ROUGE、编辑距离作为主指标
- 一开始就以整本书级 benchmark 评估系统

## Success Criteria

- `chapter_authorized` 模式下，系统能稳定通过硬门槛，并在多数样本上达到 `pass`
- `bounded_future_hint` 模式下，系统能在长场景拆段时显著降低连续性错误
- 自动评分能稳定抓出敌友关系混淆、关系跳变、设定越界等高价值错误
- 消融结果能明确区分创作知识库、Memory 与规划信息的贡献
- benchmark 结果能直接指导主系统的检索、规划、写作与校验优化
