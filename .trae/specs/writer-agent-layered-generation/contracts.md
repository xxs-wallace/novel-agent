# Writer Agent Review and User Input Contracts

## 1. 目的

本文件用于冻结 Writer Agent 章节验收、返工与用户补充问题环节的跨模块对象，供以下文档共同遵循：

- [spec.md](.trae/specs/writer-agent-layered-generation/spec.md)
- [design.md](.trae/specs/writer-agent-layered-generation/design.md)
- [../web-interface/spec.md](.trae/specs/web-interface/spec.md)
- [../web-interface/design.md](.trae/specs/web-interface/design.md)

本 contract 只定义模块间如何传递“章节验收决策”“长度调整请求”“章节重规划请求”“大纲研究补充问题与回答”，不替代各层内部实现。

## 2. Design Principles

- 所有 contract 默认 JSON 兼容
- 所有对象必须能直接落盘到 `runs/*` 目录
- 所有对象必须可被状态机直接消费，而不依赖额外自然语言解析
- 所有对象必须显式区分：
  - 必填字段
  - 可选字段
  - 状态驱动字段
- 所有对象必须避免与正式 Memory / KB 事实对象混淆

## 3. Shared Conventions

### 3.1 命名约定

- `decision_id`: 一次章节验收决策的唯一标识
- `chapter_id`: 当前章节的稳定标识
- `draft_id`: 当前待审草稿版本标识
- `run_id`: 一次生成运行的标识
- `reviewer_type`: 发起决策的主体类型
- `question_set_id`: 一组待用户回答问题的稳定标识
- `question_id`: 问题集内单个问题的稳定标识

### 3.2 时间与路径

- 时间统一使用 ISO 8601 UTC 字符串
- 路径统一使用绝对路径或仓库内可解析相对路径

### 3.3 状态机约定

- `accepted` 只允许进入 `Freeze E`
- `revise_length` 只允许回到 `wait_length_review`
- `replan_chapter` 只允许回到 `wait_chapter_review`
- `discarded` 只允许进入 `halted` 或等待用户下一步显式动作
- `needs_user_input` 只允许通过 `continue_after_outline_research_input` 或等价结构化 action 继续

## 4. Contract A: GenerationReviewDecision

### 4.1 用途

- 表达一次章节验收的结构化结果
- 驱动验收后的状态跳转
- 决定当前草稿是否可进入 `Freeze E`

### 4.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "decision_id": "review-batch03-ch02-003",
  "run_id": "run-20260503-001",
  "chapter_id": "batch03-ch02",
  "draft_id": "draft-003",
  "status": "revise_length",
  "reason_code": "length_too_short",
  "feedback_text": "字数不足，高潮段需要展开，结尾转折前的心理描写不够。",
  "next_action_checkpoint": "wait_length_review",
  "length_plan_update": {
    "target_chars": 3200,
    "min_chars": 2800,
    "max_chars": 3600,
    "reason_code": "length_too_short"
  },
  "chapter_replan_request": null,
  "supersedes_draft_id": "draft-002",
  "reviewer_type": "user",
  "created_at": "2026-05-03T12:00:00Z"
}
```

### 4.3 Required Fields

- `schema_version`
- `decision_id`
- `chapter_id`
- `draft_id`
- `status`
- `reason_code`
- `feedback_text`
- `next_action_checkpoint`
- `reviewer_type`
- `created_at`

### 4.4 Status Enum

- `accepted`
- `revise_length`
- `replan_chapter`
- `discarded`

### 4.5 Reason Code Enum

推荐至少支持：

- `approved`
- `length_too_short`
- `length_too_long`
- `pacing_mismatch`
- `structure_mismatch`
- `direction_mismatch`
- `character_voice_drift`
- `continuity_risk`
- `user_abandoned`
- `superseded_by_new_draft`
- `other`

### 4.6 Required Rules

- 当 `status = accepted` 时：
  - `reason_code` 必须为 `approved`
  - `next_action_checkpoint` 必须为 `freeze_e`
  - `length_plan_update` 必须为空或省略
  - `chapter_replan_request` 必须为空或省略
- 当 `status = revise_length` 时：
  - `next_action_checkpoint` 必须为 `wait_length_review`
  - `length_plan_update` 必须存在
  - `chapter_replan_request` 必须为空或省略
- 当 `status = replan_chapter` 时：
  - `next_action_checkpoint` 必须为 `wait_chapter_review`
  - `chapter_replan_request` 必须存在
  - `length_plan_update` 可以为空；如存在，只可作为参考，不得直接替代新的章节规划
- 当 `status = discarded` 时：
  - `next_action_checkpoint` 必须为 `halted`
  - 不得触发正式回写

### 4.7 Boundary Notes

- `GenerationReviewDecision` 是验收层对象，不是正文对象
- `GenerationReviewDecision` 只表达“本轮怎么处理当前草稿”，不直接修改上游 `ChapterPackage`
- 是否真的更新长度计划或章节梗概，必须分别由 `LengthPlanUpdate` 和 `ChapterReplanRequest` 承接

## 5. Contract B: LengthPlanUpdate

### 5.1 用途

- 表达用户对当前章节长度预算的修订请求
- 供长度规划层重新确认预算并重新生成草稿
- 不得修改章节核心方向与结构目标

### 5.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "update_id": "length-update-batch03-ch02-001",
  "decision_id": "review-batch03-ch02-003",
  "chapter_id": "batch03-ch02",
  "target_chars": 3200,
  "min_chars": 2800,
  "max_chars": 3600,
  "reason_code": "length_too_short",
  "feedback_text": "保留现有剧情方向，但高潮前需要增加心理和动作描写。",
  "preserve_story_direction": true,
  "created_at": "2026-05-03T12:00:00Z"
}
```

### 5.3 Required Fields

- `schema_version`
- `update_id`
- `decision_id`
- `chapter_id`
- `target_chars`
- `min_chars`
- `max_chars`
- `reason_code`
- `feedback_text`
- `preserve_story_direction`
- `created_at`

### 5.4 Required Rules

- `target_chars`、`min_chars`、`max_chars` 必须为正整数
- 必须满足 `min_chars <= target_chars <= max_chars`
- `preserve_story_direction` 必须为 `true`
- 该对象只允许在 `GenerationReviewDecision.status = revise_length` 时出现
- 不得通过该对象要求：
  - 修改章节核心目标
  - 修改关系推进目标
  - 修改章节结构意图
  - 修改必须出现或禁止出现事项

### 5.5 Boundary Notes

- `LengthPlanUpdate` 只服务于长度预算层
- 它不是新的 `ChapterBrief`
- 若用户实际想修改方向、结构或展开方式，必须改走 `ChapterReplanRequest`

## 6. Contract C: ChapterReplanRequest

### 6.1 用途

- 表达用户对当前章节方向、结构或展开方式的不接受
- 触发退回章节梗概层
- 作为 `ChapterPackage / ChapterBrief` 重规划的输入之一

### 6.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "request_id": "replan-batch03-ch02-001",
  "decision_id": "review-batch03-ch02-004",
  "chapter_id": "batch03-ch02",
  "reason_code": "structure_mismatch",
  "feedback_text": "当前稿在冲突升级前铺垫过长，且关系推进过快，需要重写章节梗概。",
  "replan_scope": "current_chapter",
  "must_preserve": [
    "本章仍需完成危机中的有限合作"
  ],
  "must_change": [
    "延后公开偏袒时点",
    "减少前半章解释，提前进入行动段"
  ],
  "forbidden_carryover": [
    "不得直接沿用当前草稿中的关系升温节奏"
  ],
  "requested_length_direction": {
    "keep_default_plan": false,
    "suggested_target_chars": 2600
  },
  "created_at": "2026-05-03T12:05:00Z"
}
```

### 6.3 Required Fields

- `schema_version`
- `request_id`
- `decision_id`
- `chapter_id`
- `reason_code`
- `feedback_text`
- `replan_scope`
- `must_preserve`
- `must_change`
- `forbidden_carryover`
- `created_at`

### 6.4 Required Rules

- 该对象只允许在 `GenerationReviewDecision.status = replan_chapter` 时出现
- `replan_scope` 第一阶段建议固定为：
  - `current_chapter`
- `must_change` 至少包含一项
- `must_preserve` 可为空数组，但字段必须存在
- `forbidden_carryover` 可为空数组，但字段必须存在
- `requested_length_direction` 只可表达对下一轮长度规划的建议，不得直接替代 `ChapterLengthPlan`

### 6.5 Boundary Notes

- `ChapterReplanRequest` 是重规划请求，不是新的 `ChapterPackage`
- 它不直接产出新的章节梗概，只提供重规划约束
- 它不允许越过章节梗概层直接重写正文

## 7. Contract D: OutlineResearchQuestionSet

### 7.1 用途

- 表达 Outline Research Loop 在 `needs_user_input` 时需要用户补充的问题集
- 供 Web / CLI / TUI 用同一语义展示问题、收集回答并恢复等待态
- 驱动用户回答后继续 research 或生成大纲

### 7.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "question_set_id": "outline-research-run-20260503-001-001",
  "run_id": "run-20260503-001",
  "stage": "outline_research_user_input",
  "status": "pending",
  "source_artifact_id": "writer:run-20260503-001:sufficiency-decision",
  "artifact_path": "runs/writer/run-20260503-001/outline_research_question_set.json",
  "questions": [
    {
      "question_id": "q1",
      "prompt": "这个新增角色是否应视为正式登场人物，还是只作为传闻中的名字？",
      "required": true,
      "hint": "这会影响后续人物补充和章节规划。",
      "gap_id": "gap-new-character-authorization",
      "risk_level": "high"
    }
  ],
  "actions": {
    "submit": "continue_after_outline_research_input",
    "defer": "defer_outline_research_answers"
  },
  "created_at": "2026-05-03T12:10:00Z"
}
```

### 7.3 Required Fields

- `schema_version`
- `question_set_id`
- `run_id`
- `stage`
- `status`
- `questions`
- `actions`
- `created_at`

### 7.4 Required Rules

- `questions` 必须至少包含一项
- 每个问题必须包含稳定 `question_id`、用户可读 `prompt` 和 `required`
- `stage`、`artifact_path` 和 workflow action 名不得作为普通用户界面的主状态展示；只能用于 action payload、恢复和 technical/debug 视图
- `actions.submit` 的语义必须等价于 `continue_after_outline_research_input`
- 普通聊天消息不得自动继续该问题集；必须收到结构化 submit action
- 问题集必须可通过落盘 artifact 或 `sufficiency_decision.json` 引用恢复

### 7.5 Answer Submission

```json
{
  "schema_version": "1.0",
  "submission_id": "outline-answer-run-20260503-001-001",
  "question_set_id": "outline-research-run-20260503-001-001",
  "run_id": "run-20260503-001",
  "source_message_id": "message-123",
  "answer_text": "作为正式登场人物，但先只在传闻里出现，第三章前不要正面登场。",
  "user_answers": [
    {
      "question_id": "q1",
      "answer_text": "作为正式登场人物，但先只在传闻里出现，第三章前不要正面登场。"
    }
  ],
  "reviewer_type": "user",
  "created_at": "2026-05-03T12:15:00Z"
}
```

提交对象的必填字段：

- `schema_version`
- `submission_id`
- `question_set_id`
- `run_id`
- `answer_text`
- `reviewer_type`
- `created_at`

提交规则：

- `answer_text` 必须保留用户原始回答
- `user_answers` 是可选结构化映射；若无法可靠映射，不得伪造缺失问题的答案
- 必答问题缺失时，workflow 应保持等待态或返回可读补充提示
- 被接受的回答进入 `planning_notebook` 或等价 artifact 时，来源类型必须是 `user_authorized`

### 7.6 Boundary Notes

- `OutlineResearchQuestionSet` 是用户补充问题对象，不是正式 Memory 事实对象
- 用户回答成为 Writer planning evidence，不等于直接写入 Character Memory / World KB
- 新增人物、关系跃迁和世界规则突破仍需遵守对应规划与确认规则

## 8. Object Relationships

### 8.1 Decision to Update Mapping

```text
GenerationReviewDecision.status = accepted
  -> no LengthPlanUpdate
  -> no ChapterReplanRequest

GenerationReviewDecision.status = revise_length
  -> requires LengthPlanUpdate
  -> must not include ChapterReplanRequest

GenerationReviewDecision.status = replan_chapter
  -> requires ChapterReplanRequest
  -> may later trigger a new ChapterLengthPlan

GenerationReviewDecision.status = discarded
  -> no writeback
  -> no automatic next chapter

OutlineResearchQuestionSet.status = pending
  -> submit answer via continue_after_outline_research_input
  -> accepted answers become user_authorized evidence
  -> may continue research or generate outline
```

### 8.2 Writeback Boundary

- 只有 `GenerationReviewDecision.status = accepted` 的草稿允许进入 `Freeze E`
- `revise_length`、`replan_chapter`、`discarded` 都不得触发正式 Memory / KB 回写

## 9. Recommended Storage Targets

建议运行期至少落盘以下文件：

- `generation_review_decision.json`
- `length_plan_update.json`
- `chapter_replan_request.json`
- `outline_research_question_set.json`
- `outline_research_answer_submission.json`

## 10. Breaking Change Rules

以下变更视为 breaking change：

- 删除必填字段
- 改变 `status` 或 `reason_code` 的既有语义
- 改变状态与检查点之间的映射关系
- 改变 `question_set_id` / `question_id` 的稳定性要求
- 改变用户回答必须保留原文并作为 `user_authorized` evidence 的语义

以下变更视为兼容扩展：

- 新增可选字段
- 新增非破坏性的 `reason_code`
- 为 `requested_length_direction` 增加可选提示字段
