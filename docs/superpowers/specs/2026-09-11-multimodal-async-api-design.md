# 多模态异步解析 API 设计

## 目标

在现有 9380 API 服务增加三个接口：已有知识库文档解析、上传单个文件并解析、按任务 ID 查询状态。提交请求不等待模型生成、Embedding 或索引写入；成功提交返回 HTTP 202 和文档级 task_id。只有本次任务的全部 Chunk 完成多模态解析、Embedding 与索引写入才返回 complete。

## 方案选择

采用“持久化文档级任务 + 复用现有 RAGFlow 队列和 worker”。不新建独立模型服务，不在 API 进程内用后台线程执行长时间解析。

直接将文档 ID 作为任务 ID 的实现更短，但重跑会覆盖历史状态，不能满足每次调用独立查询。另建一套解析 worker 会重复已有归档、Embedding 和存储逻辑，维护成本更高。

## 接口约定

统一前缀 `/api/v1/multimodal`，使用现有 RAGFlow Bearer API Key，按租户和知识库权限校验。

### POST /api/v1/multimodal/parse

JSON 输入：dataset_id、document_id 必填；可选 multimodal 对象，字段与当前 model、prompt、max_tokens、enable_thinking、model_revision、reuse 一致。

未提供的模型参数继承文档/知识库设置；最终必须能解析出已注册的 vision 模型。此接口明确开启多模态，不依赖调用方另做 PATCH。首版支持 PDF 和 Picture 支持的静态图片，不接受视频或其他未验证格式。

### POST /api/v1/multimodal/upload-and-parse

multipart/form-data 输入：dataset_id 和单个 file 必填，multimodal 为可选 JSON 字符串。上传完成并持久化任务后返回。接收文件本身仍需耗时，但不等待解析。

先校验权限、类型及配置，再上传；上传后如果提交失败，返回已生成的 document_id，保留文件供重试，不偷偷删除用户文件。

### 提交成功响应

```json
{
  "code": 0,
  "data": {
    "task_id": "本次文档级任务ID",
    "dataset_id": "知识库ID",
    "document_id": "文档ID",
    "status": "queued",
    "status_url": "/api/v1/multimodal/tasks/本次文档级任务ID"
  }
}
```

### GET /api/v1/multimodal/tasks/{task_id}

输出包含 task_id、dataset_id、document_id、status、progress（0～1）、message、created_at、updated_at、chunk_count、error。成功时增加 result_url，指向现有文档 Chunk 列表接口。状态查询不触发解析或模型调用。

状态：queued、running、complete、failed、cancelled。不存在或无权访问的任务统一返回 404；非完成状态不返回误导性的成功结果。

```json
{
  "code": 0,
  "data": {
    "task_id": "本次文档级任务ID",
    "dataset_id": "知识库ID",
    "document_id": "文档ID",
    "status": "complete",
    "progress": 1,
    "message": "多模态解析、Embedding 和 Chunk 入库完成",
    "chunk_count": 12,
    "error": null,
    "result_url": "/api/v1/datasets/知识库ID/documents/文档ID/chunks"
  }
}
```

以上为接口设计示例，不是已部署的返回值。

## 执行与持久化

- 为每次提交生成独立文档级任务 ID，持久化租户、文档、有效配置、本次内部子任务 ID 和最终状态。API 重启不丢失记录。
- 复用现有文件存储、任务队列、多模态截图处理、归档和向量写入路径；配置与子任务关联必须在调度时固定，不能查询时只读文档最新状态。
- 同一文档已有活跃任务时拒绝重复启动（409），返回调用方有权查看的已有自定义任务 ID（若有）；普通 RAGFlow 任务正在运行也不强制打断。
- 用户显式重跑已完成文档时生成新任务 ID。历史状态不被覆盖；本次索引结果替换旧 Chunk，现有多模态磁盘归档继续保留和复用。
- 原生界面或接口触发其他重跑、删除文档或取消任务时，旧自定义任务不得把新一轮状态归为自身成功。被替代的未完成任务标记 cancelled，并说明原因。
- complete 依据本次所有解析子任务的最终入库结果，不依据模型已有输出或缓存命中。无 Chunk、子任务失败、调度失败均不能报 complete。
- 入队失败必须记录 failed；恢复或查询不能将未完整入队的批次误报完成。实现时沿用仓库的数据库初始化/迁移机制。
- 不提供任意模型地址或密钥输入，仅使用租户已注册模型；接口错误不回传密钥或完整模型请求。

## 解析约束

PDF 使用 DeepDOC + 截图多模态路径，图片使用 Picture 直接多模态路径。关闭父子切分。对于配置了自定义 Pipeline 的已有文档，返回明确配置冲突，不自动清空用户 Pipeline；调用方先显式切回直接解析。

上传接口依文件类型选择 naive（PDF）或 picture（静态图片）。model 等参数覆盖仅限所选文档，不修改知识库全局配置。提示词不传则继承，显式空字符串使用内置提示词。

## 验证范围

先写测试再实现。覆盖两种提交入口、配置继承与覆盖、租户隔离、模型类型、非法文件、上传后入队失败、重复请求、全部子任务成功判定、部分失败、取消、原生重跑隔离、服务重启后的查询和归档复用。

文档附 PDF/PNG 调用示例、202/400/404/409 响应及轮询示例。当前本地不具备服务器完整 GPU 环境；本地契约/单元测试与服务器实际解析验收分开说明，不将模拟测试当成 GPU 联调成功。

## 不包含

不改前端；不新增同步长连接接口；不新增归档 HTTP 下载接口；不新增独立模型服务；不在本次设计阶段推送远程。
