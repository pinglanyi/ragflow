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

## 重新部署 `a9b45a7ac` 后复测

产品库 `982c06185fc011f1ae03d7c376fa307f`，中文查询：`E502 10-CH TEMP COLLECTION 是什么模块？`。所有调用都在 `http://127.0.0.1:9380/api/v1/agentic-search/tools/` 下，成功结果均为 `code=0`。

| 调用 | 结果 |
|---|---|
| `search(query,top_k=5,dataset_ids=产品库ID)` | 5 个 chunk；首个 ID `6366ff56f4055e76`、文档 ID `1f87aac863ee11f1a9d2a33ecabf0a06`、offset 4 |
| `open(chunk_id=6366ff56f4055e76,window=2)` | 同一文档的 5 个 chunk，offset `[2,3,4,5,6]` |
| `read(source_id=上述文档,start_offset=2,end_offset=6)` | 5 个 chunk；ID 和顺序与 `open` 完全相同 |
| `navigate(source_id=上述文档,start_offset=4,end_offset=4,direction=previous,top_k=2)` | offset `[2,3]`，ID 与 `read` 对应 |
| `navigate(...,direction=next,top_k=2)` | offset `[5,6]`，ID 与 `read` 对应 |
| `grep(source_id=上述文档,pattern="E502",mode="phrase",top_k=5)` | 5 个命中 chunk，offset `[0,1,2,3,4]` |
| `search(...,exclude_ids=["6366ff56f4055e76"])` | 仍返回 5 个其他 chunk，排除列表中没有原锚块 |
| `search(query,top_k=5)`（不传 `dataset_ids`） | 自动选中“产品库”，5 个 chunk，首个仍为上述锚块、offset 4 |

读链路以相同文档 ID、chunk ID 和 offset 对照验证了相邻顺序。测试确认接口返回一致的可见 chunk 序号；本次没有单独读取存储层的原始 `chunk_order_int` 值。`ingest/delete` 按设计保持关闭，本次没有执行写入。

DeepAgent 的 `scripts/test_agentic_search_primitives.py` 对同一产品库调用 `search(top_k=2)` 返回退出码 0、2 个 chunk，首个 ID 与 offset 仍是 `6366ff56f4055e76` / 4，JSONL 记录了请求和响应。测试时发现 Windows GBK 控制台打印特殊字符可能抛 `UnicodeEncodeError`，已在 DeepAgent 脚本中设置 UTF-8 stdout 后重跑通过。
