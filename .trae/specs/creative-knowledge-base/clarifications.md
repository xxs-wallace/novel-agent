# Creative Knowledge Base Clarifications

本文整理当前 `creative-knowledge-base` 相关文档里，仍然存在表述不够清楚、容易导致不同 Agent 实现分叉的点，供后续对齐使用。

依据文件：

- `/.trae/specs/creative-knowledge-base/spec.md`
- `/.trae/specs/creative-knowledge-base/tasks.md`

## 1. 结论摘要

当前最需要澄清的，不是近重复检测或 rerank rubric 这种规则本身，而是以下三类问题：

1. 入口边界不清楚
2. 验收标准不够可操作
3. 任务之间存在范围重叠

如果不先补清这三类问题，后续很容易出现：

- 多个 Agent 各自实现“入口”，但形态不同
- 测试无法准确判断“辅助输入”是否被错误提升为主路径
- 同一件事在 Task 5 和 Task 14 被重复实现

## 2. 需要澄清的问题

### 2.1 Task 14 的“编排入口”交付物不清楚

涉及：

- `tasks.md` Task 14
- `spec.md` Agent Boundaries

当前表述：

- `tasks.md` 只说要实现：
  - Creative Knowledge Base Agent 的离线入口
  - Retrieval Agent 的在线入口
  - 明确输出给续写主 Agent 的 data contract
- `spec.md` 只给了边界：
  - Creative Knowledge Base Agent 负责建卡、去重、代表片段选择
  - Retrieval Agent 负责粗筛、cluster 去重、固定 rubric rerank

不清楚点：

- “入口”到底是：
  - 一个 service facade
  - 一个 runner
  - 一个 CLI 命令
  - 一个主编排层可调用的函数
  - 还是仅文档级约定
- “不改主编排层入口”的前提下，Task 14 的实现应放在哪一层也没有写死
- “明确输出给续写主 Agent 的 data contract” 是只写文档，还是必须产出代码对象 / adapter / bundle builder

为什么会影响实现：

- 不同 Agent 可能会分别做成：
  - `service`
  - `runner`
  - `orchestrator helper`
- 这些都“看起来合理”，但后续很难合并

建议补充的澄清问题：

1. Task 14 的入口形态是什么？
2. 是否允许新增 runner / facade 文件？
3. 交付标准是“能被主层调用”，还是“真正接到主层”？
4. `WriterInputBundle` 是否属于 Task 14 的必交付范围？

建议文案方向：

- 在 `tasks.md` 中把“入口”明确为“service-level facade，不直接修改主编排层，只提供可调用接口和测试”

### 2.2 Task 9 与 Task 15 的“基础检索工具只作为辅助输入”不够可测试

涉及：

- `tasks.md` Task 9
- `tasks.md` Task 15 的相关测试项
- `spec.md` SceneBrief 输入 contract

当前表述：

- 现有基础检索工具保留为辅助输入，而非桥段主检索入口
- 基础检索结果只作为 `retrieval_context` 或过滤提示输入 `SceneBrief`
- 需要增加“基础检索工具仅作为辅助输入而非主检索路径”的测试

不清楚点：

- “辅助输入”具体允许影响哪些步骤？
  - 只允许影响 `SceneBrief`
  - 允许影响粗筛过滤
  - 允许影响 rerank prompt
  - 还是都允许但不可主导
- “不是主路径”如何落成可验证规则？
  - 不能直接生成 `candidate_fragment_ids`
  - 不能单独决定 TopK
  - 不能绕过 `fragment_cards`
  - 还是不能提高权重超过某阈值

为什么会影响实现：

- 如果没有可观察规则，就写不出稳定测试
- 很容易出现“逻辑上说是辅助，实际上权重上变成主排序依据”的回退

建议补充的澄清问题：

1. `retrieval_context` 是否允许直接参与粗筛打分？
2. `retrieval_context` 是否只能作用于 prompt，不得直接作用于排序？
3. 判定“不是主路径”的测试口径是什么？
4. 是否需要显式约束：没有 `fragment_cards` 命中时，不能只靠基础检索工具返回参考桥段？

建议文案方向：

- 明确写成：
  - `retrieval_context` 可以参与 `SceneBrief` 构造
  - 可以作为过滤提示
  - 但不得直接产出最终候选列表
  - 不得取代 `fragment_cards` 的多视图文本匹配

### 2.3 Task 5 与 Task 14 的范围重叠

涉及：

- `tasks.md` Task 5
- `tasks.md` Task 14
- `spec.md` Offline Pipeline

当前表述：

- Task 5 要实现：
  - 轻量标签 -> `fragment_card`
  - 标签同步写入 `preferred_tags`
  - 记录来源信息
- Task 14 又要实现：
  - 从 `documents` 构建 `fragment_cards` 与 `fragment_clusters`

不清楚点：

- Task 5 看起来像“流水线内部步骤”
- Task 14 看起来像“对外入口”
- 但文案没有明确两者分工

为什么会影响实现：

- 两个 Agent 可能都去做“从 documents 开始的一整条链路”
- 导致重复实现、重复测试、接口冲突

建议补充的澄清问题：

1. Task 5 是否只负责流水线内部节点，不负责对外入口？
2. Task 14 是否只负责把 Task 5/6/7 串起来，不重新实现内部逻辑？
3. 若已有建卡 service，Task 14 是否只能编排调用，不得重写核心规则？

建议文案方向：

- Task 5：负责离线链路中的“建卡节点”
- Task 14：负责离线链路的“统一入口 / 编排器”

### 2.4 Task 10 的“兼容演进”缺少明确交付物

涉及：

- `tasks.md` Task 10
- `spec.md` SceneBrief contract

当前表述：

- 旧 `ScenePlan` schema 暂时保留
- 新字段以后向兼容方式扩展
- 提供同时消费旧 `ScenePlan` 子集和新 `SceneBrief` 的过渡期 contract

不清楚点：

- 到底要交付：
  - 文档映射表
  - adapter 代码
  - schema 版本字段
  - 兼容测试
  - 还是全部都要

为什么会影响实现：

- “已实现”与“部分实现”的判断口径不一致
- 有人会觉得映射文档够了，有人会觉得必须有 runtime adapter

建议补充的澄清问题：

1. Task 10 的最低交付物是什么？
2. 是否要求必须存在 runtime adapter？
3. 是否必须提供兼容测试，才算完成？

建议文案方向：

- 把完成标准改成“adapter + 测试”或“文档 + 测试”，避免口径不一

### 2.5 Task 4 的验收口径不够具体，但整体方向清楚

涉及：

- `tasks.md` Task 4
- `spec.md` Fragment Card requirement

当前状态判断：

- 这部分不是“方向不清”
- 更像“完成标准还不够精细”

具体缺口：

- schema 失败后重试几次才算满足？
- 是否允许 fallback？
- prompt 是否必须限制 `source_excerpt` 长度？
- 输出校验失败时，是丢弃当前 document，还是写入保底卡片？

为什么会影响实现：

- 大方向一致，但不同人会做出不同失败策略
- 这些差异会影响离线构建稳定性

建议补充的澄清问题：

1. 建卡失败的标准 fallback 策略是什么？
2. retry 次数是否固定？
3. 是否允许“保底 fragment_card”进入库？

## 3. 不太算问题、相对已经清楚的部分

以下部分目前文案已经足够支撑实现：

- Task 6 近重复检测规则
- Task 7 representative 选择规则
- Task 8 SceneBrief 的输入输出字段
- Task 11 粗筛 contract
- Task 12 rerank contract
- Task 13 “标签只作辅助”的总体原则

原因：

- `spec.md` 对这些模块都给了比较明确的输入输出或判定边界
- `tasks.md` 也把实现项拆得较细，工程上容易对应

## 4. 建议优先对齐顺序

建议优先澄清顺序如下：

1. Task 14 的入口形态与交付边界
2. Task 9 / Task 15 中“辅助输入而非主路径”的可测试规则
3. Task 5 与 Task 14 的职责切分
4. Task 10 的最低交付物
5. Task 4 的失败处理与验收口径

## 5. 建议直接发给其他 Agent 的问题清单

可以直接拿下面这组问题去对齐：

1. Task 14 的“入口”具体是 service、runner、CLI 还是 facade？
2. Task 14 是否只负责编排，不重写 Task 5/6/7 的核心逻辑？
3. `retrieval_context` 允许影响哪些阶段，哪些阶段禁止直接参与排序？
4. “基础检索工具不是主路径”应如何写成可测试规则？
5. Task 10 的完成标准是文档、adapter、测试，还是三者都要？
6. Task 4 的 retry / fallback / 失败落库策略是否需要统一冻结？

## 6. 一句话总结

当前最需要补清的，不是“怎么检索桥段”，而是“谁负责提供入口、什么算完成、哪些辅助信号绝不能越级变成主路径”。
