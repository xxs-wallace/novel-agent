# Service Contributor Rules

- 禁止在 Agent service 层新增本地文本理解、文本抽取、人物识别、关系识别、情节判断等规则化处理逻辑，除非用户在当前任务中明确要求。
- 需要理解正文、人物名称、人物关系、称谓指代、情节事实或摘要时，默认交给大模型/Agent prompt 处理，并把模型输出作为结构化数据传递给 service。
- Service 层只负责 orchestration、schema normalization、persistence、budgeting、deduplication 和对模型已返回结构化字段的保守校验；不要用分词器、正则、词表或启发式规则从正文中生成新的人物名或事实。
- 如果必须加入本地文本处理兜底，先在代码注释和测试中写明用户要求、触发条件、不会进入模型 prompt 的原因，以及不会覆盖模型判断的边界。
