# 叙事 Memory 与上下文实现设计稿

## 1. 目标
本设计稿将以下两部分合并整理到 Memory 与上下文层：

- 从 [novel-continuation-mvp/spec.md](.trae/specs/novel-continuation-mvp/spec.md) 与 [novel-continuation-mvp/design.md](.trae/specs/novel-continuation-mvp/design.md) 中抽取出的 Memory / 上下文相关设计
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
- `creative-knowledge-base/spec.md`
  - 创作知识库层
  - 负责桥段卡片、去重、代表片段、`SceneBrief -> 粗筛 -> rerank`
- 本文档对应的 `narrative-memory-context/spec.md`
  - Memory 与上下文层
  - 负责人物档案、世界观、章节摘要、故事大纲、精读进度、上下文装配

### 2.2 核心原则

- 优先保存“事实、状态、关系、时间顺序”，而不是保存仿写参考。
- 所有 Memory 更新尽量基于章节级精读输出，而不是零散片段直写。
- 续写主 Agent 优先消费结构化长期上下文，而不是回读整本原文。
- Memory 层必须允许“已实现的简化版”和“目标设计的增强版”并存一段时间。
- Chapter Summary Agent 的目标粒度保持章节级，继续按 `document_title_index` 或超长章节拆批处理。
- Character Evidence Agent 可以使用独立 batch 粒度，把多个连续 `documents` 拼接后做人物抽取、发言判断、行动状态与关系线索提取。
- Character Evidence Agent 的目标不是做原文 offset 标注，而是为 Memory Candidate Agent 提供更可靠的人物更新输入。
- Source Arc Mapping 应作为 close-read 完成后的 post-processing，而不是 Reading Agent 顺序精读时的即时判断；它应基于完整大纲、章节摘要、人物线和世界观，从全局视角识别源作品中的主线篇章、过渡篇章、日常缓冲篇章、设定揭示篇章、高潮篇章与收束篇章。
- Memory 层的 `SourceArcMap` 只记录源作品事实型篇章地图；可迁移的谋篇布局、节奏模式、人物登场方式和关系推进模式属于创作知识库，应由 KB 层沉淀为 `NarrativeStructurePattern` 或 `ArcPatternCard` 后再供 Writer 使用。
- 章节摘要和故事大纲应区分 `provisional` 与 `committed` 状态：顺序 close-read 产生的即时梗概和大纲增量默认是暂定结果；结合后续窗口或 `SourceArcMap` 复核后，才能作为稳定结构判断被 Writer 优先消费。

## 3. Memory 层数据范围

### 3.1 Character Memory

保存人物的长期状态：

- `canonical_name`
- `aliases`
- `personality`
- `occupations`
- `age_timeline`
- `abilities`
- `recent_activity`
- `relationships`
- `chapter_indexes`
- `first_seen / last_seen`

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
  - 已结合后续若干章节、人物档案、故事大纲或 `SourceArcMap` 复核
  - 可作为 Writer 和结构模式沉淀的稳定输入

`evidence_window` 记录本次判断参考的上下文范围，例如 `10-20`；`target_range` 记录被定稿的章节范围，例如 `14-18`。

### 3.4 Story Outline Memory

保存整书大纲：

- 章节级一行摘要
- 时间节点
- 主线推进信息
- `outline_status`
- `evidence_window`
- `target_range`

当前顺序精读阶段生成的大纲增量默认是 `provisional`。后续可用更大的上下文窗口重算较小的目标范围，例如用第 10 到第 20 个 document/chapter 的故事梗概和人物状态，定稿第 14 到第 18 个 document/chapter 的大纲片段，并标记为 `committed`。

### 3.5 Progress Memory

保存：

- 粗读进度
- 精读进度
- checkpoint token

### 3.6 Context Assembly

面向续写主 Agent 输出：

- 相关章节摘要
- 必要时提供相关源作品篇章地图片段
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

### 3.8 Source Arc Map

保存 close-read 后的源作品事实型篇章地图：

- `source_arc_id`
- `source_arc_title`
- `start_document_title_index`
- `end_document_title_index`
- `source_arc_role`
- `core_events`
- `main_character_threads`
- `world_or_rule_reveals`
- `transition_from_previous`
- `setup_for_next`
- `pacing_notes`
- `chapter_role_map`
- `status`
- `evidence_window`

`source_arc_role` 用于标注源作品中的篇章功能，例如：

- 主线推进
- 过渡缓冲
- 日常关系
- 设定揭示
- 高潮
- 收束

该层不直接作为 Writer 的新书规划模板，而是为后续 KB 结构模式沉淀提供事实输入。KB 层可基于 `SourceArcMap` 形成 `NarrativeStructurePattern` / `ArcPatternCard`，例如“前若干章节以日常和感情生活建立人物状态”“新人物登场后用若干章节完成关系试探”“篇章切换前安排低冲突缓冲与未决问题”等可迁移结构特征。

`SourceArcMap` 由 close-read 后处理生成，默认属于 `committed` 级结构信息。它可以反向支持章节摘要和故事大纲中结构功能、节奏、篇章边界等字段的定稿。

## 4. 当前已实现代码总览

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
- 为每次更新重建一个简化版 `profile_summary_md`
- 维护 `profile_version`

当前实现特点：

- 更新策略偏“append + 去重”
- `age_update` 进入 `age_timeline_json`
- `recent_activity` 也以 list 追加
- 人物摘要目前是轻量模板，不是高保真的人物小传

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

- `novel_agent/app/services/outline_service.py`

能力：

- 自动创建故事大纲 Markdown
- 追加本轮章节一行摘要
- 追加时间节点
- 对整体内容做长度裁剪

当前实现特点：

- 目前是“追加式大纲”
- 追加内容等价于 `provisional` 大纲增量，尚未区分暂定与定稿状态
- 还没有真正的结构化主线压缩与弱相关淘汰逻辑
- 还没有基于后续窗口重算某个 `target_range` 并升级为 `committed` 的机制

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
- 时间线事件还没有去重与关联分析
- 顺序精读阶段立即写入的 `outline_update` 容易把暂时性的剧情方向误判为稳定主线
- 章节摘要中的“结构功能/节奏”同样缺少后文参照，容易把铺垫、缓冲、过渡或关系试探误判为收束、转折或主线切换
- 还没有用 `provisional / committed` 状态显式区分即时判断和复核后的定稿判断
- 还没有 close-read 完成后的源作品篇章地图；仅靠顺序精读阶段的章节摘要缺少全书视角，难以识别相对独立的故事篇章、过渡章节和缓冲章节，也难以为 KB 层沉淀可迁移结构模式提供输入

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
- 独立的 Character Evidence Agent
- 独立的 Memory Candidate Agent
- 独立的 Source Arc Mapping Agent / Service
- 独立的 Context Assembly Agent / Service
- 人物档案的结构化证据级管理
- 世界观的 section 级合并
- 故事大纲的主线压缩和弱支线淘汰
- 章节摘要和故事大纲的窗口级定稿流程
- close-read 完成后的 `SourceArcMap` 文件或表级载体

## 10. 推荐的 Memory 层目标结构

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
  - `canonical_name`
  - `aliases`
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
  - 已结合后续窗口或 `SourceArcMap` 复核
  - 对同一章节或同一 `target_range`，应优先于旧的 `provisional` 结果

推荐定稿策略：

- 章节摘要中的剧情事件链、人物状态、关键信息可以先随 close-read 暂存
- “结构功能/节奏”默认保持 `provisional`
- 故事大纲的即时 `chapter_line` 和 `timeline_events` 默认保持 `provisional`
- 当后续章节足够时，用较大的 `evidence_window` 重算较小的 `target_range`
- 例如综合第 10 到第 20 个 document/chapter 的故事梗概、人物档案和世界观概要，定稿第 14 到第 18 个 document/chapter 的大纲片段
- `SourceArcMap` 生成后，其篇章功能和节奏判断默认可作为 `committed` 级结构信息，反向支持摘要和大纲定稿

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
  "source_arc_context": [],
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

### 10.6 Source Arc Mapping Agent / Service

建议新增 close-read 后处理服务，并在代码命名中优先使用 `SourceArcMappingService`，输入：

- `book_id`
- `chapters` 中的 document/chapter 级故事梗概、短摘要、重要性评分与关联章节
- 当故事梗概总量超过预算时，先使用 `PlotSummaryUnitCompressionService` 调用模型生成 `plot_summary_units`
- 故事大纲 Markdown
- 世界观概要 Markdown
- 主要人物档案摘要

#### 10.6.1 Plot Summary Unit Compression

`SourceArcMappingService` 的常规输入不是整本原文，而是 close-read 已沉淀出的故事梗概。若梗概总量低于阈值，系统直接把全部 document/chapter 梗概发送给 Source Arc Mapping Agent，从整体上总结剧情节奏、篇章功能与章节篇幅分配。超长篇中，即使这些故事梗概也可能超过单次模型安全预算，因此需要一个前置模型压缩阶段。

触发条件：

- 生产默认：document/chapter 级故事梗概总量超过约 12KB
- 测试默认：可把阈值降到约 8KB，用于冒烟测试压缩链路
- 阈值 SHOULD 可配置，例如 `source_arc_summary_compression_threshold`

默认压缩窗口：

- 每个窗口包含 8 个连续 document 的故事梗概，并发送给模型总结为更精简的剧情单元
- 相邻窗口重叠 2 个 document
- 步长为 6 个 document
- 例：`0-7`、`6-13`、`12-19`

每个压缩单元输出：

```json
{
  "unit_id": "string",
  "source_doc_ids": [],
  "overlap_doc_ids": [],
  "start_document_title_index": 0,
  "end_document_title_index": 0,
  "unit_summary": "string",
  "continuity_hooks": [],
  "boundary_events": [],
  "major_character_state_changes": [],
  "relationship_movements": [],
  "world_or_rule_reveals": [],
  "uncertainty_notes": []
}
```

压缩要求：

- 压缩单元必须由模型基于窗口整体理解生成，保留主线事件、人物状态变化、关系推进、设定揭示、伏笔与转折边界
- 重叠 document 的作用是强化单元之间的剧情联系；后续合并时 SHOULD 去重，但不得简单丢弃重叠单元里的边界事件
- 压缩幅度不应过大；如果压缩后的 `plot_summary_units` 仍超过预算，系统 SHOULD 再做一层轻量合并摘要，而不是回退到读取原文

输出：

- `source_arc_map.json`
- 可选 `source_arc_map.md`

该 Agent / Service 负责：

- 从全局视角记录源作品中相对独立的故事篇章
- 给每个篇章标注 `source_arc_role`、核心事件、人物线、设定揭示、过渡说明与后续铺垫
- 识别日常对话、人物内心、生活状态、关系缓慢推进等低冲突但高铺垫价值的缓冲篇章
- 在输入超长时消费 `plot_summary_units`，并利用重叠窗口保留篇章边界处的剧情联系
- 产出 `committed` 级篇章功能和节奏判断，并可用于把相关章节摘要或故事大纲片段从 `provisional` 升级为 `committed`
- 为创作知识库层沉淀 `NarrativeStructurePattern` / `ArcPatternCard` 提供事实型源结构输入

该 Agent / Service 不负责：

- 重写章节摘要
- 直接更新人物档案
- 直接生成续写正文
- 在常规路径中回读全书原文
- 直接生成 Writer 的新书大纲或可迁移剧情结构 pattern

推荐存储：

- 最小实现可先保存到 `.memory/arcs/<book_id>.source_arc_map.json`
- 后续如需检索和版本化，再增加 `source_arc_maps` 表或写入 `book_assets.source_arc_map_path`

### 10.7 Narrative Structure Pattern Handoff

`SourceArcMap` 生成后，创作知识库层 SHOULD 可选择运行结构模式沉淀流程，输入：

- `SourceArcMap`
- 章节摘要与故事大纲
- 重要人物线与关系变化摘要

输出由创作知识库层拥有，例如：

- `NarrativeStructurePattern`
- `ArcPatternCard`

这些 pattern SHOULD 描述可迁移结构特征，而不是源作品事实复述，例如：

- 前若干章节主要承担日常、情绪状态和关系基线建立
- 某人物或配角登场后，经过若干章节完成身份揭示、关系试探和功能位绑定
- 冲突升级前先用过渡章节缓冲节奏并埋设未决问题
- 某个 document/chapter 之后主题、场景或冲突焦点明显切换，可视为新篇章起点

Memory 层只提供事实输入与可选定位上下文；pattern 的存储、检索、排序和 Writer 侧消费策略不在本设计稿内实现。

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

### 11.3 建议新增

- `ContextAssemblyService`
- `PlotSummaryUnitCompressionService`
- `SourceArcMappingService`
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
2. 为章节摘要和故事大纲 schema 增加 `provisional / committed` 状态、`evidence_window` 与 `target_range`
3. 拆出 Character Evidence Agent 的 batch 输入与 batch-level 输出 contract
4. 新增 Memory Candidate Agent，汇合章节摘要和人物证据结果，输出默认 `provisional` 的大纲更新候选
5. 新增 Source Arc Mapping 后处理，基于完整章节摘要和大纲生成 `SourceArcMap`；若章节梗概超过预算，先通过重叠窗口压缩为 `plot_summary_units`
6. 新增窗口级摘要 / 大纲定稿流程，用较大的 `evidence_window` 复核较小的 `target_range`，并把结果升级为 `committed`
7. 新增 `ContextAssemblyService`，先打通续写主 Agent 的事实上下文输入，并能在必要时输出相关 `SourceArcMap` 片段和 memory 状态
8. 拆分 `_persist_batch()` 为多个 update service
9. 强化人物档案 merge 策略
10. 强化世界观 section 合并
11. 强化大纲压缩与章节关联

## 13. 最小测试清单

- 精读阶段可从 `reading_progress` 继续
- `document_character_mentions` 证据过滤可拦截伪人名
- Character Evidence Agent 可把多个 document 拼接为同一个 batch
- Character Evidence Agent 输出不依赖逐 `doc_id`、原文连续子串或 offset
- Character Evidence Agent 能输出发言判断、人物性证据、行动状态证据与关系证据
- Memory Candidate Agent 能基于 Character Evidence 结果过滤低置信人物候选
- `documents.character_keywords_json` 会被精读结果回写
- `character_profiles` 会合并章节更新
- `chapters` 会保存摘要、人物、世界观、大纲增量
- 新 close-read 写入的章节摘要和大纲增量默认是 `provisional`
- 窗口级复核可基于较大的 `evidence_window` 将较小的 `target_range` 标记为 `committed`
- 对同一章节或大纲范围，`committed` 结果优先于旧的 `provisional` 结果
- 世界观 Markdown 与 world summary 会更新
- 故事大纲 Markdown 会更新
- close-read 完成后可基于章节摘要、故事大纲、人物档案和世界观概要生成 `SourceArcMap`
- 当章节/文档级故事梗概超过配置阈值时，可按 8 document window / 2 document overlap 压缩为 `plot_summary_units` 后再生成 `SourceArcMap`
- `SourceArcMap` 能标注源作品中的主线推进、过渡缓冲、日常关系、设定揭示、高潮和收束等篇章功能
- `SourceArcMap` 的篇章功能和节奏判断可作为 `committed` 级结构信息
- `ContextAssemblyService` 能在需要源作品位置定位时输出相关 `SourceArcMap` 片段，并显式标注上下文中的 `provisional` / `committed` 状态
- KB 层可基于 `SourceArcMap` 沉淀 `NarrativeStructurePattern` / `ArcPatternCard`，Writer 主要消费这些可迁移结构模式
- `ContextAssemblyService` 新增后应有独立 contract 测试
