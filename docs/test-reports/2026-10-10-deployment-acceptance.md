# 重启后部署验收（2026-10-10）

对象：9222 前端、9380 Python 后端，test2 测试账号。浏览器使用 Codex CUA；接口独立认证，无凭据写入报告。此次结果不能替代官方全部功能迁移验收。

## 已通过的线上操作

| 项目 | 实际证据 |
| --- | --- |
| 登录、首页、知识库、聊天、配置、Artifacts | 页面正常加载；未复现动态模块导入失败。 |
| Agentic 普通问答 | reasoning=1、空备用链；code=0，124 字符答案、2 条引用，约 4.7 秒。 |
| Agentic SSE | start/selection/progress/delta/final 完整，没有 error 事件，约 2.5 秒。 |
| 产品库 reasoning=4 | CAN 接线问题 code=0，1075 字符答案、3 条引用，25.1 秒；返回 reasoning=4。响应不含工具轨迹，不能据此断言本次使用了 Tree/Wiki/Graph。 |
| 参数校验 | reasoning=5 和非列表 failover_llm_ids 均明确拒绝。 |
| 原文导航工具 | 扫描 PDF 与产品库 CAN 内容的 search/open/read/grep/navigate 均 code=0。 |
| 无查询词元数据选择 | acceptance_model=GPU-PROBE-42、acceptance_year=2026 均 reason=matched，返回扫描 PDF；未知字段明确返回 unknown_field。 |
| Wiki 模板 | Global rules、实体/关系/声明/概念规范、Blueprint、Instruction、Example 可见。Global rules 加测试后缀、保存、重开确认持久化，随后恢复原文。 |
| Tree 模板 | Global rules、Summarization prompt、Claim extraction prompt、RAPTOR 参数均可见。 |
| 已有 Wiki 结果 | 测试库 Artifacts 显示已有主题导航。未在本轮重新生成所有类型的 Artifact。 |
| full/smart 多模态 | 缓存样例完成后，另生成新图片排除旧缓存。两个新任务均 complete、progress=1，各入库 1 个 chunk；均保留 256 Hz、36 V 参数。 |
| 新图片模型调用 | full：7.739 秒、1004 tokens；smart：7.667 秒、819 tokens、routed_chunks=1。smart 可复用同图 full 的解析缓存；用量包含此次路由调用。 |
| 执行器隔离 | 6/7/8 心跳 PID=3656508/3656830/3657102，均监听 te.ragflow_python_9380.1.common 与 te.ragflow_python_9380.0.common。未停止其他执行器。 |

新图片任务：full `28571e922bf24e3f91971f9dbdb2d3e9`；smart `5404228aaf3544378be8e09e17492d94`。测试文件保留在原有独立诊断知识库 `25677b88c44911f1b62f0301fcd77cb5`，未重新解析产品库文件。

## 发现并在本地修复（待部署复验）

1. **备用模型保存丢失**：实际 UI 添加备用模型可见，保存后为空。聊天基础表单将 `llm_setting` 与字段名直接拼接，少了点，提交校验过滤了错误字段。改为正确嵌套路径。新增真实基础设置组件测试，覆盖无前缀、`chat.` 前缀；修复前两项失败、修复后通过。既有备用模型显示测试一起通过，共 6 项。
2. **单片段图片不能 open/read/grep/navigate**：图片能被搜索命中，但没有 chunk_order_int 或页面坐标，文档迭代器拒绝整个文档。单个来源片段顺序没有歧义，允许其读取，保留缺失坐标而不伪造页面位置。多片段缺少顺序仍拒绝；租户、文档、重复 ID 校验保持。修复前新增用例复现，修复后文档迭代及导航共 21 项通过。线上当前仍是修复前行为。

## 尚不能签收的范围

- 真实模型主服务故障后的自动切换尚未演练；本次确认配置界面和参数入口，并发现上述保存缺陷。
- MCP 目录接口正常，但 test2 没有服务器，不能把空列表的掩码检查算作凭据恢复或 SSE/HTTP 联通验收。
- Docling remote、OSS、Search1API、其他新供应商未提供对应服务/凭据，本次未做真实调用。
- BOM、引用外链、筛选刷新、Retrieval 工作流、API Key 上限沿用前一轮本地回归，本轮没有逐项线上复测。
- 本轮心跳证明队列隔离，不直接证明 OCR GPU 占用；视觉供应商 tokens 也不是本机显存证据。
- 浏览器出现两条 react-resizable-panels 的 50% 布局归一化 warning；本轮未观察到页面崩溃或控制台 error。

## 验收结论

主要问答、文档工具、元数据选择、模板编辑和多模态任务通过；整体不能标为全部通过。两项修复需要拉取后重启前后端再复验。

本次修复的 Python 定向回归（文档迭代、导航、关键词、强制检索入口）28 passed；前端两套 6 passed。扩大到全部 unittest 时，另有 12 个 unseen-search 用例因本地隔离环境缺少 aiohttp 等完整模型依赖而无法加载；不能将此扩大运行宣称为全绿，也不能据此判定线上检索故障。线上产品库与诊断库的真实检索已单独通过。

修复后的前端 Vite 生产构建 exit=0，5m17s（VITE_MINIFY=esbuild）；仍有既有循环 chunk、PDF.js eval 和大 chunk 警告。
