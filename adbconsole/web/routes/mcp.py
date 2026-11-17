"""进程内 MCP 服务：POST /mcp 提供 JSON-RPC 2.0 接口。"""

from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, request

import adb_core
import adbconsole.config as app_config
import mcp_tools
from adbconsole.mcp.gateway import gateway

from ..common import api_route, payload

bp = Blueprint("mcp", __name__)


def _disabled_response():
    return (
        jsonify(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32000,
                    "message": "MCP 服务未启用。请在控制台「设置 → MCP 服务」中开启。",
                },
            }
        ),
        int("403"),
    )


@bp.post("/mcp")
def mcp_http():
    if not app_config.mcp_enabled():
        return _disabled_response()
    payload = request.get_json(silent=True)
    if payload is None:
        status, body = gateway.dispatch(None)
        return jsonify(body), status
    status, body = gateway.dispatch(payload)
    if body is None:
        return Response("", status=status)
    return jsonify(body), status


@bp.get("/api/mcp/tools")
@api_route
def api_mcp_tools():
    """与 MCP tools/list 等价的 HTTP 清单。"""
    if not app_config.mcp_enabled():
        return _disabled_response()
    tools = mcp_tools.manifest()
    return jsonify(adb_core.result(True, "", "", 0, tools=tools, count=len(tools)))


@bp.post("/api/mcp/tool")
@api_route
def api_mcp_tool():
    """与 MCP tools/call 等价的 HTTP 调用。"""
    if not app_config.mcp_enabled():
        return _disabled_response()
    data = payload()
    name = data.get("name") or data.get("tool")
    arguments = data.get("arguments")
    if arguments is None:
        arguments = data.get("args")
    return jsonify(mcp_tools.call_tool(name, arguments))


@bp.get("/mcp")
def mcp_http_info():
    """浏览器直接访问时给出提示；MCP 客户端应使用 POST。"""
    enabled = app_config.mcp_enabled()
    return (
        jsonify(
            {
                "ok": True,
                "service": "adb-console-mcp",
                "enabled": enabled,
                "transport": "POST JSON-RPC 2.0",
                "hint": "使用 POST 发送 JSON-RPC 消息；GET 仅用于状态检查。",
            }
        ),
        int("200") if enabled else int("403"),
    )
