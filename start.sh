#!/bin/bash
# ============================================================
# AgentScope 本地服务 —— 一键启动脚本
#
# 按依赖顺序启动(前一个就绪后才启动下一个):
#   1. Redis          存储后端       端口 6379
#   2. Agent Service  Python 后端    端口 8000
#   3. Web UI         前端 5173 + Node 后端 3100
#
# 所有服务的输出都追加写入 logs/ 目录:
#   logs/redis.log  logs/backend.log  logs/frontend.log
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
echo " AgentScope 本地服务启动"
echo "=========================================="

# ---------- 1. Redis ----------
if port_up 6379; then
    echo "[1/3] Redis 已在运行 (端口 6379), 跳过"
else
    if [ ! -f "$REDIS_DIR/redis-server.exe" ]; then
        echo "[错误] 未找到 $REDIS_DIR/redis-server.exe"
        exit 1
    fi
    echo "[1/3] 启动 Redis (端口 6379)..."
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

# ---------- 2. Agent Service (Python 后端) ----------
if port_up 8000; then
    echo "[2/3] Python 后端已在运行 (端口 8000), 跳过"
else
    echo "[2/3] 启动 Agent Service (端口 8000)..."
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
        echo "      后端就绪 (API 文档: http://localhost:8000/docs)"
    else
        echo "      [错误] 后端启动失败, 最近日志 (logs/backend.log):"
        tail -n 8 "$LOG_DIR/backend.log" | sed 's/^/        /'
        exit 1
    fi
fi

# ---------- 3. Web UI (前端 + Node 后端) ----------
export PATH="/c/Program Files/nodejs:/c/Users/58369/AppData/Roaming/npm:$PATH"
if ! command -v pnpm >/dev/null 2>&1; then
    echo "[错误] 未找到 pnpm, 请检查 Node.js 安装"
    exit 1
fi
if port_up 5173; then
    echo "[3/3] Web UI 已在运行 (端口 5173), 跳过"
else
    echo "[3/3] 启动 Web UI (前端 5173, Node 后端 3100)..."
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

echo "------------------------------------------"
echo " 全部服务已启动:"
echo "   前端:    http://localhost:5173"
echo "   后端:    http://localhost:8000  (API 文档 /docs)"
echo "   Redis:   localhost:6379"
echo "   日志:    $LOG_DIR/{redis,backend,frontend}.log"
echo ""
echo " 停止服务: bash /d/Users/code/agentscope/stop.sh"
echo "------------------------------------------"
