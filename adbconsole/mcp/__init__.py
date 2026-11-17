"""MCP 协议层：进程内网关与兼容的 stdio 入口。"""

from .gateway import McpError, McpGateway, gateway

__all__ = ["McpError", "McpGateway", "gateway"]
