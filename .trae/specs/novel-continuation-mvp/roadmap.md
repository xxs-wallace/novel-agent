# 小说续写系统跨模块执行路线图

## 1. 目的
本路线图用于统一三层任务清单的执行顺序：

- [novel-continuation-mvp/tasks.md](.trae/specs/novel-continuation-mvp/tasks.md)
- [creative-knowledge-base/tasks.md](.trae/specs/creative-knowledge-base/tasks.md)
- [narrative-memory-context/tasks.md](.trae/specs/narrative-memory-context/tasks.md)

目标不是重新定义需求，而是回答：

- 哪些任务应该先做
- 哪些任务可以并行
- 哪些任务必须等 contract 稳定后再做
- 如何在保留旧 MVP 可运行的前提下，渐进迁移到三层架构

## 2. 当前状态总览

### 2.1 已稳定可用

- 主层：
  - `documents + SQLite/FTS` 基线
  - 粗读 Agent
  - 旧 Runner
  - 基础检索工具
  - MVP 子集版 `ScenePlan`
  - `check_continuity`
- Memory 层：
  - 章节聚合与精读主流程
  - `chapters`
  - `character_profiles`
  - `reading_progress`
  - 世界观 / 大纲 Markdown 更新
  - 人物证据校验

### 2.2 已有基础但未模块化

- 轻量标签
- 旧 `ScenePlan`
- 精读结果的持久化更新链路
- 旧测试与旧 Runner

### 2.3 尚未正式落地

- `fragment_cards`
- `fragment_clusters`
- 近重复检测
- 代表片段选择
- `SceneBrief`
- 粗筛 contract
- rerank contract
- `ContextAssemblyService`
- 新总装配层

## 3. 总体策略

### 3.1 核心原则

- 先打通 **新输入 / 输出 contract**，再做复杂能力。
- 先复用已有 `documents` 与 Memory 结果，不推倒已有闭环。
- 创作知识库层先做 **SQLite-only** 的最小可运行版，不一开始引入更复杂存储。
- 主层先保留旧 Runner 外壳，只替换内部编排顺序。

### 3.2 优先级判断原则

优先级最高的任务应满足至少一个条件：

- 是多个模块的公共阻塞项
- 可以显著降低后续返工
- 能尽快形成新的最小闭环

## 4. 推荐执行阶段

### Phase 0: 文档分层稳定化

目标：

- 确保三层 spec / design / tasks 已形成稳定边界
- 确保主层不再继续吸收子模块细节

状态：

- 已完成

## 5. Phase 1: 先打通 Contract

### 5.1 目标

- 不先追求完整功能
- 先把三层之间的输入输出固定下来

### 5.2 必做任务

#### 主层

- [tasks.md Task 7](.trae/specs/novel-continuation-mvp/tasks.md)
- [tasks.md Task 8](.trae/specs/novel-continuation-mvp/tasks.md)

#### 创作知识库层

- [tasks.md Task 2](.trae/specs/creative-knowledge-base/tasks.md)
- [tasks.md Task 8](.trae/specs/creative-knowledge-base/tasks.md)
- [tasks.md Task 10](.trae/specs/creative-knowledge-base/tasks.md)

#### Memory 层

- [tasks.md Task 2](.trae/specs/narrative-memory-context/tasks.md)
- [tasks.md Task 3](.trae/specs/narrative-memory-context/tasks.md)
- [tasks.md Task 4](.trae/specs/narrative-memory-context/tasks.md)
- [tasks.md Task 6](.trae/specs/narrative-memory-context/tasks.md)
- [tasks.md Task 10](.trae/specs/narrative-memory-context/tasks.md)
- [tasks.md Task 11](.trae/specs/narrative-memory-context/tasks.md)

### 5.3 阶段产物

- `FragmentCard` / `FragmentCluster` schema
- `SceneBrief` schema
- 事实型上下文包 schema
- 主层到子层的稳定 contract
- 旧 `ScenePlan` 到新 `SceneBrief` 的映射说明

### 5.4 为什么先做这一阶段

- 如果 contract 不先固定，后续：
  - repo 会返工
  - prompt 会返工
  - 主层总装配也会返工

## 6. Phase 2: 创作知识库最小闭环

### 6.1 目标

- 尽快让创作知识库层从“纯设计”变成“可用最小系统”
- 先做到可离线建库、可在线检索、可输出 1-4 段候选

### 6.2 必做任务

- [creative-knowledge-base Task 3](.trae/specs/creative-knowledge-base/tasks.md)
- [creative-knowledge-base Task 4](.trae/specs/creative-knowledge-base/tasks.md)
- [creative-knowledge-base Task 5](.trae/specs/creative-knowledge-base/tasks.md)
- [creative-knowledge-base Task 6](.trae/specs/creative-knowledge-base/tasks.md)
- [creative-knowledge-base Task 7](.trae/specs/creative-knowledge-base/tasks.md)
- [creative-knowledge-base Task 11](.trae/specs/creative-knowledge-base/tasks.md)
- [creative-knowledge-base Task 12](.trae/specs/creative-knowledge-base/tasks.md)
- [creative-knowledge-base Task 14](.trae/specs/creative-knowledge-base/tasks.md)

### 6.3 最小可运行目标

- 从 `documents` 生成 `fragment_cards`
- 对近重复桥段生成 `fragment_clusters`
- 支持 `SceneBrief -> 粗筛 -> rerank`
- 最终输出 `1-4` 段参考片段

### 6.4 不必在这一阶段完成的内容

- 更复杂的 embedding 检索
- 高级去重模型
- 多向量检索引擎

## 7. Phase 3: Memory 层模块化补强

### 7.1 目标

- 在不破坏现有 close-read 闭环的前提下，把 Memory 层从“能跑”升级到“可装配”

### 7.2 必做任务

- [narrative-memory-context Task 5](.trae/specs/narrative-memory-context/tasks.md)
- [narrative-memory-context Task 7](.trae/specs/narrative-memory-context/tasks.md)
- [narrative-memory-context Task 8](.trae/specs/narrative-memory-context/tasks.md)
- [narrative-memory-context Task 9](.trae/specs/narrative-memory-context/tasks.md)
- [narrative-memory-context Task 12](.trae/specs/narrative-memory-context/tasks.md)

### 7.3 阶段重点

- 拆出 `Memory Update Agent / services`
- 新增 `ContextAssemblyService`
- 固化续写主 Agent 消费的事实上下文包

### 7.4 阶段收益

- 续写主 Agent 不再直接依赖 close-read 内部实现细节
- 后续可以单独调试人物档案、世界观、大纲和上下文裁剪

## 8. Phase 4: 主层重构与新闭环接线

### 8.1 目标

- 保留旧 Runner 外壳
- 接上两个子层的新输出
- 打通三层新闭环

### 8.2 必做任务

- [novel-continuation-mvp Task 9](.trae/specs/novel-continuation-mvp/tasks.md)
- [novel-continuation-mvp Task 12](.trae/specs/novel-continuation-mvp/tasks.md)

### 8.3 新编排顺序

```text
读锚点
-> 最近窗口
-> SceneBrief / 兼容 ScenePlan
-> 创作知识库检索
-> Memory 上下文装配
-> 写作
-> 一致性检查
-> 产物落盘
```

### 8.4 这一阶段要特别避免

- 直接删掉旧 Runner
- 直接删掉旧测试
- 在主层重新复制子模块逻辑

## 9. Phase 5: 测试迁移与收口

### 9.1 目标

- 保留旧路径回归能力
- 增加新路径验收能力

### 9.2 必做任务

#### 主层

- [novel-continuation-mvp Task 10](.trae/specs/novel-continuation-mvp/tasks.md)

#### 创作知识库层

- [creative-knowledge-base Task 15](.trae/specs/creative-knowledge-base/tasks.md)

#### Memory 层

- [narrative-memory-context Task 13](.trae/specs/narrative-memory-context/tasks.md)

### 9.3 验收标准

- 旧 MVP 直连路径仍能跑
- 新三层路径能跑通
- 子层任一缺失时，主层有明确降级或报错路径

## 10. 可并行工作流

### Workstream A: 创作知识库

可独立并行：

- `Task 2-7`
- `Task 11-12`
- `Task 14-15`

前置依赖：

- 只需要 `documents` 基线稳定

### Workstream B: Memory 模块化

可独立并行：

- `Task 2-9`
- `Task 12-13`

前置依赖：

- 现有 close-read 基线已可运行

### Workstream C: 主层总装配

建议后置：

- `Task 7-10`
- `Task 12`

前置依赖：

- 至少要等创作知识库层和 Memory 层 contract 稳定

## 11. 关键阻塞点

### Blocker 1: `SceneBrief` 未落地

影响：

- 创作知识库在线检索无法真正进入新路径
- 主层也无法切换到新总装配

### Blocker 2: `ContextAssemblyService` 未落地

影响：

- Memory 层虽能更新长期记忆，但续写主 Agent 还拿不到标准化事实上下文包

### Blocker 3: `fragment_cards` / `fragment_clusters` 未落表

影响：

- 创作知识库层无法形成离线索引闭环

## 12. 推荐第一批实现

如果你现在要开始真正写代码，我最推荐先做这一批：

1. `creative-knowledge-base Task 2`
2. `creative-knowledge-base Task 3`
3. `creative-knowledge-base Task 8`
4. `narrative-memory-context Task 10`
5. `novel-continuation-mvp Task 8`

原因：

- 这 5 个任务共同决定了三层之间的接口是否稳定
- 一旦接口稳定，后面的实现可以分给多个 Agent 并行

## 13. 推荐第二批实现

接口稳定后，进入真正可运行闭环：

1. `creative-knowledge-base Task 4`
2. `creative-knowledge-base Task 5`
3. `creative-knowledge-base Task 11`
4. `creative-knowledge-base Task 12`
5. `narrative-memory-context Task 12`
6. `novel-continuation-mvp Task 9`

## 14. 推荐第三批实现

最后做质量与收口：

1. `creative-knowledge-base Task 6-7`
2. `narrative-memory-context Task 8-9`
3. `novel-continuation-mvp Task 10`
4. 各层测试任务

## 15. 里程碑定义

### Milestone A: Contract Frozen

完成标志：

- `FragmentCard`
- `FragmentCluster`
- `SceneBrief`
- 事实上下文包
- 主层跨层 contract

### Milestone B: Retrieval Vertical Slice

完成标志：

- `documents -> fragment_cards -> SceneBrief -> 粗筛 -> rerank`

### Milestone C: Memory Assembly Vertical Slice

完成标志：

- `documents -> close-read -> memory updates -> context assembly`

### Milestone D: Layered End-to-End

完成标志：

- `documents -> creative KB -> memory context -> writer`

## 16. 对当前 checklist 的建议

当前 [checklist.md](.trae/specs/novel-continuation-mvp/checklist.md) 主要反映旧 MVP 已完成项。建议：

- 保留它作为“旧闭环验收记录”
- 不再把新三层架构的里程碑继续追加进去
- 新架构的推进以本 `roadmap.md` 和三个 `tasks.md` 为准
