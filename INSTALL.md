# RAGFlow 原生部署安装指南

> 在 Linux 物理机/虚拟机上从源码部署 RAGFlow，不依赖 Docker 运行 RAGFlow 本体（基础设施用 Docker）。

## 环境要求

| 组件 | 要求 |
|------|------|
| OS | Ubuntu 20.04+ / CentOS 7+ |
| Python | 3.13+ (通过 `uv` 管理) |
| Node.js | 18+ |
| uv | 最新版 (`curl -LsSf https://astral.sh/uv/install.sh \| sh`) |
| Docker | 仅用于 MySQL / ES / MinIO / Redis 基础设施 |

## 一、克隆项目

```bash
git clone https://github.com/infiniflow/ragflow.git
cd ragflow
```

## 二、安装 Python 依赖

```bash
# uv 会自动下载 Python 3.13+ 并创建 .venv
uv sync
```

> **注意**: RAGFlow v0.25+ 要求 Python >=3.13。`uv sync` 自动处理版本，无需手动安装。

## 三、准备 Docker 基础设施

RAGFlow 依赖以下外部服务，用 Docker Compose 启动：

```bash
cd docker

# 仅启动基础设施 (MySQL + ES + MinIO + Redis)
docker compose -f docker-compose-base.yml up -d
```

验证服务状态：

```bash
docker ps --filter "name=ragflow" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

预期输出：

| 容器名 | 端口映射 |
|--------|---------|
| ragflow_mysql | 5456→3306 |
| ragflow_es01 | 1200→9200 |
| ragflow_minio | 19000→9000 |
| ragflow_redis | 16380→6379 |

## 四、配置 service_conf.yaml

编辑 `conf/service_conf.yaml`，修改以下项：

```yaml
mysql:
  host: 'localhost'
  port: 5456                   # Docker 暴露端口，非默认 3306
  password: 'infini_rag_flow'

minio:
  host: 'localhost:19000'      # Docker 暴露端口，非默认 9000
  password: 'infini_rag_flow'

es:
  hosts: 'http://localhost:1200'

redis:
  db: 0
  password: 'infini_rag_flow'
  host: 'localhost:16380'      # Docker 暴露端口

# Embedding 模型 — 指向你的 vLLM/Ollama 服务
user_default_llm:
  default_models:
    embedding_model:
      name: 'qwen3-emb-0_6b'
      factory: 'OpenAI-API-Compatible'
      api_key: 'none'
      base_url: 'http://localhost:17000/v1'   # 改成你的 embedding 地址
```

> **关键**: 所有端口必须用 Docker 映射到宿主机的端口，不是容器内部端口。

## 五、启动 RAGFlow

### 一键启动

```bash
bash start.sh start
```

这会在后台依次启动：
1. **Web Server** (端口 9380) — REST API
2. **Task Executor** — 文档解析后台任务
3. **Web 前端** (端口 9223) — React UI

### 其他命令

```bash
bash start.sh stop      # 停止所有服务
bash start.sh status    # 查看运行状态
bash start.sh restart   # 重启所有服务
```

### 手动启动 (调试用)

```bash
# 1. 后端 API
PYTHONPATH=. HF_ENDPOINT=https://hf-mirror.com \
nohup .venv/bin/python api/ragflow_server.py > /tmp/ragflow_server.log 2>&1 &

# 2. 任务执行器 (文档解析必须)
PYTHONPATH=. HF_ENDPOINT=https://hf-mirror.com \
nohup .venv/bin/python rag/svr/task_executor.py 0 > /tmp/ragflow_taskexec.log 2>&1 &

# 3. 前端
cd web && npm install && PORT=9223 npm run dev -- --host 0.0.0.0 &
```

## 六、验证

```bash
# 后端 API
curl http://localhost:9380/api/v1/datasets \
  -H "Authorization: Bearer <your-api-key>"

# 前端界面
# 浏览器打开 http://<服务器IP>:9223/
```

## 七、常见问题

### 1. 文档解析卡住不动

**症状**: 文档 status 一直是 RUNNING，progress 始终 0%

**原因**:
- Task Executor 未启动
- HuggingFace 模型下载失败（国内网络）

**解决**:
```bash
# 确认 task executor 在运行
bash start.sh status

# 如果挂了，设置 HF 镜像重启
HF_ENDPOINT=https://hf-mirror.com bash start.sh restart
```

### 2. Redis 连接失败

**症状**: `Error 113 connecting to xxx:6379. No route to host.`

**原因**: `service_conf.yaml` 中 Redis 地址配置错误，指向了不可达的 IP。

**解决**: 确认 Redis 使用 Docker 暴露端口 `localhost:16380`。

### 3. MySQL 连接失败

**症状**: `Connection refused on localhost:3306`

**原因**: Docker MySQL 映射在 5456 端口，不是默认的 3306。

**解决**: `conf/service_conf.yaml` 中 mysql.port 改为 `5456`。

### 4. .doc 文件解析报错

**症状**: `File is not a zip file`

**原因**: RAGFlow 的 manual 解析器基于 python-docx，只支持 `.docx`（ZIP 格式），不支持旧版 `.doc` 二进制格式。

**解决**: `.doc` 文件仅上传不解析（均有对应 PDF 版本），在业务层跳过。

### 5. HuggingFace 模型下载超时

**症状**: `ConnectTimeout: [Errno 110]` 下载 `InfiniFlow/deepdoc`

**解决**: 设置环境变量 `HF_ENDPOINT=https://hf-mirror.com`，`start.sh` 已内置。

### 6. 端口冲突

**症状**: `address already in use`

**解决**: 修改 `start.sh` 顶部的 `BACKEND_PORT` / `FRONTEND_PORT` 变量，或杀掉占用进程。

### 7. OCR 解析速度极慢（未使用 GPU）

**症状**: 文档解析一直 RUNNING，每个 PDF 耗时 7-15 分钟，Task Executor 日志显示 `load_model ... uses CPU`

**原因**: `deepdoc/vision/ocr.py` 中 `cuda_is_available()` 通过 `torch.cuda.is_available()` 判断 GPU 可用性，但 RAGFlow venv 中未安装 PyTorch（OCR 实际使用 ONNX Runtime，不依赖 PyTorch）。即使 `onnxruntime-gpu` 已安装且 `CUDAExecutionProvider` 可用，仍回退到 CPU。

**解决**: 已修改 `deepdoc/vision/ocr.py`，`cuda_is_available()` 优先检查 ONNX Runtime 的 `CUDAExecutionProvider`，不再依赖 PyTorch：

```python
def cuda_is_available():
    try:
        return 'CUDAExecutionProvider' in ort.get_available_providers()
    except Exception:
        ...
```

重启后日志应显示 `load_model ... uses GPU (device 0, ...)`。

**性能对比**:

| 指标 | CPU | GPU |
|------|-----|-----|
| 单页 OCR | ~5s | ~0.5s |
| 100 页 PDF | ~8min | ~1min |

**GPU 显存调优** (可选):

```bash
export OCR_GPU_MEM_LIMIT_MB=4096  # 默认 2048MB，大模型可调高
```

### 8. start.sh 多 Worker 配置

`start.sh` 支持以下环境变量控制并发解析能力：

```bash
MAX_CONCURRENT_TASKS=10    # 每 worker 并发任务数 (默认 10)
TASK_EXECUTOR_COUNT=3      # worker 进程数 (默认 3)
TASK_EXECUTOR_OFFSET=3     # worker ID 起始编号，避免与其他实例冲突 (默认 3)
export MAX_CONCURRENT_TASKS
```

总并发解析容量 = `MAX_CONCURRENT_TASKS × TASK_EXECUTOR_COUNT`。例如默认配置 10×3=30 个并发解析槽位。

## 八、生产部署建议

- 使用 `vite build` 编译前端静态文件，由 nginx 托管
- 配置 systemd service 实现开机自启
- MySQL / ES 数据目录挂载到宿主机防止数据丢失
- 配置日志轮转 (`logrotate`)
