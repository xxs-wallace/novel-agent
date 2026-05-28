# Writer Agent Review and User Input Contracts

## 1. 目的

本文件用于稳定 Writer Agent 的 artifact 审阅、用户草稿决策、Draft Research Loop 返工与用户补充问题环节的跨模块对象，供以下文档共同遵循：

- [spec.md](.trae/specs/writer-agent-layered-generation/spec.md)
- [design.md](.trae/specs/writer-agent-layered-generation/design.md)
- [../web-interface/spec.md](.trae/specs/web-interface/spec.md)
- [../web-interface/design.md](.trae/specs/web-interface/design.md)

本 contract 只定义模块间如何传递“artifact 审阅决策”“用户草稿决策”“正文研究/重写决策”“大纲研究补充问题与回答”，不替代各层内部实现。

## 2. Design Principles

- 所有 contract 默认 JSON 兼容
- 所有对象必须能直接落盘到 `runs/*` 目录
- 所有对象必须可被状态机直接消费，而不依赖额外自然语言解析
- 所有对象必须显式区分必填字段、可选字段和状态驱动字段
- 所有对象必须避免与正式 Memory / KB 事实对象混淆
- 用户原始输入必须保留原文，不能被摘要、拆题或模型解释替代

## 3. Shared Conventions

### 3.1 命名约定

- `review_id`: 一次 artifact 审阅决策的唯一标识
- `decision_id`: 一次章节草稿用户决策的唯一标识
- `run_id`: 一次生成运行的标识
- `artifact_kind`: 被审阅 artifact 的类型
- `artifact_id`: 被审阅 artifact 的稳定标识
- `artifact_path`: 被审阅 artifact 的落盘路径
- `chapter_id`: 当前章节的稳定标识
- `draft_id`: 当前待审草稿版本标识
- `reviewer_type`: 发起决策的主体类型；对 `GenerationReviewDecision` 而言通常为 `user` 或显式测试脚本来源，不表示独立 Reviewer 模块
- `question_set_id`: 一组待用户回答问题的稳定标识
- `question_id`: 问题集内单个问题的稳定标识
- `draft_research_id`: 一次 Draft Research Loop 运行的唯一标识
- `rewrite_plan_id`: 一次草稿重写计划的唯一标识
- `source_message_id`: 触发结构化 action 的聊天消息标识

### 3.2 时间与路径

- 时间统一使用 ISO 8601 UTC 字符串
- 路径统一使用绝对路径或仓库内可解析相对路径
- 普通用户视图不得把 path、stage、action 名或内部 id 当作主状态展示

### 3.3 状态机约定

- Artifact review gate 只通过 `ArtifactReviewDecision` 或等价结构化 action 继续
- `needs_user_input` 只允许通过 `continue_after_outline_research_input` 或等价结构化 action 继续
- 普通聊天消息不得自动绕过 `needs_user_input`
- 章节草稿只有 `GenerationReviewDecision.status = accepted` 才允许进入正式写回候选
- 任何不接受草稿的分支都必须回到 Agent Loop，不得触发 Memory / KB 正式写回
- `rewrite_requested` 必须先进入 Draft Research Loop，不能只把用户反馈拼进旧正文 prompt 后直接重写

## 4. Contract A: ArtifactReviewDecision

### 4.1 用途

- 表达用户对一个规划类 artifact 的结构化审阅结果
- 驱动 Agent Loop 继续、修订或暂停
- 保留用户通过时的补充 prompt，以及不通过时的修订反馈

适用 artifact 包括但不限于：

- `book_continuation_plan`
- `world_expansion_pack`
- `character_cast_plan`
- `batch_plan`
- `chapter_package`
- `chapter_brief`
- `writeback_summary`

`batch_plan` 中的 `chapters` 字段由后端根据 Writer Memory `document_title_index` 计算并注入，形如 `["chapter-5", "chapter-6"]`。模型和 scoped artifact revision 不得自行推导、重排或改写该章节列表。

### 4.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "review_id": "artifact-review-run-20260503-001-004",
  "run_id": "run-20260503-001",
  "artifact_kind": "chapter_package",
  "artifact_id": "batch03-package-001",
  "artifact_path": "runs/writer/run-20260503-001/chapter_package.json",
  "artifact_version": "v3",
  "decision": "approved",
  "supplement_text": "本章控制在三千字左右，动作段更紧，结尾保留悬念，不要提前解释幕后人身份。",
  "revision_feedback": "",
  "source_message_id": "message-123",
  "reviewer_type": "user",
  "next_action": "continue_agent_loop",
  "created_at": "2026-05-03T12:00:00Z"
}
```

### 4.3 Required Fields

- `schema_version`
- `review_id`
- `run_id`
- `artifact_kind`
- `decision`
- `reviewer_type`
- `next_action`
- `created_at`

### 4.4 Decision Enum

- `approved`
- `revision_requested`
- `deferred`

### 4.5 Required Rules

- 当 `decision = approved` 时：
  - `supplement_text` 可为空，但字段存在时必须保留用户原文
  - `revision_feedback` 必须为空或省略
  - `next_action` 必须等价于继续 Agent Loop
  - 后续模型 prompt 必须能消费 `supplement_text`
- 当 `decision = revision_requested` 时：
  - `revision_feedback` 必须非空，并保留用户原文
  - `supplement_text` 必须为空或省略
  - Agent 必须把反馈、当前 artifact、上游约束和必要 evidence 交给模型修订
  - workflow 必须回到同一个 artifact review gate
- 当 `decision = deferred` 时：
  - 不得继续生成或写回
  - workflow 保持可恢复暂停态

### 4.6 Boundary Notes

- `ArtifactReviewDecision` 是交互决策对象，不是正式 Memory 事实对象
- `supplement_text` 是模型 prompt 材料，不等于用户直接改写 artifact
- `revision_feedback` 是修订请求，不等于新的 artifact
- 技术字段可以进入 debug drawer，但普通 UI 主状态应显示自然语言提示

## 5. Contract B: GenerationReviewDecision

### 5.1 用途

- 表达一次章节草稿用户决策的结构化结果
- 驱动用户决策后的 Agent Loop 分支
- 决定当前草稿是否可进入正式写回候选

### 5.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "decision_id": "draft-review-batch03-ch02-003",
  "run_id": "run-20260503-001",
  "chapter_id": "batch03-ch02",
  "draft_id": "draft-003",
  "status": "rewrite_requested",
  "reason_code": "pacing_mismatch",
  "feedback_text": "前半章解释太多，动作段不够紧。保留梗概方向，但重写时把冲突提前，并把心理描写压到关键转折前。",
  "source_message_id": "message-456",
  "reviewer_type": "user",
  "next_action": "agent_loop_rewrite_draft",
  "created_at": "2026-05-03T12:00:00Z"
}
```

### 5.3 Required Fields

- `schema_version`
- `decision_id`
- `run_id`
- `chapter_id`
- `draft_id`
- `status`
- `reason_code`
- `feedback_text`
- `reviewer_type`
- `next_action`
- `created_at`

### 5.4 Status Enum

- `accepted`
- `rewrite_requested`
- `replan_requested`
- `discarded`

### 5.5 Reason Code Enum

推荐至少支持：

- `approved`
- `too_short`
- `too_long`
- `pacing_mismatch`
- `structure_mismatch`
- `direction_mismatch`
- `character_voice_drift`
- `continuity_risk`
- `style_mismatch`
- `user_abandoned`
- `superseded_by_new_draft`
- `other`

### 5.6 Required Rules

- 当 `status = accepted` 时：
  - `reason_code` 必须为 `approved`
  - `next_action` 必须等价于进入写回摘要审阅或正式写回候选
  - `feedback_text` 可以为空
- 当 `status = rewrite_requested` 时：
  - `feedback_text` 必须非空，并保留用户原文
  - `next_action` 必须等价于 Agent Loop 基于当前通过的章节 brief 重写草稿
  - 不得触发正式写回
- 当 `status = replan_requested` 时：
  - `feedback_text` 必须非空，并保留用户原文
  - `next_action` 必须等价于 Agent Loop 修订 `ChapterPackage` / `ChapterBrief`
  - workflow 必须回到章节梗概 review gate
  - 不得触发正式写回
- 当 `status = discarded` 时：
  - `next_action` 必须等价于暂停或等待用户下一步
  - 不得触发正式写回

### 5.7 Boundary Notes

- `GenerationReviewDecision` 是用户草稿决策对象，不是正文对象，也不是 Reviewer 评分对象
- 字数、风格和节奏问题都可以通过 `feedback_text` 表达，由 Agent 判断是基于同一 brief 重写，还是回到章节梗概修订
- 不再要求单独的长度计划更新对象作为正式分支
- 当 `status = rewrite_requested` 时，`feedback_text` 必须先进入 Draft Research Loop；Draft Prose Executor 只能消费 Draft Research Loop 产出的 `draft_rewrite_plan.json` 或等价受控重写计划

## 5A. Contract B2: DraftResearchDecision

### 5A.1 用途

- 表达 Draft Research Loop 对当前章正文前研究的结构化出口
- 决定 workflow 是否进入 Draft Prose Executor、询问用户、回到上游 artifact，或阻塞
- 保留 Draft Research Loop 使用过的 seed、notebook、trace 和证据引用

### 5A.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "draft_research_id": "draft-research-run-20260503-001-ch02-001",
  "run_id": "run-20260503-001",
  "chapter_id": "batch03-ch02",
  "draft_id": "draft-003",
  "status": "ready_for_draft",
  "seed_packet_path": "runs/writer/run-20260503-001/draft_seed_packet.json",
  "notebook_path": "runs/writer/run-20260503-001/draft_context_notebook.json",
  "trace_path": "runs/writer/run-20260503-001/draft_research_trace.json",
  "question_set_id": "",
  "replan_target": "",
  "blocked_reason": "",
  "next_action": "run_draft_prose_executor",
  "created_at": "2026-05-03T12:20:00Z"
}
```

### 5A.3 Required Fields

- `schema_version`
- `draft_research_id`
- `run_id`
- `chapter_id`
- `status`
- `next_action`
- `created_at`

### 5A.4 Status Enum

- `ready_for_draft`
- `needs_user_input`
- `replan_requested`
- `blocked`

### 5A.5 Required Rules

- 当 `status = ready_for_draft` 时：
  - `notebook_path` 必须指向可恢复的 `draft_context_notebook.json` 或等价 artifact
  - `next_action` 必须等价于调用 Draft Prose Executor
- 当 `status = needs_user_input` 时：
  - 必须提供 `question_set_id` 或等价结构化问题集引用
  - 不得继续生成正文
- 当 `status = replan_requested` 时：
  - `replan_target` 必须指向 `chapter_brief`、`chapter_package`、`batch_plan` 或更上游 artifact
  - workflow 必须回到对应 review gate
- 当 `status = blocked` 时：
  - `blocked_reason` 必须非空
  - 不得生成正式草稿

### 5A.6 Boundary Notes

- `DraftResearchDecision` 是运行决策对象，不是正式 Memory 事实对象
- `draft_context_notebook.json` 是临时写作上下文，可被重写和 reviewer 复用，但不得直接污染 canon
- trace 可进入 debug / reviewer，不得作为隐藏知识无来源注入下一轮 prompt

## 5B. Contract B3: DraftRewritePlan

### 5B.1 用途

- 表达用户不接受草稿后的受控重写计划
- 将 `GenerationReviewDecision.feedback_text` 转换为 Draft Prose Executor 可消费的 preserve / change / remove 约束
- 决定本次反馈可在当前 brief 内重写，还是必须回到上游规划

### 5B.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "rewrite_plan_id": "draft-rewrite-run-20260503-001-ch02-001",
  "run_id": "run-20260503-001",
  "chapter_id": "batch03-ch02",
  "source_decision_id": "draft-review-batch03-ch02-003",
  "source_draft_id": "draft-003",
  "rewrite_mode": "full_rewrite",
  "feedback_classification": "character_voice_fix",
  "feedback_text": "这个人物不该这样说话，和前面早期设定冲突。",
  "preserve": ["本章结尾 hook", "章节核心行动结果"],
  "remove_or_change": ["修正人物称谓和对主角的关系认知"],
  "new_memory_notes": [],
  "character_constraints": [],
  "style_constraints": [],
  "must_not_change": [],
  "requires_replan": false,
  "replan_target": "",
  "created_at": "2026-05-03T12:25:00Z"
}
```

### 5B.3 Required Fields

- `schema_version`
- `rewrite_plan_id`
- `run_id`
- `chapter_id`
- `source_decision_id`
- `source_draft_id`
- `rewrite_mode`
- `feedback_classification`
- `feedback_text`
- `requires_replan`
- `created_at`

### 5B.4 Rewrite Mode Enum

- `full_rewrite`
- `targeted_rewrite`
- `regenerate_from_brief`
- `replan_required`

### 5B.5 Feedback Classification Enum

- `prose_only`
- `scene_emphasis`
- `continuity_fix`
- `character_voice_fix`
- `structure_fix`
- `upstream_conflict`
- `other`

### 5B.6 Required Rules

- `feedback_text` 必须保留用户原文
- 当 `requires_replan = true` 或 `rewrite_mode = replan_required` 时：
  - `replan_target` 必须非空
  - workflow 不得调用 Draft Prose Executor 重写当前 brief
- 当 `feedback_classification` 属于 `continuity_fix`、`character_voice_fix` 或 `upstream_conflict` 时：
  - Draft Research Loop SHOULD 先查询 Memory / KB / 用户授权，再生成最终 rewrite plan
- Draft Prose Executor 必须按 `preserve`、`remove_or_change`、`must_not_change` 和约束字段重写，不得自由扩大重写范围

## 6. Contract C: OutlineResearchQuestionSet

### 6.1 用途

- 表达 Outline Research Loop 在 `needs_user_input` 时需要用户补充的问题集
- 供 Web / CLI / TUI 用同一语义展示问题、收集回答并恢复等待态
- 驱动用户回答后继续 research 或生成大纲

### 6.2 Frozen Fields

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

### 6.3 Required Fields

- `schema_version`
- `question_set_id`
- `run_id`
- `stage`
- `status`
- `questions`
- `actions`
- `created_at`

### 6.4 Required Rules

- `questions` 必须至少包含一项
- 每个问题必须包含稳定 `question_id`、用户可读 `prompt` 和 `required`
- `stage`、`artifact_path` 和 workflow action 名不得作为普通用户界面的主状态展示；只能用于 action payload、恢复和 technical/debug 视图
- `actions.submit` 的语义必须等价于 `continue_after_outline_research_input`
- 普通聊天消息不得自动继续该问题集；必须收到结构化 submit action
- 问题集必须可通过落盘 artifact 或 `sufficiency_decision.json` 引用恢复

### 6.5 Boundary Notes

- `OutlineResearchQuestionSet` 是用户补充问题对象，不是正式 Memory 事实对象
- 用户回答成为 Writer planning evidence，不等于直接写入 Character Memory / World KB
- 新增人物、关系跃迁和世界规则突破仍需遵守对应规划与确认规则

## 7. Contract D: OutlineResearchAnswerSubmission

### 7.1 用途

- 表达用户对 `OutlineResearchQuestionSet` 的结构化回答
- 保留自然语言原文，并可选提供逐题映射
- 驱动 `continue_after_outline_research_input` 或等价 action

### 7.2 Frozen Fields

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

### 7.3 Required Fields

- `schema_version`
- `submission_id`
- `question_set_id`
- `run_id`
- `answer_text`
- `reviewer_type`
- `created_at`

### 7.4 Required Rules

- `answer_text` 必须保留用户原始回答
- `user_answers` 是可选结构化映射；若无法可靠映射，不得伪造缺失问题的答案
- 必答问题缺失时，workflow 应保持等待态或返回可读补充提示
- 被接受的回答进入 `planning_notebook` 或等价 artifact 时，来源类型必须是 `user_authorized`
- 回答提交必须绑定 `question_set_id`

## 8. Object Relationships

```text
ArtifactReviewDecision.decision = approved
  -> preserve supplement_text
  -> continue Agent Loop with supplement_text as prompt input

ArtifactReviewDecision.decision = revision_requested
  -> preserve revision_feedback
  -> revise the same artifact through model
  -> return to the same review gate

ArtifactReviewDecision.decision = deferred
  -> pause in recoverable state

GenerationReviewDecision.status = accepted
  -> draft may enter writeback review / writeback candidate

GenerationReviewDecision.status = rewrite_requested
  -> preserve feedback_text
  -> Draft Research Loop classifies feedback and may query Memory / KB / user
  -> write DraftRewritePlan
  -> Draft Prose Executor rewrites draft only if current brief remains valid
  -> no formal writeback

GenerationReviewDecision.status = replan_requested
  -> preserve feedback_text
  -> Agent Loop revises ChapterPackage / ChapterBrief
  -> return to chapter artifact review

GenerationReviewDecision.status = discarded
  -> no writeback
  -> no automatic next chapter

OutlineResearchQuestionSet.status = pending
  -> submit answer via continue_after_outline_research_input
  -> accepted answers become user_authorized evidence
  -> may continue research or generate outline

DraftResearchDecision.status = ready_for_draft
  -> Draft Prose Executor may generate draft.md

DraftResearchDecision.status = needs_user_input / replan_requested / blocked
  -> no draft generation

DraftRewritePlan.requires_replan = false
  -> Draft Prose Executor may rewrite within current approved brief

DraftRewritePlan.requires_replan = true
  -> return to upstream review gate
```

## 9. Writeback Boundary

- 只有 `GenerationReviewDecision.status = accepted` 的草稿允许进入正式写回候选
- `rewrite_requested`、`replan_requested`、`discarded` 都不得触发正式 Memory / KB 回写
- 写回摘要本身也应作为 review artifact，允许用户通过、要求修订或稍后处理

## 10. Recommended Storage Targets

建议运行期至少落盘以下文件：

- `artifact_review_decision.json`
- `user_supplement.json`
- `generation_review_decision.json`
- `draft_seed_packet.json`
- `draft_research_decision.json`
- `draft_research_trace.json`
- `draft_context_notebook.json`
- `draft_rewrite_plan.json`
- `outline_research_question_set.json`
- `outline_research_answer_submission.json`

## 11. Breaking Change Rules

以下变更视为 breaking change：

- 删除必填字段
- 改变 `decision`、`status` 或 `reason_code` 的既有语义
- 改变 review decision 与 Agent Loop 分支之间的映射关系
- 允许 `rewrite_requested` 绕过 Draft Research Loop 直接调用旧正文 prompt
- 改变 `question_set_id` / `question_id` 的稳定性要求
- 改变用户回答必须保留原文并作为 `user_authorized` evidence 的语义
- 允许普通聊天消息自动绕过结构化问题集等待态

以下变更视为兼容扩展：

- 新增可选字段
- 新增非破坏性的 `reason_code`
- 为 review / answer 对象增加 debug-only 引用字段
