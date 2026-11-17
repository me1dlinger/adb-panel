"""进程内 MCP 协议网关。

主程序通过 Flask 的 POST /mcp 暴露 JSON-RPC 2.0 接口；是否允许调用由 config.json
中的 mcp_enabled 开关控制（默认关闭）。协议实现不依赖第三方 MCP SDK。
"""

from __future__ import annotations

import json
import logging

import mcp_tools

SERVER_NAME = "adb-console"
SERVER_VERSION = "2.0.0"
SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}

logger = logging.getLogger("adb-console-mcp")

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "alert": logging.CRITICAL,
    "emergency": logging.CRITICAL,
}

HTTP_OK = int("200")
HTTP_ACCEPTED = int("202")
HTTP_BAD_REQUEST = int("400")

INSTRUCTIONS = (
    "Android 设备测试工具集。设备未连接时返回 adb 的真实错误；"
    "配对端口与无线调试连接端口不同。"
    "调用工具会直接操作已连接设备（包括执行 shell、安装/卸载应用、重启），请谨慎使用。"
)


class McpError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class McpGateway:
    """把 JSON-RPC 消息分发给 mcp_tools。"""

    def pick_protocol(self, params: dict) -> str:
        requested = str((params or {}).get("protocolVersion") or "")
        if requested in SUPPORTED_PROTOCOLS:
            return requested
        if requested.startswith("2024-") or requested.startswith("2025-"):
            return requested
        return "2024-11-05"

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            return {
                "protocolVersion": self.pick_protocol(params),
                "capabilities": {
                    "tools": {"listChanged": False},
                    "logging": {},
                },
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS,
            }
        if method == "ping":
            return {}
        if method == "logging/setLevel":
            level = str((params or {}).get("level") or "").lower()
            if level not in _LOG_LEVELS:
                raise McpError(-32602, f"无效的日志级别：{level}")
            logger.setLevel(_LOG_LEVELS[level])
            return {}
        if method == "tools/list":
            tools = mcp_tools.manifest()
            return {"tools": tools}
        if method == "tools/call":
            params = params or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            data = mcp_tools.call_tool(name, arguments)
            text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            return {
                "content": [{"type": "text", "text": text}],
                "isError": not bool(data.get("ok")),
            }
        raise McpError(-32601, f"不支持的方法：{method}")

    def handle_message(self, message):
        """处理单条消息；通知（无 id）返回 None。"""
        if not isinstance(message, dict):
            return self.make_error(None, -32600, "无效的 JSON-RPC 消息。")
        method = message.get("method")
        if not isinstance(method, str):
            return self.make_error(message.get("id"), -32600, "缺少 method 字段。")
        if "id" not in message:
            logger.info("NOTIFICATION %s", method)
            return None
        request_id = message.get("id")
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}
        try:
            result = self._dispatch(method, params)
        except McpError as exc:
            return self.make_error(request_id, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - 网关必须保持可用
            logger.exception("MCP handler error")
            return self.make_error(
                request_id, -32603, f"内部错误：{type(exc).__name__}: {exc}"
            )
        logger.info("MCP %s id=%s", method, request_id)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def make_error(request_id, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def dispatch(self, payload):
        """返回 (HTTP 状态码, 响应体或 None)。通知批次返回 202。"""
        if isinstance(payload, list):
            responses = []
            for item in payload:
                response = self.handle_message(item)
                if response is not None:
                    responses.append(response)
            if not responses:
                return HTTP_ACCEPTED, None
            return HTTP_OK, responses
        if isinstance(payload, dict):
            response = self.handle_message(payload)
            if response is None:
                return HTTP_ACCEPTED, None
            return HTTP_OK, response
        return HTTP_BAD_REQUEST, self.make_error(None, -32600, "无效的 JSON-RPC 消息。")


gateway = McpGateway()
