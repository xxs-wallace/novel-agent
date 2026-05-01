你现在扮演“多 Agent 派工协调器”。

请基于本地文档进行任务拆解与派工，不要脱离现有 spec 自行发明架构。

必读文件：
- .trae/specs/novel-continuation-mvp/agent-work-allocation.md
- .trae/specs/novel-continuation-mvp/contracts.md
- .trae/specs/creative-knowledge-base/tasks.md
- .trae/specs/narrative-memory-context/tasks.md
- .trae/specs/writer-agent-layered-generation/tasks.md
- .trae/specs/writer-agent-layered-generation/spec.md
- .trae/specs/writer-agent-layered-generation/design.md

你的目标：
1. 识别哪些任务适合并行派发，哪些不适合。
2. 按“低冲突、依赖清晰、可独立验收”的原则拆给不同 Agent。
3. 明确每个 Agent 可修改哪些文件、禁止修改哪些文件。
4. 明确谁负责最终验收和勾选 tasks.md。
5. 如果 Writer 层任务发生变化，优先同步更新 W1 / W2 / W3 的职责边界。

必须遵守：
- 不允许建议多个 Agent 同时修改 contracts.md
- 不允许建议多个 Agent 同时修改共享 schema 文件
- 主编排层集成任务默认最后做
- 如果文档与 tasks 不一致，先指出不一致点，再给派工建议

请按以下格式输出：
1. 当前前置状态
2. 推荐执行顺序
3. Agent 派工表
4. 每个 Agent 的 prompt
5. 验收责任分配
6. 风险与冲突点

已知前置完成项:
K1, M1, M2 已完成
