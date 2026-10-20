# 造价平台 L1 编排层后端（cost-platform-backend）

软件造价评估平台的业务编排层（architecture.md §2 的 L1）。它是**业务控制面**：
用户/部门/项目/审批/产物版本都归它管，真正的智能体执行交给 AgentScope 运行时。

## 边界（硬约束）

- **不 import agentscope**：与运行时只通过 HTTP 通信，且只允许（未来的）
  `app/runtime_client` 模块访问运行时（§8.7 防腐层）。本目录使用独立 venv，
  从机制上杜绝误引用。
- **独立数据库**：业务库 `platform`；AgentScope 运行时用自己的 `agentscope`
  库，两库永不共享表（§10.5）。
- 运行时永远只看到单一主体 `sys:runtime`（§8.2），平台用户体系不透传到运行时。

## 目录

```
app/
  main.py       应用工厂（create_app）
  config.py     配置（PLATFORM_ 前缀环境变量 / .env）
  db.py         异步引擎、会话工厂、DeclarativeBase
  models/       ORM 模型（org=用户/组，project=项目）
  api/          路由（meta=健康检查，auth=自助注册）
alembic/        数据库迁移（唯一改表途径，禁止 create_all）
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
- [ ] JWT 登录 / 鉴权中间件
- [ ] stage_runs / approval_tasks / artifact_versions（阶段状态机）
- [ ] runtime_client（防腐层）+ 需求分析智能体端到端
