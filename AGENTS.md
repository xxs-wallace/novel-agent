# Contributor Guidelines

本仓库的实现工作必须以 `.trae/specs` 中已经定义的产品流程、模块边界、contract 和任务说明为准。`AGENTS.md` 只整理执行规则，不替代 spec / design / contracts / tasks。

## Document Hierarchy

- `.trae/specs/spec.md` 是小说续写系统的产品级 Source of Truth，负责核心流程、用户入口、用户可见状态文案和人工确认规则。
- 各模块 `spec.md` 负责定义模块能力、输入输出边界和不可违反的业务规则。
- `design.md` 负责实现方案、模块协作、状态机、回滚策略和技术取舍。
- `contracts.md` 负责冻结跨层 JSON 对象、字段、类型和语义。
- `tasks.md` 负责开发任务拆分和验收清单；实现任务默认不得直接勾选 task，只有明确执行 QA / 验收时才更新完成状态。

## Engineering Rules

- Follow OOP principles.
- Be Pythonic: follow Python best practices and idiomatic patterns.
- Write unit tests for new functionality.
- 修改行为前先读取相关 spec / design / contracts / tasks，再判断实现方式。
- 涉及跨层对象时，必须先查对应 `contracts.md`，不得在代码里自行改变已冻结字段名、字段类型或字段语义。
- 涉及用户可见流程、入口、状态文案或人工确认点时，必须遵守 `.trae/specs/spec.md`。
- 涉及模块内部能力时，优先遵守该模块目录下的 `spec.md` 和 `design.md`。
- 不得用本地 heuristic / deterministic fallback 伪装模型已完成语义判断。若功能 contract 需要模型理解正文、摘要、人物、关系、篇章结构、规划或评审，生产路径中缺少模型、模型 id 缺失、模型不可访问、请求失败或 JSON 解析失败时，只能在有限次数和时间内重试；重试后仍失败必须抛出异常或返回显式 `failed` / `blocked` / `skipped` / `needs_model` 状态。来自用户操作的异常必须在最上层 catch 后通知用户任务失败；来自后台任务的模型异常必须标记任务失败，并保存可供用户点击查看的错误栈。只有 spec 明确允许的 dry-run、测试、兼容迁移或安全保底路径可以使用本地 fallback，并且产物必须显式标注 `dry_run` / `fallback` / `provisional`，不得标记为 `success`、`ready`、`committed` 或正常验收结果。

## Product Constraints

- 用户界面不得把内部状态、冻结点、checkpoint 或 artifact id 当作主状态展示；内部术语只能放在技术详情、日志、JSON 或开发者文档中。
- CLI / TUI、Web、GUI 必须共享同一套流程语义、状态文案、artifact 审阅规则和继续执行规则。
- 旧式 one-shot MVP CLI 入口只可作为 smoke、兼容测试或迁移脚本保留，不作为正式用户产品入口。
- 用户确认或修改后的规划、梗概、长度计划和写作材料，必须成为后续流程输入。

## Data And Domain Constraints

- Original Canon First：涉及事实、人物、关系、时间线和设定时，优先依据本地文档、Memory、KB 和代码，不自由脑补。
- Retrieval First：涉及现有 spec、tasks、contract、实现状态时，先读文件再判断。
- Traceability：关键判断应能说明依据来自哪个 spec、contract、task、artifact 或代码位置。
- No Forced Invention：证据不足时明确说明证据不足、需要补充读取或需要用户授权。
- 不得在代码、prompt、fallback、默认词典、别名表、白名单、标签规则或测试默认数据中写入只服务某一部小说的专有名词、角色名、设定名、桥段偏好或语义映射。
- 需要优化 prompt 或本地处理逻辑时，应抽象为适用于所有小说的通用能力，或从当前 book 的输入、记忆、配置和模型抽取结果中动态获得。
