#!/bin/bash
# ============================================================
# 造价平台本地服务 —— 一键停止脚本
#
# 停止方式(三重保险, 确保不残留"僵尸"进程):
#   1. 按 logs/service-pids.txt 里记录的根进程, 整棵进程树强制结束
#      (只结束监听端口的进程会留下 pnpm/concurrently 等子进程
#       变成孤儿进程锁住日志文件, 所以必须从进程树根部结束)
#   2. 按端口兜底: 结束仍在监听 5173/3100/8000/8100/6379 的进程树
#   3. 清扫命令行里带 web_ui 的残留 node 进程
#   PostgreSQL 不走强杀, 单独用 pg_ctl 优雅停止(避免数据损坏)
#
# ▶ 执行命令 —— Git Bash 终端里(任意目录均可):
#     bash /d/Users/code/agentscope/stop.sh
#
# ▶ 执行命令 —— PowerShell / CMD 里(任意目录均可):
#     D:\Users\58369\Git\bin\bash.exe /d/Users/code/agentscope/stop.sh
#
# ▶ 重新启动服务:
#     bash /d/Users/code/agentscope/start.sh
#     D:\Users\58369\Git\bin\bash.exe /d/Users/code/agentscope/start.sh
# ============================================================

BASE_DIR="/d/Users/code/agentscope"
PG_DIR="/d/Users/58369/postgresql"
LOG_DIR="$BASE_DIR/logs"
PID_FILE="$LOG_DIR/service-pids.txt"

# 检查端口是否处于监听状态
port_up() {
    netstat -ano | tr -d '\r' | grep "LISTENING" | grep -q ":$1 "
}

echo "=========================================="
echo " 造价平台本地服务停止"
echo "=========================================="

# ---------- 1. 按记录的根进程整树结束 ----------
if [ -f "$PID_FILE" ]; then
    while read -r name pid; do
        [ -n "${pid:-}" ] || continue
        echo "  停止 $name (PID $pid)..."
        taskkill //PID "$pid" //T //F >/dev/null 2>&1 || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
else
    echo "  (无 PID 记录, 按端口清理)"
fi

# ---------- 2. 按端口兜底(不含 5432, PG 由 pg_ctl 优雅停止) ----------
for port in 5173 3100 8000 8100 6379; do
    if port_up "$port"; then
        pids=$(netstat -ano | tr -d '\r' | grep "LISTENING" | grep ":$port " | awk '{print $NF}' | sort -u)
        for pid in $pids; do
            echo "  端口 $port 仍被 PID $pid 占用, 强制结束..."
            taskkill //PID "$pid" //T //F >/dev/null 2>&1 || true
        done
    fi
done

# ---------- 3. 清扫残留的 web_ui 相关 node 进程 ----------
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { \$_.CommandLine -match 'web_ui' } | ForEach-Object { Write-Host ('  清扫残留 node 进程 PID ' + \$_.ProcessId); taskkill /PID \$_.ProcessId /T /F | Out-Null }" >/dev/null 2>&1 || true

# ---------- 4. PostgreSQL 优雅停止(fast 模式: 断开连接+正常落盘) ----------
if port_up 5432; then
    echo "  停止 PostgreSQL (pg_ctl fast shutdown)..."
    # 输出重定向到文件, 不接管道(postgres 会继承管道句柄导致卡死)
    "$PG_DIR/bin/pg_ctl.exe" -D "$PG_DIR/data" stop -m fast \
        >> "$LOG_DIR/postgresql.log" 2>&1
else
    echo "  PostgreSQL 未在运行"
fi

# ---------- 结果确认 ----------
sleep 1
remaining=""
for port in 6379 8000 8100 3100 5173 5432; do
    port_up "$port" && remaining="$remaining $port"
done
echo "------------------------------------------"
if [ -n "$remaining" ]; then
    echo " [警告] 以下端口仍被占用:$remaining"
    echo "        可能被其他程序占用, 请手动检查 (如 3000 端口是 GitFox, 不属于本服务)"
else
    echo " 全部服务已停止, 端口 5432/6379/8000/3100/5173/8100 均已释放"
fi
echo "------------------------------------------"
