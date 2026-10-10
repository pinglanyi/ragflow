# Search1API Python 工作流移植设计

用户已授权按功能差异清单补缺口并保留原功能。官方基线 f2e618aed；当前 Python 基线 8ba9958ce。

采用现有 Python ToolBase/ToolParamBase 自动注册方式增加 Search1APISearch 与 Search1APICrawl。前端移植官方节点、Agent 工具表单及日志、导出凭据清理接线。搜索支持 general/news、各自服务枚举、时间范围及 1–50 条结果；模型参数中不包含 api_key。抓取只接收绝对 HTTP(S) URL，返回页面对象。

连接器集中持有固定 Search1API 服务地址，新增严格原始结果方法供工具调用；原聊天 search/retrieve_chunks 的六条结果和失败返回空行为保持。工作流失败写 _ERROR，不伪装成功，不透出凭据，不自动重复计费请求；请求有超时、调用前后检查取消。搜索证据用现有确定性 URL/内容 ID，输出 formalized_content 和 json；抓取输出 json。

不选整体 cherry-pick Go 组件（无法服务 Python），也不写另一套独立 HTTP 实现（避免重复维护）。先做连接器和工具失败测试，再实现，再测试前端节点初值、日志名和导出清理，最后生产构建与原有重点回归。线上供应商验收需要实际 Search1API 凭据，不能用百炼或 DeepSeek 密钥代替。

对照工作另行记录逐提交影响文件和关键 Python 路径。确认已有标明依据；没有证据的项目继续标待验，不能因 Go 修复就判定 Python 缺失。不会修改他人的 worker、生产数据或模型绑定。
