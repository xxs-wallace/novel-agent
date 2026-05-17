# Service Contributor Rules

- 禁止在 Agent service 层新增本地文本理解、文本抽取、人物识别、关系识别、情节判断等规则化处理逻辑，除非用户在当前任务中明确要求。
- 需要理解正文、人物名称、人物关系、称谓指代、情节事实或摘要时，默认交给大模型/Agent prompt 处理，并把模型输出作为结构化数据传递给 service。
- Service 层只负责 orchestration、schema normalization、persistence、budgeting、deduplication 和对模型已返回结构化字段的保守校验；不要用分词器、正则、词表或启发式规则从正文中生成新的人物名或事实。
- 如果必须加入本地文本处理兜底，先在代码注释和测试中写明用户要求、触发条件、不会进入模型 prompt 的原因，以及不会覆盖模型判断的边界。
- Service 层不得在未调用模型、模型 id 缺失、模型不可访问、模型请求失败或 JSON 解析失败时，把本地 heuristic / deterministic fallback 当成已完成的语义产物返回。生产路径只能在有限次数和时间内重试；重试后仍失败必须返回显式失败、阻塞、跳过或 needs-model 状态，或抛出由上层统一捕获的异常。后台任务必须把这类异常标记为任务失败并保存错误栈；只有 dry-run、单元测试、兼容迁移或 spec 明确允许的安全保底可以返回 fallback，并且必须在 schema/status/trace 中标注 fallback 质量，不得写成 ready / committed / success。
