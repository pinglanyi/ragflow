# 本项目原生 MCP 启动

在项目根目录中运行：

```bash
bash start.sh start-mcp
bash start.sh stop-mcp
bash start.sh restart-mcp
bash start.sh status
bash start.sh logs mcp
```

`start-mcp` 仅启动原生 `mcp/server/server.py`，不启动 Docker、后端、前端或执行器。
完整 `bash start.sh start` 默认也启动 MCP；`START_MCP=0 bash start.sh start` 可跳过。
完整 `stop` 和 `restart` 同样管理 MCP。进程日志及 PID 文件位于 `/tmp/ragflow/mcp.log`、`/tmp/ragflow/mcp.pid`；
使用自定义 `LOG_DIR` 时，所有管理命令须使用相同目录。

默认配置：

| 设置 | 默认值 |
| --- | --- |
| `RAGFLOW_MCP_HOST` | `0.0.0.0` |
| `RAGFLOW_MCP_PORT` | `19382` |
| `RAGFLOW_MCP_BASE_URL` | `http://127.0.0.1:${BACKEND_PORT}`，当前为 9380 |
| `RAGFLOW_MCP_LAUNCH_MODE` | `host`，每个客户端使用自己的 API Key |

局域网 SSE 地址：`http://<服务器地址>:19382/sse`。
Streamable HTTP 地址：`http://<服务器地址>:19382/mcp`。
客户端请求头设置 `Authorization: Bearer <RAGFlow API Key>`。
提供 `ragflow_retrieval`、`ragflow_list_datasets`、`ragflow_list_chats` 工具，权限由 API Key 对应的后端账号决定。

覆盖监听端口或后端时，用相同环境变量运行启动、停止、状态命令。
脚本拒绝占用已有端口，不会杀掉端口上的其他服务。MCP 无需另建 Docker 容器，也不加载 GPU 解析运行时。
这是随项目脚本管理的后台进程，未配置开机自启动。

如需跨机器访问，请按实际客户端来源地址在服务器防火墙中放行 TCP `19382`。
