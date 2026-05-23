# Reviewer Agent Contracts

## 1. Purpose

本文件冻结 Reviewer Agent 第一阶段跨层 JSON contract。

这些对象用于 Reviewer Runtime、Reviewer 插件、Memory / KB 工具、benchmark 调用方和未来 Writer / UI 接入方之间传递数据。字段语义一旦实现，不得在代码中随意改名、改类型或改变含义。

## 2. Shared Conventions

- 所有对象必须 JSON 兼容。
- 时间使用 ISO 8601 UTC 字符串。
- 路径使用绝对路径或仓库内可解析相对路径。
- `score` 为 0-100 的整数，只在 `status = success` 时表示有效参考评分。
- 所有 Reviewer 分数的用途固定为 `reference_only`，不得作为 Writer 或 Benchmark 的通过标准。
- 中文用户可见意见使用 `_zh` 后缀字段。
- `model_id` 必须记录实际使用的模型；无模型时不得返回 `success`。
- `trace` 字段用于开发和审计，不作为普通用户主状态展示。

## 3. Contract A: ReviewTarget

### 3.1 用途

表示一个可被 Reviewer 评审的目标。

### 3.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "target_id": "target-run-20260520-001",
  "target_type": "draft",
  "text": "这一段需要评审的正文……",
  "document_ids": ["123", "124"],
  "artifact_id": "chapter-003-draft-v2",
  "artifact_path": "runs/writer/run-001/draft.md",
  "chapter_id": "chapter-003",
  "range_hint": {
    "start_offset": 0,
    "end_offset": 3000
  },
  "source_refs": [
    {
      "source_type": "document",
      "source_id": "123",
      "label": "第 12 章"
    }
  ],
  "metadata": {}
}
```

### 3.3 Required Fields

- `schema_version`
- `target_id`
- `target_type`

### 3.4 Target Type Enum

- `draft`
- `synopsis`
- `outline`
- `chapter_brief`
- `planning_note`
- `raw_text`

### 3.5 Rules

- `text`、`document_ids`、`artifact_path` 至少一个必须存在。
- `document_ids` 是可选来源引用，不是 Reviewer 的唯一输入。
- `target_type` 决定可用 reviewer、prompt rubric 和上下文查询策略。

## 4. Contract B: ReviewContextPolicy

### 4.1 用途

声明本次评审可以读取哪些上下文。

### 4.2 Frozen Fields

```json
{
  "schema_version": "1.0",
  "purpose": "writer_assist",
  "allow_memory": true,
  "allow_kb": true,
  "allow_writer_artifacts": true,
  "allow_reference_truth": false,
  "allowed_artifact_kinds": ["chapter_brief", "draft", "synopsis", "outline"],
  "leakage_guard": "prefix_only",
  "notes": ""
}
```

### 4.3 Purpose Enum

- `writer_assist`
- `user_review`
- `benchmark`
- `diagnostic`

### 4.4 Leakage Guard Enum

- `prefix_only`
- `benchmark_authorized_reference`
- `user_authorized`
- `none`

### 4.5 Rules

- 当 `purpose != benchmark` 时，`allow_reference_truth` 必须为 `false`。
- 当 `allow_memory = true` 时，Memory 查询必须通过 `NarrativeMemoryQueryService` 或等价 facade。
- 当 `allow_kb = true` 时，KB 查询必须通过只读 KB facade。
- 未授权工具调用必须被拒绝并记录 trace。

## 5. Contract C: ReviewBudget

### 5.1 Frozen Fields

```json
{
  "schema_version": "1.0",
  "max_model_calls": 6,
  "max_tool_calls": 8,
  "max_memory_query_rounds": 4,
  "max_kb_query_rounds": 3,
  "max_target_chars": 12000,
  "max_context_chars": 16000,
  "max_findings": 12,
  "json_repair_attempts": 1
}
```

### 5.2 Rules

- 预算耗尽时不得无限重试。
- 若证据不足影响评审可靠性，报告必须说明 `blocked_by_missing_context` 或降低 confidence。
- JSON repair 只允许修复语法，不得改写评审语义。

## 6. Contract D: ReviewRequest

### 6.1 Frozen Fields

```json
{
  "schema_version": "1.0",
  "review_request_id": "review-req-20260520-001",
  "book_id": "book-001",
  "target": {},
  "reviewer_ids": ["local_draft_continuity", "memory_draft_consistency"],
  "context_policy": {},
  "budget": {},
  "user_focus": "重点看人物语言是否突兀",
  "created_at": "2026-05-20T10:00:00Z",
  "metadata": {}
}
```

### 6.2 Required Fields

- `schema_version`
- `review_request_id`
- `book_id`
- `target`
- `reviewer_ids`
- `context_policy`
- `budget`
- `created_at`

### 6.3 Rules

- `reviewer_ids` 为空时，调用方必须显式选择默认 suite，不得由 runtime 静默猜测。
- `user_focus` 是评审偏好，不得覆盖 Reviewer rubric 的硬性边界。

## 7. Contract E: ResolvedReviewTarget

### 7.1 Frozen Fields

```json
{
  "schema_version": "1.0",
  "target_id": "target-run-20260520-001",
  "target_type": "draft",
  "resolved_text": "归一化后的可审阅文本……",
  "source_refs": [],
  "artifact_refs": [],
  "document_refs": [],
  "truncation": {
    "truncated": false,
    "strategy": "",
    "original_chars": 3000,
    "resolved_chars": 3000
  }
}
```

### 7.2 Rules

- `resolved_text` 是模型评审目标正文。
- 若发生裁剪，必须记录 `truncation`。
- Resolver 不得新增文本事实或改写目标语义。

## 8. Contract F: ReviewPlan

### 8.1 Frozen Fields

```json
{
  "schema_version": "1.0",
  "reviewer_id": "chapter_synopsis_plot_character",
  "target_id": "target-run-20260520-001",
  "dimensions": ["人物行动", "人物语言", "关系状态"],
  "initial_risks": [
    "目标文本中出现人物关系跃迁，需要查询前文关系状态"
  ],
  "tool_requests": [
    {
      "tool": "memory_query",
      "intent": "查询主要人物最近关系状态和历史对话风格",
      "priority": "high",
      "expected_evidence": "character_profile"
    }
  ],
  "can_judge_without_context": false,
  "notes_zh": "需要先确认人物关系状态。"
}
```

### 8.2 Rules

- `ReviewPlan` 必须由模型生成。
- `tool_requests` 是请求，不是授权；runtime 必须按 `ReviewContextPolicy` 校验。

## 9. Contract G: ReviewerToolCall

### 9.1 Frozen Fields

```json
{
  "schema_version": "1.0",
  "tool_call_id": "tool-call-001",
  "tool": "memory_query",
  "intent": "查询人物 A 与人物 B 最近关系状态",
  "query": "人物 A 与人物 B 最近关系状态",
  "budget": {},
  "reason_zh": "目标文本中两人突然互相信任，需要前文证据。",
  "created_at": "2026-05-20T10:01:00Z"
}
```

### 9.2 Tool Enum

- `memory_query`
- `kb_retrieval`
- `artifact_read`

### 9.3 Rules

- 工具调用必须进入 loop trace。
- 被 policy 拒绝的工具调用必须记录拒绝原因。

## 10. Contract H: ReviewerToolResult

### 10.1 Frozen Fields

```json
{
  "schema_version": "1.0",
  "tool_call_id": "tool-call-001",
  "tool": "memory_query",
  "status": "success",
  "evidence_items": [],
  "source_refs": [],
  "trace": [],
  "error": ""
}
```

### 10.2 Status Enum

- `success`
- `skipped`
- `blocked`
- `failed`

## 11. Contract I: EvidenceRef

### 11.1 Frozen Fields

```json
{
  "evidence_id": "ev-001",
  "source_type": "target_text",
  "source_id": "target-run-20260520-001",
  "quote": "她在众人面前直接承认了自己的身份。",
  "summary_zh": "目标文本中人物公开承认身份。",
  "location": {
    "document_id": "123",
    "offset_start": 120,
    "offset_end": 150
  }
}
```

### 11.2 Source Type Enum

- `target_text`
- `memory`
- `kb`
- `writer_artifact`
- `reference_truth`
- `user_input`

### 11.3 Rules

- 强结论必须尽量绑定 evidence。
- `reference_truth` 只能在 benchmark 授权场景出现。

## 12. Contract J: ReviewFinding

### 12.1 Frozen Fields

```json
{
  "finding_id": "finding-001",
  "severity": "major",
  "category": "chapter_synopsis_plot_character",
  "message_zh": "人物的语气突然变得过于亲密，和前文关系状态缺少过渡。",
  "evidence_refs": ["ev-001", "ev-002"],
  "suggestion_zh": "建议补一段试探或共同经历，让信任关系有可见推进。",
  "confidence": 0.78
}
```

### 12.2 Severity Enum

- `critical`
- `major`
- `minor`
- `note`

## 13. Contract K: ReviewReport

### 13.1 Frozen Fields

```json
{
  "schema_version": "1.0",
  "review_report_id": "review-report-20260520-001",
  "review_request_id": "review-req-20260520-001",
  "target_id": "target-run-20260520-001",
  "target_type": "draft",
  "reviewer_id": "local_draft_continuity",
  "reviewer_version": "1.0.0",
  "status": "success",
  "score": 82,
  "score_usage": "reference_only",
  "summary_zh": "整体逻辑顺畅，但关键转折的铺垫不足。",
  "dimension_scores": {
    "因果链": 84,
    "动机": 78,
    "转折铺垫": 72
  },
  "findings": [],
  "evidence_refs": [],
  "suggested_revision_focus": [
    "补足转折前的动机铺垫"
  ],
  "confidence": 0.82,
  "memory_query_trace": [],
  "kb_query_trace": [],
  "artifact_trace": [],
  "self_check": {
    "status": "passed",
    "notes_zh": ""
  },
  "model_id": "deepseek-chat",
  "created_at": "2026-05-20T10:03:00Z",
  "metadata": {}
}
```

### 13.2 Status Enum

- `success`
- `failed`
- `needs_model`
- `skipped`

### 13.3 Rules

- `status = success` 时，`score`、`summary_zh`、`model_id` 必填。
- `status != success` 时，不得提供看似正式有效的评分。
- `score` 必须为 0-100 整数。
- `score_usage` 必须为 `reference_only`。
- `summary_zh` 必须是中文。
- `findings` 必须按严重程度排序。
- report 是参考评审意见，不是 Writer 或 Benchmark 流程决策。
- report 不得包含 `quality_decision`、`verdict` 或等价质量裁决字段；不得把运行态 `status = success / failed` 解释为目标文本质量通过或失败。

## 14. Contract L: ReviewSuiteReport

### 14.1 Frozen Fields

```json
{
  "schema_version": "1.0",
  "suite_report_id": "suite-report-20260520-001",
  "review_request_id": "review-req-20260520-001",
  "target_id": "target-run-20260520-001",
  "status": "success",
  "overall_score": 80,
  "score_usage": "reference_only",
  "summary_zh": "正文整体可用，主要问题集中在人物动机铺垫和局部节奏。",
  "reviewer_reports": [],
  "top_findings": [],
  "created_at": "2026-05-20T10:05:00Z"
}
```

### 14.2 Rules

- suite report 不得抹掉单个 reviewer 的原始报告。
- `overall_score` 的聚合策略必须记录在 metadata 或 suite config 中。
- `score_usage` 必须为 `reference_only`。
- 任何 reviewer `failed` 时，suite 必须保留失败状态和错误详情。

## 15. Contract M: ReviewerManifest

### 15.1 Frozen Fields

```json
{
  "schema_version": "1.0",
  "reviewer_id": "kb_draft_style_atmosphere",
  "reviewer_version": "1.0.0",
  "display_name_zh": "文笔与氛围评审",
  "supported_target_types": ["draft", "raw_text"],
  "dimensions": ["文笔", "氛围", "节奏", "叙述视角"],
  "requires_model": true,
  "allowed_tools": ["kb_retrieval"],
  "default_budget": {}
}
```

### 15.2 Rules

- 正式 Reviewer 的 `requires_model` 必须为 `true`。
- fake / baseline reviewer 不得出现在正式 manifest 中。
- 第一阶段正式 manifest 至少包含 `outline_plot_development`、`chapter_synopsis_plot_character`、`local_draft_continuity`、`memory_draft_consistency`、`kb_draft_style_atmosphere`。
