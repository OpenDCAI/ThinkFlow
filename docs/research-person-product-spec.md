# ThinkFlow Research Person 产品规格

> 版本：v0.1
>
> 状态：A+B 第一阶段产品基线
>
> 适用分支：`research-person`
>
> 本文描述 ThinkFlow Research Person 的目标、核心概念、交互规则和分阶段验收范围。它是产品与实现之间的共同契约；实现可以逐步替换底层解析器、模型或 Skill，但不应改变这里定义的用户可见语义。

## 1. 产品定位

ThinkFlow Research Person 是一个以 Paper 阅读为入口、以研究空间为组织边界、以长期 Memory 为沉淀方式的个人研究工作台。它不是单纯的 PDF 阅读器，也不是只返回一段摘要的 QA 页面。

用户可以：

- 导入 Paper、Blog、Project、Technical Report 等研究资料；
- 在 PDF/正文、图表和 AI Chat 之间切换，逐步理解一项工作；
- 在一个研究空间内比较多篇资料、整理 Idea、记录研究缺口；
- 让多轮 QA 自动形成可编辑的摘要和知识点；
- 点击确认后，将可靠内容沉淀为长期 Memory；
- 在之后的 Paper 或 Space 对话中检索这些 Memory；
- 以后再通过 Global Research 跨研究空间总结演进、发现共同短板并形成研究产物。

### 1.1 核心价值

1. **理解而非速读**：回答应能回到正文、页码、章节、公式、表格或图像证据。
2. **连续性而非孤立问答**：同一篇资料的多轮对话共同形成 Paper 级 QA Summary，并保留完整 history。
3. **个人语境而非通用知识库**：系统同时保存原文事实、模型总结、用户理解和未确认线索，后续回答区分可信度。
4. **空间化研究**：Paper 是全局唯一资源，研究空间通过 Link 组织主题，避免重复导入和重复解析。
5. **渐进式自动化**：普通导入、关联和草稿更新由 Codex/MCP 执行；删除、确认长期记忆等高风险操作由 UI 点击完成。

### 1.2 非目标

第一阶段不要求：

- 一次性实现跨空间 Global Summary 全部能力；
- 强制安装某个固定翻译服务或固定 Paper 搜索服务；
- 用旧的通用 RAG 流程替代 Codex sandbox 对话；
- 自动把所有模型输出当成已确认事实；
- 为每一种 Blog、Project 或数据库建立独立阅读产品；
- 通过 Chat 文本确认删除或确认长期 Memory。

## 2. 研究层级与 Memory

系统有三个研究层级。层级决定默认检索边界，不代表资源只能存在一个层级。

```text
Paper / Resource Level
  └── 单篇资源的 Summary、QA、证据、对话和 Memory

Research Space Level
  └── 一个主题内的资源、对话、Wiki、Idea、Space Summary

Global Research Level
  └── 跨空间的分析、Global Summary、总览文章、知识图谱和研究缺口
```

### 2.1 Paper / Resource Level

每个 Research Resource 有一个全局唯一 ID。资源可以是：

- `paper`：论文、预印本、期刊或会议论文；
- `blog`：博客、长文、解读文章；
- `project`：项目主页、GitHub 仓库、README 或技术文档；
- `report`：技术报告、白皮书或其他研究报告。

所有类型进入统一的导入、解析、Chat、Summary、QA Summary 和 Memory 流程。UI 通过来源类型标签区分它们，避免把 Blog 的观点默认为 Paper 的实验事实。

### 2.2 Research Space Level

研究空间是一个主题边界，例如“`SWE 演进`”“`Agent Evaluation`”。空间包含：

- 资源 Link（Paper/Blog/Project/Report 的关联）；
- 空间内 Chat；
- Paper Chat 的引用关系；
- Wiki 和 Idea；
- Space Summary、关系图和 Research Gaps；
- 空间专属标签、阅读重点和备注。

同一个全局资源可以被多个空间引用，但每个空间的关联备注和主题角色独立保存。

### 2.3 Global Research Level

全局研究助手不默认属于某一个空间。它用于：

- 批量添加资源并创建或关联研究空间；
- 根据问题推荐相关研究空间；
- 在用户调整范围后执行跨空间分析；
- 生成带版本的 Global Synthesis。

Global Summary 默认只使用已确认 Memory。执行前可以打开“包含草稿 Memory”，此时草稿仅作为带有“探索性线索 · 尚未确认”标记的候选证据。

## 3. 全局唯一 Resource 与 Space Link

### 3.1 数据关系

```text
ResearchResource
  id, type, title, canonical_url, metadata, processing_state
  source_versions[], summary, qa_summary, memories[]

ResearchSpace
  id, name, description, settings, summary_drafts, summaries[]

SpaceResourceLink
  space_id, resource_id, role, tags, note, created_at
```

`ResearchResource` 只保存一份原始文件、解析产物、基础元数据和资源级 Summary。`SpaceResourceLink` 保存该资源在某个空间中的角色，例如“评测范式转折点”“对比基线”或“实现参考”。

### 3.2 入口与交互

研究首页提供独立的全局资源库入口。研究空间提供快捷入口，但不会创建另一套导入系统。

```text
研究首页
  └── 资源库
      ├── 上传 PDF
      ├── arXiv URL / arXiv ID
      ├── DOI
      ├── Paper Title
      ├── Blog / Project URL
      └── 批量导入

研究空间
  └── 添加资料
      ├── 从资源库选择
      ├── 导入新资源
      └── 批量添加
```

从空间内导入时，当前空间默认勾选，但可以追加其他空间或暂不加入空间。导入结束后，用户可以立即进入 Reader 或继续批量整理。

全局助手也必须支持自然语言动作，例如：

```text
把这 12 篇 Paper 加入 SWE 演进空间。
新建一个 Agent Evaluation 空间，并把这些链接导入进去。
把 Paper A 同时加入 SWE 演进和 Code Reasoning。
```

这些动作由研究 MCP Function 执行，前端展示实际执行状态和结果。

### 3.3 导入和重复资源规则

匹配优先级如下：

1. arXiv ID；
2. DOI；
3. 规范化 URL；
4. PDF 内容哈希；
5. 标题、第一作者和年份组合。

高置信度匹配时自动复用已有资源，不重复上传、解析或生成基础 Summary。低置信度匹配时显示候选资源和匹配依据，由用户选择复用或创建新资源。原则上不因标题相似就静默合并。

复用资源只建立新的 `SpaceResourceLink`，不会删除或覆盖原有空间内备注。

## 4. 版本、发表状态与元数据

### 4.1 Research Work 与 Source Version

预印本和会议发表版默认归入同一个 Research Work。会议版成为主版本，arXiv 版本保留为历史版本。

```text
Research Work
  ├── canonical metadata
  ├── current_version: ACL 2025 published
  └── source_versions
      ├── arXiv v1
      ├── arXiv v2
      └── ACL 2025 published
```

主版本规则：

- Reader、默认检索、Paper Summary 和 QA Summary 以会议版为准；
- 会议版出现后，系统自动重新解析正文、图表和上下文并生成新的 Summary 草稿；
- arXiv 版本的原始 Summary/Memory 不删除，降级为历史来源；
- 旧版本默认不参与回答，只有用户查看版本历史或明确比较时才加载；
- 会议版和预印本存在差异时，当前结论以会议版自动覆盖；历史结论标记为“已被最终版本 supersede”。

### 4.2 元数据

资源导入后应尽量补全：标题、作者、作者机构、摘要、关键词、DOI、arXiv ID、来源 URL、发布日期、会议/期刊、录用或发表状态、版本号。元数据缺失不阻塞原文阅读，但 UI 要标记缺失字段。

## 5. Paper 阅读闭环（A）

第一阶段必须先打通单篇 Paper 的端到端闭环：

```text
导入资源
  ↓
选择阅读源和默认深度
  ↓
自动 skim
  ↓
PDF / 正文 / 图表 + Codex Chat
  ↓
生成 Paper Summary 与 QA Summary 草稿
  ↓
通过 Chat 修改草稿
  ↓
生成 Atomic Memory
  ↓
在卡片上点击确认
  ↓
进入 Space Chat 并被检索引用
```

### 5.1 阅读源策略

单篇资源支持：

- `latex`：优先结构化章节、公式、引用、算法和 caption；
- `pdf`：优先保留版式、图表和视觉信息；
- `both`：同时准备 LaTeX/正文和 PDF/视觉资产。

arXiv 资源默认优先获取 LaTeX Source，并渲染或保留 PDF 用于页码、图表和视觉证据。没有 LaTeX Source 时回退 PDF。DOI、Title、Blog 和 Project 资源根据可用来源选择 HTML、Markdown、PDF 或原始页面。

批量导入时由用户为整个批次选择策略，单篇导入完成后可以覆盖：

```text
优先 LaTeX，PDF 用于图表
只处理 PDF
同时准备 LaTeX 和 PDF
```

### 5.2 阅读深度

每篇资源有一个默认阅读深度：`skim`、`standard` 或 `deep`。用户可以在资源详情中修改，Codex 可以根据问题自动升级并说明原因：

- `skim`：快速理解主题、贡献、结果和初步局限；
- `standard`：按章节理解方法、实验和主要证据；
- `deep`：完整分析公式、图表、消融、失败案例、局限和开放问题。

导入后自动执行一次 `skim`，不阻塞用户进入 Reader。涉及公式、图表、实验细节或跨版本比较时，可升级到 `standard`/`deep`。

### 5.3 多轮对话

一个资源可以有多个对话，完整历史必须保留。可以建立：

- 方法理解对话；
- 实验复核对话；
- 公式或图表对话；
- 翻译/术语对话；
- 与其他 Paper 的比较对话。

一个对话也可以绑定多个 Resource，适合比较阅读。Paper 级 QA Summary 默认从该资源的全部相关对话合并生成，而不是为每个对话建立互相割裂的正式 Paper Summary。

## 6. Summary、QA Summary 与 Atomic Memory

### 6.1 Paper Summary

Paper Summary 描述资源本身，至少包括：

- TL;DR；
- 研究问题与动机；
- 核心方法；
- 主要结果；
- 局限与适用边界；
- 值得继续追问的问题；
- 读取深度和生成时间。

Blog、Project、Report 使用同一套摘要契约，但标题可按类型显示为 Article Summary、Project Overview 或 Report Summary。

### 6.2 QA Summary

QA Summary 描述“用户和资源讨论过什么”，默认采用后台草稿、阶段结束正式化的策略：

- 每轮回答后后台更新草稿，不打断当前 Chat；
- 检测到一段阅读结束、切换资源或用户要求“整理一下”时，生成正式草稿版本；
- 用户认为内容不准确时，可以继续在 Chat 中给出修改 query；
- Chat 只负责提出修改和重新生成草稿，不负责确认长期记忆；
- Paper 级 QA Summary 合并全部相关对话的关键问答；
- 冲突结论整理为“当前共识 / 冲突观点 / 尚未解决”，不静默覆盖旧内容。

QA Summary 至少保留：

- 关键问题；
- 已确认结论；
- 仍不清楚或有争议的地方；
- 用户个人理解或笔记；
- 关联对话、消息和证据。

### 6.3 Atomic Memory

长期 Memory 同时保存人类可读的 Summary 卡片和可检索的原子知识点。

```text
Paper Memory Card
  ├── Paper Summary
  ├── QA Summary
  ├── Key Takeaways
  ├── Open Questions
  └── Personal Notes

Atomic Memory
  ├── Claim
  ├── Finding
  ├── Limitation
  ├── Question
  └── Relation
```

每条 Atomic Memory 必须带：来源 Resource、来源版本、来源对话/消息、页码或章节（若可用）、类型、状态、生成时间、revision 和所属研究空间。

## 7. Memory 状态与确认机制

Memory 分为两种状态：

- **草稿 Memory**：自动生成或 Chat 修改后的内容；可以被检索，但回答必须标注来源和“尚未确认”；
- **已确认 Memory**：用户点击确认后进入长期可信 Memory，可作为后续 Space/Global 正式分析的主要依据。

确认不通过 Chat 完成。界面提供：

```text
Paper QA Summary · 草稿
[确认整张记忆]

Atomic Memories
☑ 核心方法是分层路由
☑ 实验显示推理成本下降
☐ 可能依赖特定数据分布
☐ 与 Paper B 存在相似性
```

行为规则：

- 点击“确认整张记忆”时，选中知识点一起升级；
- 展开后可以逐条确认、取消或编辑；
- 未确认内容保留在草稿区，不丢失；
- 确认、编辑、合并和删除都创建 revision；
- Paper Summary 和 QA Summary 的草稿修改可以由 Chat query 触发；
- 删除已确认 Memory 必须通过确认卡片完成。

## 8. 证据展示与 Markdown/公式渲染

回答正文保持自然阅读，不在每句前插入文件名和页码注释。回答下方显示可展开的“依据”区域：

```text
依据 3 处 · 论文原文
  - Method / 第 6 页 · 原文片段
  - Experiments / 第 9 页 · 原文片段
  - Figure 2 / 第 11 页 · 图表说明
```

点击证据后：

- PDF 跳转到对应页；
- 高亮文本或图表区域（有坐标时）；
- 显示章节、版本和原文片段；
- 对 Blog/Project 显示 URL、段落或标题锚点。

证据作为结构化字段保存，不混入 Summary 正文。Markdown 使用完整渲染器，至少支持标题、列表、表格、代码块、引用、链接、脚注和 GFM；数学公式使用 KaTeX/MathJax 渲染，支持行内 `$...$` 与块级 `$$...$$`，渲染失败时保留原始源码并显示降级状态。

## 9. Skill、Vision 与 Codex 执行状态

Codex 可以根据问题自主选择项目 Skill。`read-paper`、review、translation 或 Vision Skill 以 Description 形式提供，不强制每次调用。系统必须记录真实执行事件，不能仅凭静态提示词显示“已使用”。

前端默认显示紧凑状态条，支持展开详细事件：

```text
本次回答
已读取 Paper 上下文 · 52 页
已使用 read-paper Skill
已分析 Figure 2
已生成回答
```

执行中显示阶段：

```text
正在读取 Paper 原文
正在检查相关章节
正在调用 read-paper Skill
正在分析图表
正在生成回答
```

展开后至少展示：

- Skill 名称、版本和是否实际调用；
- 阅读深度及自动升级原因；
- 读取的章节、页数或上下文来源；
- Vision 处理的图表；
- 检索到的 Space Memory/Resource；
- Codex sandbox/thread 状态；
- 完成、失败、取消和超时状态。

状态必须单调且真实：只有收到完成事件后才能显示完成；不得出现“回复已完成”但前序阶段仍在转圈的矛盾状态。Skill 未调用时明确显示“本次未使用 Skill”，不能伪造。

## 10. Research Space Chat 与 Space Summary（B）

Space Chat 不绑定单一 Paper 时，根据问题自动检索当前空间的：

- Paper、Blog、Project、Report；
- 已确认 Memory；
- 草稿 Memory（默认可参与，但必须标注）；
- Wiki；
- Ideas；
- Space Summary 草稿。

不把空间内所有全文无差别塞进上下文。回答下方展示实际使用来源和 Memory 状态。用户可以在 Chat 中要求限定范围，例如“只看 2024 年后 Paper”“不要使用草稿”“只比较两个资源”。

### 10.1 Space Summary

Space Summary 后台维护草稿，需要时生成正式版本，并保留版本和来源。轻量完整产物包含：

1. 空间总览文章：主题、时间线、方法路线、当前共识和争议；
2. 资料关系图：Paper/Resource、Idea、Memory 之间的高置信度关系；
3. Research Gaps：带来源的缺口、开放问题和候选 Idea。

Space Summary 的正式版本默认只使用已确认内容；草稿关系可以进入“候选关系/探索性线索”，但不能伪装成确定事实。

## 11. Global Summary 与跨空间研究（C）

Global Research 是第二阶段能力。全局助手先根据问题推荐相关研究空间，用户可以在执行前添加或移除空间、设置时间范围、选择是否包含草稿 Memory。

正式 Global Synthesis 同时生成：

- 总览文章；
- Knowledge Graph；
- Research Gaps 列表；
- Evidence Links 和本次 Source Scope。

每次正式分析生成不可破坏的带版本产物，用户可以选择某一版作为当前版本。当前版本可以同步为全局 Wiki 总览。新资料不触发昂贵的全局重写，只更新后台索引和草稿；用户明确发起跨空间分析后才生成正式版本。

发现新的 Idea 或 Gap 时生成候选卡片，用户点击后选择保存到当前空间、其他空间、新空间或全局候选区。Codex 不自动把候选内容写成正式 Idea/Wiki。

## 12. 首页信息架构

首页同时展示四类入口和最近活动：

```text
研究首页
  ├── 全局研究助手输入框
  ├── 最近研究空间
  ├── 最近资源（Paper / Blog / Project / Report）
  ├── 最近 Paper / Space / Global Summary
  └── 全局资源库入口
```

全局助手支持自然语言创建空间、导入资源、批量关联和跨空间分析。进入二级研究空间后不重复放置“新建研究空间”主入口；切换空间回到首页完成。

## 13. 导入、删除与高风险操作

操作分为普通写入和高风险写入：

```text
普通写入：创建空间、导入资源、建立 Space Link、修改草稿、创建候选 Idea
  → Codex/MCP 直接执行，显示状态和结果

高风险写入：删除空间、删除全局资源、删除对话、删除已确认 Memory、批量移除
  → 显示确认卡片，用户点击确认后执行
```

从空间移除资源只删除 `SpaceResourceLink`，不删除全局 Resource、原始文件、Summary 或 Memory。资源库中的“删除资源”才会删除全局实体及其派生数据，并应显示影响范围和可恢复/审计信息。

## 14. A+B 第一阶段范围

### 14.1 必须交付

1. 全局唯一 Resource 与 `SpaceResourceLink` 数据模型；
2. 首页资源库和研究空间选择入口；
3. PDF/arXiv/Title/URL 导入和基础元数据补全；
4. LaTeX/PDF/both 阅读源策略与批量策略；
5. `skim/standard/deep` 默认深度和问题触发升级；
6. PDF/正文/图表 Reader 与 Codex Chat；
7. 多对话 history 和多资源绑定；
8. Paper Summary、QA Summary 草稿与 Chat query 修改；
9. Atomic Memory 生成、整卡/逐条确认和 revision；
10. 结构化依据面板、页码/章节跳转和 KaTeX Markdown 渲染；
11. 真实 Skill/Vision/Codex 状态条；
12. Space Chat 自动检索当前空间资料和 Memory；
13. Space Summary、关系图和 Research Gaps 的轻量版本；
14. 普通写入直达、高风险删除点击确认。

### 14.2 第一阶段明确不做

- 完整跨空间 Global Synthesis UI；
- 自动翻译服务的固定实现；
- 所有格式的高级版面还原；
- 自动确认长期 Memory；
- 无来源、无状态的“万能摘要”。

## 15. 后续 C 阶段范围

第二阶段在 A+B 稳定后实现：

1. Global Research Chat 的空间推荐和范围调整；
2. Global Summary 版本、总览文章、Knowledge Graph、Research Gaps；
3. 跨空间已确认 Memory 检索和草稿开关；
4. 候选 Idea/Gap 卡片及点击归档；
5. 资源版本比较、会议版差异追踪和历史证据视图；
6. 选配翻译、日程、任务等 Skill/MCP 外部能力；
7. 全局 Wiki 与 Summary 的双向引用和编辑。

## 16. 实现建议：实体、事件与 API

### 16.1 核心实体建议

```text
research_resources
research_resource_versions
research_spaces
space_resource_links
research_conversations
conversation_resource_links
paper_summaries
qa_summary_revisions
atomic_memories
memory_evidence
space_summaries
global_syntheses
research_ideas
research_gaps
skill_execution_events
```

具体存储可以继续使用现有 SQLite 元数据、Markdown 产物和 sandbox 目录；实体语义不应依赖某一个解析器或模型供应商。

### 16.2 建议 API 能力

```text
GET/POST  /api/v1/research/resources
POST      /api/v1/research/resources/import
GET       /api/v1/research/resources/{resource_id}
GET/POST  /api/v1/research/spaces/{space_id}/resources
DELETE    /api/v1/research/spaces/{space_id}/resources/{resource_id}

GET/POST  /api/v1/research/resources/{resource_id}/conversations
POST      /api/v1/research/conversations/{conversation_id}/turns  (SSE)
GET       /api/v1/research/conversations/{conversation_id}/events

GET       /api/v1/research/resources/{resource_id}/summary
POST      /api/v1/research/resources/{resource_id}/summary/revise
GET       /api/v1/research/resources/{resource_id}/memories
POST      /api/v1/research/memories/{memory_id}/confirm
PATCH     /api/v1/research/memories/{memory_id}

GET       /api/v1/research/spaces/{space_id}/chat/context
GET       /api/v1/research/spaces/{space_id}/summary
POST      /api/v1/research/spaces/{space_id}/summary/generate
GET       /api/v1/research/global/suggestions
POST      /api/v1/research/global/synthesis
```

删除类 API 必须返回影响范围并建立 pending confirmation；普通 MCP 写函数与 REST 写接口共享同一个执行器，避免两套状态逻辑。

### 16.3 建议事件

```text
resource.import.started / completed / failed
resource.parse.started / completed / failed
paper.skim.started / completed
codex.thread.created / resumed
skill.started / completed / skipped / failed
vision.started / completed / failed
qa_summary.draft.updated
memory.created / revised / confirmed / deleted
space.summary.draft.updated
action.pending / confirmed / cancelled / completed / failed
```

前端状态条以这些事件为唯一事实来源，不能通过超时或固定延迟猜测“已完成”。

## 17. 验收标准

### 17.1 Paper 闭环

- 可以通过 PDF、arXiv ID/URL、DOI、Title 或研究链接导入资源；
- 导入后显示元数据补全结果和解析状态；
- 自动生成 skim 草稿，不阻塞 Reader；
- Reader 能显示正文、公式、表格、图像和页码映射；
- Chat 回答能使用正确资源上下文，并显示真实 Skill/Vision 状态；
- 公式、列表、表格和代码 Markdown 正确渲染；
- 回答正文无散乱的文件名/页码前缀，依据可展开并能跳转；
- 多轮 QA 能生成可编辑的 Paper 级 QA Summary；
- Chat query 可以修改草稿，修改有 revision；
- Atomic Memory 可以整卡或逐条确认，确认后可检索；
- 删除对话、Memory 或资源显示确认卡片，取消不会产生破坏性副作用。

### 17.2 Space 闭环

- 同一 Resource 可以加入两个或多个研究空间而不重复解析；
- 从空间移除只解除 Link，不删除全局资源；
- Space Chat 默认检索当前空间，回答显示实际来源；
- 草稿 Memory 参与时明确标注，正式 Space Summary 默认不把它当已确认事实；
- Space Summary 包含总览文章、关系图和 Research Gaps；
- Paper、Space、Chat、Memory 之间可以通过来源链接回溯。

### 17.3 稳定性与可观察性

- 执行中、完成、失败、取消状态不会互相矛盾；
- Codex sandbox/thread 恢复失败时有可读错误和重试入口；
- Skill 未调用时不会显示已调用；
- 事件、操作和删除确认有审计记录；
- 重复导入的高置信度资源复用，低置信度资源给出候选；
- 前端在桌面和移动宽度下无横向溢出，长 Markdown 和状态日志不会拖垮布局；
- 后端和前端测试覆盖导入、关联、对话、Memory 确认、删除确认、状态事件和批量上限。

## 18. 产品原则摘要

```text
资源只保存一份，空间通过 Link 组织。
Chat 负责理解和修改草稿，点击负责确认和高风险操作。
正文保持干净，证据可展开且可回溯。
草稿可以帮助探索，但正式结论必须区分可信度。
Skill/Vision 的状态必须来自真实执行事件。
先把 Paper → QA → Memory → Space Chat 的闭环做稳，再做 Global。
```
