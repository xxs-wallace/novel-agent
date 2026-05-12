# Creative KB 对外接入说明

## 1. 目的

本文用于说明创作知识库层已经落地的对外调用方式，重点回答：

- 主编排层如何调用离线 facade
- 主编排层如何调用在线 facade
- 主编排层应该消费哪些输入输出
- 哪些职责仍然留在 Creative KB 内部，主层不应重复实现

本文是接入说明，不重新定义跨层 contract。

冻结边界仍以以下文档为准：

- [novel-continuation-mvp/contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)
- [creative-knowledge-base/spec.md](.trae/specs/creative-knowledge-base/spec.md)
- [creative-knowledge-base/design.md](.trae/specs/creative-knowledge-base/design.md)

## 2. 接入原则

- 主编排层只做 orchestration，不重写 Creative KB 内部规则。
- 主编排层不直接操作 `fragment_clusters` 的 dedupe 细节。
- 主编排层不直接重写 `SceneBrief` 映射、粗筛、rerank 逻辑。
- 主编排层不直接修改共享 `documents` 基线来实现 KB 去重。
- 若调用方只需要稳定检索结果，优先消费 `rerank_result`。
- 若调用方需要直接给 Writer 组装参考片段，可选择展开 `reference_fragments`。

## 3. 当前代码落点

当前 Creative KB 已落地的主入口代码如下：

- 离线 facade：
  - [`creative_kb_facade.py`](novel_agent/app/services/creative_kb_facade.py)
- 在线 facade：
  - [`retrieval_facade.py`](novel_agent/app/services/retrieval_facade.py)
- 相关 schema：
  - [`creative_kb_schema.py`](novel_agent/app/schemas/creative_kb_schema.py)
  - [`orchestration_schema.py`](novel_agent/app/schemas/orchestration_schema.py)

## 4. 离线接入

### 4.1 适用场景

主编排层在以下场景调用离线 facade：

- 粗读链路已经产出一批新的 `documents`
- 需要把这些 `documents` 建成 `fragment_cards`
- 需要完成近重复归并和 representative 回填

### 4.2 推荐调用入口

主编排层应调用：

```python
CreativeKnowledgeBaseFacade.build_creative_kb(
    conn,
    documents=documents,
)
```

### 4.3 输入要求

输入主语义来自共享 `documents` 基线。

调用方应提供：

- 已存在于主层数据库语义中的 `documents`
- 每个 `document` 的：
  - `doc_id`
  - `content`
  - `document_title`
  - `document_title_index`
  - `source_path`
  - `source offsets`
  - `content_tags`

说明：

- Creative KB 的建卡粒度固定为 `document`
- 即 `1 document -> 1 fragment_card`
- 主层不需要先把 `document` 聚合成 `chapter` 再送给 KB

### 4.4 输出对象

离线 facade 输出 `CreativeKBBuildResult`。

主层应重点消费这些字段：

```json
{
  "built_fragment_count": 0,
  "built_cluster_count": 0,
  "representative_count": 0,
  "fragment_ids": ["string"],
  "cluster_ids": ["string"],
  "failed_doc_ids": ["string"],
  "skipped_doc_ids": ["string"],
  "warnings": ["string"]
}
```

### 4.5 主层应如何使用返回值

- `built_fragment_count`
  - 用于记录本轮成功建卡数量
- `built_cluster_count`
  - 用于记录本轮聚类数量
- `representative_count`
  - 用于验证 representative 是否已回填
- `failed_doc_ids`
  - 用于显式暴露失败文档，不允许静默丢失
- `skipped_doc_ids`
  - 用于区分空内容、重复执行等未处理文档
- `warnings`
  - 用于主层 runs、日志或调试输出

### 4.6 主层不应做的事

- 不直接调用 builder 自己拼接 retry/fallback 策略
- 不直接调用 cluster service 自己拼 cluster 结果
- 不把 `failed_doc_ids` 文档从共享 `documents` 中删除
- 不把“跳过”理解为“主层物理去重 documents”

## 5. 在线接入

### 5.1 适用场景

主编排层在以下场景调用在线 facade：

- 已有锚点上下文、最近窗口、当前目标
- 需要为当前待写片段检索范文参考
- 需要获得 `selected_fragment_ids` 或可直接给 Writer 使用的参考片段

### 5.2 推荐调用入口

主层有两种调用方式。

方式 A：主层手里已经有 `SceneBrief`

```python
RetrievalFacade.retrieve_reference_fragments(
    conn,
    scene_brief=scene_brief,
    retrieval_context=retrieval_context,
    anchor_context=anchor_context,
    recent_window_summary=recent_window_summary,
    include_coarse_result=False,
    expand_reference_fragments=False,
)
```

方式 B：主层还只有 `CreativeKBRetrievalInput`

```python
RetrievalFacade.build_scene_brief_and_retrieve(
    conn,
    retrieval_input=retrieval_input,
    scene_brief=None,
    include_coarse_result=False,
    expand_reference_fragments=False,
)
```

### 5.3 在线输入准备

若主层使用方式 B，应准备 `CreativeKBRetrievalInput`，其来源遵循 [contracts.md](.trae/specs/novel-continuation-mvp/contracts.md)：

```json
{
  "anchor_context": "string",
  "recent_window_summary": "string",
  "goal": "string",
  "previous_generated_segment": "string | null",
  "retrieval_context": {
    "character_hits": [],
    "timeline_hits": [],
    "lore_hits": []
  },
  "scene_plan": {}
}
```

补充说明：

- 若上游已显式提供 `SceneBrief`，主层应优先直接传 `SceneBrief`
- 若仅有旧 `ScenePlan` 子集，可让 KB 内部兼容适配
- `retrieval_context` 只作辅助输入，不是桥段主检索入口

### 5.4 输出对象

在线 facade 输出 `CreativeKBRetrievalResult`。

默认最小稳定返回：

```json
{
  "scene_brief": {},
  "rerank_result": {}
}
```

可选字段：

```json
{
  "coarse_result": {},
  "reference_fragments": []
}
```

### 5.5 主层应如何使用返回值

主层默认应重点消费：

- `scene_brief`
  - 用于记录本轮检索意图
- `rerank_result.selected_fragment_ids`
  - 用于确定最终参考桥段主键
- `rerank_result.scores`
  - 用于调试和结果解释

当主层需要直接给 Writer 组装参考片段时：

- 可调用在线 facade 时开启 `expand_reference_fragments=True`
- 直接消费 `reference_fragments`

当主层需要调试粗筛行为时：

- 可调用在线 facade 时开启 `include_coarse_result=True`
- 读取 `coarse_result`

### 5.6 `reference_fragments` 的使用建议

`reference_fragments` 的典型字段如下：

```json
{
  "fragment_id": "string",
  "doc_id": "string",
  "source_path": "string",
  "source_excerpt": "string",
  "content_summary": "string",
  "style_profile_text": "string"
}
```

主层建议：

- 默认把 `source_excerpt` 作为 Writer prompt 的范文正文
- 用 `content_summary` 和 `style_profile_text` 做结果解释或 prompt 辅助说明
- 把 `doc_id` 仅作为回源字段，不要把它当成主排序主键

### 5.7 主层不应做的事

- 不直接根据 `retrieval_context` 构造 `selected_fragment_ids`
- 不绕过 `fragment_cards -> coarse -> rerank` 主路径
- 不把 `cluster_id` 当成 Writer 的直接消费主键
- 不在主层重做 `coarse_result` 或 rerank 打分

## 6. 推荐主层接入顺序

### 6.1 离线阶段

```text
documents 入库
-> 调用 CreativeKnowledgeBaseFacade.build_creative_kb()
-> 得到 CreativeKBBuildResult
-> 记录 fragment/cluster 构建统计与失败文档
```

### 6.2 在线阶段

```text
准备 anchor_context / recent_window_summary / goal / retrieval_context
-> 调用 RetrievalFacade.build_scene_brief_and_retrieve()
-> 得到 scene_brief + rerank_result
-> 按需展开 reference_fragments
-> 与 Memory 层 context_payload 一起组装给 Writer
```

## 7. 主层组装建议

### 7.1 组装 Writer 输入时

主层应遵循 [contracts.md](.trae/specs/novel-continuation-mvp/contracts.md) 中 `WriterInputBundle` 的语义：

- `scene_brief`
  - 来自 KB 在线 facade
- `reference_fragments`
  - 来自 `rerank_result.selected_fragment_ids` 的展开结果
- `context_payload`
  - 来自 Memory 层

建议主层执行：

```text
Creative KB 在线检索
-> 获得 rerank_result / reference_fragments
-> Memory 装配 context_payload
-> 主层组合为 WriterInputBundle
```

### 7.2 不要在 KB facade 内部做的事

以下仍属于主层职责，而不是 Creative KB facade 职责：

- 组装 `WriterInputBundle`
- 决定 Writer 的 Freeze 流程
- 决定 runs 落盘策略
- 决定与 Memory 的联动顺序

## 8. 调试与验收建议

### 8.1 离线侧

主层建议显式记录：

- `built_fragment_count`
- `built_cluster_count`
- `failed_doc_ids`
- `skipped_doc_ids`
- `warnings`

### 8.2 在线侧

主层建议默认只记录：

- `scene_brief`
- `rerank_result`

仅在调试/QA 模式下额外记录：

- `coarse_result`

说明：

- `coarse_result` 是调试字段，不应成为默认稳定对外字段
- `reference_fragments` 是便利展开字段，可按调用方需要记录

## 9. 责任边界速查

| 事项 | 主层负责 | Creative KB 负责 |
| --- | --- | --- |
| `documents` 入库 | 是 | 否 |
| `document -> fragment_card` 建卡 | 否 | 是 |
| 近重复聚类与 representative | 否 | 是 |
| `ScenePlan` 到 `SceneBrief` 的 KB 兼容适配 | 否 | 是 |
| `SceneBrief -> coarse -> rerank` | 否 | 是 |
| `rerank_result -> reference_fragments` 展开 | 可消费结果 | 可提供便利展开 |
| `WriterInputBundle` 组装 | 是 | 否 |
| `context_payload` 装配 | 否 | 否，属于 Memory |
| 正文生成 | 否 | 否，属于 Writer |

## 10. 当前仍未覆盖的接入点

以下事项当前仍需后续由主编排层实现，不属于本说明直接关闭范围：

- 把离线 facade 正式接到 segmentation/ingest 后的 orchestrator
- 把在线 facade 正式接到 continue-scene 主链路
- 把 KB 返回结果与 Memory 返回结果正式组装成 `WriterInputBundle`
- 为主编排层增加 runs 级别的 Creative KB 中间产物落盘

## 11. 一句话结论

主层对 Creative KB 的正确接法是：

```text
离线：documents -> CreativeKnowledgeBaseFacade -> CreativeKBBuildResult
在线：SceneBrief/ScenePlan + retrieval_context -> RetrievalFacade -> rerank_result -> optional reference_fragments
```

主层只负责调用、记录、组装，不负责重写 KB 内部规则。
