#!/usr/bin/env bash
# ============================================================================
# RAGFlow 一键启动脚本 (本仓库独立版)
# 参考 deepagents/scripts/start_ragflow.sh 改写: 去掉了 DeepAgents 代理,
# 端口改为从 conf/service_conf.yaml 自动解析, 组件入口适配本仓库代码。
#
# 用法: bash start.sh [run|start|stop|status|restart|check-runtime|logs [name]]
#
# 启动内容:
#   1. 依赖服务  (docker compose -f docker/docker-compose-base.yml up -d)
#   2. Web 后端   .venv/bin/python api/ragflow_server.py
#   3. 任务执行器 rag/svr/task_executor.py -i <id> -t <type>  (多个 worker)
#   4. 前端       web/ (npm run dev, 端口默认 9222)
#   5. [可选] Admin 服务 admin/server/admin_server.py  (START_ADMIN=1 时启动)
#
# 常用环境变量 (均有默认值, 也可覆盖):
#   FRONTEND_PORT=9222       前端端口 (与 web/vite.config.ts 默认一致)
#   SKIP_DEPS=1              跳过依赖服务检查/启动 (外部已启动时用)
#   REQUIRED_DEPS="mysql redis es minio"   需要就绪并自动拉起的依赖
#   RAGFLOW_EXTRA_SERVICES="clickhouse nats" 启动依赖时额外带上的 compose 服务
#   TASK_EXECUTOR_TYPES="common"  任务执行器类型 (可加 graphrag raptor resume)
#   TASK_EXECUTOR_COUNT=3    每种类型启动的 worker 数
#   TASK_EXECUTOR_OFFSET=3   worker ID 起始偏移 (避免与同一套依赖上其他
#                            ragflow 实例 (如 docker 里 root 的 worker 0..n) 冲突)
#   MAX_CONCURRENT_TASKS=10  每 worker 并发任务数 (导出给子进程)
#   START_ADMIN=1            额外启动 Admin 服务 (conf 中 admin.http_port=9381)
#   RAGFLOW_SERVICE_CONF=    自定义 service_conf.yaml 路径
#   HF_ENDPOINT=https://hf-mirror.com   HuggingFace 镜像 (国内服务器必须)
#   MYSQL_PORT/REDIS_PORT/ES_PORT/MINIO_PORT/BACKEND_PORT  手动覆盖端口
#
# 说明:
#   * 依赖服务(MySQL/Redis/MinIO/ES...)由 docker 容器承载, stop 不会停它们,
#     需要时用: cd docker && docker compose -f docker-compose-base.yml down
#   * 本脚本按 conf 默认的 elasticsearch 引擎启动依赖; 若改用 DOC_ENGINE=
#     infinity/opensearch/oceanbase, 请相应调整 REQUIRED_DEPS。
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
CONF_FILE="${RAGFLOW_SERVICE_CONF:-$PROJECT_DIR/conf/service_conf.yaml}"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
PYTHON_BOOTSTRAP="$PROJECT_DIR/scripts/start_python.py"
WEB_DIR="$PROJECT_DIR/web"
DOCKER_COMPOSE_DIR="$PROJECT_DIR/docker"

# 日志与 PID 目录 (可覆盖; 依赖它的 stop/status 需与 start 用同一个目录)
LOG_DIR="${LOG_DIR:-/tmp/ragflow}"
mkdir -p "$LOG_DIR"
LOG_SERVER="$LOG_DIR/server.log"
LOG_ADMIN="$LOG_DIR/admin.log"
LOG_WEB="$LOG_DIR/web.log"
PID_SERVER="$LOG_DIR/server.pid"
PID_ADMIN="$LOG_DIR/admin.pid"
PID_WEB="$LOG_DIR/web.pid"

# HuggingFace 镜像 (国内服务器必须, 可覆盖)
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONPATH="$PROJECT_DIR"

# 任务执行器配置
export MAX_CONCURRENT_TASKS="${MAX_CONCURRENT_TASKS:-10}"   # 每 worker 并发解析数
TASK_EXECUTOR_TYPES="${TASK_EXECUTOR_TYPES:-common}"         # 空格分隔: common graphrag raptor resume
TASK_EXECUTOR_COUNT="${TASK_EXECUTOR_COUNT:-3}"              # 每种类型 worker 数
TASK_EXECUTOR_OFFSET="${TASK_EXECUTOR_OFFSET:-3}"            # worker ID 起始偏移

# 前端端口 (vite.config.ts 默认 9222)
FRONTEND_PORT="${FRONTEND_PORT:-9222}"

# ============================================================================
# 从 conf/service_conf.yaml 解析各依赖端口 (用仓库 venv 的 pyyaml, 最可靠)
# 输出 CONF_<NAME>_PORT=xxx 供 eval; 解析失败时静默, 由下面的兜底默认值接管
# ============================================================================
read_service_ports() {
    "$VENV_PYTHON" - "$CONF_FILE" <<'PY'
import re, sys, yaml
from urllib.parse import urlsplit

path = sys.argv[1] if len(sys.argv) > 1 else "conf/service_conf.yaml"
try:
    conf = yaml.safe_load(open(path, encoding="utf-8")) or {}
except Exception:
    conf = {}

def split_host_port(h):
    """接受 'localhost:6379' / 'http://localhost:1200' / 裸 host / ipv6 形式"""
    if not h:
        return None, None
    h = str(h).strip()
    if "://" in h:
        net = urlsplit(h).netloc
        h = net if net else urlsplit(h).path
    if "@" in h:
        h = h.rsplit("@", 1)[1]
    if h.startswith("["):  # [::1]:port
        m = re.match(r"\[([^\]]+)\](?::(\d+))?", h)
        if m:
            return m.group(1), int(m.group(2)) if m.group(2) else None
        return h, None
    if h.count(":") == 1:
        host, port = h.rsplit(":", 1)
        if port.isdigit():
            return host, int(port)
        return h, None
    if h.count(":") > 1:  # 裸 ipv6
        return h, None
    return h, None

def section(name):
    s = conf.get(name)
    return s if isinstance(s, dict) else {}

mysql  = section("mysql")
redis  = section("redis")
minio  = section("minio")
es     = section("es")
ragflow= section("ragflow")

mysql_port = mysql.get("port") or 3306

redis_port = redis.get("port")
if not redis_port:
    _, redis_port = split_host_port(redis.get("host"))
redis_port = redis_port or 6379

_, minio_port = split_host_port(minio.get("host"))
minio_port = minio_port or 9000

es_host = es.get("hosts") or es.get("host")
if es_host:
    _, es_port = split_host_port(str(es_host).split(",")[0])
    es_port = es_port or 1200
else:
    es_port = None  # conf 里没有 ES -> 不检查不启动 ES

ragflow_port = ragflow.get("http_port") or ragflow.get("port") or 9380

out = {"CONF_MYSQL_PORT": mysql_port, "CONF_REDIS_PORT": redis_port,
       "CONF_MINIO_PORT": minio_port, "CONF_RAGFLOW_PORT": ragflow_port}
if es_port:
    out["CONF_ES_PORT"] = es_port
for k, v in out.items():
    print("%s=%s" % (k, v))
PY
}

# 端口配置: 环境变量 > conf 解析值 > 仓库默认值
_CONF_PORTS=""
if [ -x "$VENV_PYTHON" ] && [ -f "$CONF_FILE" ]; then
    _CONF_PORTS="$(read_service_ports 2>/dev/null)"
    [ -n "$_CONF_PORTS" ] && eval "$_CONF_PORTS"
else
    echo "[conf] 警告: 找不到 $VENV_PYTHON 或 $CONF_FILE, 使用默认端口" >&2
fi

BACKEND_PORT="${BACKEND_PORT:-${CONF_RAGFLOW_PORT:-9380}}"   # 后端 API (conf ragflow.http_port)
MYSQL_PORT="${MYSQL_PORT:-${CONF_MYSQL_PORT:-3306}}"
REDIS_PORT="${REDIS_PORT:-${CONF_REDIS_PORT:-6379}}"
MINIO_PORT="${MINIO_PORT:-${CONF_MINIO_PORT:-9000}}"
ES_PORT="${ES_PORT:-${CONF_ES_PORT:-1200}}"

# 需要就绪并自动拉起的依赖 (名 -> 端口变量, 见 dep_port)
REQUIRED_DEPS="${REQUIRED_DEPS:-mysql redis es minio}"
# 启动依赖时额外带上的 compose 服务 (不会做端口探测)
RAGFLOW_EXTRA_SERVICES="${RAGFLOW_EXTRA_SERVICES:-}"

# ============================================================================
# 基础工具
# ============================================================================
run_docker_compose() { docker compose "$@"; }

check_port() { ss -tln 2>/dev/null | grep -qE ":$1\s"; }

wait_port() {  # wait_port <port> <timeout_seconds>
    local port="$1" timeout="$2" i
    for ((i = 0; i < timeout; i++)); do
        check_port "$port" && return 0
        sleep 1
    done
    return 1
}

dep_port() {
    case "$1" in
        mysql)  echo "$MYSQL_PORT" ;;
        redis)  echo "$REDIS_PORT" ;;
        es)     echo "$ES_PORT" ;;
        minio)  echo "$MINIO_PORT" ;;
        *)      local v; v="$(echo "$1" | tr 'a-z' 'A-Z')_PORT"; eval "echo \"\${$v:-}\"" ;;
    esac
}

# 依赖名 -> docker-compose-base.yml 里的服务名
dep_service() {
    case "$1" in
        es)          echo es01 ;;
        opensearch)  echo opensearch01 ;;
        *)           echo "$1" ;;
    esac
}

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -z "$LAN_IP" ] && LAN_IP="127.0.0.1"

# 杀掉占用指定端口的进程 (用于清理僵尸进程; 非本用户进程需要 root 才能看到 pid)
kill_port() {
    local port="$1" pids pid
    pids="$(ss -tlnp 2>/dev/null | grep -E ":$port\s" | grep -oP 'pid=\K[0-9]+' | sort -u)"
    for pid in $pids; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "  [cleanup] 杀掉占用端口 $port 的进程 PID=$pid"
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
}

# 优雅停止一个 pid 文件追踪的进程
stop_pidfile() {
    local pid_file="$1" pid i
    [ -f "$pid_file" ] || return 0
    pid="$(cat "$pid_file")"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "停止 PID=$pid ($(basename "$pid_file"))"
        pkill -9 -P "$pid" 2>/dev/null || true
        kill "$pid" 2>/dev/null || true
        for i in $(seq 1 20); do          # 最多等 10s 优雅退出
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.5
        done
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
}

# 后台启动并记录【真实】进程 PID:
# 子shell exec nohup -> nohup exec 目标命令, PID 全程不变, 不会记录到外层 bash
launch_bg() {
    local pid_file="$1" log_file="$2"; shift 2
    ( exec nohup "$@" >"$log_file" 2>&1 ) &
    echo $! > "$pid_file"
}

# ============================================================================
# 依赖服务
# ============================================================================
check_and_start_deps() {
    [ "${SKIP_DEPS:-0}" = "1" ] && { echo "[deps] SKIP_DEPS=1, 跳过依赖检查"; return 0; }
    local dep p svc missing="" services="" missing_ports="" need_start=false

    for dep in $REQUIRED_DEPS; do
        p="$(dep_port "$dep")"
        if [ -z "$p" ]; then
            echo "[deps] 跳过 '$dep' (未配置 ${dep}_PORT)" >&2
            continue
        fi
        if check_port "$p"; then
            echo "[deps] $dep($p) 已在运行 ✓"
        else
            need_start=true
            missing="$missing $dep($p)"
            missing_ports="$missing_ports $p"
            svc="$(dep_service "$dep")"
            case " $services " in *" $svc "*) ;; *) services="$services $svc";; esac
        fi
    done

    if ! $need_start; then
        echo "[deps] 所有依赖服务已在运行 ✓"
        return 0
    fi

    services="$services $RAGFLOW_EXTRA_SERVICES"
    echo "[deps] 依赖服务未启动:$missing"
    echo "[deps] 逐个通过 docker compose 启动基础服务:$services"
    # 逐服务 up -d: 若某端口已被外部进程/容器占用, 只影响该服务,
    # 不会像整文件 up -d 那样拖垮 MySQL/MinIO 等其他服务
    local failed=false
    for svc in $services; do
        [ -z "$svc" ] && continue
        echo "[deps]   compose up -d $svc ..."
        if ( cd "$DOCKER_COMPOSE_DIR" && run_docker_compose -f docker-compose-base.yml up -d "$svc" ); then
            echo "[deps]   $svc 已启动"
        else
            echo "[deps]   $svc 启动失败(端口可能被占用或镜像缺失), 跳过" >&2
            failed=true
        fi
    done
    if $failed; then
        echo "[deps] 有服务启动失败, 可用: cd docker && docker compose -f docker-compose-base.yml logs <服务名>" >&2
    fi

    echo "[deps] 等待服务就绪 (最长 120s)..."
    local waited=0 allok=true
    while [ "$waited" -lt 120 ]; do
        allok=true
        for p in $missing_ports; do
            check_port "$p" || allok=false
        done
        $allok && break
        sleep 2
        waited=$((waited + 2))
    done
    local ready=true
    for dep in $REQUIRED_DEPS; do
        p="$(dep_port "$dep")"
        [ -z "$p" ] && continue
        if check_port "$p"; then
            echo "[deps] $dep($p) 已就绪 ✓"
        else
            echo "[deps] $dep($p) 等待超时, 可能未完全就绪" >&2
            ready=false
        fi
    done
    $ready || echo "[deps] 部分依赖未就绪, 请稍后用 status 复查或用 docker compose logs 排查" >&2
    return 0
}

# ============================================================================
# Web 后端  (api/ragflow_server.py, conf ragflow.http_port -> 9380)
# ============================================================================
start_server() {
    if [ -f "$PID_SERVER" ] && kill -0 "$(cat "$PID_SERVER")" 2>/dev/null; then
        echo "[server] 已在运行 PID=$(cat "$PID_SERVER")"
        return 0
    fi
    if check_port "$BACKEND_PORT"; then
        echo "[server] 端口 $BACKEND_PORT 已被占用(可能是外部实例), 跳过启动"
        return 0
    fi
    echo "[server] 启动 Web Server (端口 $BACKEND_PORT) → 日志 $LOG_SERVER"
    cd "$PROJECT_DIR" || return 1
    launch_bg "$PID_SERVER" "$LOG_SERVER" "$VENV_PYTHON" "$PYTHON_BOOTSTRAP" api/ragflow_server.py
    sleep 5
    if [ -f "$PID_SERVER" ] && kill -0 "$(cat "$PID_SERVER")" 2>/dev/null; then
        echo "[server] 进程已拉起 PID=$(cat "$PID_SERVER"), 等待端口 $BACKEND_PORT 就绪..."
        if wait_port "$BACKEND_PORT" 90; then
            echo "[server] 启动成功 ✓ http://${LAN_IP}:${BACKEND_PORT}/"
        else
            echo "[server] 进程存活但端口 90s 内未就绪, 请查看 $LOG_SERVER" >&2
        fi
    else
        echo "[server] 启动失败, 查看 $LOG_SERVER" >&2
        return 1
    fi
}

# ============================================================================
# Admin 服务 (可选, conf admin.http_port -> 9381)
# ============================================================================
start_admin() {
    [ "${START_ADMIN:-0}" = "1" ] || return 0
    if [ -f "$PID_ADMIN" ] && kill -0 "$(cat "$PID_ADMIN")" 2>/dev/null; then
        echo "[admin] 已在运行 PID=$(cat "$PID_ADMIN")"
        return 0
    fi
    echo "[admin] 启动 Admin Server (端口 ${ADMIN_PORT:-9381}) → 日志 $LOG_ADMIN"
    cd "$PROJECT_DIR" || return 1
    launch_bg "$PID_ADMIN" "$LOG_ADMIN" "$VENV_PYTHON" "$PYTHON_BOOTSTRAP" admin/server/admin_server.py
    sleep 5
    if [ -f "$PID_ADMIN" ] && kill -0 "$(cat "$PID_ADMIN")" 2>/dev/null; then
        echo "[admin] 启动成功 PID=$(cat "$PID_ADMIN")"
    else
        echo "[admin] 启动失败, 查看 $LOG_ADMIN" >&2
        return 1
    fi
}

# ============================================================================
# 任务执行器  (rag/svr/task_executor.py -i <id> -t <type>)
# ============================================================================
start_taskexec() {
    local type idx worker_id pid_file all_running=true i
    for type in $TASK_EXECUTOR_TYPES; do
        for ((i = 0; i < TASK_EXECUTOR_COUNT; i++)); do
            worker_id=$((i + TASK_EXECUTOR_OFFSET))
            pid_file="$LOG_DIR/taskexec_${type}_${worker_id}.pid"
            if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
                echo "[taskexec-$type-$worker_id] 已在运行 PID=$(cat "$pid_file")"
                continue
            fi
            echo "[taskexec-$type-$worker_id] 启动 Task Executor (类型=$type ID=$worker_id)..."
            cd "$PROJECT_DIR" || return 1
            launch_bg "$pid_file" "$LOG_DIR/taskexec_${type}_${worker_id}.log" \
                "$VENV_PYTHON" "$PYTHON_BOOTSTRAP" rag/svr/task_executor.py -t "$type" -i "$worker_id"
            sleep 2
            if kill -0 "$(cat "$pid_file")" 2>/dev/null; then
                echo "[taskexec-$type-$worker_id] 启动成功 PID=$(cat "$pid_file")"
            else
                echo "[taskexec-$type-$worker_id] 启动失败, 查看 $LOG_DIR/taskexec_${type}_${worker_id}.log" >&2
                all_running=false
            fi
        done
    done
    $all_running || return 1
}

# ============================================================================
# 前端 (web/, vite dev, 默认 9222)
# ============================================================================
start_web() {
    if [ -f "$PID_WEB" ] && kill -0 "$(cat "$PID_WEB")" 2>/dev/null; then
        echo "[web] 已在运行 PID=$(cat "$PID_WEB")"
        return 0
    fi
    # 端口冲突清理: 非本脚本管理的占用进程先杀掉 (多次 restart 会积累僵尸)
    if check_port "$FRONTEND_PORT"; then
        local managed_pid="" ppid
        [ -f "$PID_WEB" ] && managed_pid="$(cat "$PID_WEB")"
        for ppid in $(ss -tlnp 2>/dev/null | grep -E ":$FRONTEND_PORT\s" | grep -oP 'pid=\K[0-9]+' | sort -u); do
            if [ "$ppid" != "$managed_pid" ]; then
                echo "[web] 端口 $FRONTEND_PORT 被僵尸进程 PID=$ppid 占用, 强制清理..."
                kill -9 "$ppid" 2>/dev/null || true
                sleep 1
            fi
        done
    fi
    echo "[web] 启动 Web 前端 (端口 $FRONTEND_PORT) → 日志 $LOG_WEB"
    if [ ! -d "$WEB_DIR/node_modules" ]; then
        echo "[web] 安装前端依赖..."
        ( cd "$WEB_DIR" && npm install --silent )
    fi
    cd "$WEB_DIR" || return 1
    launch_bg "$PID_WEB" "$LOG_WEB" npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT"
    sleep 4
    if [ -f "$PID_WEB" ] && kill -0 "$(cat "$PID_WEB")" 2>/dev/null; then
        if wait_port "$FRONTEND_PORT" 30; then
            echo "[web] 启动成功 ✓ http://${LAN_IP}:${FRONTEND_PORT}/"
        else
            echo "[web] npm 进程存活但端口未就绪, 查看 $LOG_WEB" >&2
        fi
    else
        echo "[web] 启动失败, 查看 $LOG_WEB" >&2
        return 1
    fi
}

# ============================================================================
# 停止 / 状态
# ============================================================================
stop_all() {
    stop_pidfile "$PID_SERVER"
    stop_pidfile "$PID_WEB"
    stop_pidfile "$PID_ADMIN"
    for pid_file in "$LOG_DIR"/taskexec_*.pid; do
        [ -f "$pid_file" ] && stop_pidfile "$pid_file"
    done
    # 强制清理端口残留 (vite 的 node 子进程在 npm 被杀后可能存活)
    kill_port "$FRONTEND_PORT"
    pkill -9 -f "vite.*--port.*$FRONTEND_PORT" 2>/dev/null || true
    echo "RAGFlow 原生服务已停止 (docker 依赖容器仍在运行)"
}

status_all() {
    echo "══════════════════════════════════════════════════"
    echo " RAGFlow 服务状态  (backend=${BACKEND_PORT}, types=${TASK_EXECUTOR_TYPES}, workers/type=${TASK_EXECUTOR_COUNT})"
    echo "══════════════════════════════════════════════════"
    local name port running=""
    for name in server web admin; do
        case "$name" in
            server) port="$BACKEND_PORT";;
            web)    port="$FRONTEND_PORT";;
            admin)  [ "${START_ADMIN:-0}" = "1" ] || continue; port="${ADMIN_PORT:-9381}";;
        esac
        pid_file="$LOG_DIR/$name.pid"
        if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
            echo "  $name : 运行中 (PID=$(cat "$pid_file"), 端口 $port)"
            running=" $name$running"
        elif check_port "$port"; then
            echo "  $name : 运行中 (PID 文件丢失, 端口 $port 被占用)"
        else
            echo "  $name : 已停止"
        fi
    done

    local count=0
    for pid_file in "$LOG_DIR"/taskexec_*.pid; do
        if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
            local bn; bn="$(basename "$pid_file" .pid)"
            echo "  $bn : 运行中 (PID=$(cat "$pid_file"))"
            ((count++))
        fi
    done
    echo "  task executor workers : ${count} 个运行中"

    echo ""
    echo " 后端 API : http://${LAN_IP}:${BACKEND_PORT}/"
    echo " 前端 UI  : http://${LAN_IP}:${FRONTEND_PORT}/"
    [ "${START_ADMIN:-0}" = "1" ] && echo " Admin    : http://${LAN_IP}:${ADMIN_PORT:-9381}/"
    echo ""
    echo "端口监听:"
    for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
        if check_port "$port"; then
            echo "  $port ✓ 已监听"
        else
            echo "  $port ✗ 未监听"
        fi
    done
    echo "依赖服务 (docker 容器):"
    local dep p
    for dep in $REQUIRED_DEPS; do
        p="$(dep_port "$dep")"
        [ -n "$p" ] || continue
        check_port "$p" && echo "  $dep($p) ✓" || echo "  $dep($p) ✗"
    done
    echo "══════════════════════════════════════════════════"
}

logs_all() {
    local name="$1"
    case "$name" in
        server)  tail -n 100 -f "$LOG_SERVER";;
        web)     tail -n 100 -f "$LOG_WEB";;
        admin)   tail -n 100 -f "$LOG_ADMIN";;
        taskexec)
            # 找最近修改的一个 task executor 日志
            local latest; latest="$(ls -t "$LOG_DIR"/taskexec_*.log 2>/dev/null | head -1)"
            [ -n "$latest" ] && tail -n 100 -f "$latest" || echo "无 task executor 日志"
            ;;
        all|"")  tail -n 100 -f "$LOG_SERVER" "$LOG_WEB" 2>/dev/null;;
        *)
            local f="$LOG_DIR/taskexec_${name}.log"
            [ -f "$f" ] && tail -n 100 -f "$f" || { echo "用法: bash start.sh logs [server|web|admin|taskexec|taskexec_<type>_<id>|all]"; exit 1; }
            ;;
    esac
}

# ============================================================================
case "${1:-start}" in
    start|run)
        echo "===== RAGFlow 一键启动 ====="
        "$VENV_PYTHON" "$PYTHON_BOOTSTRAP" --check || { echo "[runtime] 环境检查失败，未启动服务" >&2; exit 1; }
        check_and_start_deps || { echo "[deps] 依赖启动失败, 终止"; exit 1; }
        start_server || exit 1
        start_taskexec || exit 1
        start_web || exit 1
        start_admin || exit 1
        echo "===== 全部启动完成 ====="
        echo "启动耗时较长时请耐心等待初始化, 或查看日志: bash start.sh logs server"
        ;;
    stop)
        stop_all
        ;;
    status)
        status_all
        ;;
    check-runtime)
        exec "$VENV_PYTHON" "$PYTHON_BOOTSTRAP" --check
        ;;
    restart)
        stop_all
        sleep 2
        exec bash "$0" start
        ;;
    logs)
        logs_all "${2:-all}"
        ;;
    *)
        echo "用法: bash start.sh [run|start|stop|status|restart|check-runtime|logs [server|web|taskexec|admin|all]]"
        exit 1
        ;;
esac
