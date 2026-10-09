# 官方更新检查与 Python 移植方案

状态：用户已批准逐项实现、测试并推送。第一项元数据选择已实现，163 项本地针对性回归通过；服务器尚未部署本次修改，线上验收待部署。

## 检查基线

- 本地自定义分支：`chunk-mm`，`b6321f84a`。
- 已合入的官方 Python 基线：`322aba7d40c739074ffce7fb0f325ca40d4030ae`，2026-09-28。
- 本次实际获取的官方主线：`14c2721236d40f730202710a108eb343fed3bbae`，2026-10-09 16:54:49 +0800。
- 检查方式：获取官方 Git 对象后读取提交、实现、测试，并与当前 Python 调用链比较；没有直接合并官方主线。
- 保留用户明确要求的 Python 后端、自定义 Agentic Search API、多模态 full/smart 解析与模板编辑能力。

## 检查结果

### 优先：元数据文档选择工具

官方 `d50f1f02d` / PR #20645 于 2026-10-09 新增 Go 智能推理工具 `search_metadata`。它按真实元数据字段筛选文档，返回文档 ID 和文档自己的元数据，再由搜索与阅读工具消费，不强制执行向量检索。

本地已有 Python `metadata_search`，并非从零缺失。但 `rag/advanced_rag/harness/action_session.py` 的模型工具 schema 只允许 `title`，要求 `query`，执行路径筛选后必须运行 hybrid search。本地外部 `/agentic-search/tools/<tool_name>` 也未提供元数据文档选择。这使“列出某作者/年份/型号对应的文档”仍依赖语义检索和 embedding 服务。

方案：扩展现有 Python 工具，保持有 query 的现有调用结果；无 query 时返回文档选择结果，允许知识库真实存在的字段，并向外部 Agentic Search API 提供同一能力。复用 `DocMetadataService` 的字段发现、过滤下推与文档元数据读取；业务规则集中在一个服务函数中，由 harness 和 HTTP 入口共用。

### 可选后续：正文标题参与检索索引

官方 `2400ca8eb` / PR #20542 将文档声明的标题加入 `title_tks`。适合文件名不包含产品真实名称的资料，但需要另外核对 Python 各解析器已经生成的标题字段，避免重复索引。存量文档的效果还涉及重新解析，建议单独实施和评测。

### 已有或无需直接照搬

- 自然文本重排序已存在于本地 `rag/nlp/search.py:rerank_by_model`，无需重复移植 PR #16961。
- 官方最新 PDF VLM/plain-text 页码范围修复 PR #20336 主要针对 Go 路径；本地 Python 已传递页码边界，尚不能仅凭官方提交标题判定本地存在同样问题。
- 可配置 worker/page 并发 PR #20121 属于 Go ingestion 配置；本地已经有 Python worker 启动配置，需要负载证据后再决定是否增加解析任务内的并发限制。
- 更换队列、存储和整体后端不在本次 Python 功能移植范围。

## 第一批推荐方案：元数据选择并接入现有 Agentic Search

### 用户行为

1. 智能检索可先按已有元数据字段筛选，例如作者、年份、型号；这些字段必须已在文档元数据中配置，不从原文猜测生成。
2. 无查询词时返回匹配文档 ID、名称与元数据；不初始化 embedding 模型。
3. 有查询词时保留原有的“筛选后检索正文”能力。
4. 外部 API 可调用 `/api/v1/agentic-search/tools/metadata_search`。
5. 普通与流式 Agentic Search 使用相同的工具能力。

### 数据边界和失败处理

- 只查询当前用户有权限的知识库，与会话文档范围取交集；重新验证元数据命中的文档仍存在且有效。
- 空匹配返回明确空集合，绝不因此扩大到全库。
- 过滤条件限制为 1–10 个，逻辑只允许 and/or；验证运算符、值类型和字符串文档 ID。
- 返回文档数和元数据体积有界，明确说明截断，禁止将截断数量当成全库计数。
- 区分“没有元数据”“没有匹配”“索引不可用”；基础设施异常不能伪装成零匹配。
- 不修改已有模型连接、凭据或生产知识库绑定，不新增数据库迁移。

### 验证和启用

- 单元测试覆盖字段发现、多条件过滤、空匹配、错误类型、文档范围交集、权限、截断和服务失败。
- 回归原来的带 query 元数据检索，以及 search/open/read/grep/navigate、普通和流式 Agentic Search。
- 单独测试无 query 模式不调用 embedding 或正文检索。
- 使用隔离测试知识库验证 API 和模型工具实际调用；保留 full/smart 多模态回归检查。
- 通过代码审查和相关检查后提交并推送 `chunk-mm`。服务器部署后再验收；本地通过不等于已在线启用。

## 范围选择

推荐先完成元数据选择，改动集中，直接服务当前产品库和自定义 API。第二种选择是同时移植正文标题索引，范围更大且需要重解析测试。仅更新 Go 主线无法满足本次 Python 要求。

## 逐项执行清单

| 功能 | Python 处理 | 当前状态 |
| --- | --- | --- |
| 真实元数据字段选择文档 | 新增无 query 路径并接入现有 API；保留带 query 路径 | 本地实现与回归通过，待部署验收 |
| 正文声明标题参与检索 | 核对后独立移植，保留文件名与正文 | 下一项 |
| grep/BM25 | 本地已有工具，比较实际差异再决定 | 待核对 |
| Web evidence 稳定 ID | 核对当前引用和去重实现 | 待核对 |
| 全局视觉增强、PDF 页码范围 | 保留 full/smart，避免重复实现现有能力 | 待核对 |
| 新模型/搜索供应商 | 按实际可用配置增补，不改当前绑定 | 后续可选 |
| Go 队列和存储重写 | 不移植整体后端 | 排除 |

## 第一项 API 示例和验证边界

`POST /api/v1/agentic-search/tools/metadata_search`，使用现有登录认证：

```json
{"dataset_ids":"<有权限的知识库ID>","filters":[{"key":"year","op":"=","value":2026}],"logic":"and","limit":50}
```

返回的 `doc_ids` 是文档句柄，不是可引用正文；每个 `documents` 项含自己的元数据。默认最多 50 篇，上限 200；结果最多 60,000 字符，字段预览也有独立限制，截断标记为 `truncated`。模型工具的预算不足时保持合法 JSON，可能进一步省略元数据或文档。空范围不会回退到全库。HTTP 入口要求显式知识库范围；同名歧义和无权访问均报错，不依赖 embedding 服务。

本地 163 项单元/路由回归覆盖 Agentic Search 普通与流式服务、搜索工具、旧模型绑定、多模态归档及 Wiki 模板，以及新增筛选、错误传播、权限和预算边界。新增文件 lint 通过；原有大型文件仍有历史 lint 告警。测试隔离外部模型和数据库，不等于线上 GPU 解析、供应商响应或生成质量已通过。代码审查发现的数字 fallback、非法 JSON 截断、检索 schema 和空范围扩大问题已补修复与回归。

## 官方依据

- https://github.com/infiniflow/ragflow/commit/d50f1f02d67c964d4479859d47ded069c34dbb1f
- https://github.com/infiniflow/ragflow/pull/20542
- https://github.com/infiniflow/ragflow/pull/16961
- https://github.com/infiniflow/ragflow/pull/20336
- https://github.com/infiniflow/ragflow/pull/20121
