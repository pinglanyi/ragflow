#!/usr/bin/env bash
# RAGFlow 一键启动脚本 — 后端 + 任务执行器 + 前端
# 用法: bash start.sh [start|stop|status|restart]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
WEB_DIR="$PROJECT_DIR/web"

# 端口配置
BACKEND_PORT=9381
FRONTEND_PORT=9223

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
    echo "[web] 启动 Web 前端 (端口 $FRONTEND_PORT)..."
    cd "$WEB_DIR"
    if [ ! -d "node_modules" ]; then
        echo "[web] 安装前端依赖..."
        npm install --silent
    fi
    PORT="$FRONTEND_PORT" nohup npm run dev -- --host 0.0.0.0 > "$LOG_WEB" 2>&1 &
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
    for pid_file in "$PID_SERVER" "$PID_WEB"; do
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
            if kill -0 "$pid" 2>/dev/null; then
                echo "停止 PID=$pid ($(basename "$pid_file"))"
                kill "$pid" 2>/dev/null || true
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
                kill "$pid" 2>/dev/null || true
            fi
            rm -f "$pid_file"
        fi
    done
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
    echo " 后端 API : http://0.0.0.0:$BACKEND_PORT/"
    echo " 前端 UI : http://0.0.0.0:$FRONTEND_PORT/"
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
