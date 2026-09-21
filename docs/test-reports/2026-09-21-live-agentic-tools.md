# 9380 Agentic Search 原生工具线上验收（2026-09-21）

测试地址：`http://127.0.0.1:9380`。使用用户此前授权的 RAGFlow API key；以下记录不包含密钥。测试仅调用只读工具，并对 `delete` 做关闭状态检查，没有修改知识库。

## 当前部署 `373bf3eea` 的实测

| 调用 | 输入摘要 | 结果 |
|---|---|---|
| `search` | 产品库 `982c06185fc011f1ae03d7c376fa307f`，查询 E502，`top_k=5` | `code=102`，`Agentic Search tools require indexed text datasets` |
| `search` | 测试库 `15c86cecb32c11f1930a7d6cf2b0f5a3`，查询“大利 立式泵托架DL180-82-H145 图号” | `code=0`，1 个 chunk，ID `9185f0e5d0d0632e`，offset 0 |
| `search` | 同上，`exclude_ids=["9185f0e5d0d0632e"]` | `code=0`，0 个 chunk；排除生效 |
| `read` | 文档 `59a0cf00b4c511f1930a7d6cf2b0f5a3`，offset 0..0 | `code=0`，1 个 chunk，offset 0 |
| `grep` | 同文档，`pattern="图号"` | `code=0`，1 个 chunk，offset 0 |
| `navigate` | 同文档，offset 0..0，`next` | `code=0`，0 个 chunk；文档仅有一个 chunk，符合边界预期 |
| `open` | chunk `9185f0e5d0d0632e` | `code=102`，同产品库错误；按可访问库查找锚点时首先遇到带 `field_map` 的库 |
| `delete` | 同测试文档 | `code=102`，`Agentic Search ingest/delete tools are disabled`；未删除 |

产品库经 `GET /api/v1/datasets?page=1&page_size=100` 确认有 27,594 个 chunk，且 `parser_config` 带 `field_map`。现有 `RAGTools` 默认将带 `field_map` 的库划入 SQL 库，排除在普通文本 `kb_ids` 外；但这个产品库实际有可检索文本 chunk。故 `search/open` 在原生工具适配层误拒绝了它。

本轮修复给 `RAGTools` 增加 `include_field_mapped_kbs` 选项，仅在七个原生工具创建实例时开启。原有 Agentic RAG 默认行为不变。修复后需重新部署 9380，再以产品库 E502 问题复测 `search → open → navigate/read/grep`，重点核对逻辑 offset 和相邻顺序。当前记录不声称这条产品库链路已通过线上验收。
