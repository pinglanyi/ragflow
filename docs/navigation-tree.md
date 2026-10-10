# chunk-mm 导航树：多层、两层、编辑与移动

## 方案与研究结论

本分支采用一个完整目录、多种读取视图：生成时保留 Corpus-to-Skills 的主题层级，保存为 RAGFlow 的 `nav_cluster` / `nav_doc` 节点。前端默认显示完整多层树，也可切换为“主题 → 文件”两层视图。两层只是投影，不覆盖目录数据，不重新调用 LLM，不扫描原文 chunk。

例如同一份目录可以展示为：

```text
完整多层                       两层
注塑设备                       注塑设备
  控制系统                       操作手册.pdf
    开模控制                     参数说明.pdf
      操作手册.pdf
    参数说明.pdf
```

文件以下的章节仍可以继续展开；“两层”限定的是知识库主题与文件的层级，不会隐藏文件内的 PageIndex 章节。

综合已有实现，保留 RAGFlow 的检索、权限、MLLM 原文和引用链路，再增加可操作的导航层，适合当前产品库。没有必要为了目录显示另建一套 PDF 解析、索引和证据系统。

需要区分三个概念：

| 功能 | 本分支状态 | 用途 |
| --- | --- | --- |
| 知识库多层导航 | 本次补齐完整 Skill 分支的持久化和前端切换 | 从主题逐级定位文件 |
| RAGFlow `page_index` 编译模板 | 已有；本次保留文件下的展开链路和补充空结构提示 | 提取文件标题层级、论点、原文证据与 source_chunk_ids |
| VectifyAI PageIndex 引擎 | 没有作为依赖接入 | 独立的树索引与 LLM 推理式树检索方案 |

所以不能把“页面上出现 Tree”或“存在 page_index 模板”等同于已经接入第三项。VectifyAI 的方法是生成树索引，再让 LLM 推理检索树，见 [PageIndex 原仓库](https://github.com/VectifyAI/PageIndex)。本次没有把 Agentic Search 替换为该引擎。

## 前端操作

1. 部署新的后端及前端构建，进入知识库 → Artifacts → Tree。
2. 在“导航层级”中选择“完整多层”或“主题 → 文件（两层）”。展开主题时才读取子节点。
3. 点击主题或文件，右侧显示说明。点击“编辑 / 移动”后，可以修改显示名称、说明，或选择目标主题并保存。
4. 移动主题会连同其下的子主题和文件一起移动；主题可移动到顶层，文件必须位于主题下。服务端拒绝移入自身、后代或其他知识库中的节点。
5. 两层视图下，“保持当前实际父主题”不会把文件误移到当前显示的顶层主题。只有明确选择目标，才改变实际目录。
6. 点击文件的展开按钮读取文档结构；若没有生成结构，右侧给出配置 PageIndex / Tree 编译模板的提示。

这是“选择目标主题并保存”的移动操作，当前没有增加拖拽排序，也不支持修改文档原文中的章节层级。编辑文件显示名称不会重命名源文件、修改 dataset_id/doc_id 或改变 MinIO 文件位置。

空主题会保留，方便人工整理目录。保存成功会清除本地展开缓存并刷新查询，避免继续显示移动前的分支。

## 已有数据与 PageIndex 的准备

旧版本只把 Skill 树投影为两层并写入导航索引，中间主题已丢失，前端切换不能凭空恢复。更新后重新运行 To Skills，完成后会写入完整层级。原始知识库文件和 chunk 不需要因此重新上传。

**重新运行 To Skills 会重建导航并覆盖人工编辑。建议先生成完整树，再人工整理。** 本版本未增加人工改动跨全量重建的合并机制。

如果目录只能展开到文件，请检查该文件是否配置并完成了知识编译：在编译模板组中包含内置 `page_index`（或 `tree`）模板，将模板组应用到文件/知识库后执行相应编译流程。生成主题导航不会自动为所有文件补跑 PageIndex。

相关实现位置：

- `api/db/init_data/compilation_templates/page_index.yaml`：源标题优先、原文顺序、论点与证据规则。
- `rag/advanced_rag/knowlege_compile/structure.py`：结构编译与持久化。
- `GET /api/v1/datasets/{dataset_id}/documents/{document_id}/structure/graph`：读取文件结构。
- 前端 `nav-tree.ts`：文件叶子下挂载 PageIndex / Tree 章节。

模型没有正确提取标题时，不能保证文件拥有预期的章节层级；这属于文档编译质量问题，不是主题层级切换能解决的。

## API 调用

以下接口均使用已有 RAGFlow 登录认证或 API Key。成功响应为 `{"code":0,"data":...}`；错误需检查 `code` 和 `message`，不能只检查 HTTP 状态。

```bash
export BASE='http://127.0.0.1:9380'
export RAGFLOW_API_KEY='替换为自己的API key'
export DATASET_ID='替换为知识库ID'

# 顶层主题；两种视图共用相同的根。
curl -sS "$BASE/api/v1/datasets/$DATASET_ID/navigation" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY"

# 列出允许作为移动目标的主题，使用返回的 name 作为稳定标识。
curl -sS "$BASE/api/v1/datasets/$DATASET_ID/navigation/targets" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY"
```

`name` 是稳定标识，`display_name` 是可编辑标签，不能把显示名称当作节点标识。节点路径中的各段需 URL 编码，保留分隔用的 `/`。

文件节点的 `name` 使用 `doc_id`；旧版本按摘要生成的节点名称会在编辑保存时安全迁移，索引行 ID、文档 ID、原文证据保持不变。同摘要文件不会合并为一个节点。

```bash
export NODE_NAME='替换为API返回的节点name'
NODE_PATH=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe="/"))' "$NODE_NAME")

# 默认 hierarchical：只取实际直接子节点。
curl -sS "$BASE/api/v1/datasets/$DATASET_ID/navigation/$NODE_PATH/children?tree_mode=hierarchical" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY"

# two_layer：按主题保存的文档范围，读取文件叶子，保留人工名称和说明。
curl -sS "$BASE/api/v1/datasets/$DATASET_ID/navigation/$NODE_PATH/children?tree_mode=two_layer" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY"

# 修改显示名称、说明；不传 parent_name 就不会移动。
curl -sS -X PATCH "$BASE/api/v1/datasets/$DATASET_ID/navigation/$NODE_PATH" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" -H 'Content-Type: application/json' \
  -d '{"display_name":"开模控制","description":"破模、高压开模及相关控制说明"}'

# 移动；目标值替换为 targets 返回的 name。
curl -sS -X PATCH "$BASE/api/v1/datasets/$DATASET_ID/navigation/$NODE_PATH" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" -H 'Content-Type: application/json' \
  -d '{"parent_name":"目标主题的稳定name"}'

# 主题可移动到顶层；文件不允许这样移动。
curl -sS -X PATCH "$BASE/api/v1/datasets/$DATASET_ID/navigation/$NODE_PATH" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" -H 'Content-Type: application/json' \
  -d '{"parent_name":"root"}'
```

| 入参 | 规则 |
| --- | --- |
| `tree_mode` | `hierarchical`（默认）或 `two_layer`，只影响读取 |
| `display_name` | 可选，非空字符串，最多 200 字符 |
| `description` | 可选字符串，可清空，最多 20000 字符 |
| `parent_name` | 可选，知识库中已存在的主题 `name`；`root` 只用于主题 |

PATCH 至少传一个字段；拒绝其他字段和不存在节点。成功示例：

```json
{"code":0,"data":{"name":"原稳定节点name","updated":4}}
```

`updated` 是本次更新的索引节点数，包含深度/成员范围发生变化的祖先及后代，不是移动文件数。API 同时支持 `/nav/{name}` 的 PATCH 别名。

## 与检索的关系

目录编辑修改真实 `parent_kwd`，并重算子树 `depth_int`、各主题 `doc_ids_kwd` / `doc_count_int`。后续按目录路由的文件范围因此随移动变化。文件增删也向所有祖先传播成员变化。

原文 chunk ID、source_id、source_chunk_ids 和文件内容不变；Agentic Search 的 search/open/read/grep/navigate 仍走既有后端。目录编辑本身不会自动把普通 search 改成 LLM 遍历目录。

改名称和说明会更新词项索引；原有向量保留，不会为一次人工编辑调用 embedding 模型。若希望新主题说明完全参与语义向量路由，需要重新编译/生成对应索引。

## 性能、一致性与限制

- 层级切换不需要 LLM/embedding 调用；多层按父节点惰性加载，两层读取成员 ID、该页文件元数据和对应导航叶子。
- 编辑仅扫描 `dataset_nav` 节点，最多 10000 个；目标下拉最多 2000 个主题。超过限制明确报错，避免用截断数据修改目录。
- 服务端使用与目录生成相同的知识库锁，校验循环、孤儿和最大深度，再写入变化字段。Elasticsearch 刷新后返回，保证成功后的读取可见。
- 写入失败时尝试恢复已修改字段并返回错误；索引存储没有多行事务，不能承诺故障下的严格事务原子性。失败后应重新加载检查，日志会记录恢复失败。
- 手动编辑的是导航主题/文件；Wiki、Skill Markdown、文件章节内容不随之修改。

## 测试

后端（隔离仓库的集成测试配置）：

```bash
python -m pytest -c /dev/null --confcutdir=test/testcases/unit_test -p no:cacheprovider \
  test/testcases/unit_test/test_compilation_fallbacks.py \
  test/unit_test/api/apps/services/test_navigation_tree_modes.py \
  test/unit_test/api/apps/services/test_navigation_tree_edit.py \
  -k 'not wiki' -q
```

Windows 将 `/dev/null` 换成 `NUL`。`not wiki` 排除本次未修改的 Wiki 测试，其隔离桩未覆盖当前 Wiki LLMCallPool 依赖。

前端，在完整安装项目依赖后：

```bash
cd web
npm exec jest -- --runInBand --no-cache --runTestsByPath \
  src/pages/dataset/compilation/utils/nav-tree.test.ts \
  src/pages/dataset/compilation/nav-node-editor.test.tsx
```

测试覆盖递归层级写入、权限、两层投影、人工标签、实际父主题保留、循环拒绝、子树深度、祖先成员更新、空成员和零深度持久化、PageIndex 章节挂载、表单提交及错误展示。本机前端通过临时 Jest/React 依赖运行，未更改项目依赖和锁文件；没有以单元测试代替服务器部署后的端到端验收。

2026-10-10 本机验证：后端 29 项通过，1 项无关 Wiki 测试排除；前端 12 项通过；本次前端文件语法转换及 Python 编译检查通过。尚未执行完整前端生产构建及新版本部署后的 9380 联调。
