# ADB Console MCP 能力文档

ADB Console 把本机 adb 能力以 23 个工具的形式暴露给 MCP 客户端（Claude Desktop、Cursor、Cline、自研 Agent 等）。MCP 服务已合并进主程序，**默认关闭**；在页面「设置 → MCP 服务」中开启，开启前会要求确认风险。

## 接入方式

1. 启动 ADB Console（源码 `python app.py` / `python run.py`，或双击 `ADBConsole.exe`）。
2. 打开页面，进入「设置 → MCP 服务」，开启开关并确认风险提示。
3. 按客户端支持的传输方式连接（端口以启动日志为准，默认 5010）。

## 传输方式

| 传输 | 入口 | 说明 |
| --- | --- | --- |
| Streamable HTTP | `POST /mcp` | JSON-RPC 消息；`Accept: application/json` 返回 JSON，`Accept: text/event-stream` 返回 SSE 事件流 |
| Streamable HTTP | `GET /mcp` | 带 SSE Accept 时保持独立 SSE 通道（keepalive）；否则返回传输能力说明 JSON |
| Streamable HTTP | `DELETE /mcp` | 携带 `Mcp-Session-Id` 结束会话 |
| 旧版 HTTP+SSE | `GET /sse` | 首个 `endpoint` 事件给出 `POST /messages?session_id=...` 地址，后续响应由该 SSE 通道推送 |
| 旧版 HTTP+SSE | `POST /messages?session_id=...` | 发送 JSON-RPC 消息，返回 202 |
| stdio | `mcp_server.py` | 仅给只能以 stdio 启动的客户端保留 |

- 协议：JSON-RPC 2.0；支持 `initialize`、`notifications/initialized`、`ping`、`logging/setLevel`、`tools/list`、`tools/call`。
- `initialize` 响应会返回 `Mcp-Session-Id`；后续请求可携带该头。
- 关闭开关后所有 MCP 入口返回 HTTP 403，页面右上角显示「MCP 关」。
- 不需要也不建议再单独启动 `mcp_server.py`。

## 客户端配置

开启 MCP 后，设置页会显示访问令牌和请求头 JSON。请把它填入客户端的自定义请求头（不同客户端可能叫 `headers` / `requestHeaders` /“请求头”）。

Streamable HTTP（推荐）：

```json
{
  "mcpServers": {
    "adb-console": {
      "url": "http://127.0.0.1:5010/mcp",
      "headers": {
        "Authorization": "Bearer <设置页显示的令牌>"
      },
      "timeoutMs": 60000
    }
  }
}
```

旧版 HTTP+SSE：

```json
{
  "mcpServers": {
    "adb-console": {
      "url": "http://127.0.0.1:5010/sse",
      "headers": {
        "Authorization": "Bearer <设置页显示的令牌>"
      },
      "timeoutMs": 60000
    }
  }
}
```

## 鉴权

- 首次开启 MCP 时自动生成访问令牌，保存在本机 `config.json`。
- 默认请求头：`Authorization: Bearer <token>`；头名称可在“设置 → MCP 服务 → 请求头鉴权”中修改。
- 兼容三种写法：裸 token、`Bearer <token>`、`Token <token>`；同时接受 `X-MCP-Token` 作为回退头。
- 未携带或令牌错误的 MCP 请求返回 HTTP 401（JSON-RPC 错误码 `-32001`）。
- 旧版 SSE：`GET /sse` 必须携带令牌；`POST /messages` 可携带令牌，或使用已通过鉴权建立的 `session_id`。
- 点击“重新生成令牌”后旧令牌立即失效，需要同步更新客户端配置。
- `/api/mcp/tools`、`/api/mcp/tool` 同样需要令牌。

SSE 响应示例：

```bash
curl -N -X POST http://127.0.0.1:5010/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -H "Accept: text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26"}}'
# event: message
# data: {"jsonrpc":"2.0","id":1,"result":{...}}
```

- 工具失败时 `result.isError = true`，文本内容仍是结构化 JSON，不会伪造成功。

## 通用约定

- **serial 参数**：所有涉及设备的工具都接受可选 `serial`（设备序列号）。省略时自动使用唯一在线设备；多设备在线且未指定时返回明确错误。
- **返回格式**：每个工具返回紧凑 JSON，至少包含：

```json
{ "ok": true, "stdout": "...", "stderr": "...", "code": 0 }
```

失败时 `ok=false`，`stdout`/`stderr` 是 adb 的原始输出，`code` 是 adb 退出码。部分工具附带额外字段（如 `adb_screenshot` 的 `file`、`url`、`thumbnail_base64`；`adb_pull` 的 `local_path`、`download_url`）。

- **adb 路径**：与网页服务共用同一配置（`config.json` > 环境变量 `ADB_PATH` > PATH 探测）。

## 典型调用流程（AI 提示）

1. `adb_devices` / `adb_status` 查看在线设备与发现结果；
2. 无线设备未连接时先 `adb_pair`（配对端口 + 6 位配对码），再 `adb_connect`（无线调试端口，注意两个端口不同）；
3. 用 `adb_device_info` 获取屏幕分辨率与前台应用；
4. 用 `adb_shell` / `adb_tap` / `adb_swipe` / `adb_key` 操控设备；
5. 用 `adb_screenshot` 截图确认界面状态，用 `adb_logcat` 排查日志。

## 工具清单

### 设备连接

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `adb_status` | `serial?` | 设备状态、mDNS 自动发现与自动连接结果 |
| `adb_devices` | — | 列出设备与 mDNS 自动发现服务 |
| `adb_connect` | `host*`, `port*` | `adb connect` 连接无线设备 |
| `adb_pair` | `host*`, `port*`(配对端口), `code*`(6 位配对码) | 配对无线设备；配对端口 ≠ 连接端口 |
| `adb_disconnect` | `serial?` | 断开指定设备或全部无线连接 |

### Shell 与应用

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `adb_shell` | `cmd*`, `serial?`, `timeout?`(1–300s) | 执行单条设备 shell 命令 |
| `adb_install` | `apk_path*`(本机路径), `serial?` | 推送并 `adb install -r` |
| `adb_uninstall` | `package*`, `serial?` | 卸载应用 |
| `adb_launch` | `package*`, `activity?`(如 `.MainActivity`), `serial?` | 启动应用或指定 Activity |
| `adb_force_stop` | `package*`, `serial?` | 强制停止应用 |
| `adb_clear_data` | `package*`, `serial?` | 清除应用数据 |
| `adb_package_list` | `filter?`, `third_party?`(bool), `serial?` | 包列表筛选 |

### 信息读取

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `adb_device_info` | `serial?` | 型号、系统、电量、存储、内存、网络、屏幕、前台应用 |
| `adb_processes` | `serial?` | 进程列表（PID、名称、RSS） |
| `adb_screenshot` | `serial?` | 截图保存到 `screenshots/`，返回文件路径与 base64 小图 |
| `adb_logcat` | `lines?`(20–5000，默认 200), `filter?`, `serial?` | 读取最近日志 |
| `adb_logcat_clear` | `serial?` | 清空 logcat 缓冲区 |

### 文件传输

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `adb_push` | `local_path*`(须在项目目录内), `remote_path*`, `serial?` | 推送文件到设备 |
| `adb_pull` | `remote_path*`, `local_name?`, `serial?` | 拉取文件到 `pulls/`，返回下载地址 |

### 触控 / 按键 / 重启

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `adb_tap` | `x*`, `y*`, `serial?` | 坐标轻触 |
| `adb_swipe` | `x1*`, `y1*`, `x2*`, `y2*`, `duration_ms?`(50–10000，默认 300), `serial?` | 滑动 |
| `adb_key` | `code*`(`home`/`back`/`recent`/`power`/`volume_up`/`volume_down` 或数字键值), `serial?` | 按键事件 |
| `adb_reboot` | `mode?`(`system`/`recovery`/`bootloader`，默认 `system`), `serial?` | 重启设备 |

`*` 为必填参数，`?` 为可选参数。

## HTTP 等价接口

不使用 MCP 时，同样的工具能力可通过 HTTP 调用（需先在页面开启 MCP 服务）：

- `GET /api/mcp/tools` — 获取本清单（含完整 JSON Schema）；
- `POST /api/mcp/tool` — `{"name": "adb_shell", "arguments": {"cmd": "wm size"}}`；
- `GET /api/mcp/status` — 开关状态、工具数量与风险提示；
- `POST /api/mcp/toggle` — `{"enabled": true, "acknowledge_risk": true}` 开启或关闭。

HTTP API 全表见 [API.md](API.md)。
