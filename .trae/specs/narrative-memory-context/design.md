# 叙事 Memory 与上下文实现设计稿

## Agent Reading Guide

先读 [`AGENT_CONTEXT.md`](AGENT_CONTEXT.md) 判断是否需要展开本文。Memory
设计较长，默认按工作面读取：

- 章节边界、粗读入库、document 对齐：读第 3.0、4.0、10.0 节。
- 精读、章节摘要、大纲、人物/世界更新：读第 3、4、6、7、8 节。
- BTree / Query / context assembly：读第 3.6、3.9、10.5 节。
- 当前实现和迁移判断：读第 4、5、9、11、12 节。
- 涉及跨层 Writer 输入时，回查
  [`../novel-continuation-mvp/contracts.md`](../novel-continuation-mvp/contracts.md)。

## 1. 目标
本设计稿将以下两部分合并整理到 Memory 与上下文层：

- 从 [`../novel-continuation-mvp/spec.md`](../novel-continuation-mvp/spec.md) 与 [`../novel-continuation-mvp/design.md`](../novel-continuation-mvp/design.md) 中抽取出的 Memory / 上下文相关设计
- 当前 `novel_agent/` 已实现的精读 Agent、人物档案、世界观、大纲、进度与上下文输入装配逻辑

本文档的目的不是再定义桥段检索，而是明确：

- Memory 层当前负责什么
- 当前代码已经实现到什么程度
- 目标设计与现状之间还有哪些差距

## 2. 模块定位

### 2.1 与其他 spec 的关系

- `novel-continuation-mvp/spec.md`
  - 总编排层
  - 负责系统闭环与主流程
- `narrative-indexer/spec.md`
  - 统一叙事索引框架
  - 负责把 Memory / KB 派生信息整理为可检索 IndexCard family
- `creative-knowledge-base/spec.md`
  - 创作知识库层
  - 负责 `creative_reference` card family、桥段卡片、去重、代表片段、`SceneBrief -> 粗筛 -> rerank`
- 本文档对应的 `narrative-memory-context/spec.md`
  - Memory 与上下文层
  - 负责人物档案、世界观、章节摘要、故事大纲、精读进度、上下文装配

### 2.2 核心原则

- 优先保存“事实、状态、关系、时间顺序”，而不是保存仿写参考。
- 所有 Memory 更新尽量基于章节级精读输出，而不是零散片段直写。
- 续写主 Agent 优先消费结构化长期上下文，而不是回读整本原文。
- Memory 层必须允许“已实现的简化版”和“目标设计的增强版”并存一段时间。
- 粗读入库阶段需要先识别章节边界候选，再把候选交给 segmenter、模型和 validator；本地规则负责候选与置信度，不负责用少数硬编码格式替代模型的语义分组。
- 高置信章节边界必须保护 source offset、segment boundary 和后续 `document_title_index`，否则 close-read、人物档案、故事大纲和 Narrative Indexer 都会继承错误章节索引。
- Chapter Summary Agent 的目标粒度保持章节级，继续按 `document_title_index` 或超长章节拆批处理。
- Character Evidence Agent 可以使用独立 batch 粒度，把多个连续 `documents` 拼接后做人物抽取、发言判断、行动状态与关系线索提取。
- Character Evidence Agent 的目标不是做原文 offset 标注，而是为 Memory Candidate Agent 提供更可靠的人物更新输入。
- Narrative Scene Indexer / SourceArcMapBuilder 属于 `narrative-indexer` 层。Memory 层只提供 documents、章节摘要、outline segment、人物/世界概要和回源索引，不在本层直接生成源作品篇章地图。
- `SourceArcMap` 应由 SceneCards 聚合生成；旧 Memory 层 SourceArcMap 文件只能作为兼容输入或迁移输入，不再是标准结构判断路径。
- Memory 层 close-read 产物 SHOULD 为 Narrative Indexer 提供多维索引素材，包括 outline segment、chapter summary、人物关键经历、世界规则、伏笔、主题信号和结构模式的可回源字段。Memory 仍是事实资产 source of truth；Indexer 负责检索形态和 card family 标准化。
- 章节摘要和故事大纲应区分 `provisional` 与 `committed` 状态：顺序 close-read 产生的即时梗概和大纲增量默认是暂定结果；结合后续窗口、SceneCards 或人工复核后，才能作为稳定事实压缩被 Writer 优先消费。

## 3. Memory 层数据范围

### 3.0 Ingest Boundary Metadata

粗读入库产出的 `documents` 是后续 Memory 的 leaf node。章节边界一旦在这一层被吞入上一 document，精读、人物档案、故事大纲与 Narrative Indexer 都只能消费错误索引。因此粗读阶段需要显式维护章节边界候选与校验结果。

推荐的边界候选结构：

```json
{
  "candidate_id": "boundary-couple-txt-0009",
  "source_path": "couple.txt",
  "start_offset": 123456,
  "end_offset": 123460,
  "raw_heading": "（九）",
  "normalized_heading": "（九）",
  "normalized_ordinal": 9,
  "boundary_type": "chapter",
  "confidence": 0.96,
  "format_family": "parenthesized_chinese_ordinal",
  "evidence": [
    "standalone_short_line",
    "ordinal_sequence",
    "repeated_book_pattern"
  ]
}
```

推荐在 document 或可重建的 sidecar 中保存：

- `boundary_candidate_id`
- `raw_heading`
- `normalized_heading`
- `boundary_confidence`
- `boundary_status`
- `source_start_offset`
- `source_end_offset`

`boundary_status` 推荐至少区分：

- `confirmed`
  - 高置信边界，且模型分组和 validator 均未发现冲突
- `model_inferred`
  - 模型判定为章节边界，但本地候选置信度不高
- `uncertain`
  - 边界候选存在冲突、缺序、跳序或格式不稳定
- `corrected`
  - validator 发现模型吞并多个高置信边界后做过拆分或重跑

### 3.1 Character Memory

保存人物的长期状态：

- `canonical_name`
  - 叙事视角中稳定使用的人物主称呼
  - 默认不因后续出现全名、昵称、职业称谓或关系内称呼而改写
  - 只有明确证据表明既有主称呼是误认对象、写错、伪装名或假名时才允许 retitle
- `aliases`
- `personality`
- `occupations`
- `age_timeline`
- `abilities`
- `recent_activity`
- `relationships`
  - 每条关系可携带 `address_terms`，记录关系内称呼及方向，例如“妻子称他为老公”“同事称他为 Don”
- `profile_brief`
- `story_events`
- `chapter_indexes`
- `mentioned_doc_ids`
- `speaking_doc_ids`
- `first_seen / last_seen`

目标结构分三层：

- 基础属性层
  - 保存姓名、别名、年龄或阶段、国籍/身份、外貌或显著特征、性格、稳定关系、能力和特长
  - 姓名部分应区分叙事主称呼、检索别名和关系内称呼；关系内称呼跟随关系条目，不覆盖人物档案标题
  - 该层用于 Writer 快速获得人物稳定状态，不应塞入过长流水账
- 常驻简档层
  - `profile_brief` 是持久化的高度浓缩人物状态，不是每次 close-read 临时生成的 prompt 输入参数
  - 保存身份锚点、当前状态、稳定特征、能力/限制、关键关系摘要、未解问题、最近重大变化、compact 进度和关键 source refs
  - close-read / Character Reduce 默认只读取 `profile_brief`、当前人物 evidence、当前 outline segment / chapter summary 和必要身份索引
  - 如果旧人物档案没有 `profile_brief`，系统应执行一次模型 bootstrap compact，生成初始 brief；该成本只发生在兼容初始化或显式修复任务中，不得退回每批临时压缩完整档案
- 人物经历层
  - `recent_activity` 保留为热层增量队列，保存尚未被 brief compact 吸收的近期经历、状态变化和关系变化；它不默认进入每次 Character Reduce
  - `story_events` 保存长期经历索引摘要，重点保留 `experience_id`、`outline_segment_id`、source range、角色作用和高度概括剧情
  - 低频、背景出场或弱相关人物走 `defer_index_only` / `index_only`：只追加极简人物经历索引，不读取或压缩完整旧档案
  - 每条经历包含 `experience_id`、`outline_segment_id`、`role_in_segment`、`compression_level`、`label`、`summary`、`source_chapter_indexes`、`source_doc_ids`、`source_doc_range`、`participants`
  - 该层用于模型先筛选人物相关经历，再按 `outline_segment_id` 展开剧情段，必要时继续展开原始 document
  - 同一个 outline segment 对不同角色的意义不同；背景出场角色只保留大致事件和人物相关点，主要推动者、主要关联者或主要发言者保留更完整的剧情因果、行动结果和关系变化
  - 当角色连续多个 document 不再出现、recent_activity 积累超阈值，或当前剧情触发重大变化时，系统应调用模型 compact loop，将必要经历吸收进 `profile_brief`，并把已吸收热层经历转入长期索引或标记为已 compact
  - 所有经历压缩都必须由模型完成语义概括；生产路径禁止用字符数、token 数、句子数或列表长度硬截断伪装压缩

`mentioned_doc_ids` / `speaking_doc_ids` 继续作为底层倒排索引存在，但不再是模型理解人物过往的主要入口。模型应优先读取 `profile_brief` 与人物经历索引；只有需要确认细节时，才根据经历携带的 `outline_segment_id`、doc ids 或 source range 请求剧情段、章节摘要或原文证据。

### 3.2 World Memory

保存每部小说唯一的：

- 详细世界观 Markdown
- 压缩世界观概要 Markdown

### 3.3 Chapter Memory

保存章节级精读结果：

- `summary_md`
- `summary_short`
- `summary_status`
- `evidence_window`
- `target_range`
- `importance_score`
- `related_chapters`
- `mentioned_characters`
- `world_update`
- `outline_update`

`summary_status` 推荐使用：

- `provisional`
  - 当前顺序 close-read 处理完该章节后立即生成
  - 可用于事实型剧情记忆，但其中“结构功能/节奏”只代表当前读到的位置下的暂判
- `committed`
  - 已结合后续若干章节、人物档案、故事大纲、SceneCards 或人工复核
  - 可作为 Writer 和结构模式沉淀的稳定输入

`evidence_window` 记录本次判断参考的上下文范围，例如 `10-20`；`target_range` 记录被定稿的章节范围，例如 `14-18`。

### 3.4 Story Outline Memory

保存整书大纲：

- 章节级一行摘要
- 主线推进信息
- 分段连续剧情压缩 `outline_segment`
- 上层 `outline_root` 索引
- `outline_status`
- `evidence_window`
- `target_range`

当前顺序精读阶段生成的大纲增量默认是 `provisional`。后续可用更大的上下文窗口重算较小的目标范围，例如用第 10 到第 20 个 document/chapter 的故事梗概和人物状态，定稿第 14 到第 18 个 document/chapter 的大纲片段，并标记为 `committed`。

目标叙事压缩链路为：

```text
document -> chapter summary -> outline segment -> outline root
```

- `document`
  - 粗读入库的原文片段，保存 `doc_id`、`content`、`source_path`、`source_start_offset`、`source_end_offset`
- `chapter summary`
  - close-read 后的章节/批次概要，压缩一个或多个 documents
  - 通过 `source_doc_start_id` / `source_doc_end_id` 或 `source_doc_ids` 回到原始文档
- `outline segment`
  - 每 N 个连续 document / chapter 的连续剧情压缩梗概
  - 必须能回到 `source_doc_ids` / `source_doc_range`
  - 不输出 `timeline_events`、`event list` 或等价事件数组
- `outline root`
  - 多个 outline segment 的上层索引，保存 segment id、范围、状态和模型压缩后的 root summary
  - 服务于 Writer 快速理解历史剧情顺序和因果衔接

推荐的 outline segment 结构：

```json
{
  "outline_segment_id": "outline-segment-0004",
  "summary": "连续剧情压缩梗概，保留顺序、因果、主要人物状态变化、关系推进、设定揭示、未解问题和阶段结果。",
  "source_title_indexes": [12, 13, 14, 15],
  "source_doc_ids": [48, 49, 50, 51, 52],
  "source_doc_start_id": 48,
  "source_doc_end_id": 52,
  "source_doc_range": "48-52",
  "status": "provisional"
}
```

`outline_segment_id` 是 BTree-like Memory Query 的范围定位关键。后续 Writer Outline Research Loop / Analyzer 不应一次性读取全部章节摘要，而应先选择相关 outline segment，再由 Context Broker 确定性展开到 chapter summary 或 document range。

多维事件检索不再由 Story Outline Memory 的 `timeline_events` 承担。需要事件级索引时，应使用 Narrative Indexer 派生的 `NarrativeSceneCard` 或等价事件 / 场景级 IndexCard；Memory 层只提供 documents、chapter summaries、outline segments、character experiences 和回源索引。

### 3.5 Progress Memory

保存：

- 粗读进度
- 精读进度
- checkpoint token

### 3.6 Context Assembly

面向续写主 Agent 输出：

- 相关章节摘要
- 必要时提供 Narrative Indexer 生成的相关 SceneCards / SourceArcMap 片段
- 世界观概要
- 相关人物档案
- 故事大纲摘要

### 3.7 Character Evidence Batch

保存或临时传递 Character Evidence Agent 的轻量批次信息：

- `character_evidence_batch_id`
- 有序 `doc_ids`
- 拼接后的 batch 文本或可重建 batch 文本的引用
- batch 级人物抽取结果
- batch 级发言判断、人物性证据、行动状态证据、关系证据

该层不要求保存原文 offset，不要求把每个人物证据反查到具体 `doc_id`。

Character Evidence Agent 输入中的 `existing_character_roster` 必须携带稳定人物映射：

- `character_id`
- `canonical_name`
- `aliases`
- 必要的短标签，例如阶段、职业、最近出现位置和发言状态

当模型判断正文中的称呼指向 roster 中已有角色时，输出应同时返回 `character_id` 与 `canonical_name`。`character_id` 是后续人物档案更新的优先索引；`canonical_name` 仅作为可读标签和兼容字段。若人物不在 roster 中，`character_id` 为空，并用 `resolution_status = new_or_unresolved` 或等价状态标明需要后续身份归并。这样可以避免同一人物因别名、称谓或临时称呼被 close-read 写成多个档案。

### 3.8 Narrative Indexer Handoff

Memory 层为 Narrative Indexer 提供只读输入包，而不是直接生成场景卡或篇章地图：

- 有序 `documents` 原文、source offset、章节边界状态
- chapter summaries
- outline segments / outline roots
- 相关人物档案概要
- 世界观概要和世界观文档定位
- 从上层 Page 回源到 document 的索引

Narrative Scene Indexer 使用这些输入，通过带 overlap 的滑动窗口生成 `NarrativeSceneCard`。`SourceArcMap` 由 SceneCards 聚合生成，归属 `narrative-indexer` 层；Memory 层 MAY 兼容读取旧 `.memory/arcs/<book_id>.source_arc_map.json`，但该文件不再是新流程的标准产物。

该边界的目的：

- 保持 Memory 作为事实资产 source of truth，不混入结构判断 card。
- 让结构判断能够读取连续原文窗口，而不是只看单章摘要。
- 避免旧 `SourceArcMap` 在没有 SceneCards 支撑时干扰 Analyzer / Writer 的检索。

### 3.9 BTree Descent Query

BTree descent query 是 Memory 层面向 Writer / Outline Research Loop 的标准故事细节查询协议。它不把整本原文或所有摘要一次性塞给模型，而是让模型沿着 Page 层级逐步选择需要展开的范围。

推荐运行时接口：

```python
class NarrativeMemoryQueryService:
    def root_scan(self, query: str, *, budget: MemoryQueryBudget) -> MemoryQueryState: ...
    def drill_down(self, state: MemoryQueryState, selected_ids: list[str]) -> MemoryQueryState: ...
    def resolve_outline_segment_refs(self, segment_ids: list[str]) -> MemoryEvidenceBundle: ...
    def resolve_chapter_refs(self, chapter_refs: list[str]) -> MemoryEvidenceBundle: ...
    def resolve_document_refs(self, doc_ids: list[int], *, excerpt_budget: int) -> MemoryEvidenceBundle: ...
```

Memory 层负责返回候选 Page、确定性展开下层索引、裁剪 excerpt、标注 `provisional` / `committed` 和生成 `memory_query_trace`。
Writer 层负责把当前候选交给 Outline Research 模型选择，并把模型返回的 `selected_ids` / `query_suffix` / `reason` / `confidence` 传回 Memory。Memory 不生成续写规划，Writer 不直接扫描 SQLite 或 Markdown 绕过 Memory facade。

`NarrativeMemoryQueryService` 是输入来源无关的。`query` 可以来自首次用户输入，也可以来自用户反馈、reviewer feedback 或 retry instruction。Writer Prompt Loop 负责把这些 turn-level 信号归一化为 research intent；Memory facade 只看到查询意图、预算和已选路径，并按同一套 BTree descent 协议返回下一层候选或证据。

查询路径：

```text
original_query
  -> outline_root index
  -> selected outline_segment range
  -> chapter summary candidates
  -> selected chapter ids / title ranges
  -> document candidates
  -> selected document ids / excerpts
```

每一层都由模型做一次结构化选择，Agent 只负责确定性展开下一层：

```json
{
  "need_drill_down": true,
  "selected_ids": ["outline-segment-0004"],
  "query_suffix": "重点确认角色为何改变立场以及该转折的直接后果。",
  "reason": "该段连续梗概覆盖立场转折、关系变化和后续行动结果。",
  "confidence": 0.82,
  "need_sibling_scan": false
}
```

`query_suffix` 设计：

- `query_suffix` 是模型在当前层筛选后追加的查询约束，不替代 `original_query`。
- Agent 在下一层 prompt 中同时传入 `original_query` 和累计 `query_suffix_chain`。
- `query_suffix` 应该短、具体、可审计，只能基于当前层候选内容产生。
- 多层查询时，`query_suffix_chain` 形成一条逐步收窄的意图路径，例如：

```json
[
  "已定位到3E考试前夜和交易压力相关剧情。",
  "重点确认芬格尔提供答案的方式、路明非的反应和交易后果。"
]
```

裁剪策略采用 `Path Context + Current Candidates`：

- 永远保留 `original_query`。
- 永远保留累计 `query_suffix_chain`。
- 进入下一层后，上一层未被选中的 sibling candidates 默认裁剪掉。
- `path_context` 只保留已选中的上层节点：
  - level
  - selected id / id range
  - summary
  - source range
  - selection reason
  - confidence
- 当前层候选节点必须完整提供必要信息；例如 outline segment 层要提供 `outline_segment_id`、`summary`、`source_title_indexes`、`source_doc_range` 和 `status`。
- 只有在模型返回低置信、空选择或 `need_sibling_scan = true` 时，Agent 才回到上一层扩展相邻 sibling。

推荐 prompt payload：

```json
{
  "original_query": "确认芬格尔和路明非关于3E考试的交易细节。",
  "query_suffix_chain": [
    "已定位到3E考试前夜和入学考试压力相关剧情。"
  ],
  "path_context": [
    {
      "level": "outline_segment",
      "selected_id": "outline-segment-0004",
      "summary": "路明非进入卡塞尔前后遭遇考试压力、信息差交易和身份审查。",
      "source_doc_range": "480-620",
      "selection_reason": "该摘要覆盖3E考试前后的准备与交易线索。",
      "confidence": 0.86
    }
  ],
  "current_level": "chapter",
  "current_candidates": [
    {
      "chapter_id": "chapter-012",
      "document_title_index": 12,
      "summary": "章节摘要或预算裁剪后的摘要片段。",
      "source_doc_range": "501-506",
      "status": "committed"
    }
  ],
  "selection_task": "判断是否需要继续展开某些 chapter 来回答 original_query。",
  "output_schema": {
    "need_drill_down": "boolean",
    "selected_ids": ["string"],
    "query_suffix": "string",
    "reason": "string",
    "confidence": "number",
    "need_sibling_scan": "boolean"
  }
}
```

不同层的候选最小字段：

- `outline_root` 层：
  - `outline_root_id`
  - `segment_refs`
  - `source_doc_range`
  - `status`
- `outline_segment` 层：
  - `outline_segment_id`
  - `summary`
  - `source_title_indexes`
  - `source_doc_range`
  - `status`
- `chapter` 层：
  - `chapter_id`
  - `document_title_index`
  - `summary_md` 或经过预算裁剪的 `summary_excerpt`
  - `source_doc_range`
  - `mentioned_characters`
  - `summary_status`
- `document` 层：
  - `doc_id`
  - `document_title_index`
  - `source_path`
  - `source_offsets`
  - `content` 或预算裁剪后的 excerpt

查询轨迹应写入结构化 trace：

```json
{
  "original_query": "...",
  "steps": [
    {
      "level": "outline_segment",
      "input_candidate_ids": ["outline-segment-0003", "outline-segment-0004"],
      "selected_ids": ["outline-segment-0004"],
      "query_suffix": "已定位到3E考试前夜相关剧情。",
      "reason": "覆盖考试压力和交易线索。",
      "confidence": 0.86
    }
  ],
  "final_document_ids": [501, 502, 503]
}
```

这条 trace 是可审计解释链：它说明系统为什么从 root page 最终回源到某些 document。Writer 只消费最终必要上下文；调试和 reviewer 可以读取完整 trace。

## 4. 当前已实现代码总览

### 4.0 粗读入库与章节边界识别

当前粗读入口的核心实现位于：

- `novel_agent/app/services/document_ingest_service.py`

当前链路是：

```text
source text
  -> 本地切成 byte-bounded segments
  -> segmentation prompt
  -> 模型返回 documents + segment_ids
  -> 本地校验 segment 连续覆盖
  -> documents 入库
```

已实现能力：

- 按文本预算切 segment，保证字符不丢失
- Markdown 标题作为 hard boundary
- 独占一行的中文括号章号，例如 `（九）`，作为 hard boundary
- `_extract_explicit_title()` 识别短章节标题
- 如果模型把多个显式章节标题合成同一个 document，入库前会按 segment 标题拆开
- 模型输出必须覆盖连续 `segment_ids`，否则使用安全 fallback 或报错

当前限制：

- 章节边界识别仍散落在 `DocumentIngestService` 的 segment、title extraction 和 postprocess 中
- 还没有独立 `ChapterBoundaryDetector` 数据结构保存候选、置信度、证据和格式族
- 还没有基于同一本书动态学习 `format_family` 与 ordinal sequence 的机制
- `documents` 表尚未显式保存 `boundary_candidate_id`、`boundary_confidence`、`boundary_status`
- 当已有任务的 `documents` 表已经把多个章节写成同一个 `document_title_index` 时，单独重跑 close-read 不能修复章节边界，必须重跑粗读入库或重建受影响的 documents

目标重构后，粗读链路应变为：

```text
source text + toc/bookmarks
  -> ChapterBoundaryDetector: candidates + confidence
  -> SegmentBuilder: high-confidence boundaries become hard boundaries
  -> Segmentation Agent: model groups segment_ids into documents
  -> SegmentationValidator: coverage + high-confidence boundary checks
  -> DocumentIngestService: persist documents + boundary metadata
```

`ChapterBoundaryDetector` 不应是额外的用户可见任务，也不应替代模型分组。它是粗读流程内部的边界候选器，负责把规则、目录、编号序列和同书格式学习统一成可解释的候选输入。

### 4.1 精读主流程

当前已实现的主入口：

- `novel_agent/app/runner/close_read_runner.py`

当前主流程已经具备：

- 读取 `documents`
- 按 `document_title_index` 聚合章节
- 按预算切批
- 生成精读 prompt
- 调用模型输出 JSON
- 在失败时 fallback
- 回写 `chapters`
- 回写 `documents.character_keywords_json`
- 合并 `character_profiles`
- 更新世界观 Markdown 与概要
- 更新故事大纲 Markdown
- 更新 `reading_progress`

### 4.2 章节批次装配

当前已实现：

- `novel_agent/app/services/chapter_assembler_service.py`

能力：

- 从 `reading_progress` 读取 `last_completed_doc_id`
- 从 `documents` 读取后续正文
- 按 `document_title_index` 聚合章节
- 若章节总字数超预算，则切出部分 `documents`

当前策略特点：

- 整章优先
- 超预算时按 `document_chars_budget` 切批
- 不做更细粒度的“章节内语义切段”
- 该策略属于 Chapter Summary Agent，不应因为 Character Evidence Agent 引入 batch 粒度而改变

### 4.3 人物候选提取与证据校验

当前已实现：

- `novel_agent/app/services/character_mention_service.py`
- `novel_agent/app/services/character_evidence_validator.py`

能力：

- 本地基于分词、模式和规则抽取人名候选
- 过滤常见伪人名、目录词、物品词、动作短语
- 对模型返回的人物名要求附带证据片段
- 证据片段必须是原文连续子串，且包含人物名
- 对高风险二字词（如“张开”）要求更强的人物性证据

这一部分已经体现了“本地候选抽取 -> 模型补充 -> 规则校验”的分层思路。

目标重构后：

- 原文连续子串要求只作为当前实现现状，不作为新 Character Evidence Agent 的目标 contract
- 新 Character Evidence Agent 输出简短的 `speaking_evidence`、`personhood_evidence`、`activity_or_state_evidence` 和 `relationship_evidence`
- `speaking_evidence` 用于判断候选是否有明确发言行为，但不要求复制原文
- `personhood_evidence` 用于判断候选是否是真实角色，而不是动词、物品、抽象名词或场景词
- `activity_or_state_evidence` 和 `relationship_evidence` 主要服务于 Memory Candidate Agent 的人物档案更新

### 4.4 人物档案更新

当前已实现：

- `novel_agent/app/services/character_profile_service.py`
- `novel_agent/app/repos/character_profiles_repo.py`

能力：

- 按 `canonical_name` 查找既有人物
- 对别名、性格、职业、能力、关系、章节索引做 JSON list 合并
- 记录 `first_seen_doc_id` / `last_seen_doc_id`
- 记录 `first_seen_title_index` / `last_seen_title_index`
- 记录 `mentioned_doc_ids_json` / `speaking_doc_ids_json`
- 为每次更新重建一个简化版 `profile_summary_md`
- 维护 `profile_version`

当前实现特点：

- 更新策略偏“append + 去重”
- `age_update` 进入 `age_timeline_json`
- `recent_activity` 也以 list 追加
- 人物摘要目前是轻量模板，不是高保真的人物小传

目标扩展：

- `character_profiles.profile_brief_json` 保存人物常驻简档，默认作为 close-read / Writer / Research Loop 的主要人物上下文
- `character_profiles.recent_activity_json` 保留为热层增量队列，保存尚未被 brief compact 吸收的近期人物经历；普通 Character Reduce 不默认展开全量 recent activity
- `character_profiles.story_events_json` 保存长期经历索引摘要，条目保留 `outline_segment_id`、source range、角色作用和高度概括剧情
- Character Reduce prompt 消费当前 `outline_segment` 索引、人物 evidence、章节短摘要和持久化 `profile_brief`，只输出本批次人物经历增量、短关系状态变化和 compact 触发信号
- Brief Compact Gate 先按当前窗口 document 覆盖率、发言/行动/关系证据、角色作用和重大变化类型分为 `append_delta` / `needs_brief_compact` / `needs_full_profile_compact` / `index_only`：
  - `append_delta`：普通人物经历增量，追加到 `recent_activity_json` 或 `story_events_json`，不改写 brief
  - `needs_brief_compact`：当前剧情改变了人物当前状态、关键关系、身份锚点、能力/限制、性格/形象概括或未解问题，需要模型更新 `profile_brief`
  - `needs_full_profile_compact`：身份合并、误归因修复、重大设定矛盾或历史经历大规模重整，进入专门 Agent Loop，可按需读取 story events、outline segment 和原文
  - `index_only`：低频、背景或弱相关人物；只记录当前 `outline_segment_id`、source range 和极短人物相关说明
- 每条经历应保留 `outline_segment_id`、`role_in_segment`、`compression_level`、source doc/title range；背景出场角色应高度压缩为 index-only，主要推动者 / 主要发言者保留更完整剧情
- 当角色连续多个 document 不再出现、recent_activity 积累超阈值，或当前剧情触发重大变化时，系统应调用模型 compact loop，将必要经历吸收进 `profile_brief` 并标记 compact 进度；该过程不能用本地硬截断代替
- Narrative Indexer character / scene cards 可作为后续复核或增强输入，但 close-read 不依赖 outline `timeline_events`
- `profile_summary_md` 按两层渲染：
  - `## 基本属性/能力`
  - `## 人物经历`
- 人物经历的每条条目必须显示 `experience_id`、`outline_segment_id` 与 `documents` 范围，方便模型先定位 outline segment，再二次请求章节摘要或原文

关系信息只保存在结构化 `relationships_json`，并由 UI 的“关系网络”或 Writer 的结构化人物上下文单独消费。`relationships_json.status_summary` 只描述当前关系状态、关系类型、情感状态、称呼和回源索引，不承载完整剧情因果、小型章节摘要或人物经历；关系变化的过程、冲突细节和结果应写入 `recent_activity_json` / `story_events_json`。`profile_summary_md` 不再展开关系明细，最多保留一句“关系见 relationships_json / 关系网络”的提示或完全省略关系段。这样避免“已确认事实 / 基本信息”与“关系网络”展示同一批关系事实，也避免 Writer prompt 同时从摘要文本和结构化关系列表读到重复甚至互相覆盖的关系描述。

Character Reduce 不应再读取完整 `profile_summary_md`、全量 `relationships_json`、全量经历和全量 recent activity。系统也不应再生成每批临时完整档案压缩上下文。持久化 `profile_brief` 是唯一默认人物上下文入口；缺失 brief 的旧人物通过一次性 bootstrap compact 补齐。

人物性证据、基础属性和关系更新都不能长期采用纯 append。新的 close-read 写回应采用“逐人物档案更新 Agent Loop”：

1. Character Evidence Agent 先按连续 `documents` 组装 evidence batch，输出本批次涉及人物，并尽量对齐 `character_id`。
2. 本地 Agent 按 `character_id` 优先、`canonical_name / aliases` 兜底，读取涉及人物的 `profile_brief` 和身份索引；不读取全量旧档案。
3. 若人物缺失 `profile_brief`，调度 `CharacterProfileBriefBootstrap` 对该旧档案执行一次模型 compact，生成初始 brief；该步骤可在后台或当前人物首次进入 reduce 前完成。
4. `CharacterImportanceTracker` / Brief Compact Gate 负责三层判断：
   - 当前 segment 重要性：按当前窗口 document 覆盖率、发言、行动、关系变化、候选置信度和弱候选类型计算 `current_segment_score`。
   - 滚动历史重要性：按既有人物档案中的 mentioned/speaking doc、story events、主要事件角色和最近出现间隔计算 `rolling_score` / `rolling_tier`。
   - 状态转换：输出 `append_delta` / `needs_brief_compact` / `needs_full_profile_compact` / `defer_index_only` / `drop_for_profile`。
5. 普通 Character Reduce 每条 prompt 只包含当前 batch 的 ordered evidence、章节短摘要、当前 outline segment、持久化 `profile_brief` 和必要来源索引。
6. `defer_index_only` 的人物跳过 Character Reduce 模型调用，只保存极简 `outline_segment_id` / source range / role / one-line summary，累计到阈值或再次变热时再交给模型归并；`drop_for_profile` 的人物只保留底层 mention / scene index。
7. 初始建议的 character reduce 预算是：document evidence 摘要不超过约 16KB；同一 prompt 默认一个目标人物；`profile_brief` 约 1-2KB。这些数字必须可配置，并通过 benchmark 调参。
8. 如果人物之间关系高度耦合，系统可以把相关人物 brief 作为关系参照；如果关系冲突复杂、模型低置信或输出混淆身份，则退回单人物 reduce 或人工确认。
9. 模型输出每个人物的增量更新或重写后的局部字段，覆盖范围包括人物性证据、基础属性、发言状态、关系、人物经历增量和 compact 触发信号；输出必须按 `character_id` 或 canonical identity 分离。
10. 本地 merge 层按字段语义写回：基础属性和人物性证据做去重 / 归并，关系按目标人物和最近证据合并冲突，人物经历按 `experience_id` / `outline_segment_id` 合并。

该 loop 的目的不是让模型自由重写整个档案，而是在有限 evidence 和少量相关现有档案之间做语义归并，减少重复、别名分裂、关系冲突和调用次数。

身份揭示是独立于普通 alias 归一的增量流程：

- Character Evidence Agent 可以在当前 document 明确揭示两个既有人物、代号、伪装身份或过去身份为同一人物时输出 `identity_revelations`。
- `identity_revelations` 必须带 `relation = same_person` 或等价状态、左右人物的 `character_id` / name、证据摘要、source doc/title 或 `outline_segment_id`、置信度。
- `CharacterIdentityMergeService` 不直接消费 `identity_revelations` 写库合并；它先调用专门 review prompt，输出 `same_person_score`、`recommended_action`、证据强度与证据缺口。
- 评分门控：
  - `< 75`：视为低分相似/误报，只写消息流提示，不创建待确认合并。
  - `75-89`：写入 `character_identity_merge_candidates`，状态为 `needs_more_evidence`，close-read 继续运行。
  - `>= 90` 且 `recommended_action` 为 `merge_profiles` 或 `memory_correction`：写入 `character_identity_merge_candidates`，状态为 `pending_user_confirmation`，close-read 挂起在 `blocked_identity_merge_review`，等待人工确认。
- 人工确认后，`CharacterIdentityMergeService` 才执行高置信 profile-to-profile merge：保留 survivor 的稳定 `canonical_name` 与 `character_id`，把 duplicate canonical / aliases 迁移到 aliases，合并基础属性、关系、经历、出场和发言 doc refs，追加一条 `role_in_segment = identity_reveal` 的经历索引，并删除 duplicate profile。
- 合并后，其他人物 `relationships_json.target_name` 中指向 duplicate canonical / aliases 的关系应改写为 survivor canonical；事件 participants 也应尽量改写到 survivor canonical。
- 服务不得基于本地名字相似、共现、关系亲密或能力相似自动判断同人；证据不足时必须返回 skipped / request_more_evidence，不得静默合并。
- 存量污染修复是单独任务：当错误身份已经被写进无关人物 aliases 或经历时，应先做目标化 profile surgery / model-backed regeneration，再用 `CharacterIdentityMergeService` 处理确实存在的双档案合并。

叙事误导后的历史记忆修正由 `CharacterMemoryCorrectionService` 承担：

- Correction 是比 identity merge 更通用的 belief revision：后文可能推翻早期人物归属、事件时间、地点理解、因果解释或叙述者可信度。
- 修正发现阶段应先运行 seed loop：从用户给出的疑似污染目标、人物档案索引、`outline_root.summary`、`outline_segment` 摘要和已有经历索引出发，选择少量 root / segment / doc 展开；不得为了定位证据重读整本小说。
- 服务不自行发现语义错误，只执行模型确认或用户明确确认的 correction plan。生产路径不得用本地名字匹配、共现、相似能力等 heuristic 伪装“已理解叙事误导”。
- Correction plan 至少包含 `status`、`correction_type`、`reason`、`confidence`、source refs 和 `operations`。
- 初始支持的 operations：
  - `remove_aliases`：从污染人物档案移除错误 alias。
  - `move_story_events`：按明确 selector 将误归因经历从 source profile 迁移到 target profile，可在目标不存在时创建目标档案。
  - `remove_story_events`：移除已被后文推翻且不应迁移的经历。
  - `rewrite_relationship_target`：把其他人物关系中指向旧错误身份的 `target_name` 改写到正确人物。
  - `ensure_profile`：为被误导阶段没有独立建档的真实人物创建最小档案。
  - `append_correction_event`：追加一条可回源的修正经历，保留“后文揭示推翻早期理解”的审计痕迹。
- `move_story_events` 必须使用明确 selector，例如 `event_ids`、`outline_segment_ids`、`source_doc_ids`、`participant_names` 或 `label_contains`；`misattributed_names` 只用于迁移后重写 participants，不能作为事件筛选条件，避免把正常出场事件误迁移。
- 身份合并可以在概念上视为 CharacterMemoryCorrectionService 的特例；当前实现仍保留 `CharacterIdentityMergeService` 作为专门 profile-to-profile merge 内核，因为它需要更强的 survivor / duplicate / alias / relationship rewrite 约束。

### 4.5 世界观维护

当前已实现：

- `novel_agent/app/services/world_state_service.py`

能力：

- 自动创建世界观 Markdown 与世界观概要文件
- 将本轮 `world_update` 追加到详细世界观 Markdown
- 用模型或本地 `clamp_text` 重建概要

当前实现特点：

- 详细世界观当前是“追加式更新”
- 世界观结构存在模板，但没有做 section 级 merge
- 世界观概要在无模型或 dry-run 时退化为直接截断

### 4.6 大纲维护

当前已实现：

- `novel_agent/app/services/outline_segment_index_service.py`
- `novel_agent/app/prompts/outline_root_summary_prompt.py`
- `novel_agent/app/services/narrative_memory_query_service.py`

能力：

- 从 chapters 的 `outline_update_json` 读取 `chapter_line`、`outline_segment`、`outline_segment_id` 和 source ranges
- 刷新 `.memory/outlines/<book>.outline_segments.json`
- 在同一 artifact 中保存 `segments` 与 `roots`
- 使用模型把一组连续 `outline_segment` 压缩为 `root.summary`
- 由 `segments` / `roots` 投影生成 `.memory/outlines/<book>.outline.md`
- 为 BTree descent query 提供 `outline_root -> outline_segment -> chapter -> document` 的检索入口

当前实现特点：

- close-read / writer 写回的 `outline_update_json` 只应包含 `chapter_line`、`outline_segment`、`outline_segment_id`、source ranges、status 等字段
- close-read / writer 不再生成或依赖 `timeline_events`
- `.outline.md` 是人类可读投影，不是 Analyzer / Writer 的检索 source of truth
- `outline_root.summary` 是模型压缩结果，用于快速判断相关性；不是多个 segment summary 的简单拼接
- 还没有基于后续窗口重算某个 `target_range` 并升级为 `committed` 的机制

标准 artifact：

- `outline_update_json` 不再输出 `timeline_events` 或等价事件数组，避免模型沿旧 schema 生成弱事件列表
- `.memory/outlines/<book>.outline_segments.json` 保存滚动压缩后的 outline segments 与 root indexes：
  - `segments[].outline_segment_id` 是分段摘要主键
  - `segments[].summary` 是模型对连续 chapter summaries 的自然语言压缩梗概
  - `segments[].source_doc_ids` / `segments[].source_doc_range` 用于回源到粗读 document
  - `segments[].source_title_indexes` 用于回源到 chapter summaries
  - `roots[].outline_root_id` 是根索引主键
  - `roots[].summary` 是模型对多个 segment 的连续剧情压缩概览
  - `roots[].outline_segment_ids` 用于展开到下层 segment
  - `roots[].source_doc_ids` / `roots[].source_doc_range`
  - `roots[].source_title_indexes`
  - status
- `.memory/outlines/<book>.outline.md` 只由 segments / roots 投影生成，汇总为连续、易读的自然语言文本
- 事件级多维索引的 source of truth SHOULD 是 Narrative Indexer cards，而不是 Story Outline Memory
- Context Broker 应能按 `outline_segment_id`、`document_title_index` 或 `source_doc_range` 确定性返回摘要和原文证据

滚动压缩策略：

1. Agent 从 chapter summaries 收集尚未被任何 `outline_segment` 覆盖的连续章节。
2. 当 pending chapter/document 数量达到阈值时，Agent 将连续摘要窗口发给模型，生成或刷新 `outline_segment`。
3. 模型直接输出一个连续 `outline_segment.summary`，不得输出 `timeline_events`、`event_ids` 或 pending event 字段。
4. Agent 保存该 segment 的 `source_doc_ids`、`source_doc_range`、`source_title_indexes` 与状态。
5. Agent 将每组连续 segments 发给模型压缩为 `outline_root.summary`；root summary 用于快速检索，root 保留 `outline_segment_ids` 用于确定性展开。
6. 新 segment / root 进入 BTree descent 查询，供 Analyzer / Writer 先做范围选择。

### 4.7 章节结果持久化

当前已实现：

- `novel_agent/app/repos/chapters_repo.py`

能力：

- upsert `chapters`
- 保存：
  - `summary_intermediate_json`
  - `summary_md`
  - `summary_short`
  - `importance_score`
  - `related_chapters_json`
  - `mentioned_characters_json`
  - `world_update_json`
  - `outline_update_json`

目标扩展后还应能保存或等价表达：

- `summary_status`
- `summary_evidence_window`
- `summary_target_range`
- `outline_status`
- `outline_evidence_window`
- `outline_target_range`

### 4.8 进度管理

当前已实现：

- `novel_agent/app/repos/reading_progress_repo.py`

能力：

- 按 `book_id + agent_stage` 读取进度
- upsert 粗读与精读阶段的当前状态、最近完成位置和 checkpoint token

### 4.9 资产路径管理

当前已实现：

- `novel_agent/app/repos/assets_repo.py`

能力：

- 保存：
  - 世界观 Markdown 路径
  - 世界观概要路径
  - 大纲路径
  - 调试导出路径
  - 目录 Markdown 信息

## 5. 当前 SQLite / 文件载体现状

### 5.1 当前已实现表

当前 `NovelAgentDB.init_schema()` 已创建：

- `documents`
- `chapters`
- `character_profiles`
- `reading_progress`
- `book_assets`
- `documents_fts`

实现位置：

- `novel_agent/app/repos/db.py`

### 5.2 当前已实现文件载体

当前已实现：

- `.memory/worlds/<book_id>.world.md`
- `.memory/worlds/<book_id>.world_summary.md`
- `.memory/outlines/<book_id>.outline.md`

说明：

- 当前路径由 service 自动 ensure
- 目录约定已经可用
- 但“结构化合并”仍较弱

## 6. 当前精读 Agent 的实际运行逻辑

### 6.1 Prompt 输入装配

当前 `CloseReadRunner._build_prompt_input()` 已实现：

- 读取当前 batch documents
- 从人物候选中推断本轮相关角色
- 按预算读取人物档案
- 读取故事大纲 Markdown
- 读取世界观概要 Markdown
- 构造 `CloseReadPromptInput`

当前真实输入字段包括：

- `documents`
- `story_outline_md`
- `world_summary_md`
- `character_profiles`
- `token_budget`
- `source_total_chars`
- `summary_target_chars_min`

目标拆分后：

- Chapter Summary Agent 继续消费章节级 documents，负责章节摘要、世界观候选、剧情事实压缩
- Character Evidence Agent 消费独立的 `character_evidence_batch`，可以合并多个连续 documents，负责人物抽取与人物性判断
- Memory Candidate Agent 汇合章节摘要和 Character Evidence 结果，生成可写入长期 Memory 的候选更新

### 6.2 Prompt 约束

当前 `close_read_prompt.py` 已明确要求模型：

- 不摘抄原文
- 保留地点、人物、行动、冲突、结果、关键心理变化
- 必须逐个 `doc_id` 返回 `document_character_mentions`
- 必须返回 `character_evidence`
- 非显然人物名必须附带更强人物性线索
- `character_updates` 必须只包含真实人物
- 无证据不得编造人物性格、年龄、关系或设定

这说明当前项目已经把“人物提取的证据约束”前移到了 prompt 和本地校验双层。

目标 prompt 约束应调整为：

- Chapter Summary Agent 不再承担逐 `doc_id` 人物抽取主职责
- Character Evidence Agent 不要求逐 `doc_id` 返回 `document_character_mentions`
- Character Evidence Agent 不要求返回原文连续子串、offset 或可回源证据片段
- Character Evidence Agent 必须返回 batch-level 人物列表、发言判断、人物性证据、行动状态证据、关系证据、置信度与不确定原因
- Memory Candidate Agent 只从高置信人物结果中生成长期人物档案更新，低置信候选应降权或丢弃

### 6.3 Fallback 行为

当前 `CloseReadRunner._fallback_close_read_output()` 已实现启发式 fallback：

- 直接从正文抽局部句子拼接章节摘要
- 按章节长度、人物密度和推进粗估重要性
- 根据关键词粗生成世界观 update
- 以提及人物生成最小 `character_updates`
- 自动生成一行 outline update

这意味着：

- 即使模型输出失败，Memory 层也能保底产出章节摘要、人物命中、世界观增量和大纲增量
- 但这些结果是“保底可用”，不是“高质量精读”

## 7. 当前人物档案提取逻辑细化

### 7.1 当前链路

当前链路是：

1. `CharacterMentionService.extract_document_mentions()`
2. 模型输出 `document_character_mentions`
3. `CharacterEvidenceValidator.filter_names()`
4. `documents_repo.update_character_keywords()`
5. `CharacterProfileService.merge_updates()`

### 7.2 现状优点

- 已经避免完全信任模型的人物列表
- 已经实现证据级过滤
- 已经把人物提取放在精读阶段，而不是粗读阶段
- 已经把每章人物变化向长期 profile 归并

### 7.3 当前限制

- 人物别名归一仍较弱，主要依赖 `canonical_name`
- `relationship` 合并是简单 list merge，还没有冲突消解
- `importance_score` 尚未真正驱动人物档案优先级
- `profile_summary_md` 目前还是最小模板，不是高密度事实摘要
- 当前人物抽取仍偏 document 级，模型输出维度随 document 数量增长
- 过度依赖本地候选名与原文连续证据片段，会让 Character Evidence Agent 的 prompt 和 JSON 输出变重
- 当前章节摘要返回的索引信息对人物档案更新利用有限，人物更新更需要 batch-level 的人物性、发言、行动状态与关系判断

## 8. 当前世界观与大纲提取逻辑细化

### 8.1 世界观

当前逻辑：

- 每轮精读从模型输出 `world_update`
- `WorldStateService.apply_update()` 把变更追加到世界观 Markdown
- 之后重建 `world_summary.md`

当前优点：

- 已有唯一文档载体
- 已有自动概要重建

当前限制：

- 还不是 section 级 patch
- 证据只是以短文本写入，没有结构化证据索引
- 追加模式容易累积重复信息

### 8.2 大纲

当前逻辑：

- 每轮精读从模型输出 `outline_update`
- `OutlineService.apply_update()` 追加章节行和时间节点
- 超长直接裁剪

当前优点：

- 已有运行闭环
- 已能给后续 prompt 提供低成本概要

当前限制：

- 还没有真正的“主线/弱支线淘汰”机制
- 顺序精读阶段立即写入的 `outline_update` 容易把暂时性的剧情方向误判为稳定主线
- 章节摘要中的“结构功能/节奏”同样缺少后文参照，容易把铺垫、缓冲、过渡或关系试探误判为收束、转折或主线切换
- 还没有用 `provisional / committed` 状态显式区分即时判断和复核后的定稿判断
- 还没有面向 Narrative Indexer 的稳定 handoff 服务；仅靠顺序精读阶段的章节摘要缺少连续原文窗口，难以识别相对独立的场景、过渡章节和缓冲章节，也难以为 SceneCards / SourceArcMap / ArcPatternCard 提供可靠输入

## 9. 目标设计与当前实现映射

### 9.1 已基本落地

- 精读 Agent 主流程
- 章节级输入装配
- `chapters` 落库
- `character_profiles` 落库
- `reading_progress` 落库
- 世界观 Markdown / world summary 自动维护
- 故事大纲 Markdown 自动维护
- 人物提取证据校验

### 9.2 已部分落地

- 粗读章节边界保护
  - 当前已能保护 Markdown 标题和独占一行的中文括号章号
  - 当前已能在模型吞并多个显式章节标题时做入库前拆分
  - 但尚未抽象为独立 `ChapterBoundaryDetector` / `SegmentationValidator`
- 章节相关性评分
  - 表已支持
  - 但当前模型输出和后处理仍较弱
- 章节摘要和故事大纲状态
  - 当前流程已能持续写入摘要和大纲
  - 但尚未在 schema 中区分 `provisional` 与 `committed`
  - 也尚未保存 `evidence_window` / `target_range`
- 人物关系维护
  - 字段已支持
  - 但缺乏强约束 merge 策略
- 年龄/阶段变化追踪
  - `age_timeline_json` 已支持
  - 但依赖模型更新质量
- 上下文装配
  - 精读输入装配已实现
  - 但尚未有独立的 `ContextAssemblyService` 面向续写主 Agent 输出标准上下文包

### 9.3 尚未正式独立成模块

- 独立的 Memory Update Agent
- 独立的 `ChapterBoundaryDetector` 与 boundary metadata 持久化
- 独立的 Character Evidence Agent
- 独立的 Memory Candidate Agent
- 独立的 Narrative Indexer Handoff Service
- 独立的 Context Assembly Agent / Service
- 人物档案的结构化证据级管理
- 世界观的 section 级合并
- 故事大纲的主线压缩和弱支线淘汰
- 章节摘要和故事大纲的窗口级定稿流程
- close-read 完成后给 Narrative Scene Indexer 使用的只读 evidence bundle 与窗口 trace

## 10. 推荐的 Memory 层目标结构

### 10.0 ChapterBoundaryDetector

推荐新增 `ChapterBoundaryDetector`，但它属于粗读入库流程内部组件，不是新的用户可见 Agent。它的职责是发现候选、标注置信度和提供可审计证据；最终 document 分组仍由 Segmentation Agent 的模型输出和本地 validator 共同决定。

建议接口：

```python
@dataclass(frozen=True)
class ChapterBoundaryCandidate:
    candidate_id: str
    source_path: str
    start_offset: int
    end_offset: int
    raw_heading: str
    normalized_heading: str
    normalized_ordinal: int | None
    boundary_type: Literal["chapter", "volume", "part", "scene", "unknown"]
    confidence: float
    format_family: str
    evidence: tuple[str, ...]


class ChapterBoundaryDetector:
    def detect(
        self,
        text: str,
        *,
        source_path: str,
        source_start_offset: int,
        toc_entries: Sequence[TocEntry] = (),
        book_profile: ChapterBoundaryProfile | None = None,
    ) -> list[ChapterBoundaryCandidate]: ...
```

候选来源：

- 目录 / PDF bookmark / 文件名中的章节序号
- 独立短行标题
- 连续编号序列
- `第N章`、`第N回`、`卷N`、`幕N`
- `Chapter N`、`Part N`
- 中文数字、阿拉伯数字、罗马数字
- 括号编号，例如 `（九）`
- 同一本书内反复出现的标题格式

Detector 的输出进入两个地方：

- `SegmentBuilder`
  - 高置信 `chapter` / `volume` / `part` 候选必须成为 hard boundary
  - 中低置信候选可作为 prompt hint，不强制切分
- `SegmentationValidator`
  - 如果模型返回的单个 document 含多个高置信章节边界，validator 必须拆分或重跑该 batch
  - 如果模型跳过候选、跳序或把低置信候选提升为章节，validator 应记录 `boundary_status`

建议逐步迁移路径：

1. 先把当前 `DocumentIngestService._segment_span_text()`、`_extract_explicit_title()` 和 `_split_materialized_documents_by_segment_titles()` 中的章节判断抽到 Detector / Validator。
2. 保存候选到内存 sidecar，并在 debug export 中输出，便于解释粗读为什么切章。
3. 为 `documents` 增加可选 boundary metadata 字段或独立 sidecar 表。
4. 引入 `ChapterBoundaryProfile`，根据一本书前若干章动态学习 format family 与 ordinal sequence。
5. 当 close-read、Narrative Scene Indexer 或人工复核发现章节边界错误时，提供“重建粗读 documents + 级联重跑受影响 close-read”的修复入口。

### 10.1 Reading Agent

保留当前 `CloseReadRunner` 的章节精读职责：

- 组装章节输入
- 调用模型
- 生成章节摘要 / world update / `provisional` outline update
- 继续按 `document_title_index` 或超长章节拆批运行
- 对章节摘要中的结构功能、节奏、篇章作用等后验判断只给出 `provisional` 结果，不承担最终定稿职责

### 10.2 Character Evidence Agent

建议从现有精读 prompt 中拆出独立人物证据职责：

- 输入为 `character_evidence_batch`
- batch 可由多个连续 `documents` 拼接而成
- 输出 batch-level 人物抽取结果
- 对每个候选人物输出：
  - `character_id`
  - `canonical_name`
  - `aliases`
  - `resolution_status`
  - `is_speaking_character`
  - `speaking_evidence`
  - `personhood_evidence`
  - `activity_or_state_evidence`
  - `relationship_evidence`
  - `confidence`
  - `uncertainty_reason`

该 Agent 不要求：

- 逐 `doc_id` 输出人物列表
- 输出原文连续子串
- 输出 offset
- 直接写入人物档案

当输入提供 `existing_character_roster` 时，Character Evidence Agent 应把正文称呼解析到 roster 中的 `character_id`。若只确认了 canonical name 但不能确认 id，必须通过 `resolution_status` 标注为 `unresolved_alias` 或等价状态，交给后续身份归并服务处理。

### 10.3 Memory Candidate Agent

建议新增 Memory Candidate Agent，汇合：

- Chapter Summary Agent 的章节摘要和事实压缩结果
- Character Evidence Agent 的 batch-level 人物结果
- 已有人物档案、世界观概要和故事大纲

输出：

- 人物更新候选
- 世界观更新候选
- `provisional` 大纲更新候选

该层负责判断哪些人物事实值得写入长期 Memory，并过滤低置信人物候选。

人物更新候选的实际落地应拆为逐人物 loop，而不是一次性 Memory Candidate prompt 输出所有人的最终更新。推荐边界：

- `Memory Candidate Agent` 负责把 Character Evidence 过滤为“本批次值得更新的人物集合”，保留 `character_id`、`canonical_name`、source ids 和 confidence。
- `Character Reduce Agent` 负责逐人物增量更新，每次只处理一个人物；`Character Profile Brief Compact Agent` 只在 brief 缺失、重大变化或 compact 阈值触发时运行。
- 本地 merge 层负责把模型 patch 写回长期档案，并维护结构化去重。

逐人物 prompt 至少包含：

- `target_character_id`
- `target_canonical_name`
- `profile_brief`
- `ordered_character_evidence`
- `chapter_summary`
- `brief_compact_policy`

`brief_compact_policy` 必须声明：普通 reduce 只写当前增量与 compact 触发信号，不要重复已有同义事实；人物性证据、基础属性和关系都要归并；关系明细写入 `relationships`，不要再复制进 `profile_summary_md`。

### 10.3.1 Summary / Outline Commit 状态

建议不新增复杂 Agent 时，先在 schema 层引入状态字段：

```json
{
  "status": "provisional",
  "evidence_window": {
    "start_document_title_index": 10,
    "end_document_title_index": 20
  },
  "target_range": {
    "start_document_title_index": 14,
    "end_document_title_index": 18
  }
}
```

状态语义：

- `provisional`
  - 顺序 close-read 或 Memory Candidate Agent 立即生成的结果
  - 可用于事实追踪和短期上下文，但结构功能、节奏和主线归纳不应视为最终判断
- `committed`
  - 已结合后续窗口、SceneCards 或人工复核
  - 对同一章节或同一 `target_range`，应优先于旧的 `provisional` 结果

推荐定稿策略：

- 章节摘要中的剧情事件链、人物状态、关键信息可以先随 close-read 暂存
- “结构功能/节奏”默认保持 `provisional`
- 故事大纲的即时 `chapter_line` 和 `outline_segment` 默认保持 `provisional`
- 当后续章节足够时，用较大的 `evidence_window` 重算较小的 `target_range`
- 例如综合第 10 到第 20 个 document/chapter 的故事梗概、人物档案和世界观概要，定稿第 14 到第 18 个 document/chapter 的大纲片段
- Narrative Scene Indexer 生成的 SceneCards 可作为结构复核输入；Memory 层不因 `SourceArcMap` 自动反向覆盖章节摘要或大纲

### 10.4 Memory Update Agent

建议从当前 `CloseReadRunner._persist_batch()` 中拆出：

- `ChapterPersistenceService`
- `CharacterProfileUpdateService`
- `WorldMemoryUpdateService`
- `OutlineMemoryUpdateService`
- `ReadingProgressUpdateService`

原因：

- 现在 `_persist_batch()` 聚合职责过重
- 后续要并行或独立调试人物 / 世界观 / 大纲时不够灵活

### 10.5 Context Assembly Service

建议新增一个面向续写主 Agent 的独立服务，输入：

- `book_id`
- 当前章节位置
- 相关角色名
- 目标预算

输出：

```json
{
  "chapter_context": [],
  "scene_or_arc_context": [],
  "world_summary_md": "string",
  "character_profiles": [],
  "story_outline_md": "string",
  "memory_status": {"chapter_context": "committed|provisional|mixed", "story_outline": "committed|provisional|mixed"},
  "missing_context": []
}
```

该层应负责：

- 按预算裁剪上下文
- 优先级排序
- 优先选择 `committed` 摘要和大纲片段；仅在缺失时回退到 `provisional`
- 当上下文包含 `provisional` 结果时显式标注，避免 Writer 把暂定结构判断当作定稿事实
- 缺失信息显式返回

### 10.6 Narrative Indexer Handoff Service

建议新增 close-read 后的只读 handoff 服务，输入：

- `book_id`
- `documents` 的有序原文、source offset、章节边界状态
- `chapters` 中的 document/chapter 级故事梗概、短摘要、重要性评分与关联章节
- outline segment / outline root artifact
- 世界观概要 Markdown
- 主要人物档案摘要

该服务不做结构判断，只负责按预算组装 Narrative Scene Indexer 所需证据：

```json
{
  "book_id": "string",
  "window_id": "scene-window-0004",
  "previous_context_summary": "窗口之前的高度压缩梗概",
  "raw_document_window": [
    {"doc_id": 10, "document_title_index": 3, "content": "string"}
  ],
  "next_context_summary": "窗口之后的高度压缩梗概",
  "character_context": [],
  "world_context": "string",
  "source_doc_ids": [10, 11, 12],
  "overlap_doc_ids": [12]
}
```

推荐窗口策略：

- 先由 outline root / outline segment / chapter summaries 规划候选范围。
- 每个 raw window 按原文字符预算组装，建议初始值不超过 16KB。
- 相邻 raw window 必须有 overlap；overlap 用于处理 document 边界切断同一场景的问题。
- 前后上下文只传高度压缩梗概，不传全量原文。
- Handoff trace 必须记录窗口覆盖的 doc ids、title indexes、摘要来源和裁剪原因。

该服务不负责：

- 生成 `NarrativeSceneCard`
- 生成 `SourceArcMap`
- 生成 `ArcPatternCard`
- 重写章节摘要
- 直接更新人物档案、世界观或故事大纲

`NarrativeSceneCard -> SourceArcMap -> ArcPatternCard` 的生成与存储属于 `narrative-indexer/design.md`。Memory 层只保证原文与摘要可回源、可裁剪、可审计。

## 11. 当前实现建议保留与建议重构

### 11.1 建议保留

- `CloseReadRunner` 作为当前精读主入口
- `ChapterAssemblerService`
- `CharacterMentionService`
- `CharacterEvidenceValidator`
- `CharacterProfilesRepo`
- `ChaptersRepo`
- `ReadingProgressRepo`
- `AssetsRepo`
- `WorldStateService.ensure_paths()` / `OutlineService.ensure_path()`

### 11.2 建议渐进重构

- `CloseReadRunner._persist_batch()`
  - 拆 service
- `CharacterProfileService._build_summary()`
  - 升级为更稳定的人物摘要构建器
- `WorldStateService.apply_update()`
  - 从 append-only 升级为 section-aware merge
- `OutlineService.apply_update()`
  - 从 append-only 升级为主线优先压缩
- `DocumentIngestService`
  - 把章节边界候选、segment hard boundary、模型分组校验拆成 `ChapterBoundaryDetector`、`SegmentBuilder` 和 `SegmentationValidator`

### 11.3 建议新增

- `ChapterBoundaryDetector`
- `ChapterBoundaryProfile`
- `SegmentationValidator`
- `ContextAssemblyService`
- `NarrativeIndexerHandoffService`
- `CharacterEvidenceBatchAssembler`
- `CharacterEvidenceAgent`
- `MemoryCandidateAgent`
- `CharacterAliasResolver`
- `RelationshipMergePolicy`
- `WorldSectionMergePolicy`
- `OutlineCompressionService`
- `SummaryOutlineCommitService`

## 12. 推荐实现顺序

1. 将当前精读与 Memory 逻辑文档化并保持可运行
2. 抽出 `ChapterBoundaryDetector` / `SegmentationValidator`，保护粗读入库的高置信章节边界，并为错误边界提供重建入口
3. 为章节摘要和故事大纲 schema 增加 `provisional / committed` 状态、`evidence_window` 与 `target_range`
4. 拆出 Character Evidence Agent 的 batch 输入与 batch-level 输出 contract
5. 新增 Memory Candidate Agent，汇合章节摘要和人物证据结果，输出默认 `provisional` 的大纲更新候选
6. 新增 Narrative Indexer Handoff Service，为 Scene Indexer 提供带 overlap 的连续原文窗口、窗口前后压缩梗概和回源 trace
7. 新增窗口级摘要 / 大纲定稿流程，用较大的 `evidence_window`、SceneCards 或人工复核较小的 `target_range`，并把结果升级为 `committed`
8. 新增 `ContextAssemblyService`，先打通续写主 Agent 的事实上下文输入，并能在必要时输出 Narrative Indexer 生成的相关 SceneCards / SourceArcMap 片段和 memory 状态
9. 拆分 `_persist_batch()` 为多个 update service
10. 强化人物档案 merge 策略
11. 强化世界观 section 合并
12. 强化大纲压缩与章节关联

## 13. 最小测试清单

- 精读阶段可从 `reading_progress` 继续
- 粗读分段时高置信章节边界不会被合并进前一个 segment
- 模型把多个高置信章节边界合入同一个 document 时，validator 会拆分或重跑
- `boundary_status = uncertain` 的 document 不会被当作稳定章节结构输入 Writer
- `document_character_mentions` 证据过滤可拦截伪人名
- Character Evidence Agent 可把多个 document 拼接为同一个 batch
- Character Evidence Agent 输出不依赖逐 `doc_id`、原文连续子串或 offset
- Character Evidence Agent 能输出发言判断、人物性证据、行动状态证据与关系证据
- Character Reduce Agent 默认按单人物 `profile_brief` + 当前 evidence 运行；相关人物 brief 只能作为短关系参照
- Character Reduce 输出按 `character_id` / canonical identity 分离，不串写人物经历
- Memory Candidate Agent 能基于 Character Evidence 结果过滤低置信人物候选
- `documents.character_keywords_json` 会被精读结果回写
- `character_profiles` 会合并章节更新
- `chapters` 会保存摘要、人物、世界观、大纲增量
- 新 close-read 写入的章节摘要和大纲增量默认是 `provisional`
- 窗口级复核可基于较大的 `evidence_window` 将较小的 `target_range` 标记为 `committed`
- 对同一章节或大纲范围，`committed` 结果优先于旧的 `provisional` 结果
- 世界观 Markdown 与 world summary 会更新
- 故事大纲 Markdown 会更新
- Narrative Indexer Handoff Service 能按预算返回连续 raw document window、窗口前后压缩梗概和 source trace
- Handoff raw window 支持 overlap，避免同一场景被 document 边界切断
- Handoff bundle 不直接生成 SceneCards、SourceArcMap 或 ArcPatternCard
- `ContextAssemblyService` 能在需要源作品位置定位时输出 Narrative Indexer 生成的相关 SceneCards / SourceArcMap 片段，并显式标注上下文中的 `provisional` / `committed` 状态
- Narrative Indexer 层可基于 SceneCards 聚合 `SourceArcMap`，再沉淀 `ArcPatternCard`，Writer 主要消费这些可检索结构 card
- `ContextAssemblyService` 新增后应有独立 contract 测试
