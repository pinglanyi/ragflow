# Mistral Agentic Search 七工具适配设计

已确认目标：在 `ragflow/chunk-mm` 的 9380 后端暴露 Mistral Agentic Search 的 `search`、`open`、`navigate`、`read`、`grep`、`ingest`、`delete` 七个独立 HTTP 工具，并接入 `est_knowledge_base/feat/fyc` DeepAgent。保留现有整轮 `/api/v1/agentic-search` 和 SSE API。

## 语义与接口

新路由统一为 `POST /api/v1/agentic-search/tools/{tool}`，沿用 Bearer API key。成功返回 RAGFlow `{code:0,data:{...}}`。五个只读工具的 `data.chunks` 统一使用 `id`、`content`、`score`、`source_id`、`start_offset`、`end_offset`、`metadata`；`source_id` 为 RAGFlow `document_id`，offset 是过滤辅助记录后从 0 开始的可见 chunk 序号，`end_offset` 与 `start_offset` 相等。返回 `coordinate:"visible_chunk_ordinal"`，不冒充 Mistral 的字符偏移。

- `search(query, top_k=5, exclude_ids=[], dataset_ids="")`：显式知识库 ID 用逗号分隔；空值根据知识库描述自动选库。沿用已授权 RAGFlow 混合检索和排除已见块的有界候选机制。
- `open(chunk_id, window=2)`：解析锚块所属授权文档，返回前后各 `window` 个块及锚块。
- `navigate(source_id, start_offset, end_offset, direction, top_k=1)`：在同一授权文档向 `next` 或 `previous` 方向移动。
- `read(source_id, start_offset=null, end_offset=null, top_k=20)`：读取给定可见 chunk 序号范围，不做邻接扩张。
- `grep(source_id, pattern, mode="phrase", top_k=5)`：单文档大小写不敏感字面匹配；`phrase` 保持词序，`term` 要求各词同块出现。
- `ingest(uri, dataset_id)`：调用现有 RAGFlow 文档上传与解析链路；`dataset_id` 在多库系统中必需。仅接受显式允许的 URI 来源和授权知识库。
- `delete(source_id)`：只删除调用者有权修改的单个文档及其分块，不提供删除整个知识库的语义。

## 安全边界

所有工具从 Bearer key 解析用户身份。每次导航重新验证文档所属知识库和用户权限，不能仅信任上一次工具返回的 ID。`search` 显式选库需验证访问权，自动选库只在可访问且已解析的库中进行。`ingest`/`delete` 在 9380 和 DeepAgent 均默认禁用，由部署配置分别显式启用；远程 URL 及本地路径必须受部署端允许列表约束。写入接口不得因为 `source_id` 或 URI 自带内容而越权。

## 实现与验证

复用 `hybrid_search`、`RAGTools.iter_document_chunks` 及 RAGFlow 已有的文件上传、解析和删除服务，不引入 Vespa/Mistral SDK。后端服务负责参数验证、授权、标准化输出和错误映射；路由只负责鉴权和 HTTP 包装。DeepAgent 以七个独立 `@tool` 调用 9380，默认节点目录仅注册五个只读工具；写入工具经独立配置启用。单元测试覆盖参数边界、跨租户拒绝、顺序、`exclude_ids`、空结果和写入开关；线上用现有知识库做只读验收，写入工具使用专用测试知识库。
