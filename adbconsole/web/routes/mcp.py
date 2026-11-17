"""进程内 MCP 服务。

传输方式：
    POST   /mcp         Streamable HTTP：JSON 或 SSE 响应
    GET    /mcp         Streamable HTTP 的独立 SSE 通道（keepalive）
    DELETE /mcp         结束 Streamable HTTP 会话
    GET    /sse         旧版 HTTP+SSE 传输：先下发 endpoint 事件
    POST   /messages    旧版 HTTP+SSE：客户端消息入口

是否允许调用由 config.json 的 mcp_enabled 开关控制（默认关闭）。
"""

from __future__ import annotations

import json
import queue
import time

from flask import Blueprint, Response, jsonify, request

import adb_core
import adbconsole.config as app_config
import mcp_tools
from adbconsole.mcp.gateway import gateway
from adbconsole.mcp.sessions import sessions

from ..common import api_route, payload

bp = Blueprint("mcp", __name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
SSE_KEEPALIVE_SECONDS = 15
SSE_RETRY_MS = 3000


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


def _sse_message(message) -> str:
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    return f"event: message\ndata: {data}\n\n"


def _accepts_sse() -> bool:
    return "text/event-stream" in (request.headers.get("Accept") or "").lower()


def _messages(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    return []


def _initialize_protocol(payload) -> str:
    for message in _messages(payload):
        if isinstance(message, dict) and message.get("method") == "initialize":
            params = message.get("params")
            if isinstance(params, dict):
                return str(params.get("protocolVersion") or "")
    return ""


def _has_initialize(payload) -> bool:
    return any(
        isinstance(message, dict) and message.get("method") == "initialize"
        for message in _messages(payload)
    )


def _streamable_session(payload) -> str:
    session_id = (request.headers.get("Mcp-Session-Id") or "").strip()
    if session_id:
        return session_id
    if _has_initialize(payload):
        return sessions.create(_initialize_protocol(payload), "streamable").id
    return ""


def _response_stream(body):
    messages = body if isinstance(body, list) else [body]
    for message in messages:
        yield _sse_message(message)


# --------------------------------------------------------------------------- #
# Streamable HTTP
# --------------------------------------------------------------------------- #


@bp.post("/mcp")
def mcp_http():
    if not app_config.mcp_enabled():
        return _disabled_response()

    incoming = request.get_json(silent=True)
    if incoming is None:
        status, body = gateway.dispatch(None)
        return jsonify(body), status

    session_id = _streamable_session(incoming)
    status, body = gateway.dispatch(incoming)

    headers = {"Mcp-Session-Id": session_id} if session_id else {}

    if body is None:
        return Response("", status=status, headers=headers)

    if _accepts_sse():
        return Response(
            _response_stream(body),
            mimetype="text/event-stream",
            headers={**SSE_HEADERS, **headers},
        )

    if headers:
        response = jsonify(body)
        response.headers.update(headers)
        return response, status
    return jsonify(body), status


@bp.get("/mcp")
def mcp_http_info():
    """浏览器直接访问给出说明；MCP 客户端带 Accept: text/event-stream 时打开 SSE 通道。"""
    if not app_config.mcp_enabled():
        return _disabled_response()

    if not _accepts_sse():
        return jsonify(
            {
                "ok": True,
                "service": "adb-console-mcp",
                "enabled": True,
                "transports": {
                    "streamable-http": {
                        "url": "/mcp",
                        "methods": ["POST", "GET", "DELETE"],
                    },
                    "http-sse": {"sse": "/sse", "messages": "/messages"},
                    "stdio": {"entry": "mcp_server.py"},
                },
                "hint": "POST /mcp 发送 JSON-RPC；Accept: text/event-stream 可获得 SSE 响应。",
            }
        )

    def generate():
        try:
            yield f"retry: {SSE_RETRY_MS}\n\n"
            yield ": connected\n\n"
            while True:
                yield ": ping\n\n"
                time.sleep(SSE_KEEPALIVE_SECONDS)
        except GeneratorExit:
            return

    return Response(generate(), mimetype="text/event-stream", headers=SSE_HEADERS)


@bp.delete("/mcp")
def mcp_delete():
    if not app_config.mcp_enabled():
        return _disabled_response()
    sessions.remove((request.headers.get("Mcp-Session-Id") or "").strip())
    return Response("", status=int("204"))


# --------------------------------------------------------------------------- #
# 旧版 HTTP+SSE
# --------------------------------------------------------------------------- #


@bp.get("/sse")
def mcp_sse():
    if not app_config.mcp_enabled():
        return _disabled_response()

    session = sessions.create(request.args.get("protocol") or "", "sse")
    endpoint = request.host_url.rstrip("/") + "/messages?session_id=" + session.id

    def generate():
        try:
            yield f"retry: {SSE_RETRY_MS}\n\n"
            yield f"event: endpoint\ndata: {endpoint}\n\n"
            while True:
                try:
                    message = session.queue.get(timeout=SSE_KEEPALIVE_SECONDS)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if message is None:
                    break
                yield _sse_message(message)
        except GeneratorExit:
            return
        finally:
            sessions.remove(session.id)

    return Response(generate(), mimetype="text/event-stream", headers=SSE_HEADERS)


@bp.post("/messages")
def mcp_sse_messages():
    if not app_config.mcp_enabled():
        return _disabled_response()

    session_id = (
        request.args.get("session_id")
        or request.headers.get("Mcp-Session-Id")
        or ""
    ).strip()
    session = sessions.get(session_id)
    if session is None:
        return (
            jsonify(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32001,
                        "message": "SSE 会话不存在或已过期，请重新连接 /sse。",
                    },
                }
            ),
            int("404"),
        )

    incoming = request.get_json(silent=True)
    if incoming is None:
        return (
            jsonify(gateway.make_error(None, -32700, "JSON 解析失败。")),
            int("400"),
        )

    _, body = gateway.dispatch(incoming)
    for message in _messages(body):
        sessions.push(session_id, message)

    return Response("", status=int("202"))


# --------------------------------------------------------------------------- #
# 与网页设置共享的 HTTP 工具接口
# --------------------------------------------------------------------------- #


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
