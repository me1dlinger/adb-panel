# ADB Console HTTP API 文档

Base URL：`http://127.0.0.1:<port>`（默认 5010，被占用时自动顺延到 5010–5049；实际地址见启动日志）。

## 通用约定

- 请求体：JSON（`application/json`）；文件上传用 `multipart/form-data`。
- 标准响应：

```json
{ "ok": true, "stdout": "", "stderr": "", "code": 0 }
```

失败时 `ok=false`，`stdout`/`stderr` 为 adb 原始输出，`code` 为 adb 退出码。
- `serial` 参数：多数接口接受可选设备序列号。省略时使用唯一在线设备；多设备时需显式指定。
- 所有接口只监听 `127.0.0.1`。

## 系统与 adb 配置

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/status` | — | 设备、mDNS、自动连接快照，附当前 adb 路径 |
| GET | `/api/meta` | — | 程序版本、数据目录、当前 adb 路径 |
| GET | `/api/adb/config` | — | 读取当前 adb 路径 |
| POST | `/api/adb/config` | `{"adb_path": "..."}` | 校验（`adb version`）并保存 adb 路径到 `config.json` |
| POST | `/api/adb/test` | `{"adb_path": "..."}`（空则测试当前路径） | 仅测试路径可用性，**不修改**已保存配置 |
| POST | `/api/adb/browse` | `{"initialdir": "..."}`（可选） | 弹出系统文件选择框，返回 `{"path": "...", "cancelled": false}` |

## 设备发现与连接

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/devices` | — | 设备与 mDNS 发现列表 |
| POST | `/api/autoconnect` | — | 强制扫描并等待自动连接完成 |
| POST | `/api/connect` | `{"host": "IP", "port": 5555}` | 连接无线设备 |
| POST | `/api/pair` | `{"host": "IP", "port": 配对端口, "code": "123456"}` | 无线配对（配对端口 ≠ 连接端口） |
| POST | `/api/disconnect` | `{"serial": "..."}` | 断开设备 |

## 设备信息

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/device/info` | `?serial=` | 实时状态（电量、存储、内存、网络、屏幕、前台应用等） |
| GET | `/api/processes` | `?serial=` | 进程列表（PID、名称、RSS） |
| GET | `/api/packages` | `?filter=&third_party=1&serial=` | 包列表 |
| GET | `/api/screen/size` | `?serial=` | 屏幕分辨率 |

## 应用管理

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/app/start` | `{"package": "...", "activity": ".MainActivity"}` | 启动应用 / Activity |
| POST | `/api/app/stop` | `{"package": "..."}` | 强制停止 |
| POST | `/api/app/clear` | `{"package": "..."}` | 清除数据 |
| POST | `/api/app/uninstall` | `{"package": "..."}` | 卸载 |
| POST | `/api/install` | `file`（multipart 上传 APK）或 `{"local": "本机 APK 路径"}` | 安装 APK |

## Shell 与重启

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/shell` | `{"cmd": "...", "timeout": 30}` | 执行设备 shell 命令 |
| POST | `/api/reboot` | `{"mode": "system|recovery|bootloader"}` | 重启 |

## 屏幕与操控

| 方法 | 路径 | 参数 / 响应头 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/screen/frame` | `?serial=` | 单帧 PNG。响应头 `X-Device-Width` / `X-Device-Height` / `X-Capture-Ms` / `X-Frame-Ts`（用于去重）；无设备时返回 JSON 错误 |
| GET | `/api/screen/stream` | `?serial=` | MJPEG 风格 PNG 流（multipart/x-mixed-replace） |
| POST | `/api/screen/start` | `?serial=` | 启动后台取帧镜像 |
| POST | `/api/screen/stop` | `?serial=` | 停止镜像 |
| GET | `/api/screen/stats` | `?serial=` | 镜像帧率 / 延迟统计 |
| POST | `/api/screenshot` | `{"serial": "..."}` | 截图保存到 `screenshots/`，返回文件与缩略图 |
| GET | `/api/screenshot/file/<name>` | — | 查看已保存截图 |
| POST | `/api/tap` | `{"x": 500, "y": 800}` | 坐标轻触 |
| POST | `/api/swipe` | `{"x1","y1","x2","y2","duration_ms":300}` | 滑动 |
| POST | `/api/key` | `{"code": "home|back|recent|power|volume_up|volume_down" 或数字键值}` | 按键 |

## 日志（logcat）

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/logcat` | `{"lines": 200, "filter": ""}` | 读取最近日志 |
| POST | `/api/logcat/clear` | — | 清空缓冲区 |
| POST | `/api/logcat/stream/start` | — | 启动实时日志流 |
| POST | `/api/logcat/stream/stop` | — | 停止实时日志流 |
| GET | `/api/logcat/stream` | `?since=0&filter=&level=V&limit=500` | 增量拉取实时日志 |

## 文件传输

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/push` | `file`（multipart）或 `{"local": "项目目录内路径"}` + `{"remote": "/sdcard/..."}` | 推送到设备 |
| POST | `/api/pull` | `{"remote": "/sdcard/x", "local_name": "x"}` | 拉取到 `pulls/` |
| GET | `/api/pulls` | — | 已拉取文件列表 |
| GET | `/api/download/<name>` | — | 下载已拉取文件（拒绝目录穿越） |

## MCP 对齐接口

MCP 默认关闭；以下接口和 `/mcp` 一样，在关闭时返回 HTTP 403（`/api/mcp/status` 除外）。开启后，MCP 入口需要携带访问令牌（默认 `Authorization: Bearer <token>`），未授权返回 401；`/api/mcp/status`、`/api/mcp/toggle`、`/api/mcp/auth` 供本地页面使用，不校验令牌。

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/mcp/status` | — | MCP 开关、工具数量、传输方式、鉴权信息与风险提示 |
| POST | `/api/mcp/toggle` | `{"enabled": true, "acknowledge_risk": true}` | 开启 / 关闭 MCP；开启自动生成令牌 |
| POST | `/api/mcp/auth` | `{"header": "Authorization"}` 或 `{"regenerate": true}` | 修改鉴权头名称或重新生成令牌 |
| GET | `/api/mcp/tools` | 请求头令牌 | MCP 工具清单（含 JSON Schema） |
| POST | `/api/mcp/tool` | 请求头令牌 + `{"name": "adb_shell", "arguments": {"cmd": "..."}}` | 调用任意 MCP 工具 |
| POST | `/mcp` | 请求头令牌 + JSON-RPC 2.0 消息 | Streamable HTTP：普通请求返回 JSON；`Accept: text/event-stream` 返回 SSE 事件流 |
| GET | `/mcp` | 请求头令牌 + `Accept: text/event-stream` | 带 SSE Accept 时打开 keepalive 通道，否则返回传输能力说明 JSON |
| DELETE | `/mcp` | 请求头令牌 + `Mcp-Session-Id` | 结束 Streamable HTTP 会话 |
| GET | `/sse` | 请求头令牌 + `?protocol=` 可选 | 旧版 HTTP+SSE：首个 `endpoint` 事件给出消息入口地址 |
| POST | `/messages` | `?session_id=`（或请求头令牌）+ JSON-RPC 消息 | 旧版 HTTP+SSE 的消息入口，响应由 `/sse` 推送，返回 202 |

工具能力详见 [MCP.md](MCP.md)。
