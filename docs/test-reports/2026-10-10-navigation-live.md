# 9380 导航树线上测试（2026-10-10）

测试服务：`http://127.0.0.1:9380`，使用产品库已有导航数据。凭据未写入本报告。

## 线上通过项

- 根节点、移动目标列表均返回 16 个主题。
- 编辑主题显示名称、描述后可立即读到修改结果。
- 临时将一个含 4 个文件的主题移动到含 5 个文件的主题下：父节点更新，主题深度变为 1、文件深度变为 2；根列表不再显示被移动主题，目标祖先文件数更新为 9。
- 两层投影返回目标主题下全部 9 个文件。
- 循环移动、自引用、未知父节点、以文件为父节点、将文件移到根目录均被拒绝。
- 文件跨主题移动后，两边文件数从 4/5 更新为 3/6，文件归属同步改变。
- 所有临时名称、描述、父节点、文件归属和文件数均已恢复并核对一致。
- 一个抽样文件的文档结构接口返回 `templates: []`；该文件没有现成章节树，本次不能证明其章节导航可用。

## 发现的问题与修复验证

移动后的 `GET /navigation/{name}/children?tree_mode=hierarchical` 返回平铺文件，没有返回直接子主题，因此本次线上验收不是全部通过。

直接读取实际 Elasticsearch 映射确认：该租户索引的 `parent_kwd` 是 `text`，同时存在 `parent_kwd.keyword` 精确子字段。完整主题标识被分析器拆词，原来的 `terms(parent_kwd)` 查不到直接子节点，触发了文件成员兜底。根节点 `root` 恰好是单个词项，所以根列表能够正常显示。

修复在 Elasticsearch 的 search/update/delete 父节点条件中统一使用精确匹配：存在 `.keyword` 时匹配该子字段；没有该子字段时使用本身为 keyword 的 `parent_kwd`，避免把分析后的词项当作主题身份。

已用修复生成的查询在实际搜索索引只读验证：根节点 16 条、抽样主题直接文件 5 条、主题名片段 0 条。回归测试覆盖两种映射、标量/列表条件、完整身份匹配与部分身份排除。**此验证不等于修复后的 9380 HTTP 接口已通过；需部署本次代码并重启后再复测多层读取。**

## 本地验证

```bash
python -m pytest -c /dev/null --confcutdir=test/testcases/unit_test -p no:cacheprovider \
  test/testcases/unit_test/test_compilation_fallbacks.py \
  test/unit_test/api/apps/services/test_navigation_tree_modes.py \
  test/unit_test/api/apps/services/test_navigation_tree_edit.py \
  test/unit_test/api/apps/services/test_navigation_parent_filter.py \
  -k 'not wiki' -q
```

Windows 将 `/dev/null` 换成 `NUL`。排除项是独立 Wiki 测试，不属于本次目录修改的验收范围。本次没有完成部署页面的浏览器交互验收，也没有运行完整前端生产构建。
