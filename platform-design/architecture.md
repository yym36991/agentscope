# 软件造价评估平台 · 总体架构设计

> 版本 v0.1（讨论稿）· 2026-10-20
> 状态：**设计阶段，未开始实现**。本文档用于对齐认知，所有 AgentScope 相关论断均核对过当前仓库代码（v2.x，分支 za_yym_1019）。

---

## 0. 怎么读这份文档

- 第 1~3 章：业务全景、总体分层、前端两视图 —— 回答"整体长什么样"
- 第 4~5 章：领域模型与状态机 —— 回答"人/组/项目/知识库/会话怎么建模、人工审批怎么管"
- 第 6~7 章：记忆与知识库 —— 回答"上下文、短期/长期记忆、知识沉淀怎么组织"
- 第 8~9 章：AgentScope 集成与产物管理 —— 回答"开源框架怎么嵌入、边界在哪"
- 第 10~13 章：部署、选型、路线图、待决策清单

---

## 1. 业务全景与目标

**业务域**：银行行业软件造价评估——从需求提出到验收审计的全生命周期管控。单个项目周期以**月**计，贯穿 6 个专业阶段，每个阶段由一个智能体辅助产出，且**必须经人工确认/审批**后才能进入下一阶段。

```
┌────────┐   ┌────────┐   ┌──────────┐   ┌────────┐   ┌────────┐   ┌─────────┐
│①需求分析│──▶│②原型设计│──▶│③工时预算  │──▶│④测试用例│──▶│⑤测试    │──▶│⑥验收审计 │
│ 智能体  │审 │ 智能体  │审 │ 罗盘智能体│审 │ 智能体  │审 │ 智能体  │审 │ 智能体   │
└────────┘批 └────────┘批 └──────────┘批 └────────┘批 └────────┘批 └─────────┘
   PRD         原型         功能点清单/      用例文档      测试报告      结算/审计
              (HTML等)      预算表                       (功能+单元)    汇总报告
              ▲             ▲                                          ▲
              └──── 人工审批不通过则退回当前阶段修订（可多轮）──────────────┘
```

**硬性要求**：

| 要求 | 含义 |
|---|---|
| 多租户 | 用户属于组（部门），组间数据隔离；知识库按组授权 |
| 长周期项目 | 项目持续数月，绝非单个会话能统筹；需要项目 → 阶段 → 会话的层级 |
| 人工审批 | 每阶段闸门，不同阶段可由不同负责人审批，全部留痕（银行审计要求） |
| 双形态部署 | 公有云 K8s 多实例 + 银行内网全离线部署 |
| 会话隔离 | 用户隔离、项目隔离、会话级隔离（并发互斥） |
| 多轮对话与记忆 | 阶段内多轮交互，跨阶段有交接，跨项目有沉淀 |
| 编排能力 | 阶段流程可配置（审批策略、是否自动流转等） |

---

## 2. 总体架构：四层

```
┌──────────────────────────────────────────────────────────────────────┐
│ 前端 SPA（React 19 + Vite，一套代码、两个视图）                          │
│  ┌───────────────────────────┐    ┌─────────────────────────────────┐ │
│  │ 视图A·项目生命周期(类禅道)    │    │ 视图B·Agent工作台(类WorkBuddy三栏)│ │
│  │ 看板/详情/时间线/审批/版本链  │◀──▶│ 左:项目上下文 中:对话 右:产物预览  │ │
│  └───────────────────────────┘    └─────────────────────────────────┘ │
└───────────────────────────────┬──────────────────────────────────────┘
                        HTTPS/JWT│  前端只对接业务编排层（BFF 模式）
┌───────────────────────────────▼──────────────────────────────────────┐
│ 业务编排层 platform-backend（自研 FastAPI）——平台的"控制面"               │
│  用户/组/RBAC · 项目管理 · 阶段状态机 · 审批任务 · 产物版本链              │
│  知识库授权 · 项目档案(跨阶段记忆) · SSE 透传 · 文档导出(docx/xlsx)        │
│  业务库: PostgreSQL                                                   │
└──────┬──────────────────────────────────────────┬────────────────────┘
       │ HTTP（X-User-ID: p:{project_id}）          │
┌──────▼──────────────────────────────────────────▼────────────────────┐
│ 智能体运行时层 agentscope-service（AgentScope）——平台的"执行面"          │
│  6×阶段智能体(AgentRecord) · 会话/上下文压缩 · 工具/技能/MCP             │
│  RAG 检索 · 项目 Workspace(产物落盘) · 长期记忆中间件 · SSE 事件流        │
└──────┬───────────────┬───────────────────┬──────────────┬─────────────┘
       │               │                   │              │
 ┌─────▼─────┐  ┌──────▼──────┐  ┌─────────▼─────┐  ┌─────▼─────────┐
 │ PostgreSQL │  │ Redis       │  │ Qdrant        │  │ 模型服务        │
 │ 会话/智能体  │  │ 消息总线/分布式锁│  │ 向量检索(每KB一库)│  │ vLLM / 智谱GLM │
 │ 记录存储     │  │             │  │               │  │ (OpenAI/Anthropic兼容)│
 └───────────┘  └─────────────┘  └───────────────┘  └───────────────┘
                 MinIO/S3：知识库文档原文 + 产物归档
```

**三条核心原则**（后面所有设计都从这三条推导）：

1. **控制面与执行面分离**。业务流程（谁审批、走到哪步、产物哪个版本有效）是普通工程问题，用普通工程手段（数据库 + 状态机）解决；智能体只负责"阶段内的智力劳动"。不要把业务流程塞进 Agent 的自治协作里。
2. **AgentScope 不直接面向最终用户**。所有前端流量经过业务编排层（BFF 模式）：鉴权、授权、审计、租户隔离全部收敛在一处；AgentScope 退居内网，是编排层的"智能体引擎"。
3. **平台用户体系与 AgentScope 主体解耦**。AgentScope 的 `X-User-ID` 只是运行时主体标识，由编排层按规则映射（见 §8.2），平台的用户/组织/权限体系完全自己持有。

---

## 3. 前端：一个前端、两个视图

结论先行：**你的"一个前端、两个视图"判断是对的**。不需要部署禅道，禅道只是信息架构的参考范式（仪表盘/列表/详情/审批流），用 React 自研管理视图即可。

### 3.1 视图划分与路由

| 视图 | 主要用户 | 路由（示意） | 内容 |
|---|---|---|---|
| A·项目生命周期 | 项目经理、审批人、审计人员 | `/projects`、`/projects/:id` | 项目看板（卡片显示当前阶段/待审事项/产物数）、项目详情（阶段时间线 + 产物版本链 + 审批操作） |
| B·Agent 工作台 | 需求提出者、开发人员等与智能体直接交互的人 | `/projects/:id/stages/:stage/chat` | 三栏：左=项目上下文（当前阶段可用智能体/技能/MCP/知识库），中=对话，右=产物预览与下载 |

两视图共享：登录、全局导航、项目上下文（当前项目/阶段）。视图 A 的项目详情页点击"进入 Agent 对话"，携带项目 ID + 阶段上下文跳到视图 B —— 与你草案的设想一致。

### 3.2 与现有 web_ui 的关系

现有 `examples/web_ui` 的底子直接复用：

- 技术栈一致：React 19 + Vite + TanStack Query + Tailwind + shadcn 风格组件
- 视图 B 以现有 ChatPage 为基座改造：它已是"侧栏 + 对话区 + 右侧 PanelDock"三区结构（`components/panel/` 已有 KnowledgeBasePanel/McpPanel/SkillPanel/TaskPanel 等），把"会话侧栏"换成"项目阶段上下文"，把 PanelDock 之一固定为"产物面板"即可
- 视图 A 是全新页面，但复用其 UI 组件库与请求层
- **一个关键改动**：现有前端直连 AgentScope（localStorage `server_url` + `X-User-ID`），平台版前端必须改为**只连业务编排层**（JWT 登录），SSE 由编排层透传（见 §8.4）

---

## 4. 领域模型：人 / 组 / 项目 / 知识库 / 会话

### 4.1 实体关系图

```
users ──< group_members >── groups
  │                            │
  │ (一人多项目,一项目多人)        │ (组级授权)
  ├──< project_members >──┐    │
  │                       ▼    │
  │                    projects ──< project_kb_links >── kbs ──< kb_grants >──┘
  │                       │
  │                       ├──< stage_runs(阶段运行) ──< approval_tasks(审批任务)
  │                       │         │
  │                       │         └── session_id → AgentScope 会话(外部系统)
  │                       └──< artifact_versions(产物版本)
  │
  └──(沉淀)── kb_documents / case_library(案例库, 属于 kbs)
```

### 4.2 核心表（业务库 PostgreSQL，属编排层）

| 表 | 关键字段 | 说明 |
|---|---|---|
| `users` | id, name, email, platform_role | platform_role：平台管理员/普通用户 |
| `groups` | id, name, parent_id | 组（部门），支持树形 |
| `group_members` | user_id, group_id | **用户 N—N 组**（一人可属多组） |
| `kbs` | id, name, kb_type, agentscope_kb_id, owner_group_id | kb_type：行业规范/价格基准/案例/模板/沉淀；`agentscope_kb_id` 指向 AgentScope 侧知识库 |
| `kb_grants` | kb_id, group_id, level(read/write) | **组级授权**；write 可管理文档 |
| `projects` | id, name, status, current_stage, owner_user_id | 项目聚合根，周期以月计 |
| `project_members` | project_id, user_id, project_role | project_role：发起人/项目经理/审批人/成员/观察者 |
| `stage_runs` | id, project_id, stage_type, status, version, agentscope_session_id, agentscope_agent_id | **一次阶段执行**；修订循环复用同一条 run（version 递增）；跨大版本重开新 run |
| `approval_tasks` | id, stage_run_id, artifact_version_id, assignee_user_id, action, comment, acted_at | 审批留痕，银行审计的核心表 |
| `artifact_versions` | id, project_id, stage_type, version, file_path, format, status | status：draft/submitted/approved/superseded |
| `project_kb_links` | project_id, kb_id, stage_type(nullable) | 项目用哪些知识库；**可按阶段绑定**（需求阶段→规范库，预算阶段→价格库） |
| `stage_flow_configs` | project_id(或全局默认), stage_type, approval_policy, auto_advance | 编排能力落点：每阶段谁审批、通过后是否自动流转 |

### 4.3 权限模型：RBAC + 资源 ACL 两层

业内标准做法（GitLab 同款思路），不要发明新模型：

1. **平台角色（RBAC）**：管理员/普通用户 —— 决定"能不能进这个功能"
2. **资源访问（ACL）**：
   - 项目：看 `project_members`（成员才可见）
   - 知识库：看 `kb_grants`（组级授权 + 可选的用户级例外授权表）
   - 权限判断永远发生在**编排层**，AgentScope 侧不做业务权限（见 §8.2）
3. **读写分离**：知识库 read（检索/浏览）与 write（上传/删除文档）分开授权

> 为什么组级授权而非用户级？银行场景部门边界清晰、人员流动频繁，按组授权管理成本最低；用户级只做例外补充（如外聘专家单独开某个库）。

---

## 5. 流程引擎：业务状态机与人工审批

### 5.1 你的判断是对的：用状态机，不用 Agent 自治协作

三个理由：

1. **周期错配**。AgentScope 的 Team 机制（leader 派发 AgentCreate + TeamSay 消息传递）为"单次任务内的多智能体协作"设计；而我们的流程横跨数月、数百次人机交互，状态必须落在**持久化数据库**里，而非某个会话的上下文里。
2. **人工闸门是一等公民**。审批人、审批意见、版本锁定、退回修改——这些是业务数据不是对话内容；状态机 + `approval_tasks` 表天然留痕，满足银行审计。
3. **Agent 无状态可重跑**。任何阶段的智能体崩溃/换模型/重跑，都不影响流程状态；流程状态也永远不依赖某个会话是否存活。

### 5.2 两级状态机

**项目级**：`DRAFT → ACTIVE → ACCEPTED → ARCHIVED`（外加 `SUSPENDED`/`CANCELLED`）

**阶段级**（每个 stage_run 一个实例，核心）：

```
                    ┌─────────────┐
   上一阶段 APPROVED │ NOT_STARTED │
        ───────────▶│   未开始     │
                    └──────┬──────┘
                           │ 启动（按配置：自动 / 项目经理手动）
                           ▼
                    ┌─────────────┐   提交产物送审
                    │ IN_PROGRESS │──────────────────┐
     退回修改 ◀───── │ 人机协作中   │                  ▼
     （附审批意见）   └─────────────┘           ┌──────────────┐
           │                                 │ UNDER_REVIEW │
           │        重新协作修改                │   待审批      │
           └──────────────────────────────── └──────┬───────┘
                                          审批通过    │ 审批驳回(退回)
                                                  ▼
                                          ┌──────────────┐
                                          │   APPROVED   │──▶ 驱动下一阶段
                                          │   已通过      │
                                          └──────────────┘
```

要点：

- **IN_PROGRESS 就是"人机协作中"**——不是批处理任务在跑。智能体在会话里多轮交互，用户认为产物成熟了才点"提交送审"
- **退回修改 = 同一 stage_run 的 version+1，同一个 AgentScope 会话继续聊**（智能体带着此前全部上下文 + 审批意见修改；AgentScope 自动做上下文压缩，见 §6）
- **并发互斥**：AgentScope 对每个会话有分布式运行锁（同一 session 同时只允许一个 run，`POST /chat/` 冲突返回 409）——天然防止两个人同时驱使同一阶段的智能体
- **每次状态转移写一条转移日志**（who/when/from/to/comment），审计兜底

### 5.3 与"对话内确认"的分工（容易混淆，明确一下）

平台里有两层"人机确认"，**不要互相替代**：

| 层 | 机制 | 用途 |
|---|---|---|
| 对话内确认（微观） | AgentScope 的 `AskUser` 工具、工具权限确认卡（HITL 卡片，前端已有 `SubagentHitlCard`/`ConfirmCard`） | 智能体干活途中的即时确认："要覆盖这个文件吗？""这个功能点分类对吗？" |
| 阶段审批（宏观） | 编排层状态机 + `approval_tasks` | 阶段产物是否合格、能否进入下一阶段——**这才是你要的"人工参与"** |

### 5.4 要不要上 BPMN 工作流引擎（Activiti/Camunda/Flowable）？

**初版不要**。6 阶段线性流 + 退回循环，用代码化状态机（枚举 + 合法转移表 + 转移日志）200 行搞定，可读可测。**何时引入**：审批规则频繁变化、出现会签（多人同时审）/条件分支/跨项目流程编排需求时，再评估——`stage_flow_configs` 表已经为"配置化"留了口子，届时把状态机的转移规则数据化即可平滑过渡。

---

## 6. 会话与记忆设计

### 6.1 层级映射：项目 → 阶段运行 → 会话（你问的"要不要引入项目 id、多个 session"）

**要，而且必须**。先澄清一个代码事实：**AgentScope 没有 thread 概念，会话（session）就是唯一对话单元**（`UserRecord → AgentRecord → SessionRecord` 三级）。所以平台自己定义层级，把 AgentScope 的 session 挂在最末级：

```
项目 project（月级，编排层实体，AgentScope 无此概念）
 └─ 阶段运行 stage_run（天~周级，修订循环内 version 递增）
     └─ AgentScope session（一次连续的人机协作对话，多轮消息）
         └─ 消息/上下文（AgentScope 自动压缩管理）
```

规则：

| 场景 | 做法 |
|---|---|
| 阶段首次启动 | 编排层创建 session，kickoff 消息注入项目档案 + 上游产物（见 6.3） |
| 退回修改 | **续用同一 session**——智能体保有全部上下文与审批意见，直接改 |
| 大版本重开（数月后重做/范围大变） | 新建 session（stage_run 新 run），kickoff 注入结构化交接摘要 |

### 6.2 三层记忆（对齐业内 working memory / episodic / semantic 分层）

| 层 | 载体 | 实现机制（AgentScope 现成能力） | 生命周期 |
|---|---|---|---|
| ① 工作记忆 | 会话上下文 | `AgentState.context` + `ContextConfig`：上下文达 80% 自动压缩为结构化摘要（任务概览/当前状态/重要发现/待办），工具结果超限截断，旧图片卸载到 workspace | 单会话 |
| ② 项目记忆（跨阶段交接） | 双份：a) 编排层**项目档案表**（结构化：需求摘要/关键决策/预算口径/产物索引）；b) AgentScope **`AgenticMemoryMiddleware`**（项目 workspace 下的 MEMORY.md，智能体自主记录/检索） | a) 每次阶段 kickoff 由编排层注入 system 上下文；b) 中间件挂载即用 | 项目周期 |
| ③ 长期知识（跨项目共享） | 知识库（按组授权） | AgentScope KB + `RAGMiddleware`（会话绑定的 KB 自动检索注入） | 永久，按组维护 |

关键认知：**"记忆"和"知识库"是两种东西**。记忆是经验性的（自动捕获、相似度召回、无需审核）；知识库是策划性的（人工维护、有版本、有权限）。项目档案（②a）是权威交接依据——不依赖任何智能体的自觉。

### 6.3 阶段交接（kickoff）协议

每个阶段的 kickoff 消息由编排层**模板化组装**，保证下游智能体的输入确定性：

```
[项目档案摘要]  ← 项目档案表渲染（需求关键点、既有决策、预算口径…）
[上游产物]      ← 引用 project workspace 中的文件路径 + 版本号
[本阶段任务]    ← 阶段任务模板 + 审批意见（若是退回修改）
[知识库提示]    ← 本阶段绑定的 KB 已通过 RAG 中间件挂载，无需显式传内容
```

### 6.4 知识沉淀闭环（项目 → 组织资产）

```
⑥验收审计 APPROVED
   → 沉淀流程（可配置为人工触发或自动起草）：
     编排层调用一个"沉淀智能体"（或固定流水线）提取：项目案例/功能点系数偏差/常见问题
   → 人工审核（同样走 approval_tasks）
   → 脱敏后写入所属组的"沉淀库"（kb_type=沉淀）
   → 此后所有该组的新项目在 RAG 检索中受益
```

沉淀库与案例库的分离：案例库（结构化项目档案检索）服务预算阶段找相似项目；沉淀库（经验教训）服务全阶段。

---

## 7. 知识库体系与权限

### 7.1 知识库分类（kb_type）

| 类型 | 内容 | 形态 | 主要消费阶段 |
|---|---|---|---|
| 行业规范库 | 银行监管文件、软件工程规范、造价标准（如功能点计数规范） | 文档 RAG | ①④⑥ |
| 价格基准库 | 功能点单价、地区系数、人月费率 | **结构化表 + 文档** | ③ |
| 案例库 | 历史项目档案（功能点数/实际工期/实际成本） | 结构化 + RAG | ③⑥ |
| 模板库 | PRD 模板、测试用例模板、审计报告模板 | 文档 | ①②④⑥ |
| 沉淀库 | 项目经验、系数修正、常见问题 | 文档 RAG | 全阶段 |

> 价格基准库建议**双轨**：核心数值（单价/系数）放业务库结构化表（③的预算智能体用工具精确查询，保证计算确定性），说明性文档走 RAG。**不要把费率表扔进向量库让模型"检索着算"**——造价场景数字必须可审计。

### 7.2 权限执行点（全部在编排层）

```
用户发起检索/上传
  → 编排层: 用户 ∈ 哪些组? → 可见 KB 集合 = Σ kb_grants(组) ∪ 用户例外授权
  → 阶段可用 KB = project_kb_links(本阶段) ∩ 可见集合
  → 编排层以内部主体代理调用 AgentScope KB API（检索/挂载到会话）
```

- **先过滤、后检索**（authorization-aware RAG）：权限不通过的知识库根本不进入检索候选，而不是检索完再过滤（防泄漏 + 省算力）
- AgentScope 侧每个 KB 物理独立一个向量集合（`CollectionPerKbManager`，`kb_<uuid>`），天然按库隔离
- 文档上传/删除 = write 权限，仅授予管理组

---

## 8. AgentScope 集成设计

### 8.1 能力对照：已有 vs 需要自建（诚实清单）

| 能力 | AgentScope 现状（代码核实） | 平台需要做的 |
|---|---|---|
| 会话/多轮对话/SSE | ✅ `POST /chat/`（触发即返回）+ `GET /sessions/{id}/stream`（先回放后实时，游标续传） | 编排层透传 SSE |
| 会话运行互斥 | ✅ 分布式锁（Redis 总线 CAS），同 session 并发 409 | 无 |
| 上下文压缩 | ✅ `ContextConfig`（80% 触发结构化摘要） | 调参 |
| 长期记忆 | ✅ `AgenticMemoryMiddleware`（workspace 内 MEMORY.md）| 挂载到项目 workspace |
| 知识库全链路 | ✅ 上传→解析(PDF/Word/Excel/PPT/图片)→分块→嵌入→检索 API + `RAGMiddleware` | 组级授权（自建，见 §7） |
| 智能体定义 | ✅ `POST /agent/`（DB 记录，系统提示词/上下文参数），前端有 schema 驱动表单 | 编排层按项目工厂化创建（§8.3） |
| 工具/技能/MCP | ✅ workspace 级挂载，MCP 库/技能库（GitHub/ClawHub） | 按阶段配置 |
| 多实例 | ✅ `RedisMessageBus`（Redis Streams+Lua）、`AsyncSQLAlchemyStorage`(PG/MySQL)、分布式锁、专用 worker 开关（index/channel/scheduler）、`download_secret`（LB 后必设） | 部署层组装（§10） |
| 沙箱工作区 | ✅ Docker/E2B/K8s/OpenSandbox 等 8 种 WorkspaceManager | 内网选型 |
| 定时任务 | ✅ `/schedules`（APScheduler） | 审计/对账定时任务可用 |
| 渠道集成 | ✅ 钉钉/飞书/Discord channel | 审批通知可对接钉钉 |
| **文档生成（docx/xlsx）** | ❌ **仓库内没有**。`formatter/` 是模型消息格式化（OpenAI/Anthropic 适配），不是文档导出；全库无 docx/pdf/xlsx 生成 | **编排层自建导出服务**（pandoc/python-docx/openpyxl：md→docx，表格→xlsx） |
| **组级权限/组织架构** | ❌ 只有 user 级归属 + 可插拔 `ResourceAccessPolicy`（默认全拒绝） | 编排层自建（§4.3/§7） |
| **业务流程/审批** | ❌ 无此概念（SOP 是会话内步骤编排，不是跨天流程） | 编排层状态机（§5） |

### 8.2 主体映射（关键设计，纠正一个常见误区）

AgentScope 的一切资源以 `X-User-ID` 为主体归属（user 级隔离是有的，**但没有组/租户级**）。平台的映射规则：

| 平台身份 | AgentScope 主体 | 用途 |
|---|---|---|
| 项目（抽象主体） | `p:{project_id}` | **项目阶段会话、阶段智能体实例、项目 workspace 都挂在这个主体下** |
| 平台管理员（服务身份） | `sys:admin` | 全局知识库的创建/管理、平台级智能体模板管理 |
| 个人用户（可选，后期） | `u:{user_id}` | 个人助理等与项目无关的对话 |

为什么项目会话挂 `p:{project_id}` 而不是发起人的 `u:{user_id}`：同一阶段的协作与审批需要多人看到**同一段对话**，而 AgentScope 会话按主体隔离（A 的会话 B 天然不可见）。挂项目主体后，"谁能看这个项目的会话"完全由编排层判断后透传——**可见性规则只有一个真相来源**。

模型凭证：平台管理员在 `sys:admin`（或每项目主体）下配置模型凭证（内网 vLLM / 智谱 GLM——本机已跑通 Anthropic 兼容端点），**不对最终用户开放**——银行场景模型出口必须集中管控。

### 8.3 六个阶段智能体怎么建（纠正草案里的一个技术点）

> 草案原话："预先注册 5 个 SubAgentTemplate"。**SubAgentTemplate 不是干这个的**——它是给 Team 机制用的：leader 智能体在会话里用 `AgentCreate` 工具动态孵化子智能体（模板只是孵化配方）。我们的 6 个阶段智能体是**长期存在的用户级智能体**，正确机制是 `POST /agent/` 创建 `AgentRecord`。

平台启动时（或项目创建时）的"智能体工厂"：

```
智能体蓝图（编排层代码/配置定义 6 份：系统提示词、推荐模型、
  技能/MCP 清单、知识库绑定、权限模式、上下文参数）
        │
        ▼ 项目创建时
编排层以 p:{project_id} 为主体, POST /agent/ ×6
  → 每个项目拥有自己的 6 个智能体实例
  → 好处: ① 项目间提示词/配置互不影响
          ② 同一项目同阶段唯一 session 约束(见下)按 (主体,智能体,workspace) 天然成立
          ③ 后续可按项目定制提示词(银行不同分行差异化)
```

SubAgentTemplate 留给另一个用途：**阶段内部**的子任务孵化（例如需求分析智能体孵化"只读探索员"处理大文档——示例里的 explorer 模板就是这个用法，本仓库已有现成参考）。

### 8.4 一次阶段协作的完整时序

```
用户(视图B)          编排层L1                    AgentScope
   │ POST /stage-run/{id}/message  │                    │
   ├──────────────▶│ 鉴权: 是项目成员? 阶段 IN_PROGRESS?  │
   │               │ POST /chat/ {agent_id, session_id, input}
   │               ├───────────────────▶│ 分布式锁获取(run 开始)
   │               │◀─── {status:started}│
   │ 202           │                    │ 智能体推理/工具/RAG…
   │               │ GET /sessions/{sid}/stream?after=cursor
   │◀═════════ SSE 事件透传(增量消息/工具卡/HITL确认卡) ═════│
   │               │                    │
   │ 用户点"提交送审"(视图A/B) │            │
   ├──────────────▶│ 快照 workspace 产物 → artifact_versions
   │               │ 状态机 IN_PROGRESS→UNDER_REVIEW, 生成审批任务
   │  审批人(视图A) │                    │
   ├──────────────▶│ APPROVED → 驱动下一阶段: 创建/复用 session,
   │               │   组装 kickoff(项目档案+上游产物+任务) 
   │               │   POST /chat/ 触发下一阶段智能体首轮产出
```

要点：kickoff 也是一次 `/chat/` 调用——下游智能体的首轮产出是"被流程驱动"的，用户进会话时往往已有初稿可改。

### 8.5 产物落盘与传递（修正草案的 workspace 论述）

草案说"产物传递通过 Workspace 机制"——方向对，落点是：**一个项目一个 workspace**（阶段间共享），目录约定：

```
project-workspace/
├── 01-需求分析/   prd-v1.md, prd-v2.md, ...
├── 02-原型设计/   prototype-v1.html, ...
├── 03-工时预算/   function-points-v1.md, budget-v1.xlsx...
├── .../
├── uploads/       用户上传的原始文档(需求文件等)
└── MEMORY.md      项目级长期记忆(AgenticMemoryMiddleware 自动维护)
```

- 智能体用内置 Write/Edit 工具写文件（前端已有对应渲染器，体验成熟）
- 提交送审时编排层经 `/workspace/files` 拉取快照存入 `artifact_versions`（版本定格，后续修改不影响已审版本）
- 需要核实的小点（实现时验证）：`POST /sessions/` 能否显式指定 `workspace_id`（SessionConfig 含该字段）；若不能，退路是 PER_AGENT 隔离策略 + 编排层在 kickoff 消息里附上游产物文件引用

---

## 9. 产物管理与版本链

- **版本模型**：`artifact_versions` 记录每次送审快照（stage、version、file_path、format、status）。同一阶段多次退回修改 = version 递增；APPROVED 的版本被 superseded 需走变更流程
- **预览**（视图B右栏/视图A详情页）：markdown 渲染（PRD/用例/报告）、HTML iframe（原型）、表格渲染（功能点清单）；workspace 下载令牌机制现成（短时签名，支持浏览器直下）
- **导出**：编排层导出服务做 md→docx（pandoc/python-docx）、清单→xlsx（openpyxl）——**这是自建件**，AgentScope 没有文档生成能力（§8.1 已列）
- **版本对比**：文本类 diff（前端已有 DiffPreview 组件可复用）

---

## 10. 部署架构

### 10.1 公有云（K8s，多实例）

```
                    Ingress/LB
        ┌──────────────┼───────────────┐
   前端静态        编排层×N副本      agentscope-service×N副本
  (CDN/OSS)      (FastAPI,无状态)    (无状态; 专用worker可分拆:
        │              │               index/channel/scheduler 开关)
        │         ┌────┴────────────────────┐
        │         ▼                         │
   PostgreSQL(业务库+会话库)   Redis(消息总线/分布式锁)
   Qdrant(向量)  MinIO/S3(KB文档blob)  共享存储或K8s工作区(产物)
        模型服务: vLLM/OpenAI兼容网关 或 智谱API(Anthropic兼容)
```

多实例要点（全部有现成支撑，已核实）：
- 消息总线必须 `RedisMessageBus`（InMemory 版仅单进程）
- 存储用 `AsyncSQLAlchemyStorage`（PostgreSQL，带 alembic 迁移）
- LB 后必须设置 `download_secret`（文件下载令牌跨实例签名）
- 运行锁是分布式的（Redis 总线），多副本安全

### 10.2 银行内网（全离线）

同一套代码，换成 on-prem 组件：PostgreSQL/Redis/Qdrant/MinIO 均内网部署；模型走**行内推理服务**（vLLM 起开源模型，OpenAI 兼容端点；或行内采购的 GLM 等的兼容网关）；模型卡片 YAML 离线导入（本机已验证 GLM 卡片 + Anthropic 兼容端点这条路）；沙箱工作区用 DockerWorkspaceManager（测试智能体跑测试需要）；离线安装包（镜像 tar + pip/pnpm 离线源）。

合规要点：数据不出域（模型端点全部内网）、全量审计日志（状态转移日志 + 审批表导出）、产物落存储加密。

### 10.3 隔离层次总览

| 层次 | 机制 | 在哪实现 |
|---|---|---|
| 用户隔离 | JWT 登录 + RBAC | 编排层 |
| 项目隔离（租户级） | 项目主体 `p:{id}` + 会话/智能体/workspace 挂项目主体 + 项目成员 ACL | 编排层 + AgentScope 主体映射 |
| 会话隔离 | AgentScope 按 (user, agent, workspace) 唯一 + 分布式运行锁（并发 409） | AgentScope（现成） |
| 知识库隔离 | 每 KB 独立向量集合 + 组授权先过滤后检索 | AgentScope（物理）+ 编排层（授权） |

---

## 11. 技术选型建议

| 件 | 选型 | 理由 |
|---|---|---|
| 编排层 | FastAPI + SQLAlchemy + Alembic + PostgreSQL | 与 AgentScope 同语言同生态，SSE 透传/异步天然支持；PG 满足审计与事务 |
| 前端 | 现有 web_ui 栈扩展（React 19 + Vite + TanStack Query + Tailwind） | 视图B基座现成，团队无切换成本 |
| 认证 | JWT（access+refresh），预留 OIDC/LDAP 对接 | 银行多对接统一认证，接口留好 |
| 导出 | pandoc + python-docx + openpyxl | md→docx、xlsx 结构化导出 |
| 状态机 | 代码化（枚举+合法转移表+转移日志表） | §5.4 论证；不引入 BPMN |
| 部署 | Docker Compose（内网单机起步）→ K8s（多实例） | 与 §10 双形态对齐 |

---

## 12. 实施路线图（每步可演示）

| 里程碑 | 内容 | 验收标准 |
|---|---|---|
| M1 骨架端到端 | 编排层骨架（用户/组/项目 CRUD + JWT）+ 状态机 + 前端两视图骨架 + **仅①需求分析智能体**接通（创建项目→进会话→产出 PRD→提交→审批通过） | 全流程在页面上走通一遍 |
| M2 六阶段闭环 | 6 智能体蓝图 + 阶段流转/退回 + 产物版本链 + kickoff 交接 | 假项目从需求走到验收审计 |
| M3 知识库 | KB 组授权 + 阶段绑定 + RAG 挂载 + 价格基准结构化查询工具 | 权限用例通过；预算智能体能查准费率 |
| M4 记忆与沉淀 | 项目档案表 + AgenticMemoryMiddleware + 沉淀流程 | 跨阶段交接引用上游结论；沉淀入库可检索 |
| M5 部署形态 | 多实例（Redis 总线/PG 存储/LB 配置）+ 内网离线包 + 导出服务 | 双形态部署演练通过 |

M1 期间并行敲定 §13 的决策清单。

---

## 13. 待你拍板的决策清单（实现前需要答案）

1. **审批规则**：每阶段的审批人如何指定——按项目角色（如"项目经理"）？指定到人？是否需要会签？
2. **产物格式**：送审/归档产物的标准格式是 docx？模板是否已有（银行的 PRD/测试报告模板）？
3. **原型形态**：②原型设计智能体产出什么——HTML 页面？图片？对接 Axure/墨刀？
4. **⑤测试智能体的边界**：被测系统从哪来（上传代码包？只做测试设计不执行？）——若要真执行，内网沙箱方案要提前定
5. **用户体系**：自建账号密码，还是对接行内 LDAP/OA 统一认证？
6. **模型策略**：行内统一模型网关（什么形态）？云上用什么（智谱已跑通）？各阶段是否用不同模型（如预算阶段用推理强的）？
7. **价格基准库**：功能点单价/地区系数是否有权威数据源，数据量级多大？
8. **规模预期**：并发项目数/用户数量级——决定 M5 之前要不要提前做多实例

---

## 附录 A：AgentScope 关键接口速查（本仓库核实版）

| 用途 | 接口/类 |
|---|---|
| 触发智能体一轮 | `POST /chat/` `{agent_id, session_id, input}`（立即返回，单会话单运行锁） |
| 事件流 | `GET /sessions/{sid}/stream`（SSE，先按游标回放再实时，30s 心跳） |
| 会话管理 | `POST/GET/PATCH/DELETE /sessions/`、`GET /sessions/{sid}/messages`（游标分页） |
| 智能体管理 | `POST/GET/PATCH/DELETE /agent/`，表单 schema：`GET /agent/schema/v2` |
| 知识库 | `POST/GET/DELETE /knowledge_bases/`，文档上传/状态/分块/下载，检索 `POST /knowledge_bases/{id}/search` |
| 工作区 | `GET /workspace/directories|files|status`，`POST /workspace/files/download-token` |
| 凭证/模型 | `/credential/`、`/model/`、`/embedding_model/`（模型卡片 YAML） |
| 存储 | `RedisStorage` / `AsyncSQLAlchemyStorage`（PG/MySQL/SQLite，alembic） |
| 消息总线 | `InMemoryMessageBus`（单进程）/ `RedisMessageBus`（多实例必选） |
| 工作区管理器 | Local / Docker / E2B / Daytona / K8s / OpenSandbox / AppleContainer / Bubblewrap |
| 向量库 | Qdrant（内嵌或服务）/ MilvusLite / Elasticsearch / MongoDB |
| 长期记忆中间件 | `AgenticMemoryMiddleware`（文件式）/ `Mem0Middleware` / `ReMeMiddleware` |
| 上下文压缩 | `ContextConfig`（trigger_ratio/结构化摘要 schema/工具结果截断/图片卸载） |
| 团队机制 | `TeamCreate`/`AgentCreate`/`TeamSay`（会话内动态孵化，SubAgentTemplate 为配方） |
| SOP | `/sop/` 会话内步骤化流程（人/智能体验证器）——注意：不是跨天业务流程 |
