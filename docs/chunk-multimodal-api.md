# 多模态文件解析 API 输入输出说明

依据：当前 `chunk-mm` 分支源码。以下接口挂载于 RAGFlow API 服务（你的部署端口为 9380）；本文未对服务器做在线调用验证。

## 自定义异步接口（新增）

9380 后端新增三个接口。两个提交入口不等待模型解析，成功提交返回 HTTP 202；文件上传传输、参数校验及入队准备仍需时间。后端 task executor 必须正常运行。

| 功能 | 方法与路径 |
| --- | --- |
| 已有文档多模态解析 | POST `/api/v1/multimodal/parse` |
| 上传单个文件并解析 | POST `/api/v1/multimodal/upload-and-parse` |
| 查询任务状态 | GET `/api/v1/multimodal/tasks/{task_id}` |

### 输入示例

以下在 Ubuntu 上执行。API Key 是 RAGFlow 的访问密钥，不是供应商密钥。

```bash
BASE='http://127.0.0.1:9380/api/v1'
RAGFLOW_API_KEY='替换为RAGFlow访问密钥'
```

已有文档（document_id 是知识库文档 ID，不是文件管理器中的 File ID）：

```bash
curl -sS -X POST "$BASE/multimodal/parse" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_id": "知识库ID",
    "document_id": "文档ID",
    "multimodal": {
      "model": "实际模型名@实际实例名@VLLM",
      "prompt": "",
      "max_tokens": 8192,
      "enable_thinking": false,
      "reuse": true
    }
  }'
```

上传并解析（一次一个文件）：

```bash
curl -sS -X POST "$BASE/multimodal/upload-and-parse" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" \
  -F 'dataset_id=知识库ID' \
  -F 'file=@/home/wangzilong/manual.pdf' \
  -F 'multimodal={"model":"实际模型名@实际实例名@VLLM","enable_thinking":false,"reuse":true}'
```

PDF 自动使用 naive + DeepDOC，静态 PNG/JPEG/BMP/TIFF/WebP 图片自动使用 Picture；不支持视频、DOCX 等其他格式。PNG 示例只需替换 file 路径。

multimodal 可省略，省略的字段继承文档/知识库配置，但必须能得到可用的 vision 模型。enabled 自动开启、父子切分自动关闭，不修改知识库的全局配置。有自定义 Pipeline 的文档/知识库会返回 409，不会偷偷清除 Pipeline。

### 提交返回（HTTP 202，关键字段示例）

```json
{
  "code": 0,
  "data": {
    "task_id": "本次任务ID",
    "dataset_id": "知识库ID",
    "document_id": "文档ID",
    "status": "queued",
    "progress": 0,
    "chunk_count": 0,
    "error": null,
    "status_url": "/api/v1/multimodal/tasks/本次任务ID"
  }
}
```

返回状态可能已是 running；不能因收到 202 就当作完成。

### 查询状态

```bash
TASK_ID='替换为提交返回的task_id'
curl -sS "$BASE/multimodal/tasks/$TASK_ID" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY"
```

完成响应示例（时间、计数均为示例）：

```json
{
  "code": 0,
  "data": {
    "task_id": "本次任务ID",
    "dataset_id": "知识库ID",
    "document_id": "文档ID",
    "status": "complete",
    "progress": 1,
    "message": "Multimodal parsing, embedding and indexing complete",
    "created_at": "2026-09-11T03:00:00+00:00",
    "updated_at": "2026-09-11T03:02:00+00:00",
    "chunk_count": 12,
    "error": null,
    "status_url": "/api/v1/multimodal/tasks/本次任务ID",
    "result_url": "/api/v1/datasets/知识库ID/documents/文档ID/chunks"
  }
}
```

| 状态 | 含义 |
| --- | --- |
| queued | 已入队，等待 worker |
| running | 正在解析、向量化或入库 |
| complete | 本次所有解析子任务完成且至少产生一个 Chunk |
| failed | 提交中断、模型/解析/Embedding/索引失败或无 Chunk 输出 |
| cancelled | 文档被删除、任务取消或被其他一轮解析替代 |

查询接口 HTTP 200 / code 0 表示查询成功，任务是否成功必须检查 `data.status`。失败信息放在 `error`：例如 `parse_failed` 附内部任务 ID；`dispatch_error` 表示入队失败；`dispatch_interrupted` 表示提交过程超过 10 分钟仍未完成（可能 API 中断）；`empty_output` 表示没有有效 Chunk。为避免模型密钥泄露，接口不直接透传原始异常；详细异常到 RAGFlow 文档进度日志和归档中查看。

建议每 3～5 秒查询一次，遇到 complete / failed / cancelled 停止轮询。不需要保持原提交连接。断线也不要直接重复 POST，先用已返回的 task_id 查询；若响应丢失，重复已有文档提交可能返回 409 并附现有任务 ID。上传入口不承诺幂等，重复上传可能新增文件。

`result_url` 指向现有 Chunk 列表，返回 Markdown 的 `content` 和图片引用 `image_id`，需继续分页获取。它指向该文档的当前索引，不是历史不可变快照；历史模型结果使用多模态磁盘归档。

### 错误与部署注意

- HTTP 400：参数、文件格式或模型配置无效。
- HTTP 401：未通过 RAGFlow 鉴权。
- HTTP 404：任务/文档/知识库不存在或无权访问。
- HTTP 409：已有活跃任务，或仍使用 Pipeline。已有自定义任务时 `data.task_id` 可用于继续查询。
- HTTP 503：调度失败；尽可能返回 task_id、document_id，便于查询与重试。上传成功但提交失败时保留已上传文件，不自动删除。
- 重跑会替换该文档现有索引 Chunk、重新 Embedding，但保留并复用多模态归档；任务记录按本次子任务 ID 独立保存，历史 complete 不会随新一轮解析变化。
- 新增 `multimodaljob` 数据表，沿用 API 启动时的表发现与创建机制。部署需数据库账号有建表权限，并更新重启 API 和 task executor。任务记录在数据库、模型结果在归档目录，两者都需要备份。
- 本地已做 SQLite 状态测试、Quart 接口契约测试和既有归档回归测试；未代替你服务器上的 MySQL/PostgreSQL、Redis、GPU 和模型 API 联调。

## 原生接口调用方式

以下保留原生“上传 → PATCH 配置 → 启动解析 → 查询 Chunk”的分步说明。使用上面的自定义接口不需要再逐个调用这些步骤。

## 1. 能力与边界

已有接口可触发多模态解析，调用流程为：上传文件 → 设置文档解析配置 → 启动异步解析 → 查询状态 → 读取 Chunk Markdown。

目前没有独立的“上传文件并同步返回全文 Markdown”接口，也没有通过 HTTP 下载多模态归档的专用接口。任务执行器必须运行，Embedding 模型和检索存储也必须可用；这不是脱离知识库的纯解析服务。

开启多模态后，PDF（DeepDOC 路径）先解析、切分，再将 Chunk 截图交给模型；PNG（Picture 路径）直接将整张图片交给模型。输出包含文字转录、图片描述和 Markdown 表格；提示词要求合并值复制到对应行列、嵌套表格摊平，但格式校验不能保证内容完全正确。

## 2. 公共参数

基础地址：`http://<服务器IP>:9380/api/v1`。

鉴权：`Authorization: Bearer <RAGFlow API Key>`。这是 RAGFlow 的访问密钥，不是模型供应商的 API Key。

前置条件：已有知识库；已在 RAGFlow 注册可用的 vision 模型及其服务地址、密钥；关闭父子 Chunk；使用直接解析路径而非自定义 Pipeline。建议使用独立测试知识库。

所有 JSON 请求均带 `Content-Type: application/json`。以下响应是仅保留关键字段的示例，不是实测结果；其他字段以实际返回为准。不能只判断 HTTP 200，还必须检查 JSON 的 `code`，0 表示接口操作成功。

## 3. 接口一览

| 操作 | 方法与路径（相对于基础地址） | 主要输出 |
| --- | --- | --- |
| 上传文件 | POST `/datasets/{dataset_id}/documents` | `data[].id` 文档 ID |
| 配置解析 | PATCH `/datasets/{dataset_id}/documents/{document_id}` | `data` 更新后的文档信息 |
| 启动解析 | POST `/datasets/{dataset_id}/documents/parse` | `data.success_count` 提交数量 |
| 查询状态 | GET `/datasets/{dataset_id}/documents?id={document_id}` | `data.docs[]` 中的状态和进度 |
| 读取结果 | GET `/datasets/{dataset_id}/documents/{document_id}/chunks` | `data.chunks[].content` Markdown |
| 读取图片 | GET `/documents/images/{image_id}` | 图片二进制，需要鉴权 |

注意：GET `/datasets/{dataset_id}/documents/{document_id}` 是下载原文件，不是查询解析状态。

## 4. 上传文件

使用 multipart/form-data，字段名 `file`，支持多个同名字段。不要自行填写 multipart boundary。

```bash
BASE='http://127.0.0.1:9380/api/v1'
RAGFLOW_API_KEY='替换为RAGFlow访问密钥'
DATASET_ID='替换为知识库ID'

curl -sS -X POST "$BASE/datasets/$DATASET_ID/documents" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" \
  -F 'file=@/home/wangzilong/manual.pdf'
```

响应示例：

```json
{"code":0,"data":[{"id":"文档ID","name":"manual.pdf","run":"UNSTART"}]}
```

上传本身不代表多模态解析完成。此上传接口的表单 `parser_config` 仅允许部分表格列配置，不能用它传入多模态设置。

## 5. 设置多模态解析参数

将上传返回的 ID 保存为 `DOCUMENT_ID`。PDF 请求体示例：

```json
{
  "chunk_method": "naive",
  "parser_config": {
    "layout_recognize": "DeepDOC",
    "chunk_token_num": 512,
    "parent_child": {"use_parent_child": false},
    "ext": {
      "enable_children": false,
      "multimodal": {
        "enabled": true,
        "model": "实际模型名@实际实例名@VLLM",
        "prompt": "",
        "max_tokens": 8192,
        "enable_thinking": false,
        "model_revision": "v1",
        "reuse": true
      }
    }
  }
}
```

将请求体保存为 `multimodal-config.json`，再调用：

```bash
DOCUMENT_ID='替换为上传返回的文档ID'
curl -sS -X PATCH "$BASE/datasets/$DATASET_ID/documents/$DOCUMENT_ID" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @multimodal-config.json
```

响应：`{"code":0,"data":{...更新后的文档字段...}}`（结构示意）。确认返回配置中保留了多模态参数。

PNG 将 `chunk_method` 改为 `picture`；此时 `layout_recognize` 不参与 Picture 路径。扩展参数使用 `parser_config.ext` 是为了通过 REST 的 ParserConfig 数据校验，后端会将其展开并交给任务执行器。

| 多模态字段 | 输入类型 / 默认值 | 说明 |
| --- | --- | --- |
| enabled | boolean / 关闭 | 开启截图多模态解析 |
| model | string / 开启时必填 | 已注册的 vision 模型引用，可为模型 ID 或 `模型名@实例名@供应商`；优先使用前端实际保存的值，不要照抄示例占位符 |
| prompt | string / 空字符串 | 空字符串使用内置工业文档提示词；非空时替换提示词，需要自己保留文字、图片和表格处理要求 |
| max_tokens | integer / 8192 | 允许 256～65536；实际仍受模型服务上限限制 |
| enable_thinking | boolean / false | Qwen 思考开关；VLLM 与其他供应商使用不同兼容参数 |
| model_revision | string / 空字符串 | 自定义缓存版本标记，不会自动切换模型权重 |
| reuse | boolean / true | 复用成功归档；false 强制重新调用模型，增加开销 |

不要在此请求里传模型 API Key 或 base_url；它们从已注册的模型配置读取。若文档已有自定义 Pipeline，需先明确切回直接解析路径；可单独 PATCH `{"pipeline_id":""}`，再设置以上参数。不要把清空 Pipeline 和切换 chunk_method 放进同一次 PATCH（当前处理分支是互斥的）。修改已有配置前应保留仍需使用的其他配置项。

## 6. 启动异步解析

```bash
curl -sS -X POST "$BASE/datasets/$DATASET_ID/documents/parse" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"document_ids\":[\"$DOCUMENT_ID\"]}"
```

输入：非空 `document_ids` 字符串数组，可批量提交。

响应示例：

```json
{"code":0,"data":{"success_count":1}}
```

`success_count` 是成功提交的数量，不是已完成解析的数量。不要反复调用此接口轮询：重跑会删除该文档已有索引 Chunk 并重新构建，但不会删除磁盘多模态归档。即使归档命中，也仍需重新切分和生成向量。

## 7. 查询进度

```bash
curl -sS "$BASE/datasets/$DATASET_ID/documents?id=$DOCUMENT_ID" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY"
```

关键响应示例：

```json
{
  "code": 0,
  "data": {
    "total": 1,
    "docs": [{
      "id": "文档ID",
      "run": "3",
      "progress": 1,
      "progress_msg": "...解析进度日志...",
      "chunk_count": 12
    }]
  }
}
```

当前列表接口返回内部状态：`0` 未开始、`1` 处理中、`2` 已取消、`3` 完成、`4` 失败（字符串形式）。上传响应的 `UNSTART` 是另一处做过转换的状态，不要混淆。建议每隔几秒查询一次，遇到失败或取消就停止轮询，并保留 `progress_msg`。

## 8. 获取 Markdown 和截图

```bash
curl -sS "$BASE/datasets/$DATASET_ID/documents/$DOCUMENT_ID/chunks?page=1&page_size=30" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY"
```

关键响应示例：

```json
{
  "code": 0,
  "data": {
    "total": 1,
    "chunks": [{
      "id": "ChunkID",
      "document_id": "文档ID",
      "content": "## 参数表\n\n| 型号 | 功率 |\n| --- | --- |\n| A | 10 kW |",
      "image_id": "实际返回的图片ID",
      "positions": [],
      "available": true
    }],
    "doc": {"id": "文档ID"}
  }
}
```

`content` 是最终索引文本；`image_id` 是图片引用，不是完整 URL，也不是“纯图片分类”标签；`positions` 为原文位置数据，独立图片可能没有页码位置。

按 `total` 继续翻页直到取完，不要只读第一页。不带 `keywords` 可避免内容被搜索高亮加工。接口返回的是各个 Chunk，不承诺直接拼接就能恢复完整原文阅读顺序或完成跨页表格合并。

`image_id` 非空时，可对其做 URL 路径编码后请求：

```text
GET http://<服务器IP>:9380/api/v1/documents/images/<image_id>
Authorization: Bearer <RAGFlow API Key>
```

返回图片二进制，而非 JSON。它不是无需认证的公共图片链接。

## 9. 归档与失败结果

默认目录为 worker 工作目录下 `data/multimodal_archive`，可由 `RAGFLOW_MULTIMODAL_ARCHIVE_DIR` 覆盖。

- `entries/.../attempts/.../result.md`：通过格式校验的模型文本。
- `entries/.../attempts/.../response.json`：已收到的原始模型响应，校验失败也保留；API 失败且没有响应时不产生该文件。
- `runs/*.json`：文档与 Chunk 对应关系，`chunks[].indexed_markdown` 保存实际入库文本（PNG 包含文件名）。

上述磁盘归档没有专用 REST 下载接口；Chunk 查询只提供索引中的结果，不提供归档键、模型原始响应或所有失败尝试。查失败原因先看文档进度日志，需要原始内容时从服务器归档读取。详情见 [归档使用文档](chunk-multimodal-parser.md)。

## 10. 源码依据

- `api/apps/__init__.py`：REST 路由 `/api/v1` 注册及 Bearer 鉴权。
- `api/apps/restful_apis/document_api.py`：上传、PATCH 配置、异步启动、状态列表、图片读取。
- `api/apps/restful_apis/chunk_api.py`：分页返回 `content`、`image_id`、`positions`。
- `api/utils/validation_utils.py`：`ParserConfig.ext` 扩展入口。
- `rag/svr/chunk_multimodal.py`：模型解析、缓存复用、结果归档。
