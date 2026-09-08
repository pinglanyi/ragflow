# Chunk 多模态解析与结果归档

## 功能与范围

当前接入 Python 内置解析任务（API + Python task executor 部署），包括默认 `TE_RUN_MODE=0` 的重构执行器与备用入口，共用同一个解析/归档模块。在原解析器完成切分和截图后，对每张 Chunk 截图调用多模态模型，再生成关键词和 Embedding。此实现不覆盖 Go ingestion 进程或自定义 Dataflow 的独立执行路径。

文字忠实转录；图片/接线图/流程图输出详细描述；复杂表格输出 Markdown，多层表头明确关联，合并值逐行逐列复制，嵌套表拆分并带上父级条件。结果替换 `content_with_weight` 并重新分词，Embedding 使用处理后的正文。原截图和位置继续用于 RAGFlow 图片引用。模型不生成图片 URL，引用地址由 RAGFlow 的图片存储接口提供。

这属于基于现有 Chunk 的增强解析：原切分遗漏的区域、被切断的跨页表格不能凭空恢复。Markdown 校验可发现空输出、截断、HTML 表格和列数不一致，不能证明数值、连线或合并语义一定正确。重点参数应结合原截图验收；不做猜测填充。

## 前端操作

1. 在模型设置中添加 **vision** 模型，填入 OpenAI-compatible API base URL、模型名与密钥。本地 vLLM 示例 base URL 为 `http://模型服务器:8000/v1`；商用服务使用自己的兼容地址。密钥只存在模型配置里，不填进提示词。
2. 在数据集解析设置或单文档切分设置中打开 **Chunk 多模态解析**，选择模型。推荐先选 DeepDOC 作为 PDF 布局/切分来源，并关闭父子切分。
3. 可以编辑提示词。留空使用内置工业文档提示词。最大输出默认 8192；大表可提高至模型支持的范围。Qwen 默认关闭思考；vLLM 使用 `chat_template_kwargs.enable_thinking`，其他兼容 Qwen API 使用 `enable_thinking`，服务端需支持对应参数。
4. 默认打开 **复用已归档解析结果**。本地相同模型名更换权重时，修改 **模型版本标记**。关闭复用会再次调用模型，但保留旧版本。
5. 重新解析文档。Chunk 卡片显示 Markdown 表格与描述，图片预览保留。进度显示 `Multimodal Markdown n/N (archive reused: True/False)`。

不生成截图的解析器/文件类型会明确报错，不会把未处理的 OCR 当作多模态结果。父子切分也会在解析前报错。输出超出 Embedding 输入上限会明确失败并保留归档；请使用更大上下文的 Embedding 模型或减少源 Chunk 大小。

配置字段为 `parser_config.multimodal`（API 扩展配置也可放在 `parser_config.ext.multimodal`）：

```json
{"enabled": true, "model": "模型设置返回的模型 ID", "prompt": "", "max_tokens": 8192, "enable_thinking": false, "model_revision": "v1", "reuse": true}
```

## Ubuntu 持久化与同步

在启动 Python task executor 的同一个环境中设置：

```bash
export RAGFLOW_MULTIMODAL_ARCHIVE_DIR=/home/wangzilong/ragflow_multimodal_archive
mkdir -p "$RAGFLOW_MULTIMODAL_ARCHIVE_DIR"
```

目录必须对 worker 可写。多 worker 使用同一共享持久目录；容器部署需挂载持久卷，不能只存在容器可写层。未设置时使用 worker 工作目录下 `data/multimodal_archive`。部署时依照本仓库 Python 3.13 环境更新依赖并重新构建前端。

在仓库根目录、已激活 RAGFlow venv 下运行：

```bash
python scripts/multimodal_archive.py export /home/wangzilong/multimodal-results.zip
python scripts/multimodal_archive.py import /home/wangzilong/multimodal-results.zip
```

第二条在目标服务器执行。可以用 `--root /目标归档目录` 指定路径。导出包不能覆盖已有 ZIP；导入校验文件名与 SHA256，已有成功指针优先保留，原始尝试不会被覆盖。导出条目时加锁；建议等待当前任务完成后再导出，以获得完整运行清单。归档含原文图片，按源文档同等权限管理。只导入可信管理员提供的归档。

同步后需保留相同的 RAGFlow tenant 身份与模型配置（地址、名称、版本、提示词等），再次提交文档解析即可命中相同截图结果。跨 tenant 不自动复用；更换 API 地址会视为不同模型配置。归档不包含数据库配置、索引或向量，源文件和租户迁移应使用现有备份流程。

## Chunk 数量变化时如何复用

| 变化 | 行为 |
| --- | --- |
| Chunk 顺序、数量、ID 或文档 ID 变化，但截图完全相同 | 在同一租户、同一模型配置下复用 |
| 切分边界、截图像素发生变化 | 新解析；不按序号误配旧结果 |
| 模型、API 地址、输出上限、思考模式、提示词、版本标记变化 | 新归档，不覆盖旧结果 |
| 重新生成向量或重建索引 | 归档独立保留，相同截图无需重复模型调用 |
| 强制重解析失败 | 原始失败响应仍存档，上一次成功结果仍可复用 |

键为 `SHA256(规范化截图 PNG + 解析配置)`。截图不会进行有损缩放。每个运行清单记录文件 SHA256、文档/任务 ID、页码/裁剪坐标、当次 Chunk 序号、归档键和实际使用的版本。序号只用于追溯，不用于缓存匹配。

同一任务中，共用同一截图且位置相同的重复片段合并为一个结果；不同页或不同位置分别保留引用。因此多模态处理前后的 Chunk 数量可以不同。对发生变化的新裁剪区域，程序不会拼接旧答案冒充新解析。

```text
归档目录/租户SHA256/
  entries/内容配置SHA256/
    screenshot.png
    config.json
    success.json
    attempts/版本ID/
      request.json
      response.json
      status.json
      result.md
  runs/运行ID.json
```

API 失败保留错误类型；收到响应后先保存完整响应，再校验。无效结果最多重新看图修正一次，两次都无效则任务失败。成功的 Markdown 与所有旧尝试均保留，`success.json` 只指向当前可复用版本。取消或失败后重新运行可复用前面已完成的截图；缓存命中不调用模型，但仍重新分词与生成向量。

## 验收

```bash
python test/unit_test/test_chunk_multimodal_archive.py -v
```

先用一份带图片和合并表的短 PDF 开启功能；核对正文、表格列与图片描述，检查截图引用。重复解析确认缓存命中且模型请求数不增加；改变切分长度检查仅相同截图复用。提高版本标记确认产生新尝试。导出到另一持久目录、导入并复测，确认归档可以恢复。模型质量和完整服务联调需在实际 Ubuntu RAGFlow/模型服务环境完成。
