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
| GPU | 推荐 NVIDIA GPU + CUDA 12+（OCR 加速 10x） |

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
>
> **GPU 用户**: 确认 `onnxruntime-gpu` 已安装（而非 `onnxruntime`）:
> ```bash
> .venv/bin/pip list | grep onnxruntime
> # 应显示: onnxruntime-gpu
> ```

## 三、准备 Docker 基础设施

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

## 五、GPU OCR 加速配置

RAGFlow 使用 ONNX Runtime 进行 OCR（文本检测 & 识别），支持 CUDA GPU 加速。

### 5.1 检查 GPU 可用性

```bash
# 确认 GPU 驱动正常
nvidia-smi

# 确认 onnxruntime-gpu 可用 CUDA
.venv/bin/python -c "import onnxruntime; print(onnxruntime.get_available_providers())"
# 应包含: CUDAExecutionProvider
```

### 5.2 确认 GPU OCR 补丁

`deepdoc/vision/ocr.py` 中的 `cuda_is_available()` 已被修改为直接检查 ONNX Runtime providers，不再依赖 PyTorch：

```python
def cuda_is_available():
    try:
        return 'CUDAExecutionProvider' in ort.get_available_providers()
    except Exception:
        ...
```

### 5.3 验证 GPU 生效

启动后检查 task executor 日志：

```bash
grep "load_model.*uses" /tmp/ragflow/taskexec_3.log | head -5
# 应显示: load_model .../det.onnx uses GPU (device 0, ...)
#         load_model .../rec.onnx uses GPU (device 0, ...)
#         load_model .../layout.onnx uses GPU (device 0, ...)
#         load_model .../tsr.onnx uses GPU (device 0, ...)
```

如果显示 `uses CPU`，说明 GPU 未生效，检查 `onnxruntime-gpu` 是否安装。

### 5.4 GPU 显存调优

```bash
export OCR_GPU_MEM_LIMIT_MB=4096          # 默认 2048MB，大模型可调高
export OCR_GPU_MEM_ARENA_SHRINKAGE=1      # 启用显存回收 (默认关闭)
export OCR_INTRA_OP_NUM_THREADS=2         # ONNX 内部线程数 (默认 2)
```

### 5.5 性能参考

| 指标 | CPU | GPU |
|------|-----|-----|
| 单页文本检测 | ~2-3s | ~0.3s |
| 单页文本识别 | ~0.05s | ~0.00001s |
| 12 页 PDF OCR | ~60s | ~6s |
| 100 页含表 PDF 完整解析 | ~30-60min | ~8-15min |

> **注意**: 表结构识别（tsr.onnx）仍然是 PDF 解析中最耗时的步骤，GPU 加速后仍需 10-70s/表。

## 六、启动 RAGFlow

### 6.1 一键启动

```bash
bash start.sh start
```

启动 3 个组件：
1. **Web Server** (端口 `${BACKEND_PORT:-9380}`) — REST API
2. **Task Executor** — ${TASK_EXECUTOR_COUNT} 个 worker 进程（默认 3 个）
3. **Web 前端** (端口 `${FRONTEND_PORT:-9223}`) — React UI

### 6.2 并发配置

通过环境变量控制解析并发度：

```bash
# 默认配置 (可修改 start.sh 顶部常量)
MAX_CONCURRENT_TASKS=10       # 每 worker 并发任务数 (默认 10)
TASK_EXECUTOR_COUNT=3         # worker 进程数 (默认 3)
TASK_EXECUTOR_OFFSET=3        # worker ID 起始偏移 (默认 3, 避免多实例冲突)

# 总并发解析容量 = MAX_CONCURRENT_TASKS × TASK_EXECUTOR_COUNT
# 默认: 10 × 3 = 30 个并发解析槽位
```

### 6.3 多实例部署

同一台机器运行多个 RAGFlow 实例时：

```bash
# 实例 A (默认端口)
BACKEND_PORT=9380 TASK_EXECUTOR_OFFSET=0 bash start.sh start

# 实例 B (需不同端口和 worker ID 避免冲突)
BACKEND_PORT=9381 TASK_EXECUTOR_OFFSET=3 bash start.sh start
```

不同 worker ID 的 task executor 在同一个 Redis stream 消费者组中协同工作，共享解析任务。

### 6.4 其他命令

```bash
bash start.sh stop      # 停止所有服务
bash start.sh status    # 查看运行状态
bash start.sh restart   # 重启所有服务
```

### 6.5 手动启动 (调试用)

```bash
# 1. 后端 API
PYTHONPATH=. HF_ENDPOINT=https://hf-mirror.com \
nohup .venv/bin/python api/ragflow_server.py > /tmp/ragflow_server.log 2>&1 &

# 2. 任务执行器 (多 worker)
PYTHONPATH=. HF_ENDPOINT=https://hf-mirror.com MAX_CONCURRENT_TASKS=10 \
nohup .venv/bin/python rag/svr/task_executor.py 3 > /tmp/ragflow_taskexec_3.log 2>&1 &

# 3. 前端
cd web && npm install && PORT=9223 npm run dev -- --host 0.0.0.0 &
```

## 七、知识库配置 (首次部署)

首次部署需要在 RAGFlow 中手动创建知识库并获取 API Key。

### 7.1 创建知识库

通过 Web UI (http://<IP>:9223/) 或 API 创建 6 个知识库：

```
产品库    4c0f8e72544d11f1b0904d93f269c4c9  (chunk_method=manual)
图片库    4c138356544d11f1b0904d93f269c4c9  (chunk_method=table, Excel索引)
视频库    4c15fd2a544d11f1b0904d93f269c4c9  (chunk_method=table, Excel索引)
文件库    4c18d086544d11f1b0904d93f269c4c9  (chunk_method=table, Excel索引)
程序库    4c1bfee6544d11f1b0904d93f269c4c9  (chunk_method=table)
经验库    4c1e4994544d11f1b0904d93f269c4c9  (chunk_method=table)
```

### 7.2 获取 API Key

Web UI → 右上角头像 → API → 生成 Key，配置到 deepagents 的 `.env`:

```bash
RAGFLOW_API_URL=http://localhost:9381
RAGFLOW_API_KEY=ragflow-xxxxxxxxxxxx
```

## 八、验证

```bash
# 后端 API
curl http://localhost:9380/api/v1/datasets \
  -H "Authorization: Bearer <your-api-key>"

# 解析状态
curl 'http://localhost:9380/api/v1/datasets/<dataset_id>/documents?page=1&page_size=12' \
  -H "Authorization: Bearer <your-api-key>"

# 前端界面
# 浏览器打开 http://<服务器IP>:9223/
```

## 九、常见问题

### 1. 文档解析卡住不动

**症状**: 文档 status 一直是 RUNNING，progress 始终 0%

**原因**:
- Task Executor 未启动
- HuggingFace 模型下载失败（国内网络）
- OCR 模型下载到 CPU 运行极慢

**解决**:
```bash
# 确认 task executor 在运行
bash start.sh status

# 如果挂了，设置 HF 镜像重启
HF_ENDPOINT=https://hf-mirror.com bash start.sh restart

# 确认 OCR 使用 GPU (见第五节)
grep "load_model.*GPU\|load_model.*CPU" /tmp/ragflow/taskexec_*.log
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

### 7. 解析速度慢但不报错

**症状**: 文档一直在 RUNNING，但 task executor 在运行且无异常日志。

**诊断方法**:
```bash
# 查看 worker 心跳 (done/lag)
grep "reported heartbeat" /tmp/ragflow/taskexec_3.log | tail -1 | python3 -c "
import json,sys;l=sys.stdin.read().strip().split('reported heartbeat: ')[1];h=json.loads(l)
print(f'done={h[\"done\"]} failed={h[\"failed\"]} lag={h[\"lag\"]} pending={h[\"pending\"]}')"

# lag 持续很高 → 积压大
# done 不增长 → 可能大文档阻塞 (RAGFlow 按 12 页一组拆分 PDF)
# pending 稳定 → 处理正常但慢
```

**可能原因**:
1. OCR 使用 CPU 而非 GPU → 参考第五节
2. 大 PDF (200+ 页) 表结构识别耗时 → 正常现象
3. Embedding API 慢 → 检查 vLLM/Ollama

### 8. Task Executor 反复崩溃

**症状**: start.sh 启动后 worker 秒退，日志 `PermissionError`

**原因**: `logs/` 目录下有 root 拥有的日志文件。

**解决**:
```bash
# logs/ 目录默认 world-writable，直接删除旧日志
rm -f /home/wangzilong/EST/ragflow/logs/task_executor_*.log
bash start.sh restart
```

### 9. 大批量上传后部分文档始终 UNSTART/queued

**症状**: 上传 + 触发解析后，大量文档 status 一直不是 RUNNING。

**原因**: 批量触发时 RAGFlow 内部任务队列已满 (code=102 "already being processed")，或 trigger_parse 超时。

**解决**:
```bash
# 等待 5-10 分钟后重新触发解析
curl -X POST http://localhost:9380/api/v1/datasets/<ds_id>/chunks \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"document_ids": ["<doc_id1>", "<doc_id2>", ...]}'

# 如果 RAGFlow 返回 code=102，说明已在处理，忽略即可
```

**预防**: deepagents 批量上传接口已内置:
- 批次结束后统一触发解析（不逐个轮询）
- 最多 3 次重试即时失败的文档
- 最终失败入 Kafka DLQ 待人工补偿

## 十、批量上传与知识库管理

通过 deepagents 的批量上传 API 集成 RAGFlow：

```
deepagents (api/ragflow_router.py)
    ↓ POST /api/v1/batch/upload-from-folder
    ↓ manifest + folder_path
    ↓
RAGFlow (rest API)
    ↓ 上传 + SHA256 去重 + 元数据注入
    ↓ 批量触发解析
    ↓ Excel 索引构建 (图片/视频/文件库)
```

API 文档: [deepagents/docs/kb-api.md](../deepagents/docs/kb-api.md)

关键特性:
- SHA256 增量上传（二次上传秒级完成）
- 熔断 + 限流 + Kafka DLQ 容错
- 产品库解析完成自动联动写入文件库索引
- 图片/视频库自动构建 Excel 索引（table chunking）

## 十一、生产部署建议

- 使用 `vite build` 编译前端静态文件，由 nginx 托管
- 配置 systemd service 实现开机自启
- MySQL / ES 数据目录挂载到宿主机防止数据丢失
- 配置日志轮转 (`logrotate`)
- GPU 服务器: 设置 `MAX_CONCURRENT_TASKS=10` + `TASK_EXECUTOR_COUNT=3`
- 非 GPU 服务器: 降低 `MAX_CONCURRENT_TASKS=3` + `TASK_EXECUTOR_COUNT=1`
