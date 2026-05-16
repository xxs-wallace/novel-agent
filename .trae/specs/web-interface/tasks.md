# Web Interface Tasks

本任务清单只拆分 Web UI 与 Writer workflow 接入工作，不替代 [`spec.md`](spec.md)、[`design.md`](design.md) 或 Writer 侧 spec / design / contracts。实现前必须重新读取相关文档与对应代码，涉及跨层对象时以 contracts 为准。

## Group A: Writer 启动与聊天式问题接入

- [ ] Task W1: 定义 Web 侧 Writer view model 与 API contract
  - `来源`: [`spec.md`](spec.md), [`design.md`](design.md), [`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md), [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md)
  - `建议关注代码`: `novel_agent/app/web/schemas.py`, `web/src/api/types.ts`, OpenAPI 生成链路
  - [ ] 定义 `WriterQuestionSet` / `WriterQuestion` / `WriterQuestionAnswerMessage` 或等价类型
  - [ ] 确保问题 payload 包含 `run_id`、`question_set_id`、`questions[]`、可选 artifact 引用和可执行 action
  - [ ] 区分用户可见中文文案与 debug-only 的 workflow stage / checkpoint / raw contract
  - [ ] 增加 OpenAPI / 类型生成或 schema snapshot 测试

- [ ] Task W2: 后端把 Outline Research `needs_user_input` 转成聊天问题消息
  - `来源`: [`spec.md`](spec.md) 的 `Conversational Writer Question Contract`, [`design.md`](design.md) 的 Outline Research action 语义
  - `依赖`: Writer Task 60
  - `建议关注代码`: `novel_agent/app/web/services/web_session_service.py`, `novel_agent/app/web/services/web_action_service.py`, `novel_agent/app/web/services/artifact_view_service.py`
  - [ ] 从 Writer workflow / sufficiency decision 中读取问题集，而不是解析日志纯文本
  - [ ] 在会话流中追加 Agent message + `WriterQuestionSet` payload
  - [ ] 问题卡普通视图不得暴露 checkpoint id、artifact path 或内部 action 名；技术详情可展示
  - [ ] 回放历史消息时可以恢复待回答问题卡和输入框回答上下文

- [ ] Task W3: 实现 `submit_outline_research_answers` 与 `defer_outline_research_answers`
  - `来源`: [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `依赖`: Writer Task 61
  - `建议关注代码`: `novel_agent/app/web/services/web_action_service.py`, `novel_agent/app/orchestrators/writer_workflow.py`, `novel_agent/tests/`
  - [ ] `submit_outline_research_answers` 调用共享 Writer workflow 的 `continue_after_outline_research_input` 或等价入口
  - [ ] payload 支持 `answer_text`、可选 `user_answers[]`、`source_message_id`、`run_id` 和 `question_set_id`
  - [ ] 原始回答文本必须落入会话与 Writer evidence；不得伪造未回答问题
  - [ ] `defer_outline_research_answers` 只保留等待态，不推进 Freeze A
  - [ ] 普通 `/messages` 自然语言输入不得自动继续 workflow

- [ ] Task W4: 实现前端 `WriterQuestionCard` 与回答上下文
  - `来源`: [`spec.md`](spec.md), [`design.md`](design.md)
  - `建议关注代码`: `web/src/components/conversation/ConversationPane.tsx`, `web/src/components/conversation/`, `web/src/api/`
  - [ ] Agent 消息内渲染问题列表、必答状态、提示文本和 inline buttons
  - [ ] 同一个聊天输入框可进入当前 question set 的回答上下文，并支持取消上下文
  - [ ] 用户发送回答后生成绑定 `question_set_id` 的 user message
  - [ ] “提交回答并继续研究”按钮发送结构化 action，而不是 slash command
  - [ ] 增加 React Testing Library / MSW 测试覆盖渲染、回答、提交和稍后继续

## Group B: Writer 审阅面板补齐

- [ ] Task W5: 扩展 Web Writer intent wizard 到完整 Writer 启动输入
  - `来源`: [`../writer-agent-layered-generation/spec.md`](../writer-agent-layered-generation/spec.md) Layer 0A, [`../writer-agent-layered-generation/tasks.md`](../writer-agent-layered-generation/tasks.md) Task 21A
  - `建议关注代码`: `web/src/components/conversation/WriterIntentWizard.tsx`, `novel_agent/app/cli/forms.py`, `novel_agent/app/web/services/web_action_service.py`
  - [ ] 收集故事规模、目标总字数、默认单章字数、节奏偏好、长度分布说明
  - [ ] 收集冲突高潮、情感高潮、目标章节位置、必须铺垫与禁止提前解决项
  - [ ] 提交 payload 映射到 Writer 现有启动 contract，不新增冲突字段

- [ ] Task W6: 补齐章节验收的结构化输入
  - `来源`: [`spec.md`](spec.md), [`design.md`](design.md), [`../writer-agent-layered-generation/contracts.md`](../writer-agent-layered-generation/contracts.md)
  - `建议关注代码`: `web/src/components/conversation/`, `novel_agent/app/web/services/web_action_service.py`
  - [ ] `revise_chapter_length` 使用目标 / 最小 / 最大字数和反馈理由的结构化输入
  - [ ] `replan_chapter` 使用必须保留、必须改变、禁止沿用项的结构化输入
  - [ ] `discard_chapter` 与 `defer_chapter_acceptance` 保持 runs 产物与等待态语义
  - [ ] 后端测试覆盖五种章节验收 action 到 Writer contract 的映射

- [ ] Task W7: 补齐 Writer artifact tree 与审阅视图
  - `来源`: [`spec.md`](spec.md), [`design.md`](design.md), [`../writer-agent-layered-generation/design.md`](../writer-agent-layered-generation/design.md)
  - `建议关注代码`: `novel_agent/app/web/services/artifact_tree_service.py`, `novel_agent/app/web/services/artifact_view_service.py`, `web/src/components/result/`
  - [ ] Writer 树增加大纲研究、问题集、planning notebook、trace、规划、批次、章节包、长度计划、正文草稿和验收记录节点
  - [ ] 普通视图展示用户能理解的摘要、证据、缺口和风险，不展示裸 JSON
  - [ ] technical drawer 可查看 artifact path、raw contract 和 debug trace
  - [ ] Scoped revision diff 与当前 artifact / run / stage 绑定，应用后不自动确认继续

## Group C: 验收与回归

- [ ] Task W8: Web / Writer 接入测试矩阵
  - `来源`: [`design.md`](design.md) Testing Strategy
  - `依赖`: Task W1-W7, Writer Task 60-63
  - [ ] 后端测试覆盖 Writer 问题消息生成、回答提交、稍后继续、普通聊天不推进 workflow
  - [ ] 前端测试覆盖 Writer intent wizard、WriterQuestionCard、章节验收表单、artifact tree
  - [ ] Playwright 覆盖“开始续写 -> 大纲研究提问 -> 聊天框回答 -> 按钮继续 -> 全书规划审阅”
  - [ ] 验收确认普通用户界面不把内部状态、checkpoint 或 artifact id 当作主状态展示

## Dependencies

- Task W2 depends on Task W1 and Writer Task 60.
- Task W3 depends on Task W1 and Writer Task 61.
- Task W4 depends on Task W1-W3.
- Task W5 depends on Writer Task 21A and existing Writer start action.
- Task W6 depends on existing Writer chapter review contracts.
- Task W7 depends on Task W1 and current Writer artifact layout.
- Task W8 depends on Task W1-W7 and Writer Task 60-63.
