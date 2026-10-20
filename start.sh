#!/bin/bash
# ============================================================
# 造价平台本地服务 —— 一键启动脚本
#
# 按依赖顺序启动(前一个就绪后才启动下一个):
#   1. PostgreSQL       平台/运行时落盘库  端口 5432
#   2. Redis            总线/缓存         端口 6379
#   3. Agent Service    AgentScope 运行时  端口 8000
#   4. Web UI           前端 5173 + Node 后端 3100
#   5. Platform API     L1 编排层后端      端口 8100
#   6. Platform 前端    平台 SPA 两视图   端口 5174
#
# 所有服务的输出都追加写入 logs/ 目录:
#   logs/postgresql.log  logs/redis.log  logs/backend.log
#   logs/frontend.log    logs/platform.log  logs/platform-frontend.log
#
# ▶ 执行命令 —— Git Bash 终端里(任意目录均可):
#     bash /d/Users/code/agentscope/start.sh
#
# ▶ 执行命令 —— PowerShell / CMD 里(任意目录均可):
#     D:\Users\58369\Git\bin\bash.exe /d/Users/code/agentscope/start.sh
#
# ▶ 停止服务:
#     bash /d/Users/code/agentscope/stop.sh
#     D:\Users\58369\Git\bin\bash.exe /d/Users/code/agentscope/stop.sh
# ============================================================

BASE_DIR="/d/Users/code/agentscope"
PG_DIR="/d/Users/58369/postgresql"
REDIS_DIR="/d/Users/code/tools/redis"
LOG_DIR="$BASE_DIR/logs"
PID_FILE="$LOG_DIR/service-pids.txt"

# ---------- 工具函数 ----------

# 检查端口是否处于监听状态
port_up() {
    netstat -ano | tr -d '\r' | grep "LISTENING" | grep -q ":$1 "
}

# 等待端口就绪: $1=端口, $2=最长等待秒数(默认 30)
wait_port() {
    local port=$1 timeout=${2:-30}
    local deadline=$(( $(date +%s) + timeout ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        port_up "$port" && return 0
        sleep 0.3
    done
    return 1
}

# 取 bash 后台进程对应的 Windows PID(stop.sh 里的 taskkill 需要它)
winpid_of() {
    cat "/proc/$1/winpid" 2>/dev/null || echo "$1"
}

# ---------- 启动流程 ----------

mkdir -p "$LOG_DIR"
: > "$PID_FILE"

echo "=========================================="
echo " 造价平台本地服务启动"
echo "=========================================="

# ---------- 1. PostgreSQL ----------
if port_up 5432; then
    echo "[1/6] PostgreSQL 已在运行 (端口 5432), 跳过"
else
    if [ ! -f "$PG_DIR/bin/pg_ctl.exe" ]; then
        echo "[错误] 未找到 $PG_DIR/bin/pg_ctl.exe"
        exit 1
    fi
    # 首次运行: 初始化数据目录(本机监听 + trust 认证, 仅本地开发)
    if [ ! -f "$PG_DIR/data/PG_VERSION" ]; then
        echo "[1/6] 初始化 PostgreSQL 数据目录..."
        "$PG_DIR/bin/initdb.exe" -D "$PG_DIR/data" -U postgres \
            -A trust -E UTF8 --locale=C >> "$LOG_DIR/postgresql.log" 2>&1
    fi
    echo "[1/6] 启动 PostgreSQL (端口 5432)..."
    {
        echo ""
        echo "===== $(date '+%Y-%m-%d %H:%M:%S') postgresql starting ====="
    } >> "$LOG_DIR/postgresql.log"
    # 注意: pg_ctl 的输出必须重定向到文件, 不能接管道 —— postgres.exe
    # 会继承管道句柄, 导致管道永远等不到 EOF(脚本卡死)
    "$PG_DIR/bin/pg_ctl.exe" -D "$PG_DIR/data" \
        -l "$LOG_DIR/postgresql.log" -w start >> "$LOG_DIR/postgresql.log" 2>&1
    if wait_port 5432 20; then
        echo "      PostgreSQL 就绪"
        # 确保两个业务库存在(已存在则跳过)
        for db in platform agentscope; do
            "$PG_DIR/bin/psql.exe" -U postgres -h localhost -tAc \
                "SELECT 1 FROM pg_database WHERE datname='$db'" 2>/dev/null \
                | grep -q 1 || \
                "$PG_DIR/bin/createdb.exe" -U postgres -h localhost "$db" \
                    >> "$LOG_DIR/postgresql.log" 2>&1
        done
    else
        echo "      [错误] PostgreSQL 启动失败, 最近日志 (logs/postgresql.log):"
        tail -n 5 "$LOG_DIR/postgresql.log" | sed 's/^/        /'
        exit 1
    fi
fi

# ---------- 2. Redis ----------
if port_up 6379; then
    echo "[2/6] Redis 已在运行 (端口 6379), 跳过"
else
    if [ ! -f "$REDIS_DIR/redis-server.exe" ]; then
        echo "[错误] 未找到 $REDIS_DIR/redis-server.exe"
        exit 1
    fi
    echo "[2/6] 启动 Redis (端口 6379)..."
    {
        echo ""
        echo "===== $(date '+%Y-%m-%d %H:%M:%S') redis starting ====="
    } >> "$LOG_DIR/redis.log"
    cd "$REDIS_DIR"
    nohup ./redis-server.exe redis.windows.conf --port 6379 \
        >> "$LOG_DIR/redis.log" 2>&1 &
    REDIS_PID=$!
    cd "$BASE_DIR"
    echo "redis $(winpid_of "$REDIS_PID")" >> "$PID_FILE"
    if wait_port 6379 20; then
        echo "      Redis 就绪"
    else
        echo "      [错误] Redis 启动失败, 最近日志 (logs/redis.log):"
        tail -n 5 "$LOG_DIR/redis.log" | sed 's/^/        /'
        exit 1
    fi
fi

# ---------- 3. Agent Service (AgentScope 运行时) ----------
if port_up 8000; then
    echo "[3/6] AgentScope 运行时已在运行 (端口 8000), 跳过"
else
    echo "[3/6] 启动 Agent Service (端口 8000)..."
    {
        echo ""
        echo "===== $(date '+%Y-%m-%d %H:%M:%S') backend starting ====="
    } >> "$LOG_DIR/backend.log"
    cd "$BASE_DIR/examples/agent_service"
    nohup "$BASE_DIR/.venv/Scripts/python.exe" main.py \
        >> "$LOG_DIR/backend.log" 2>&1 &
    BACKEND_PID=$!
    cd "$BASE_DIR"
    echo "backend $(winpid_of "$BACKEND_PID")" >> "$PID_FILE"
    if wait_port 8000 40; then
        echo "      运行时就绪 (API 文档: http://localhost:8000/docs)"
    else
        echo "      [错误] 运行时启动失败, 最近日志 (logs/backend.log):"
        tail -n 8 "$LOG_DIR/backend.log" | sed 's/^/        /'
        exit 1
    fi
fi

# ---------- 4. Web UI (前端 + Node 后端) ----------
export PATH="/c/Program Files/nodejs:/c/Users/58369/AppData/Roaming/npm:$PATH"
if ! command -v pnpm >/dev/null 2>&1; then
    echo "[错误] 未找到 pnpm, 请检查 Node.js 安装"
    exit 1
fi
if port_up 5173; then
    echo "[4/6] Web UI 已在运行 (端口 5173), 跳过"
else
    echo "[4/6] 启动 Web UI (前端 5173, Node 后端 3100)..."
    {
        echo ""
        echo "===== $(date '+%Y-%m-%d %H:%M:%S') web_ui starting ====="
    } >> "$LOG_DIR/frontend.log"
    export PORT=3100
    cd "$BASE_DIR/examples/web_ui"
    nohup pnpm dev >> "$LOG_DIR/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    cd "$BASE_DIR"
    echo "frontend $(winpid_of "$FRONTEND_PID")" >> "$PID_FILE"
    if wait_port 5173 40; then
        echo "      前端就绪"
    else
        echo "      [错误] 前端启动失败, 最近日志 (logs/frontend.log):"
        tail -n 8 "$LOG_DIR/frontend.log" | sed 's/^/        /'
        exit 1
    fi
    if wait_port 3100 15; then
        echo "      Node 后端就绪 (端口 3100)"
    else
        echo "      [提示] Node 后端 (3100) 未就绪, 不影响主要功能, 详见 logs/frontend.log"
    fi
fi

# ---------- 5. Platform API (L1 编排层) ----------
if port_up 8100; then
    echo "[5/6] Platform API 已在运行 (端口 8100), 跳过"
else
    if [ ! -f "$BASE_DIR/platform/backend/.venv/Scripts/python.exe" ]; then
        echo "[错误] 未找到 platform/backend/.venv, 请先参阅 platform/backend/README.md 初始化"
        exit 1
    fi
    echo "[5/6] 启动 Platform API (端口 8100)..."
    {
        echo ""
        echo "===== $(date '+%Y-%m-%d %H:%M:%S') platform starting ====="
    } >> "$LOG_DIR/platform.log"
    cd "$BASE_DIR/platform/backend"
    # 幂等: 无待执行迁移时为空操作
    .venv/Scripts/python.exe -m alembic upgrade head >> "$LOG_DIR/platform.log" 2>&1
    nohup .venv/Scripts/python.exe -m uvicorn app.main:app \
        --host 127.0.0.1 --port 8100 >> "$LOG_DIR/platform.log" 2>&1 &
    PLATFORM_PID=$!
    cd "$BASE_DIR"
    echo "platform $(winpid_of "$PLATFORM_PID")" >> "$PID_FILE"
    if wait_port 8100 30; then
        echo "      Platform API 就绪 (API 文档: http://localhost:8100/docs)"
    else
        echo "      [错误] Platform API 启动失败, 最近日志 (logs/platform.log):"
        tail -n 8 "$LOG_DIR/platform.log" | sed 's/^/        /'
        exit 1
    fi
fi

# ---------- 6. Platform 前端 (平台 SPA, 5174) ----------
if port_up 5174; then
    echo "[6/6] Platform 前端已在运行 (端口 5174), 跳过"
else
    if [ ! -d "$BASE_DIR/platform/frontend/node_modules" ]; then
        echo "[6/6] 首次运行, 安装 Platform 前端依赖 (pnpm install)..."
        (cd "$BASE_DIR/platform/frontend" && pnpm install >> "$LOG_DIR/platform-frontend.log" 2>&1)
    fi
    echo "[6/6] 启动 Platform 前端 (端口 5174)..."
    {
        echo ""
        echo "===== $(date '+%Y-%m-%d %H:%M:%S') platform-frontend starting ====="
    } >> "$LOG_DIR/platform-frontend.log"
    cd "$BASE_DIR/platform/frontend"
    nohup pnpm dev >> "$LOG_DIR/platform-frontend.log" 2>&1 &
    PLATFE_PID=$!
    cd "$BASE_DIR"
    echo "platform-frontend $(winpid_of "$PLATFE_PID")" >> "$PID_FILE"
    if wait_port 5174 40; then
        echo "      Platform 前端就绪"
    else
        echo "      [错误] Platform 前端启动失败, 最近日志 (logs/platform-frontend.log):"
        tail -n 8 "$LOG_DIR/platform-frontend.log" | sed 's/^/        /'
        exit 1
    fi
fi

echo "------------------------------------------"
echo " 全部服务已启动:"
echo "   PostgreSQL:       localhost:5432 (库: platform / agentscope)"
echo "   Redis:            localhost:6379"
echo "   运行时:           http://localhost:8000  (API 文档 /docs)"
echo "   Web UI:           http://localhost:5173  (AgentScope 自带, 调试用)"
echo "   Platform API:     http://localhost:8100  (API 文档 /docs)"
echo "   Platform 前端:    http://localhost:5174  ★ 平台入口(两视图)"
echo "   日志:             $LOG_DIR/{postgresql,redis,backend,frontend,platform,platform-frontend}.log"
echo ""
echo " 停止服务: bash /d/Users/code/agentscope/stop.sh"
echo "------------------------------------------"
