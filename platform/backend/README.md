# 造价平台 L1 编排层后端（cost-platform-backend）

软件全生命周期管控平台的业务编排层（architecture.md §2 的 L1）。它是**业务控制面**：
用户/部门/项目/审批/产物版本都归它管，真正的智能体执行交给 AgentScope 运行时。

## 边界（硬约束）

- **不 import agentscope**：与运行时只通过 HTTP 通信，且只允许
  `app/runtime_client` 模块访问运行时（§8.7 防腐层）。本目录使用独立
  venv，从机制上杜绝误引用。
- **独立数据库**：业务库 `platform`；AgentScope 运行时用自己的 `agentscope`
  库，两库永不共享表（§10.5）。
- 运行时永远只看到单一主体 `sys:runtime`（§8.2），平台用户体系不透传到运行时。

## 目录

```
app/
  main.py            应用工厂（create_app）
  config.py          配置（PLATFORM_ 前缀环境变量 / .env）
  db.py              异步引擎、会话工厂、DeclarativeBase
  models/            ORM 模型（org=用户/组，project=项目，stage=流程）
  api/               路由（meta/auth/projects）
  services/flow.py   阶段状态机（唯一实现）
  runtime_client.py  运行时防腐层（唯一允许访问运行时的模块）
scripts/seed.py      引导脚本：在 sys:runtime 名下种阶段智能体
alembic/             数据库迁移（唯一改表途径，禁止 create_all）
```

## 本地开发

```bash
# 前置：PostgreSQL 已由仓库根目录 start.sh 启动（端口 5432，trust 认证）

cd platform/backend
python -m venv .venv
.venv/Scripts/python -m pip install -e .

# 首次：建库 + 迁移
.venv/Scripts/createdb -U postgres -h localhost platform   # 或 start.sh 已自动建
.venv/Scripts/python -m alembic upgrade head

# 启动（start.sh 会自动带起，也可手动）
.venv/Scripts/python -m uvicorn app.main:app --port 8100
```

API 文档：http://localhost:8100/docs

## 进度（M1）

- [x] 项目骨架、配置、DB 层
- [x] 组织模型：users / groups / group_members（自助注册入 default 组）
- [x] 项目模型：projects / project_members（状态机枚举就位）
- [x] JWT 登录 / 鉴权中间件（scrypt 口令哈希 + Bearer；无口令账号为开发引导态）
- [x] 阶段状态机：stage_runs / approval_tasks / artifact_versions
      （提交→待审→通过/退回；退回重开 round+1；审批通过自动推进项目阶段）
- [x] runtime_client 防腐层 + 阶段会话生命周期
      （启动阶段即建会话；运行时不可用时降级为懒创建，对话中自愈）
- [x] 需求生成智能体接入（scripts/seed.py 种到 sys:runtime 名下）

## 一次性引导

```bash
# 1) 种阶段智能体（幂等，可重复执行）
.venv/Scripts/python -m scripts.seed

# 2) 在 sys:runtime 名下注册模型凭证（把 YOUR_KEY 换成你的智谱 API key）
#    key 只进这一条命令，不落仓库、不进日志
curl -X POST http://localhost:8000/credential/ \
  -H "X-User-ID: sys:runtime" -H "Content-Type: application/json" \
  -d '{"data":{"name":"zhipu","type":"anthropic_credential",
       "api_key":"YOUR_KEY","base_url":"https://open.bigmodel.cn/api/anthropic"}}'
```

配好凭证后即可走通：建项目 → 启动需求阶段 → `chat` 对话 →
`submit-latest` 把智能体最后回答提交为产物 → 审批。

## API 一览（鉴权后 Bearer）

```
POST /auth/register      自助注册（入 default 组）
POST /auth/login         登录 → JWT
GET  /users/me           当前用户

POST /projects                 建项目
GET  /projects                 我的项目列表
GET  /projects/{id}            项目详情
POST /projects/{id}/stages/{stage}/start   开阶段运行（顺序+去重守卫）
GET  /projects/{id}/stage-runs 运行历史
POST /stage-runs/{id}/chat     对话（转发到运行时会话，模型配置自愈）
GET  /stage-runs/{id}/messages 会话消息（前端轮询用）
POST /stage-runs/{id}/confirm  工具确认（HITL：允许/拒绝 asking 调用）
POST /stage-runs/{id}/submit   提交产物（落盘 artifacts/，进入待审）
POST /stage-runs/{id}/submit-latest   把智能体最新回答提交为产物
GET  /stage-runs/{id}/artifacts       产物版本列表
GET  /stage-runs/{id}/artifacts/{aid} 产物内容（预览）
GET  /approvals/pending        我的待审批
POST /approvals/{id}/decide    审批（approve | return+意见）
```
