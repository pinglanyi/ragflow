# DeepDOC 分块裁图坐标异常修复

## 现场证据

账号 test1 的“HY测试”有两个失败文件，配置使用 DeepDOC，基础解析方式为 manual：

| 文件 | 失败任务页范围 |
| --- | --- |
| 《IS580-1系列伺服驱动器用户手册》（19010279-SC_B02，20170928） | 61–72 |
| 《ES810系列多机传动伺服驱动器用户手册》（20170829） | 73–84 |

两份文件的任务记录都在 `Finish parsing` 后报告 `Internal server error while chunking: Coordinate lower is less than upper`。这将调查范围指向解析后的分块处理。manual 最终通过 `tokenize_chunks` 调用 DeepDOC `crop` 生成分块预览。

已下载 IS580 原文件检查 PDF 页面信息：188 页，其中 61–72 页均为 595.22 × 842 pt、旋转 0 的 A4 页面。因此不能将本次现场问题直接认定为横竖页混排。

## 本地复现及修复

使用真实 Pillow 图像调用源代码中的 DeepDOC 裁图方法：单页上下坐标颠倒、坐标整体超出页面时，旧代码可复现完全相同的 `Coordinate 'lower' is less than 'upper'` 异常。另发现引用横坐标可能超出页面、空预览及上下文遮罩应用到正文的问题。

修复位于 `deepdoc/parser/pdf_parser.py`：

- 校正左右坐标，以及单页颠倒的上下坐标。
- 跨页标签按每页分别裁图；第一页的 top 和最后一页的 bottom 不进行互换。
- 裁图矩形和返回的引用位置都限制在对应页面范围内。
- 跳过空矩形并记录页码、边界和页面尺寸；无有效正文预览时返回 `(None, None)`，调用方继续处理文字。
- 显式记录上下文图像，避免跳过无效图块后把正文误加暗色遮罩。

本次不更改 OCR、模型配置或多模态解析流程。

## 验证

新增 `test/unit_test/deepdoc/parser/test_pdf_parser_crop_bounds.py`。修复前首批 7 项测试中 5 项失败，其中 3 项出现相同的 Pillow 坐标异常。修复后新增的 12 项测试与原有 13 项表格坐标测试全部通过。

```bash
python -m pytest \
  test/unit_test/deepdoc/parser/test_pdf_parser_crop_bounds.py \
  test/unit_test/deepdoc/parser/test_pdf_parser_table_coordinates.py \
  -q -p no:cacheprovider
```

本地 Python 环境 pytest 较旧，实际执行时额外使用 `-o filterwarnings=ignore::pytest.PytestConfigWarning`，仅忽略其不认识项目 asyncio 配置项的警告。

**验证边界：尚未获得服务器的完整裁图堆栈或失败时的实际矩形，尚未完成原文件的端到端重新解析。本地验证证明裁图路径的异常及修复有效，不能代替原文件部署复测。**

## 部署后复测

```bash
git pull --ff-only origin chunk-mm
bash start.sh restart
bash start.sh status
```

必须让解析任务执行器加载新代码，仅重启 9380 API 进程不足以更新正在运行的 worker。若使用其他服务管理方式，应重启对应的解析 worker。

在 test1 的“HY测试”中重新解析上述两份失败文件，确认：

1. 原先失败的 61–72 页和 73–84 页任务不再报裁图坐标异常。
2. 文档整体解析完成，产生可检索分块。
3. 页面引用及分块预览正常；无效预览可以缺省，但文字分块继续保留。
4. 若日志出现 `Skipping empty DeepDOC crop`，检查其中的页码、边界与页面尺寸；若仍失败，保留完整 Python 堆栈，确认是否来自其他裁图调用。

## 上游相关记录

[上游 PR #13483](https://github.com/infiniflow/ragflow/pull/13483) 已针对 MinerU 的同类坐标问题合入修复，其范围不能替代本次 DeepDOC 分块预览路径的处理。
