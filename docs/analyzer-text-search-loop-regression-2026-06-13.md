# Analyzer Text Search Loop Regression - 2026-06-13

## 背景

回归任务：

> 诺诺发给路明非的生日快乐歌唱的是什么歌词？

这个任务暴露的核心问题不是“歌词问题要强制 raw source excerpt”，而是 Analyzer 在已经用 `text_search` 找到相关证据后，没有继续使用更像 grep 的策略核验后续状态。它把 doc-103 中“草稿箱、当时未发出”的早期状态当成了最终事实，忽略了后续 doc-173 中路明非实际点开并播放同一生日歌的片段。

最终优化后的回答正确定位为：

> 祝你生日快乐，李呀李嘉图，祝你生日快乐，李呀李嘉图……

并确认两段证据的时间边界：doc-103 是诺诺录制并放在草稿箱中犹豫；doc-173 是后来该短信出现在路明非手机中，他点开并反复播放。

## 代码改动

主要改动文件：

- `novel_agent/app/services/narrative_inquiry_broker.py`
- `novel_agent/app/services/outline_analyzer_service.py`
- `novel_agent/app/services/outline_research_service.py`
- `novel_agent/tests/test_outline_analyzer_service.py`
- `.trae/specs/outline-analyzer/design.md`
- `.trae/specs/writer-agent-layered-generation/spec.md`
- `.trae/specs/writer-agent-layered-generation/design.md`
- `.trae/specs/writer-agent-layered-generation/designs/outline-research-loop.design.md`

关键实现点：

- `text_search` 明确支持 `metadata.match_mode = all | any`：`all` 是 AND / 交集，`any` 是 OR / 并集。
- document scope 的 `text_search` 返回 `compact_match_window`，即共同命中窗口或最紧凑命中窗口，不默认返回完整 document。
- `text_search` evidence item 增加 `snippet_policy` 和 `full_document_available_via=raw_excerpt`，让模型知道当前只是定位窗口，长上下文要用 bounded `raw_excerpt`。
- Analyzer prompt / readiness / triage / final prompt 增加“内容事实”和“事件生命周期事实”分离规则。
- 用户题面里的动作、关系、对象、时间或结果限定被视为 sufficiency 条件，不能把“发给/收到/说出/使用”静默降级成“准备/计划/草稿”。
- 一旦发现高精度原句、标题、编号或独特称谓，下一轮应优先用该 exact phrase 做 document `text_search`，查找重复出现或后续结果场景。
- final evidence digest 保留 `text_search.snippet`，避免最终回答阶段丢掉命中片段。

## Snippet 还是完整 Document

最终策略不是把当前 document 全量塞回模型。

默认路径：

1. 先用 `text_search` 做低成本定位，返回紧凑命中窗口。
2. 如果 snippet 已经覆盖问题所需的事实粒度，可以作为候选事实。
3. 如果问题依赖长铺垫、相邻对话、动机、跨段关系或事件生命周期，就用返回的 `source_doc_ids` 请求 bounded `raw_excerpt`。
4. 如果已经发现 exact phrase，则优先用 exact phrase 继续 grep 后续出现，而不是扩大主题词噪音。

对小说文本来说，“只返回十几行”不总是够，但“直接返回完整 document”会放大 prompt 成本和无关干扰。因此当前折中是 compact snippet 作为 locator，bounded raw excerpt 作为升级路径。

## Analyzer Loop 决策策略

优化后的 Analyzer prompt loop 应按下面的顺序决策：

1. 判断用户问题需要哪些可核验事实，不只看关键词，也看题面限定。
2. 用少量具体关键词发起 `text_search`。多个约束必须共同出现时用 `all`，同义词、别名、译名、误写召回时用 `any`。
3. document search 命中后先读 compact snippet，判断它是答案证据、定位证据，还是暴露冲突的证据。
4. 如果 snippet 只证明“内容是什么”，但用户问题还要求“是否发送/收到/说出/使用/兑现/产生影响”，继续核验生命周期。
5. 如果 snippet 给出 exact phrase，用该 exact phrase 或更窄词组继续 document `text_search`，避免继续用宽词。
6. 如果需要完整语境，才基于 `source_doc_ids` 请求 bounded `raw_excerpt`。
7. readiness 逐条检查 proposed answer 中的断言，也检查 user question 的限定是否被满足；不能让模型把题面限定静默改写成更弱版本。
8. final answer 必须标明证据边界，不能把早期状态当成全书最终状态。

## 本次成功执行

成功 turn：

- `turn_id`: `e1b87756068044e1ba18d99206a05cb4`
- trace: `.memory/analyzer/longzu-前三部/turns/e1b87756068044e1ba18d99206a05cb4.md`
- prompt trace: `.memory/analyzer/longzu-前三部/turns/e1b87756068044e1ba18d99206a05cb4.prompts.jsonl`
- 状态：`succeeded`
- 模型 prompt 调用：14 次
- Analyzer loop 轮次：5 轮 loop + 1 次 readiness

执行概要：

| Step | Stage | Input | Output / memory |
| --- | --- | ---: | --- |
| 1 | intent_gate | 6.6 KB | 选择 `relationship_analysis`，要求定位诺诺向路明非发送生日歌的原文 |
| 2 | loop 1 | 20.1 KB | 请求 `text_search`，terms 包含“生日歌”“诺诺”，AND 定位章节摘要 |
| 3 | triage 1 | 10.3 KB | 保留 chapter-20 摘要；发现草稿箱/未发出早期状态 |
| 4 | loop 2 | 19.8 KB | 请求 doc-103 bounded `raw_excerpt`，提取草稿箱歌词 |
| 5 | triage 2 | 7.9 KB | 保留 doc-103；确认歌词文本，但发送状态仍是早期状态 |
| 6 | loop 3 | 20.4 KB | 因题面“发给”未满足，继续 document `text_search` 搜“生日歌” |
| 7 | triage 3a | 12.3 KB | 保留 doc-173 候选；命中路明非播放同一生日歌 |
| 8 | triage 3b | 13.3 KB | 处理同轮其他候选，过滤无关生日歌命中 |
| 9 | loop 4 | 34.9 KB | 用更窄 terms 继续核验“李嘉图 + 生日”和后续状态 |
| 10 | triage 4a | 15.3 KB | 保留 doc-103/doc-173 的前后状态链 |
| 11 | triage 4b | 9.0 KB | 剔除或降权无关命中 |
| 12 | triage 4c | 16.8 KB | 补充确认 doc-173 是收到/播放而非想象 |
| 13 | loop 5 | 44.1 KB | 生成最终回答：歌词 + 草稿到收到的生命周期 |
| 14 | readiness 5 | 33.1 KB | `ready_to_answer`；确认 doc-103 支撑歌词，doc-173 支撑最终发送/接收 |

本次结果相对前两次：

- 第一次错误 run：10 次 prompt，4 轮 loop，过早停在 doc-103，误答“没有发出”。
- 第二次错误 run：8 次 prompt，3 轮 loop，答对歌词但仍把题面降级成“准备给路明非”。
- 第三次成功 run：14 次 prompt，5 轮 loop，正确找到 doc-173 并完成生命周期核验。

因此，这次修改没有让该 case 的 prompt 次数下降；它让 Analyzer 不再为了省轮次而提前给出错误结论。后续若要降低轮数，应把“exact phrase 复查后续出现”进一步做成更强的本地候选提示或 evidence hint，让模型在 doc-103 后直接搜索“李呀李嘉图”，而不是先经历宽词召回和多次 triage。

## 验证

已运行：

```bash
.venv/bin/pytest novel_agent/tests/test_outline_analyzer_service.py -q
.venv/bin/pytest novel_agent/tests/test_writer_outline_research.py -q
.venv/bin/python -m compileall -q novel_agent/app/services/narrative_inquiry_broker.py novel_agent/app/services/outline_analyzer_service.py novel_agent/app/services/outline_research_service.py novel_agent/tests/test_outline_analyzer_service.py
```

结果：

- `43 passed`
- `29 passed`
- compileall 通过

