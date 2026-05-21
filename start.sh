#!/usr/bin/env bash
# RAGFlow 一键启动脚本 — 后端 + 任务执行器 + 前端
# 用法: bash start.sh [start|stop|status|restart]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
WEB_DIR="$PROJECT_DIR/web"

# 端口配置
BACKEND_PORT="${BACKEND_PORT:-9380}"     # 后端 API 端口 (从 service_conf.yaml 读取, 这里仅用于 echo)
FRONTEND_PORT="${FRONTEND_PORT:-9222}"   # 前端 UI 端口

# 日志
LOG_DIR="/tmp/ragflow"
mkdir -p "$LOG_DIR"

LOG_SERVER="$LOG_DIR/server.log"
LOG_TASKEXEC="$LOG_DIR/taskexec.log"
LOG_WEB="$LOG_DIR/web.log"
PID_SERVER="$LOG_DIR/server.pid"
PID_TASKEXEC="$LOG_DIR/taskexec.pid"
PID_WEB="$LOG_DIR/web.pid"

# HuggingFace 镜像 (国内服务器必须)
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONPATH="$PROJECT_DIR"

# 任务执行器配置
MAX_CONCURRENT_TASKS="${MAX_CONCURRENT_TASKS:-10}"   # 每 worker 并发解析数 (默认 5 → 10)
TASK_EXECUTOR_COUNT="${TASK_EXECUTOR_COUNT:-3}"       # task executor worker 数量 (默认 1 → 3)
TASK_EXECUTOR_OFFSET="${TASK_EXECUTOR_OFFSET:-3}"     # worker ID 起始偏移 (避免与 root 的 worker 冲突)
export MAX_CONCURRENT_TASKS

# 端口清理: 杀掉占用指定端口的进程 (用于清理僵尸进程)
kill_port() {
    local port="$1"
    local pids
    pids=$(ss -tlnp 2>/dev/null | grep -E ":$port\s" | grep -oP 'pid=\K[0-9]+' | sort -u)
    for pid in $pids; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "  [cleanup] 杀掉占用端口 $port 的进程 PID=$pid"
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
}

# ══════════════════════════════════════════════════════════════════════
start_server() {
    if [ -f "$PID_SERVER" ] && kill -0 "$(cat "$PID_SERVER")" 2>/dev/null; then
        echo "[server] 已在运行 PID=$(cat "$PID_SERVER")"
        return
    fi
    echo "[server] 启动 Web Server (端口 $BACKEND_PORT)..."
    cd "$PROJECT_DIR"
    nohup "$VENV_PYTHON" api/ragflow_server.py > "$LOG_SERVER" 2>&1 &
    echo $! > "$PID_SERVER"
    sleep 3
    if kill -0 "$(cat "$PID_SERVER")" 2>/dev/null; then
        echo "[server] 启动成功 PID=$(cat "$PID_SERVER")"
    else
        echo "[server] 启动失败, 查看 $LOG_SERVER"
        return 1
    fi
}

start_taskexec() {
    # 启动多个 task executor worker
    local count="${TASK_EXECUTOR_COUNT:-3}"
    local offset="${TASK_EXECUTOR_OFFSET:-3}"
    local all_running=true

    for ((i=0; i<count; i++)); do
        local worker_id=$((i + offset))
        local pid_file="$LOG_DIR/taskexec_${worker_id}.pid"
        if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
            echo "[taskexec-${worker_id}] 已在运行 PID=$(cat "$pid_file")"
            continue
        fi
        echo "[taskexec-${worker_id}] 启动 Task Executor worker ${worker_id}..."
        cd "$PROJECT_DIR"
        nohup "$VENV_PYTHON" rag/svr/task_executor.py "${worker_id}" > "$LOG_DIR/taskexec_${worker_id}.log" 2>&1 &
        echo $! > "$pid_file"
        sleep 2
        if kill -0 "$(cat "$pid_file")" 2>/dev/null; then
            echo "[taskexec-${worker_id}] 启动成功 PID=$(cat "$pid_file")"
        else
            echo "[taskexec-${worker_id}] 启动失败, 查看 $LOG_DIR/taskexec_${worker_id}.log"
            all_running=false
        fi
    done
    $all_running || return 1
}

start_web() {
    if [ -f "$PID_WEB" ] && kill -0 "$(cat "$PID_WEB")" 2>/dev/null; then
        echo "[web] 已在运行 PID=$(cat "$PID_WEB")"
        return
    fi
    # 检查端口冲突: 如果 $FRONTEND_PORT 被非本脚本管理的进程占用，先清理
    if ss -tlnp 2>/dev/null | grep -qE ":$FRONTEND_PORT\s"; then
        managed_pid=""
        [ -f "$PID_WEB" ] && managed_pid=$(cat "$PID_WEB")
        port_pids=$(ss -tlnp 2>/dev/null | grep -E ":$FRONTEND_PORT\s" | grep -oP 'pid=\K[0-9]+' | sort -u)
        for ppid in $port_pids; do
            if [ "$ppid" != "$managed_pid" ]; then
                echo "[web] 端口 $FRONTEND_PORT 被僵尸进程 PID=$ppid 占用，强制清理..."
                kill -9 "$ppid" 2>/dev/null || true
                sleep 1
            fi
        done
    fi
    echo "[web] 启动 Web 前端 (端口 $FRONTEND_PORT)..."
    cd "$WEB_DIR"
    if [ ! -d "node_modules" ]; then
        echo "[web] 安装前端依赖..."
        npm install --silent
    fi
    PORT="$FRONTEND_PORT" nohup npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" > "$LOG_WEB" 2>&1 &
    echo $! > "$PID_WEB"
    sleep 4
    if kill -0 "$(cat "$PID_WEB")" 2>/dev/null; then
        echo "[web] 启动成功 PID=$(cat "$PID_WEB") → http://$(hostname -I 2>/dev/null | awk '{print $1}'):$FRONTEND_PORT/"
    else
        echo "[web] 启动失败, 查看 $LOG_WEB"
        return 1
    fi
}

stop_all() {
    # 停止通过 PID 文件追踪的进程
    for pid_file in "$PID_SERVER" "$PID_WEB"; do
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
            if kill -0 "$pid" 2>/dev/null; then
                echo "停止 PID=$pid ($(basename "$pid_file"))"
                kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
                sleep 0.5
            fi
            rm -f "$pid_file"
        fi
    done
    # 停止所有 task executor worker
    for pid_file in "$LOG_DIR"/taskexec_*.pid; do
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
            if kill -0 "$pid" 2>/dev/null; then
                echo "停止 PID=$pid ($(basename "$pid_file"))"
                kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
            fi
            rm -f "$pid_file"
        fi
    done
    # 强制清理端口上的残留进程 (多次 restart 容易积累僵尸)
    kill_port "$FRONTEND_PORT"
    # 也清理可能残留的 vite node 进程（父进程 npm 被 kill 后子进程可能存活）
    pkill -9 -f "vite.*--port.*$FRONTEND_PORT" 2>/dev/null || true
    echo "所有服务已停止"
}

status_all() {
    echo "══════════════════════════════════════"
    echo " RAGFlow 服务状态 (MAX_CONCURRENT_TASKS=${MAX_CONCURRENT_TASKS})"
    echo "══════════════════════════════════════"
    for name in server web; do
        pid_file="$LOG_DIR/$name.pid"
        if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
            echo "  $name: 运行中 (PID=$(cat "$pid_file"))"
        else
            echo "  $name: 已停止"
        fi
    done
    # task executor workers
    local taskexec_count=0
    for pid_file in "$LOG_DIR"/taskexec_*.pid; do
        if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
            local bn=$(basename "$pid_file" .pid)
            echo "  $bn: 运行中 (PID=$(cat "$pid_file"))"
            ((taskexec_count++))
        fi
    done
    echo "  task executor workers: ${taskexec_count} 个运行中"
    echo ""
    echo " 后端 API : http://localhost:${BACKEND_PORT}/"
    echo " 前端 UI : http://localhost:${FRONTEND_PORT}/"
    echo ""
    # 端口健康检查
    echo "端口监听:"
    for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
        if ss -tlnp 2>/dev/null | grep -qE ":$port\s"; then
            pids=$(ss -tlnp 2>/dev/null | grep -E ":$port\s" | grep -oP 'pid=\K[0-9]+' | sort -u | tr '\n' ',' | sed 's/,$//')
            echo "  $port ✓ (PID=$pids)"
        else
            echo "  $port ✗ 未监听"
        fi
    done
    echo "══════════════════════════════════════"
}

# ══════════════════════════════════════════════════════════════════════
case "${1:-start}" in
    start)
        echo "===== RAGFlow 一键启动 ====="
        start_server
        start_taskexec
        start_web
        echo "===== 全部启动完成 ====="
        ;;
    stop)
        stop_all
        ;;
    status)
        status_all
        ;;
    restart)
        stop_all
        sleep 2
        exec bash "$0" start
        ;;
    *)
        echo "用法: bash start.sh [start|stop|status|restart]"
        exit 1
        ;;
esac
