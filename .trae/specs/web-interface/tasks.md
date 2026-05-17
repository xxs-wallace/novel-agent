# Web Interface Tasks

本任务清单只拆分 Web UI 与 Writer Agent Loop 接入工作，不替代 [`spec.md`](spec.md)、[`design.md`](design.md) 或 Writer 侧 spec / design / contracts。实现前必须重新读取相关文档与对应代码，涉及跨层对象时以 contracts 为准。

## Reading Rules

- 涉及 Writer 问题集、artifact review、章节验收或回答提交时，必须先读 [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md)。
- 涉及 Writer 状态、review gate、用户补充信息进入 prompt 或章节草稿分支时，必须先读 [`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md)、[`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md) 和 [`../writer-agent-layered-generation/specs/runtime-boundaries.spec.md`](../writer-agent-layered-generation/specs/runtime-boundaries.spec.md)。
- Web 普通 UI 不得把 checkpoint id、artifact path、workflow stage/action 名当作主状态展示；这些只能进入 technical drawer、日志或 debug payload。
- 本任务文件不勾选实现状态，除非明确执行对应 QA / 验收。

## Group A: Conversation Model And Writer Questions

- [ ] Task W1: 定义 Web 侧 Writer 会话 payload 与 API 类型
  - `来源`: [`spec.md`](spec.md), [`design.md`](design.md), [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md)
  - `依赖`: Writer Task 60
  - `建议关注代码`: `novel_agent/app/web/schemas.py`, `web/src/api/types.ts`, OpenAPI 生成链路
  - [ ] 定义 `WriterQuestionSet` / `WriterQuestion` / `WriterQuestionAnswerMessage`
  - [ ] 定义 `WriterArtifactReview` 或等价 view model，包含 `run_id`、`review_id`、`artifact_kind`、artifact 引用、用户可见提示和可执行 actions
  - [ ] 定义 `WriterDraftReview` 或等价 view model，覆盖 `accepted / rewrite_requested / replan_requested / discarded / deferred`
  - [ ] 区分普通可见字段与 debug-only 的 workflow stage、artifact path、raw contract
  - [ ] 增加 OpenAPI / schema snapshot 测试，确保前后端类型一致

- [ ] Task W2: 后端把 Outline Research `needs_user_input` 转成聊天问题消息
  - `来源`: [`spec.md`](spec.md) 的 Writer 提问聊天式结构化交互, [`design.md`](design.md) 的 Outline Research action 语义
  - `依赖`: Task W1, Writer Task 60
  - `建议关注代码`: `novel_agent/app/web/services/web_session_service.py`, `novel_agent/app/web/services/web_action_service.py`, `novel_agent/app/web/services/artifact_view_service.py`
  - [ ] 从 Writer workflow / sufficiency decision / question set artifact 读取问题集，而不是解析日志纯文本
  - [ ] 在会话流中追加 Agent message + `WriterQuestionSet` payload
  - [ ] 问题卡普通视图不得暴露 checkpoint id、artifact path 或内部 action 名；technical drawer 可展示
  - [ ] 回放历史消息时可以恢复待回答问题卡和输入框回答上下文

- [ ] Task W3: 实现 `submit_outline_research_answers` 与 `defer_outline_research_answers`
  - `来源`: [`design.md`](design.md), [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md)
  - `依赖`: Task W1, Task W2, Writer Task 61
  - `建议关注代码`: `novel_agent/app/web/services/web_action_service.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/`
  - [ ] `submit_outline_research_answers` 调用共享 Writer workflow 的 `continue_after_outline_research_input` 或等价入口
  - [ ] payload 支持 `answer_text`、可选 `user_answers[]`、`source_message_id`、`run_id` 和 `question_set_id`
  - [ ] 原始回答文本必须落入会话与 Writer evidence；不得伪造未回答问题
  - [ ] `defer_outline_research_answers` 只保留等待态，不推进 workflow
  - [ ] 普通 `/messages` 自然语言输入不得自动继续 workflow

- [ ] Task W4: 实现前端 `WriterQuestionCard` 与回答上下文
  - `来源`: [`spec.md`](spec.md), [`design.md`](design.md)
  - `依赖`: Task W1-W3
  - `建议关注代码`: `web/src/components/conversation/ConversationPane.tsx`, `web/src/components/conversation/`, `web/src/api/`
  - [ ] Agent 消息内渲染问题列表、必答状态、提示文本和 inline buttons
  - [ ] 同一个聊天输入框可进入当前 question set 的回答上下文，并支持取消上下文
  - [ ] 用户发送回答后生成绑定 `question_set_id` 的 user message
  - [ ] “提交回答并继续研究”按钮发送结构化 action，而不是 slash command
  - [ ] 增加 React Testing Library / MSW 测试覆盖渲染、回答、提交和稍后继续

## Group B: Writer Artifact Review Loop

- [ ] Task W5: 后端实现 `ArtifactReviewDecision` action adapter
  - `来源`: [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md) 的 `ArtifactReviewDecision`
  - `依赖`: Task W1, Writer Task 65
  - `建议关注代码`: `novel_agent/app/web/services/web_action_service.py`, `novel_agent/app/web/services/web_session_service.py`, `novel_agent/runs/writer.py`, `novel_agent/tests/test_web_action_service.py`
  - [ ] 实现 `approve_writer_artifact`，payload 包含 `run_id`、`review_id`、`artifact_kind`、可选 artifact 引用、`supplement_text`、`source_message_id`
  - [ ] 实现 `request_writer_artifact_revision`，payload 包含 `revision_feedback` 原文，并交给 Writer workflow 修订当前 artifact
  - [ ] 实现 `defer_writer_artifact_review`，只保持可恢复等待态
  - [ ] action result 返回下一条 Agent 消息、可刷新 artifact id 和 technical details
  - [ ] 后端测试覆盖 supplement / revision feedback 原文保留、defer 不推进、普通 UI 不泄露技术字段

- [ ] Task W6: 前端实现 `WriterArtifactReviewCard`
  - `来源`: [`spec.md`](spec.md), [`design.md`](design.md)
  - `依赖`: Task W1, Task W5
  - `建议关注代码`: `web/src/components/conversation/`, `web/src/components/result/`, `web/src/api/`
  - [ ] 在 Agent 消息内展示 artifact 摘要、右侧详情入口和下一步提示
  - [ ] “通过并继续”允许输入可选 `supplement_text`，并调用 `approve_writer_artifact`
  - [ ] “不通过并调整”要求输入 `revision_feedback`，并调用 `request_writer_artifact_revision`
  - [ ] “稍后继续”调用 `defer_writer_artifact_review`
  - [ ] 同一个聊天输入框可进入通过补充或调整反馈上下文，体验类似 Codex 对话循环
  - [ ] 增加前端测试覆盖三种 action、输入上下文切换和技术字段隐藏

- [ ] Task W7: 实现 Writer artifact review 消息恢复与刷新
  - `来源`: [`design.md`](design.md) 的 ConversationPane / ResultExplorer 协作
  - `依赖`: Task W5, Task W6
  - `建议关注代码`: `novel_agent/app/web/services/web_session_service.py`, `novel_agent/app/web/services/artifact_view_service.py`, `web/src/components/conversation/MessageList.tsx`, `web/src/components/result/`
  - [ ] 刷新页面后可恢复当前 artifact review card 与输入上下文
  - [ ] 修订完成后刷新右侧 artifact view，并在会话中追加“已生成调整版本，请审阅”之类的自然语言消息
  - [ ] 应用新版 artifact 不自动继续 workflow，必须等待用户通过
  - [ ] technical drawer 可以查看 raw decision、artifact path 和 run id

## Group C: Chapter Draft Review Loop

- [ ] Task W8: 更新章节草稿验收后端 action
  - `来源`: [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md) 的 `GenerationReviewDecision`
  - `依赖`: Writer Task 67
  - `建议关注代码`: `novel_agent/app/web/services/web_action_service.py`, `novel_agent/app/cli/decisions.py`, `novel_agent/tests/test_web_action_service.py`
  - [ ] `accept_chapter` 映射为 `GenerationReviewDecision.status = accepted`
  - [ ] `rewrite_chapter` 映射为 `GenerationReviewDecision.status = rewrite_requested`，保留 `feedback_text` 原文
  - [ ] `replan_chapter` 映射为 `GenerationReviewDecision.status = replan_requested`，保留 `feedback_text` 原文，并回到章节梗概 review gate
  - [ ] `discard_chapter` 映射为 `discarded`
  - [ ] `defer_chapter_acceptance` 不写正式 decision，只保留待验收状态
  - [ ] 后端测试覆盖非 accepted 分支不得触发 Memory / KB 写回

- [ ] Task W9: 前端更新章节草稿验收卡
  - `来源`: [`spec.md`](spec.md), [`design.md`](design.md)
  - `依赖`: Task W8
  - `建议关注代码`: `web/src/components/conversation/`, `web/src/components/result/`
  - [ ] 展示正文草稿短预览、字数、连续性摘要和右侧完整正文入口
  - [ ] 提供“接受本章 / 基于反馈重写 / 修改章节梗概后重写 / 作废本次草稿 / 稍后再决定”
  - [ ] 非接受分支要求或允许输入 `feedback_text`，并通过同一聊天输入框提交
  - [ ] 不再展示“调整字数后重写”作为单独主分支；字数要求进入 `feedback_text`
  - [ ] 前端测试覆盖五种分支和非接受分支不显示写回成功

## Group D: Result Explorer And Writer Views

- [ ] Task W10: 更新 Writer artifact tree 到 Agent Loop 结构
  - `来源`: [`spec.md`](spec.md), [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `建议关注代码`: `novel_agent/app/web/services/artifact_tree_service.py`, `novel_agent/app/web/services/artifact_view_service.py`, `web/src/components/result/`
  - [ ] Writer 树增加大纲研究、问题集、planning notebook、trace、全书规划、批次计划、章节梗概、写作指导、正文草稿、验收决策和写回摘要节点
  - [ ] 移除“章节长度计划”作为普通用户必须审阅的主节点；可在写作指导或 technical drawer 中展示派生长度预算
  - [ ] 普通视图展示用户能理解的摘要、证据、缺口、风险和下一步建议，不展示裸 JSON
  - [ ] technical drawer 可查看 artifact path、raw contract 和 debug trace

- [ ] Task W11: 实现 Writer artifact view model
  - `来源`: [`design.md`](design.md) 的 ArtifactView / WriterArtifactView
  - `依赖`: Task W10
  - `建议关注代码`: `novel_agent/app/web/services/artifact_view_service.py`, `web/src/components/result/`
  - [ ] `BookContinuationPlan` 展示续写目标、规模、高潮、角色弧、假设和未决问题
  - [ ] `BatchPlan` 展示阶段目标、主要冲突、情绪节奏、出口钩子和禁止提前消费项
  - [ ] `ChapterPackage` / `ChapterBrief` 展示标题、梗概、scene beats、人物行动、关系推进、必须出现和禁止项
  - [ ] `ChapterWritingGuidance` 展示用户补充原文、派生长度预算、风格节奏和重点展开要求
  - [ ] `draft.md` 展示短预览、完整正文入口、连续性检查和验收状态
  - [ ] 增加 snapshot 测试确认普通视图不泄露 raw JSON

## Group E: Writer Start And Conversation Shell

- [ ] Task W12: 扩展 Web Writer intent wizard 到完整 Writer 启动输入
  - `来源`: [`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md) Layer 0A, [`../writer-agent-layered-generation/tasks.md`](../writer-agent-layered-generation/tasks.md) Task 21A
  - `建议关注代码`: `web/src/components/conversation/WriterIntentWizard.tsx`, `novel_agent/app/cli/forms.py`, `novel_agent/app/web/services/web_action_service.py`
  - [ ] 收集故事规模、目标总字数、默认单章字数、节奏偏好、长度分布说明
  - [ ] 收集冲突高潮、情感高潮、目标章节位置、必须铺垫与禁止提前解决项
  - [ ] 支持从聊天输入自然语言预填 wizard 字段
  - [ ] 提交 payload 映射到 Writer 现有启动 contract，不新增冲突字段

- [ ] Task W13: ConversationPane 支持 Codex-like Writer Loop
  - `来源`: [`design.md`](design.md) 的 ConversationPane
  - `依赖`: Task W4, Task W6, Task W9
  - `建议关注代码`: `web/src/components/conversation/ConversationPane.tsx`, `web/src/components/conversation/MessageList.tsx`, `web/src/api/`
  - [ ] 同一个输入框支持普通聊天、问题回答、artifact 通过补充、artifact 修订反馈和草稿验收反馈五种上下文
  - [ ] 输入框清楚显示当前上下文，并允许取消回到普通聊天
  - [ ] 普通聊天发送只写 message，不自动推进 Writer workflow
  - [ ] 结构化按钮负责调用 `/actions`，并把最近 user message 作为 `source_message_id`
  - [ ] 前端测试覆盖上下文切换与普通消息不推进 workflow

## Group F: Integration And Acceptance

- [ ] Task W14: Web / Writer 接入测试矩阵
  - `来源`: [`design.md`](design.md) Testing Strategy
  - `依赖`: Task W1-W13, Writer Task 60-74
  - [ ] 后端测试覆盖 Writer 问题消息生成、回答提交、稍后继续、artifact approve/revision/defer、普通聊天不推进 workflow
  - [ ] 后端测试覆盖章节草稿 accepted-only writeback 和 rewrite/replan/discard/defer 分支
  - [ ] 前端测试覆盖 Writer intent wizard、WriterQuestionCard、WriterArtifactReviewCard、章节验收卡、artifact tree
  - [ ] Playwright 覆盖“开始续写 -> 大纲研究提问 -> 聊天框回答 -> 按钮继续 -> 全书规划审阅 -> 通过并补充 -> 章节梗概审阅”
  - [ ] 验收确认普通用户界面不把内部状态、checkpoint 或 artifact id 当作主状态展示

## Dependencies

- Task W2 depends on Task W1 and Writer Task 60.
- Task W3 depends on Task W1, Task W2 and Writer Task 61.
- Task W4 depends on Task W1-W3.
- Task W5 depends on Task W1 and Writer Task 65.
- Task W6 depends on Task W1 and Task W5.
- Task W7 depends on Task W5-W6.
- Task W8 depends on Writer Task 67.
- Task W9 depends on Task W8.
- Task W10 depends on current Writer artifact layout and Writer Task 66.
- Task W11 depends on Task W10.
- Task W12 depends on Writer Task 21A and existing Writer start action.
- Task W13 depends on Task W4, Task W6 and Task W9.
- Task W14 depends on Task W1-W13 and Writer Task 60-74.
