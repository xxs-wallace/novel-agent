# Novel Agent Harness 架构评审报告

日期：2026-07-21  
范围：`novel-agent` 仓库的 Writer 主流程、Narrative Memory / Creative KB 检索、人工确认控制面与 agentic benchmark。

## 1. 关键发现

| 优先级 | 风险 | 直接后果 |
| --- | --- | --- |
| P0 | Draft Research 耗尽预算后错误进入正文 | 在证据仍不足时生成并固化事实 |
| P0 | 确认决定未绑定当前 artifact 版本 | 旧卡片、重复请求或构造 payload 推进错误状态 |
| P1 | 缺少请求级全局 token 预算 | 长文本请求超限、成本失控、注意力稀释 |
| P1 | 产品 Writer 与 benchmark 使用平行上下文路径 | 测到的不是线上实际 Harness 行为 |
| P1 | 中文粗排 tokenization 失效 | rerank 前漏掉相关 Creative KB 片段 |
| P1 | 事实上下文缺少目标相关性排序 | 远期关键伏笔被近期低价值信息挤出 |
| P1 | 被测模型与 judge 不独立 | 跨模型比较存在同源偏差 |
| P1 | benchmark 缓存 provenance 不完整 | 旧建模结果被静默复用，无法复现 |
| P1 | 缺失评测输入默认满分 | 低覆盖样本反而更容易通过 |

## 2. 结论摘要

当前系统已经具备一个成熟 Agent Harness 的主要部件：分层规划、研究循环、结构化 artifact、可恢复状态、人工确认、事实 Memory 与创作 KB 隔离、规则评分和模型评审。项目说明对关键原则的定义也基本正确，特别是：用户确认后的产物必须成为下游输入、正文前必须经过 Draft Research Loop、benchmark 必须隔离未授权未来信息、Memory 与 Creative KB 的贡献不能混算。

主要问题不在“缺少 Agent”，而在 Harness 的控制面没有统一收口：不同阶段各自组装上下文和检索，缺少全局 token 预算；研究预算耗尽会被误判为资料充分；人工确认没有绑定 artifact 版本；benchmark 又存在被测模型与裁判同源、缓存缺少模型与代码版本、缺失数据反而得到满分等问题。因此目前的运行结果可用，但还不能稳定证明“模型是在正确上下文、正确授权边界和正确确认版本上完成了任务”。

建议按以下顺序整改：

1. 先修 Draft Research 的错误成功状态和确认决定的版本绑定。
2. 再建立统一的 `ContextEnvelope`、token 预算器与检索证据协议。
3. 最后重构 benchmark 的裁判独立性、覆盖率语义与可复现清单。

## 3. 评审基线

本报告以这些项目约束为判断基线：

- 产品总流程要求“用户确认后的内容”成为后续流程准绳（`.trae/specs/spec.md:63-84`）。
- Writer 模块要求正文必须先经过 Draft Research Loop，并要求上游修改触发下游回滚（`.trae/specs/writer-agent-layered-generation/AGENT_CONTEXT.md:58-65`）。
- `ContextAssemblyPayload` / `WriterInputBundle` 是跨层共享 contract，而非仅供 smoke 使用的对象（`.trae/specs/writer-agent-layered-generation/AGENT_CONTEXT.md:41-43`）。
- benchmark 应调用正式 Writer 接口，区分 Memory 与 Creative KB，并隔离未授权 reference truth（`.trae/specs/agentic-benchmark/AGENT_CONTEXT.md:44-49`）。

风险等级定义：P0 表示可能破坏流程正确性或人工控制边界；P1 表示会显著降低长文本稳定性、检索质量或评测可信度；P2 表示不会立即阻断流程，但会扩大成本、漂移和诊断难度。

## 4. 详细发现

### P0-1：Draft Research 预算耗尽被错误标记为“可以写正文”

**证据**

`DraftResearchService.run()` 在模型每轮都继续返回检索请求时，会一直执行到 `max_rounds`。Python `for ... else` 分支随后无条件把状态设为 `ready_for_draft`（`novel_agent/app/services/draft_research_service.py:132-177`）。这与同一方法已经支持的 `blocked`、`needs_user_input`、`replan_requested` 状态相矛盾。

**风险**

- “尚未找到人物事实、关系状态或连续性证据”会被解释成“证据充分”。
- 正文 Agent 会在研究预算恰好耗尽时开始补全事实，形成最难追踪的幻觉类型。
- 增加 `max_rounds` 只会提高成本，不能修复错误状态语义。

**建议**

- 新增显式 `budget_exhausted` 或复用 `blocked`，并保存未完成请求、关键缺口和已用预算。
- 只有模型明确返回 `ready_for_draft` 且没有未处理的高优先级请求时才允许进入 Draft Prose。
- 增加“每轮都有 requests，直到耗尽”的回归测试，断言正文 executor 不会被调用。

### P0-2：人工确认没有与当前 artifact 版本做原子绑定

**证据**

`review_writer_artifact()` 接受客户端提供的 `artifact_path`、`artifact_kind`、`artifact_id` 和 `review_id`，仅在缺省时才回退到当前 checkpoint；随后立即写入决定并按该路径继续流程（`novel_agent/app/orchestrators/writer_workflow.py:1294-1387`）。它没有验证这些字段必须与当前 `pending_checkpoint` 完全相等，也没有校验 artifact 内容摘要或版本是否仍然有效。

Web 层同样直接透传这些标识，甚至允许 payload 显式覆盖 `workflow_action`（`novel_agent/app/web/services/web_action_service.py:1630-1654`、`1696-1699`）。此外，Web 启动 Writer 时直接接受 `product_mode`（`novel_agent/app/web/services/web_action_service.py:519-538`），而 `auto_novel` 模式没有任何确认点（`novel_agent/app/orchestrators/writer_workflow.py:41-48`）。

**风险**

- 用户在旧卡片上点击确认，可能批准已经被修订替换的旧版本。
- 重复点击、并发 tab 或重试请求可能重复推进状态机。
- 若 Web API 不仅限受信本地调用，构造 payload 可以绕过产品应有的人工确认。

**建议**

- checkpoint 增加不可猜测 nonce、`artifact_version`、内容 SHA-256 和状态版本号。
- 确认接口采用 compare-and-swap：只接受当前 run、stage、review、artifact、version 全部匹配且尚未终结的决定。
- 为决定加入 idempotency key；重复请求返回第一次结果，旧版本返回 `409 stale_review`。
- Web 产品接口固定允许的模式；`auto_novel` 只通过 benchmark / dev capability 开启，不能由普通请求字段选择。

### P1-1：上下文只有局部分项截断，没有一次请求的全局 token 预算

**证据**

Outline seed 对“最近章节概览”设置了 2400 字符预算（`novel_agent/app/services/outline_research_service.py:380-384`），但每轮模型请求仍重新序列化完整 `seed_packet`、不断增长的 `planning_notebook` 和全部 `prior_results`（同文件 `2335-2412`）；sufficiency gate 又重复发送完整 seed 和 notebook（`2477-2518`）。代码会记录 `prompt_chars`，但没有在请求前执行模型上下文上限检查或全局裁剪。

本地已有运行证据：`runs/writer/62bb0b0917a04a6e96947f0bcf857894/outline_research_trace.json` 中三次 research prompt 分别达到 98,494、211,480、237,697 字符（39,612、78,017、85,475 input tokens），sufficiency prompt 为 142,669 字符 / 56,059 input tokens。

**风险**

- 大型小说上出现 provider context-limit 错误、超时、费用突增和重试放大。
- 即使 API 接受请求，关键约束也可能因长上下文注意力稀释而被忽略。
- 同一任务在不同模型上下文窗口下表现不同，错误难以复现。

**建议**

- 建立模型感知的 `ContextEnvelope`：包含总 input token 上限、保留输出预算、分区配额、实际 token 数和裁剪日志。
- notebook 使用增量摘要和 evidence reference，避免每轮重发完整检索结果；模型按需通过 ID 读取证据正文。
- preflight 超预算时先压缩，再明确 `budget_exhausted`，禁止依赖 provider 截断。
- SLO 至少记录 p50/p95 prompt tokens、每阶段成本、压缩率和因预算阻塞的比例。

### P1-2：生产 Writer 与 contract 中的 Context Assembly 已形成平行路径

**证据**

`ContextAssemblyService` 会统一组装章节、篇章、世界观、人物和缺失项（`novel_agent/app/services/context_assembly_service.py:63-104`），`MainLayerOrchestrator` 再把它放入正式 `WriterInputBundle`（`novel_agent/app/orchestrators/main_layer_orchestrator.py:196-248`）。但当前生产 Writer 的 `RestrictedWriterExecutor.prepare_execution_input()` 独立构造 recent synopses、前章尾部、人物事实和规划切片（`novel_agent/app/orchestrators/writer_execution.py:733-835`），之后再进入另一套 Draft Research broker；它并不消费上述统一 bundle。

与此同时，单样本 benchmark 仍走 `MainLayerOrchestrator.assemble_context_payload()` 和 `build_writer_input_bundle()`（`novel_agent/app/runner/single_sample_smoke_runner.py:390-425`）。

**风险**

- benchmark 验证的上下文路径并非 Web Writer 的真实路径。
- `missing_context`、来源追踪和预算修复只覆盖其中一条路径。
- Outline Research、Draft Research、Reviewer 与 smoke 各自演化检索语义，出现“某处已修复、另一处仍失败”。

**建议**

- 保留消费者特定 selector，但统一为同一个 typed broker / query / evidence contract。
- 让 `ContextAssemblyPayload` 升级为执行 envelope，Writer、Analyzer、Reviewer、benchmark 都从中选择视图，而不是各自拼接事实。
- 建立 contract parity 测试：同一 query 在产品 Writer 与 benchmark 中必须返回相同授权范围、来源类型和缺失状态。

### P1-3：Creative KB 的中文粗排 tokenization 会漏掉大多数语义重叠

**证据**

粗排用正则 `r"[\w\u4e00-\u9fff]+"` 取 token（`novel_agent/app/services/coarse_retrieval_service.py:8`），再直接把每个匹配串加入集合（同文件 `224-238`）。连续中文句子通常会成为一个长 token，因此只有整段完全相同才产生 overlap。粗排分数又把该 overlap 作为 `summary_match` 和 `style_profile_text` 的核心信号（同文件 `74-136`）。

**风险**

- 中文改写、近义表达和短语交叉几乎无法召回，结果过度依赖精确标签和 FTS。
- 高质量 fragment 在 rerank 前就被过滤，后续模型没有纠错机会。
- 当前 benchmark 的检索分数无法解释“未召回”和“召回后未使用”的区别。

**建议**

- 最低限度采用中文字符 bigram / trigram + BM25；更理想的是 lexical + embedding 混合召回，再由 reranker 排序。
- 建立带 paraphrase、别名、关系变化和情绪机制的中文 retrieval gold set，报告 Recall@K、MRR、nDCG 和空召回率。
- 保存每个候选的 query facet、召回通道、分数分解与淘汰原因。

### P1-4：事实上下文排序偏重“近”，缺少面向当前写作目标的相关性

**证据**

章节选择在有当前章节时按距离、章节序号、重要度排序；没有 scene goal、冲突目标或待核验事实参与排序（`novel_agent/app/services/context_selectors.py:7-36`）。人物排序也主要依赖显式名字、重要度和最近出现位置（同文件 `66-85`）。

**风险**

- 早期埋下但当前需要回收的承诺、物件、伤势和关系事件容易被近期摘要挤出。
- `missing_context` 只能表达“资料不存在/没装入”，不能表达“当前问题所需证据不足”。

**建议**

- Context query 必须携带 scene goal、required facts、entities、time boundary 和 risk facets。
- 排序结合 lexical / semantic relevance、时间邻近、重要度、关系边权和伏笔状态。
- sufficiency 基于“每个 required facet 是否有可引用证据”，而不是只看 payload 是否非空。

### P1-5：benchmark 的被测模型与裁判模型不独立

**证据**

单样本 CLI 把同一个 `generation_config` 同时传给正文生成器和 `SmokeReviewerService`（`novel_agent/app/run_single_sample_smoke.py:194-221`）。Agentic benchmark 的 Writer 使用默认 `deepseek-v4-pro`（`novel_agent/app/run_interactive.py:43`、`225-244`），其 reviewer 也硬编码为相同模型（`novel_agent/app/services/smoke_benchmark_service.py:1207-1222`）。

**风险**

- 裁判可能偏好与自身生成习惯相似的答案，模型对比产生同源偏差。
- 更换 Writer 模型时，judge 是否跟随变化不透明，历史分数不可直接比较。
- 单一模型 judge 的稳定性无法通过当前结果估计。

**建议**

- 独立配置 `writer_model_id` 与 `judge_model_id`，禁止默认复用同一 config。
- 候选文本盲化模型身份并随机顺序；关键 benchmark 使用两种 judge + 少量人工校准集。
- 报告 judge 间一致率、与人工的一致率和成对偏好置信区间，不只给单次绝对分。

### P1-6：benchmark 缓存缺少模型、prompt 与代码版本，结果不可可靠复现

**证据**

建模缓存参数只包含切片大小、批次数和一个手写 prompt version（`novel_agent/app/services/smoke_benchmark_service.py:912-932`）。cache key 包含源文件 hash、reference hash、schema version 和这些参数，但不包含模型 ID、模型参数、prompt 内容 hash、代码提交或依赖版本（同文件 `2683-2701`）。开启 `reuse_modeling_cache` 后会直接加载该缓存（同文件 `943-951`）。

**风险**

- 模型或 prompt 已变化，却静默复用旧 Memory / KB，造成伪可比结果。
- 同一个 cache key 无法重建当时的真实执行环境。
- 单次随机生成没有重复试验和方差，微小分差容易被误判为改进。

**建议**

- 每次运行保存 provenance manifest：git SHA、dirty diff hash、模型/endpoint、采样参数、prompt/schema hash、依赖 lock hash、数据 hash、cache lineage。
- cache key 纳入所有影响建模语义的字段；改变 prompt 或模型即失效。
- 每个正式样本至少重复运行，报告均值、标准差和 bootstrap confidence interval；provider 支持时记录 seed。

### P1-7：缺失评测数据会得到满分，聚合分数掩盖覆盖率

**证据**

规则评分在没有人物名时将人物一致性记为 1.0，没有关系状态时将关系合法性记为 1.0，没有世界观摘要时也将世界规则合规记为 1.0（`novel_agent/app/services/smoke_compare_service.py:234-270`）。最终把所有非空指标做无权重算术平均（同文件 `314-336`），并以 0.8 直接判 pass（`338-345`）。

**风险**

- 上下文建模越不完整，某些维度反而越容易获得满分。
- “没有检测到违规”与“没有足够信息进行检测”被混为一谈。
- 一个总分无法区分生成质量、评测覆盖率和检索覆盖率。

**建议**

- 缺失输入返回 `not_evaluable`，同时计算独立 coverage score。
- 人物、关系、世界规则等关键维度设置最低可评估覆盖门槛；覆盖不足不能 pass。
- 分开报告 legality、continuity、plan fulfillment、style、retrieval utilization 和 coverage，不用一个平均值代替结论。

## 5. 横向风险判断

### 上下文管理

最大风险是“对象很多，但没有请求级 envelope”。现有 char budget 是局部优化，无法保证一次模型调用安全；多个 context builder 也让事实边界、授权边界和压缩策略难以统一。建议将 context management 提升为 Harness 基础设施，而不是各 Agent 内部 helper。

### 检索

当前已经有 coarse retrieval、rerank、Narrative Index 和 research request 等组件，但缺少统一的 query facet 与 evidence provenance。检索质量首先受中文 lexical recall 限制，其次受不同 Agent 各自实现 broker 影响。检索 benchmark 应先评价“找没找到”，再评价“模型有没有正确使用”，不能用正文 token overlap 同时替代两者。

### 人工确认

界面上存在确认点，不代表控制面已经可靠。有效确认必须回答四个问题：谁确认、确认哪个 run、哪个 artifact 版本、状态是否仍停在该节点。当前只较好回答了前两个。版本绑定、幂等和并发控制应作为 artifact review contract 的一部分。

### Benchmark

现有 benchmark 对未来信息授权边界的设计方向是正确的，但评分独立性、缓存 provenance 和 coverage 语义不足。当前分数适合作为开发期 smoke signal，不应直接当作跨模型能力排名或发布门禁。

## 6. 假设与待确认

- 本报告按“Web action endpoint 可能接收不完全受信的客户端 payload”评估确认风险。若部署始终是单用户本机且 endpoint 不对外暴露，安全攻击面下降，但旧卡片、重复点击和并发 tab 的正确性风险仍然存在。
- 本报告把 agentic benchmark 视为未来可能用于模型比较和发布门禁。如果它只承担开发期 smoke，judge 同源与单次运行可以暂时接受，但结果必须明确标注为非独立、非统计显著。
- 当前代码中合法的 authorized future planning 没有被判定为泄漏；风险集中在模式标识、裁判独立性、缓存 provenance 与评测覆盖率，而不是要求取消授权规划。
- 本次是静态架构评审并结合已有运行 trace 取证，没有重新执行完整长篇 benchmark；因此成本和失败率尚未形成统计分布。

## 7. 建议目标架构

建议把 Harness 收敛为五个明确层次：

1. **Run Control Plane**：状态机、checkpoint version、幂等、取消/重试、人工决定与 rollback。
2. **Context Plane**：统一 `ContextQuery -> EvidenceSet -> ContextEnvelope`，执行授权过滤、token 预算、压缩和 provenance。
3. **Agent Plane**：Outline Research、Draft Research、Writer、Reviewer 只声明所需 facets 和输出 contract，不自行绕过 Context Plane。
4. **Artifact Plane**：不可变版本 artifact + mutable current pointer；所有决定引用内容 hash，写回采用事务或 CAS。
5. **Evaluation Plane**：冻结数据切分、独立 judge、规则与模型评分分离、coverage、重复试验和完整 provenance。

一个最小的 `ContextEnvelope` 至少应包含：

```json
{
  "run_id": "...",
  "consumer": "draft_research",
  "authorization_scope": "...",
  "required_facets": ["character_state", "relationship_state", "open_threads"],
  "evidence": [{"evidence_id": "...", "source_type": "memory", "source_ref": "...", "text": "..."}],
  "missing_facets": [],
  "budget": {"model_context_tokens": 131072, "reserved_output_tokens": 16384, "used_input_tokens": 42000},
  "compaction_trace": [],
  "content_sha256": "..."
}
```

## 8. 分阶段整改计划

### 第一阶段：正确性止血

- 修复 Draft Research budget exhaustion 状态并加回归测试。
- ArtifactReviewDecision 增加 checkpoint/version/hash 校验、幂等与 stale decision 拒绝。
- Web 禁止普通请求启用 `auto_novel` 或覆盖内部 workflow action。

### 第二阶段：Context / Retrieval 收口

- 引入统一 Context broker 与 request-level token budget。
- 让生产 Writer 和 benchmark 使用同一个 Context contract。
- 修复中文 coarse retrieval，增加独立 retrieval gold benchmark。

### 第三阶段：评测可信度

- 分离 Writer/Judge 配置并加入人工校准样本。
- 建立 provenance manifest 和完整 cache invalidation。
- 引入 coverage-aware scoring、重复试验和置信区间。

## 9. 建议验收门槛

- 任一研究循环预算耗尽时，不得生成正文，且 UI 能说明缺少什么。
- 对旧 artifact、旧 review card、重复决定和并发决定均有确定且可测试的拒绝/幂等语义。
- 所有生产模型调用在发出前都能证明 `input + reserved output <= model context limit`。
- 产品 Writer 与 benchmark 对同一输入产生相同的授权 evidence lineage。
- 中文检索 gold set 达到预先约定的 Recall@K，且空召回率可观测。
- 正式 benchmark 不使用与被测模型完全相同的单一 judge 配置。
- 每个分数同时携带 coverage、运行 provenance 和统计不确定性。

## 10. 总体评价

这个项目的产品分层与 artifact 思路已经超过普通的 prompt pipeline，方向上确实是在构建 Agent Harness。下一阶段不需要继续增加更多 Agent 角色，而应优先把预算、证据、状态与评测四类基础协议做成全局一致的控制面。完成前三项 P0/P1 整改后，系统才会从“多数时候能跑完整流程”提升为“能够说明为何可以继续、确认了什么、用了哪些证据，以及结果是否真的更好”。
