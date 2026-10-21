# 造价平台前端（platform-frontend）

软件全生命周期管控平台的 SPA —— **一个前端、两个视图**（architecture.md §3）：

- **视图 A · 项目生命周期**（类禅道）：项目列表 / 详情（六阶段时间线、
  阶段运行、审批中心），路由 `/projects`、`/projects/:id`
- **视图 B · Agent 工作台**（类 WorkBuddy 三栏）：左=项目阶段上下文，
  中=与阶段智能体对话（轮询），右=产物面板（提交送审 / 版本预览），
  路由 `/projects/:id/workbench/:runId`

## 边界（硬约束）

- **只连 L1 编排层**（BFF 模式）：所有请求走 Vite 代理
  `/api → http://localhost:8100`，JWT 鉴权；**绝不直连 AgentScope 运行时**。
- 本目录由 AgentScope `examples/web_ui/frontend` 一次性收割而来
  （§8.7），之后独立演化；上游改进按需手工 cherry-pick。

## 与原 web_ui 的差异

- `src/App.tsx` 重写为平台路由（登录 / 项目 / 工作台），
  原页面（chat/credential/knowledge/...）保留在 `src/pages/` 作为
  M2 素材（未挂路由）
- `src/api/platform.ts` 新增：L1 客户端（JWT + 401 跳登录）
- `src/auth.tsx` 新增：AuthProvider
- `src/pages/{Login,Projects,ProjectDetail,Workbench}.tsx` 新增
- `vite.config.ts`：端口 5174（5173 留给原 web_ui），代理指向 8100

## 本地开发

```bash
cd platform/frontend
pnpm install
pnpm dev        # http://localhost:5174 （由仓库根 start.sh 一键带起）
pnpm build      # tsc -b + vite build
```

前置：L1（8100）与运行时（8000）已启动（见仓库根 start.sh）。

## M1 已通页面流

登录 → 建项目 → 启动需求阶段 → 进入工作台对话（HITL 工具确认）→
提交产物送审 → 项目详情页审批 → 阶段自动推进。
