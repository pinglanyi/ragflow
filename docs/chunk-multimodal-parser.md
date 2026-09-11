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

## Picture 图片文件直接解析（2026-09-09）

适用于本仓库 Python task executor 的 Picture 解析方式。开启后直接将图片传给所选多模态模型，不先跑 OCR，也不受原流程“文字超过 32 就不描述图片”的限制。关闭开关则保留默认解析流程。视频不适用该开关，误用时会明确报错。

前端操作：

1. 在模型设置中配置本地 vLLM 或商用 OpenAI 兼容 API；点击模型类型旁的编辑图标，勾选**视觉（vision）**。Embedding 模型只勾选 **embedding**，不要保留误判的 chat。
2. 在知识库解析设置或单文件解析设置中选择 **Picture**，打开**图片多模态直接解析**，选择模型。
3. 提示词留空使用内置规则，也可自定义。默认关闭 Qwen 思考模式、最大输出 8192 Token、开启归档复用。复杂大图若出现输出截断，可在模型支持范围内提高上限。
4. 保存设置，重新解析图片。已有索引不会因修改设置自动重建。

最终检索文本由两部分组成：程序添加的图片文件名，以及模型生成的 Markdown。示例：

```markdown
图片文件名：` CAN扩展模块接线图.png `

## 图片描述
图中包含……

## 表格
| 模块 | 电源 |
| --- | --- |
| IA321A | 24 V |
```

文件名来自上传文件信息，不依赖模型识别或提示词；同一图片改名后复用描述，但重新附上当前文件名。文件名和描述一起分词并参与向量化，图片引用仍走原来的存储/引用链路，不让模型猜 URL。因此无需另行手填“图片描述”元数据；业务分类、设备编号等额外筛选字段仍可按需要维护。

输入图片按 EXIF 纠正旋转方向后转换为 RGB PNG，不做有损缩放。表格要求将合并值复制到实际覆盖的行列，多层表头组合、嵌套表拆平；图示要求描述可见实体、连线和条件。不确定内容应标注，不允许补造。程序校验空响应、输出截断、HTML 表格及 Markdown 表格列数；**不能自动证明每个数值或连线都正确**，关键工业参数仍需抽检。

归档中 `entries/.../attempts/.../result.md` 保存模型本身的输出；`runs/运行ID.json` 的 `chunks[].indexed_markdown` 保存本次实际入库文本（含文件名），同文件名、文档 ID 和归档键一起随原有同步脚本导出。响应无效或 API 失败不会悄悄退回 OCR 冒充多模态成功；失败记录保留，成功缓存不被失败重试覆盖。

### 模型类型修复

类型改为必选复选框，可多选真实具备的能力。新建实例时编辑类型只更新草稿，保存使用该类型；已保存实例更新成功后才显示为已修改；未添加模型可先编辑再添加。重新获取模型列表时，已配置类型优先于按名字猜测的类型。`emb` 分隔词也会被识别为 embedding，但名字仅是初始建议，不是模型能力的验证结果。

### DeepDOC ONNX 显存异常

针对日志中 `BFCArena / p2o.Conv.0` 请求约 `3.8e18` 字节的异常，不能简单判断为普通显存不足。修复包含正确传递 `sess_options`、保守 cuDNN 卷积配置、检查输入张量、串行执行共享 session，以及识别到内存分配类错误后对该 session 切换 CPU 重试。CUDA 非法访问、参数错误等非分配异常不回退，CPU 也失败则继续报错，不返回假 OCR 结果。日志记录模型、输入尺寸和数据大小，便于服务器定位。

Ubuntu worker 启动前可设置：

```bash
export OCR_DEVICE=auto             # auto / cpu / cuda；排障可用 cpu
export OCR_GPU_FALLBACK_CPU=1      # GPU 内存分配失败后允许 CPU 接管
export OCR_CUDNN_CONV_ALGO_SEARCH=DEFAULT
```

修改后重启 task executor，使模型 session 重新创建。CPU 回退可能降低速度；这些回归测试不等于在 RTX PRO 5000 上完成 CUDA/cuDNN 联调。Picture 多模态模式跳过本地 OCR，模型计算仍由所选本地服务或商用 API 执行。

### 使用 start.sh run 的 CUDA 13 环境

`start.sh run` 与 `start.sh start` 等效，不会替换已经运行的进程。API、worker、可选 Admin 经由 `scripts/start_python.py` 启动：自动查找当前 `.venv` 中的 NVIDIA/Torch 动态库目录，将 cuDNN 放在系统 CUDA 目录之前，在进程启动时生效；同一服务进程中先导入 Torch，再导入 ORT。继承的 OpenFOAM 等路径保留在后方，不改系统配置。前端和 Docker 依赖不使用此 Python 包装入口。

本次服务器验证使用 Torch `2.14.0+cu130`、cuDNN `9.24.0`、ORT `1.27.0`。脚本不自动安装依赖；检测到 CUDA 13 搭配旧版 ORT 会停止启动并提示。仓库依赖仍锁定 ORT `1.23.2`，暂勿在此 CUDA 13 测试环境运行 `uv sync`，以免回退版本。

```bash
bash start.sh check-runtime                 # GPU 断言: 不满足即退出 1
bash start.sh check-executors [--strict]    # 是否有外部执行器抢同一 Redis 队列
bash start.sh restart
bash start.sh logs taskexec
```

`check-runtime` 真实验证 GPU，而不是只看导入：`torch.cuda.is_available()` 必须为真且设备数 ≥ 1，并且 `onnxruntime` 必须能找到、能加载随包发布的 CUDA provider（`libonnxruntime_providers_cuda.so`，含 cuDNN 等子库依赖可解析）。任一不满足就打印可执行建议并退出 1；`CUDA_VISIBLE_DEVICES` 被设成空串也会被点名。任务执行器带着这个断言启动，因此不会再出现"日志写着 GPU、实际静默回退 CPU"。确实要用 CPU 时设 `RAGFLOW_ALLOW_CPU=1`（只告警不终止，结束语会说明当前是 CPU-only），`RAGFLOW_REQUIRE_GPU=1` 则让后端/Admin 也强制要求 GPU。该检查不验证 OCR 准确率或 CUDA 卷积。

`check-executors` 读取 Redis `TASKEXE` 与各执行器心跳，报告不属于本栈命名（`TASK_EXECUTOR_TYPES/COUNT/OFFSET`）的执行器。外部实例（另一份 checkout 或旧部署指向同一 Redis）会抢同一队列，而它们的进程没有本仓库的 CUDA 运行库，抢到的任务 OCR 必然走 CPU。`start` 会自动执行该检查并告警（不终止），`--strict` 时以非零退出。处理方式：停掉那个实例，或让本栈改用独立 Redis DB。

运行日志开头的 `[runtime]` 行记录 Python、Torch、CUDA、ORT、provider 列表、实际设备数与库搜索路径。重启后请重新解析真实文档，确认不再出现子库加载失败或 `Falling back to ['CPUExecutionProvider']`。`Conv ... Fallback mode` 则是保守 cuDNN 算法的提示，不等于执行器切换到 CPU。脚本此次不修改算法设置和 OCR 析构清理行为。

### 回归命令

```bash
python test/unit_test/test_chunk_multimodal_archive.py -v
python test/unit_test/test_model_discovery_ocr_runtime.py -v
python test/unit_test/test_start_runtime.py -v
node --test test/unit_test/model_type_edit.test.cjs
```

最后一条使用 `web/node_modules/typescript`，也可通过 `TYPESCRIPT_PATH` 指定 TypeScript 编译器路径。测试加载实际 Hook 逻辑、隔离 React 状态与网络依赖，不替代浏览器交互测试。前端上线前在安装依赖的环境执行 `npm run type-check` 和 `npm run build`。

服务器验收至少包含：纯图、图文混排、复杂表格各一张；通过文件名及内容检索；检查图片引用；同图重解析确认缓存复用；改名后确认新文件名且没有重复模型调用；embedding 类型保存和连接验证。

## 原有 PDF 验收

```bash
python test/unit_test/test_chunk_multimodal_archive.py -v
```

先用一份带图片和合并表的短 PDF 开启功能；核对正文、表格列与图片描述，检查截图引用。重复解析确认缓存命中且模型请求数不增加；改变切分长度检查仅相同截图复用。提高版本标记确认产生新尝试。导出到另一持久目录、导入并复测，确认归档可以恢复。模型质量和完整服务联调需在实际 Ubuntu RAGFlow/模型服务环境完成。
