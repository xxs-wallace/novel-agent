# 小说续写 RAG 检索方案再评估

## 文档目标

- 用途：在“高精度小候选 rerank”与“索引尽量小、尽量简单”这两个新增约束下，重新评估小说续写系统的检索方案。
- 输出对象：工程设计评估，不直接替代 `spec.md`；用于后续决定是否继续保持 `SQLite` 路线，是否需要引入向量库或 late-interaction 检索。
- 结论导向：给出多个可落地方案、适用前提、复杂度对比与推荐路线。

## 新增约束

### 约束 1：最终返回仅 1-4 段参考，rerank 精度必须很高

- 续写 prompt 最终只能容纳很少的参考段落。
- 因此系统不是“召回尽量多”就够了，而是必须在最后一跳尽可能稳定地找出最适合当前场景的少量桥段。
- 这意味着：
  - 在线阶段不能依赖“再让模型临时读很多候选慢慢想”。
  - 离线阶段必须尽量把桥段预处理成更容易比较、更容易筛掉错误候选的结构。
  - rerank 不能只靠宽泛的语义相似度，而要显式比较叙事功能、人物气质、情绪表达方式、上下文依赖度。

### 约束 2：作家原文中存在大量相似或重复段落，希望索引尽量小且简单

- 同一作者会复用相似的景物描写、人物口气、过场结构、悲伤或暧昧时的写法。
- 因此没有必要把所有段落都原样放进检索索引。
- 更合理的做法是：
  - 在建立索引时先做去重、聚类、代表片段提炼。
  - 把索引收缩为“小而精”的桥段库。
  - 检索系统优先使用本地文件或 `SQLite`，而不是一开始就引入复杂外部基础设施。

## 评估原则

- 优先保证 `rerank` 的最终可控性，而不是盲目追求召回规模。
- 优先保证索引的可解释性，而不是依赖不可解释的单一 embedding。
- 优先复用本地文件与 `SQLite`，在索引体量明显增大前不引入重型向量数据库。
- 优先做离线预处理，把高成本分析前移。
- 优先选择“可渐进升级”的方案，避免第一版架构锁死。

## 核心判断

- 对当前项目来说，真正重要的不是“先上最强 multi-vector 检索引擎”，而是“先把桥段索引压缩成一个高质量、低重复、可解释的多视图桥段库”。
- 只要索引体量被控制得足够小，就不一定需要专门的向量数据库；很多向量比较完全可以在本地内存或 `SQLite + sidecar` 文件中完成。
- 在这一前提下，`多视图索引 + 离线去重 + 固定 rubric rerank` 的价值，高于直接上 `ColBERT/Qdrant`。
- `late-interaction multi-vector` 仍然有价值，但更适合作为后续增强项，而不是第一阶段主干。

## 共识性设计

无论选哪条方案，下面几件事都建议先做：

### 1. 先做离线桥段压缩，而不是全文直检

- 原文切成 `document` 后，不直接把所有 `document` 作为最终检索单元。
- 应先生成桥段级 `fragment_card`。
- 每个 `fragment_card` 表达“这一段发生了什么”“这一段在叙事上做了什么”“这一段如何表达情绪”“它是否适合复用”。

### 2. 建立代表片段库，而不是全量段落库

- 对高相似片段做聚类或近重复合并。
- 每一组只保留：
  - 1 个主代表片段
  - 0-2 个风格偏移明显但仍可复用的补充片段
- 对强上下文依赖、重复度高、信息增量低的段落直接降权或丢弃。

### 3. 在线查询只做轻量查询构造

- 在线阶段只基于：
  - 最近窗口
  - 锚点上下文
  - 用户目标
  - 上一段生成结果
- 先生成 `SceneBrief`
- 再根据 `SceneBrief` 去查离线好的桥段索引
- 避免在线阶段重新分析大量原文

### 4. 最终 rerank 采用固定结构

- 不允许 LLM 自由发挥“这段更有感觉”。
- 必须输出固定评分：
  - `continuity_fit`
  - `scene_function_fit`
  - `character_temperament_fit`
  - `relationship_state_fit`
  - `emotion_expression_fit`
  - `style_fit`
  - `transferability`
  - `context_dependency_penalty`

## 方案一：纯文件索引方案（Markdown / JSON）

### 方案描述

- 所有桥段卡片存为本地 `JSON` 或 `Markdown + frontmatter` 文件。
- 目录中按书目、章节、桥段类型组织。
- 在线检索时：
  - 先读取所有卡片元数据
  - 在内存中按标签、摘要文本、规则分数做粗筛
  - 再交给 rerank

### 适合前提

- 目标小说数量很少。
- 每部小说压缩后的代表片段数量较低，例如数百条以内。
- 系统使用者主要是单机、单人、低频运行。

### 优点

- 最简单，几乎没有基础设施成本。
- 文件直观，便于人工审查和手工修正。
- 做全量重建很方便。

### 缺点

- 查询效率和维护性在条目增多后会迅速下降。
- 缺少稳定的过滤、排序、增量校验能力。
- 多字段查询、去重、版本控制都不如 `SQLite` 自然。

### 结论

- 适合做极小规模实验或人工评审样本库。
- 不建议作为正式的长期索引底座。

## 方案二：SQLite-only 多视图桥段库

### 方案描述

- 使用 `SQLite + FTS5` 保存：
  - `documents`
  - `fragment_cards`
  - `fragment_clusters`
  - `scene_templates` 或其他辅助表
- 多视图文本字段直接存入 `fragment_cards`：
  - `content_summary`
  - `narrative_function_text`
  - `emotion_mechanism_text`
  - `character_relation_text`
  - `style_profile_text`
- 若需要 embedding：
  - 向量可存成 `JSON`、`BLOB` 或 sidecar 文件
  - 在线查询时在 Python 中做小规模余弦相似度计算

### 适合前提

- 压缩后的代表片段规模仍较小，例如几百到几千。
- 重点是工程简洁、可解释与易维护。
- 接受全量重建索引。

### 优点

- 与当前项目方向最一致。
- `SQLite` 适合保存结构化卡片、标签、簇关系、来源、评分。
- `FTS5` 足以完成标签、摘要、人物、章节等粗筛。
- 对于小索引，向量相似度完全可以本地算，不一定需要向量库。

### 缺点

- 如果未来片段量扩大到几万级以上，纯本地扫描会变慢。
- 自己维护多视图排序逻辑，工程工作量比纯文件方案稍高。
- 没有原生 late-interaction 能力。

### 结论

- 这是当前最推荐的默认路线。
- 对你的两个新增约束最友好：
  - 索引可以做得很小
  - 结构清晰
  - 可全量更新
  - 不需要额外服务

## 方案三：SQLite + sidecar embeddings

### 方案描述

- 主索引仍在 `SQLite`
- 每个代表桥段额外生成多视图 embedding
- 向量不放进独立向量数据库，而是放在：
  - `SQLite BLOB`
  - `npy` / `npz`
  - `jsonl` sidecar 文件
- 在线阶段先用 `FTS5 + 标签 + 规则` 粗筛出少量候选
- 再对这少量候选做多视图向量相似度计算

### 适合前提

- 希望保留 embedding 的表达能力
- 又不想引入 `Qdrant`、`Milvus` 之类外部组件
- 索引规模已经比纯规则方案稍大，但仍可控

### 优点

- 保留“多视图 embedding”的好处
- 仍保持单机、单文件、全量更新友好
- 易于和现有 `fragment_card` 结构结合

### 缺点

- 需要自己维护向量序列化和相似度逻辑
- 如果 embedding 视图较多，数据组织要更严谨
- 查询逻辑比纯 `SQLite` 稍复杂

### 结论

- 如果你想要一点 embedding 能力，但又明确不想引入外部向量库，这是一个很平衡的方案。
- 它非常适合作为 `SQLite-only` 的增强版。

## 方案四：SQLite + 向量数据库 + late interaction

### 方案描述

- `SQLite` 保存元数据与桥段卡片
- 向量检索单独交给：
  - `Qdrant`
  - 或者后续接 `ColBERT/RAGatouille`
- 在线阶段：
  - 第一阶段在向量库召回
  - 第二阶段用 LLM rerank
  - 或使用 late-interaction 模型做第二阶段精筛

### 适合前提

- 语料规模扩大明显
- 需要更高召回质量
- 团队愿意承担部署、维护和测试成本

### 优点

- 易于扩展
- 更适合未来上真正的 multi-vector / late-interaction
- 召回层能力更强

### 缺点

- 对当前“小索引、全量重建、本地文件优先”的要求不友好
- 会引入额外复杂度
- 在当前阶段，收益很可能不如把离线去重和卡片质量做好

### 结论

- 不适合作为当前第一阶段默认方案。
- 适合作为未来索引规模增大后的升级目标。

## 方案对比

| 方案 | 存储复杂度 | 检索复杂度 | 适合索引规模 | 可解释性 | 对当前约束匹配度 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 纯文件索引 | 最低 | 低 | 很小 | 高 | 中 | 可做实验，不建议长期使用 |
| SQLite-only | 低 | 低到中 | 小到中 | 很高 | 很高 | 当前首选 |
| SQLite + sidecar embeddings | 中 | 中 | 小到中 | 高 | 很高 | 推荐作为增强版 |
| SQLite + 向量库 / late interaction | 高 | 中到高 | 中到大 | 中 | 中 | 暂不作为第一阶段默认 |

## 推荐路线

### 推荐结论

- 第一阶段推荐：`SQLite-only` 或 `SQLite + sidecar embeddings`
- 不推荐第一阶段就引入独立向量数据库
- 不推荐第一阶段就上真正的 `late-interaction multi-vector` 引擎

### 推荐原因

- 你的索引目标不是“覆盖所有原文”，而是“压缩成高质量代表桥段库”。
- 一旦桥段库足够小，检索系统的关键不再是“海量 ANN 检索”，而是：
  - 离线去重是否做得好
  - 片段卡片是否准确
  - rerank 评分是否稳定
- 这些问题和引入 `Qdrant` 没有直接关系。

## 第一阶段推荐架构

### 存储层

- `SQLite`
  - `documents`
  - `fragment_cards`
  - `fragment_clusters`
  - `scene_queries_log` 可选
- sidecar 文件可选
  - `fragment_embeddings.jsonl`
  - 或 `fragment_embeddings.npz`

### 检索层

#### 第 0 阶段：离线压缩

- 原文切为 `document`
- `document` 生成 `fragment_card`
- 对 `fragment_card` 做近重复检测
- 将重复桥段聚为 cluster
- 仅保留代表片段与少数补充片段

#### 第 1 阶段：在线粗筛

- 输入 `SceneBrief`
- 用 `FTS5 + 标签 + 规则过滤` 筛出候选
- 目标候选数建议 `12-40`

#### 第 2 阶段：轻量向量重排

- 若启用 sidecar embeddings，则对候选做多视图相似度计算
- 只在候选集内做，不做全库 ANN 检索

#### 第 3 阶段：高精度 LLM rerank

- 对前 `6-12` 个候选按固定 rubric 打分
- 最终只保留 `1-4` 段

## 为什么这个架构更适合高精度 rerank

- 高精度 rerank 最怕“候选池中充满高度重复文本”。
- 如果离线阶段不去重，LLM 很容易：
  - 在多个近似候选之间浪费判断预算
  - 被重复语气误导
  - 把多个同质段落排进前几名
- 离线先聚类和抽代表片段，可以显著提升最后 `1-4` 段的多样性和质量。

## 离线预处理建议

### 1. 近重复检测目标

- 删除真正重复的段落
- 合并“表达方式几乎一样、仅换了具体人名或地点”的段落
- 保留“情绪机制相同但人物气质不同”的段落

### 2. 近重复检测粒度

- 先以 `document` 作为基础粒度
- 再根据 `fragment_card` 做桥段级聚类

### 3. 近重复检测特征

- 词面相似度
- 标签相似度
- 内容摘要相似度
- 风格特征相似度
- 情绪机制相似度

### 4. 聚类后的保留策略

- `canonical_fragment`
  - 该簇最具有代表性、上下文依赖较低、最适合复用的片段
- `alternate_fragments`
  - 风格或人物气质有明显差异、可作为补充参考的片段
- `discarded_fragments`
  - 仅用于追溯，不参与在线检索

## 建议的表结构

### `fragment_cards`

```json
{
  "fragment_id": "string",
  "doc_id": "string",
  "cluster_id": "string",
  "is_cluster_representative": true,
  "content_summary": "string",
  "narrative_function_text": "string",
  "emotion_mechanism_text": "string",
  "character_relation_text": "string",
  "style_profile_text": "string",
  "preferred_tags_json": ["string"],
  "transferability_score": 0.0,
  "context_dependency_level": "low | medium | high",
  "source_excerpt": "string"
}
```

### `fragment_clusters`

```json
{
  "cluster_id": "string",
  "cluster_theme": "string",
  "representative_fragment_id": "string",
  "member_count": 0,
  "dedup_reason": "string"
}
```

## 建议的在线查询结构

### `SceneBrief`

```json
{
  "scene_objective": "string",
  "emotional_goal": "string",
  "conflict_goal": "string",
  "narrative_function": ["string"],
  "emotion_mode": ["string"],
  "character_temperament": ["string"],
  "relationship_state": ["string"],
  "style_need": ["string"],
  "must_avoid": ["string"],
  "preferred_tags": ["string"]
}
```

## 检索排序建议

### 粗筛阶段

- 先过滤：
  - `context_dependency_level = high` 的片段降权
  - 非代表片段默认不参与首轮检索
  - 明显标签不匹配的片段直接排除
- 再排序：
  - `preferred_tags`
  - `narrative_function_text`
  - `emotion_mechanism_text`
  - `character_relation_text`

### rerank 阶段

- 只对少量候选执行
- 输出固定评分 JSON
- 最终选择时增加一个规则：
  - 不允许前 4 名全部来自同一个 `cluster_id`

这条规则对避免“重复桥段挤占 prompt”非常重要。

## 是否需要 embedding

### 不使用 embedding 的情况

- 桥段库规模较小
- 标签和结构化摘要质量较高
- 主要依靠：
  - `FTS5`
  - 标签匹配
  - 规则排序
  - LLM rerank

这种情况下，完全可能先不做 embedding。

### 建议使用 embedding 的情况

- 同标签桥段之间需要更细的区分
- 结构化摘要的语义相似度很重要
- 候选量开始增长

此时建议只对下列文本建立 embedding：

- `content_summary`
- `narrative_function_text`
- `emotion_mechanism_text`
- `style_profile_text`

而不是直接对原文全文做 embedding。

## 关于真正的 multi-vector / late interaction

### 当前阶段的判断

- 不必作为主方案优先落地。
- 主要原因不是它没价值，而是你的当前瓶颈更可能出在：
  - 去重不充分
  - 片段卡片质量不足
  - rerank rubric 不稳定

### 更合适的引入时机

- 当 `SQLite + sidecar embeddings + LLM rerank` 已经稳定后
- 如果仍然出现：
  - 细粒度误判很多
  - 相似桥段之间难以精确区分
  - 候选召回质量成为瓶颈
- 再考虑引入 `late interaction` 作为第二阶段精排

## 最终建议

### 推荐方案排序

1. `SQLite-only` 多视图桥段库
2. `SQLite + sidecar embeddings`
3. `纯文件索引`
4. `SQLite + 向量库 / late interaction`

### 当前最推荐的工程路线

1. 保持现有 `SQLite` 主体架构。
2. 增加 `fragment_card` 与 `fragment_cluster` 两层。
3. 在离线索引阶段先做桥段去重与代表片段提炼。
4. 在线阶段使用 `SceneBrief -> FTS5/标签/规则粗筛 -> 小候选 rerank -> 1-4 段输出`。
5. 若需要，再引入 sidecar embeddings 做候选集内的多视图相似度排序。
6. 等第一版稳定后，再评估是否需要升级到 `late interaction multi-vector`。

### 一句话结论

- 在你的两个新增约束下，最优先的不是更复杂的检索基础设施，而是“把索引压小、压精、压可解释”。
- 因此第一阶段最合理的方案，是基于 `SQLite` 的桥段卡片库，加上离线去重和高精度 rerank，而不是直接上重型多向量检索引擎。
