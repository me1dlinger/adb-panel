"""设置：adb 路径、MCP 开关与运行时元信息。"""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify

import adb_core
import adbconsole.config as app_config
import mcp_tools
from adbconsole.services.dialogs import DialogUnavailable, pick_file

from ..common import api_route, payload

bp = Blueprint("settings", __name__)

MCP_WARNING = (
    "启用后，任何能访问本机 MCP 地址的程序或 AI 客户端都可以读取设备状态、"
    "执行 shell 命令、安装或卸载应用、重启设备。请只在你信任的客户端上开启，"
    "用完及时关闭。"
)

ADB_FILETYPES = (
    ("adb 可执行文件", "adb.exe"),
    ("可执行文件", "*.exe"),
    ("所有文件", "*.*"),
)


@bp.get("/api/adb/config")
@api_route
def api_adb_config():
    return jsonify({"ok": True, "adb_path": adb_core.adb_path()})


@bp.post("/api/adb/config")
@api_route
def api_adb_config_set():
    data = payload()
    path = str(data.get("adb_path") or data.get("path") or "").strip()
    info = adb_core.set_adb_path(path)
    info["ok"] = True
    return jsonify(info)


@bp.post("/api/adb/test")
@api_route
def api_adb_test():
    data = payload()
    path = str(data.get("adb_path") or data.get("path") or "").strip()
    return jsonify(adb_core.set_adb_path(path or adb_core.adb_path(), persist=False))


@bp.post("/api/adb/browse")
@api_route
def api_adb_browse():
    """弹出系统文件选择框，返回选中的 adb 可执行文件路径。"""
    data = payload()
    initial = str(data.get("initialdir") or "").strip()
    if not initial or not os.path.isdir(initial):
        initial = str(adb_core.BASE_DIR)
    try:
        selected = pick_file("选择 adb.exe", ADB_FILETYPES, initial)
    except DialogUnavailable as exc:
        raise adb_core.ApiError(str(exc))
    return jsonify(
        adb_core.result(True, "", "", 0, path=selected, cancelled=not bool(selected))
    )


@bp.get("/api/mcp/status")
@api_route
def api_mcp_status():
    tools = mcp_tools.manifest()
    return jsonify(
        adb_core.result(
            True,
            "",
            "",
            0,
            enabled=app_config.mcp_enabled(),
            endpoint="/mcp",
            protocol="JSON-RPC 2.0 over HTTP",
            tool_count=len(tools),
            tools=[tool["name"] for tool in tools],
            warning=MCP_WARNING,
        )
    )


@bp.post("/api/mcp/toggle")
@api_route
def api_mcp_toggle():
    data = payload()
    requested = data.get("enabled")
    if isinstance(requested, str):
        requested = requested.strip().lower() in {"1", "true", "yes", "on"}
    requested = bool(requested)
    if requested and not data.get("acknowledge_risk"):
        raise adb_core.ApiError("启用 MCP 需要先确认风险提示。")
    enabled = app_config.set_mcp_enabled(requested)
    current_app.logger.info("MCP 服务已%s", "启用" if enabled else "关闭")
    return jsonify(
        adb_core.result(
            True,
            f"MCP 服务已{'启用' if enabled else '关闭'}。",
            "",
            0,
            enabled=enabled,
            endpoint="/mcp",
        )
    )


@bp.get("/api/meta")
@api_route
def api_meta():
    import adbconsole

    return jsonify(
        adb_core.result(
            True,
            "",
            "",
            0,
            version=adbconsole.__version__,
            data_dir=str(adb_core.BASE_DIR),
            adb_path=adb_core.adb_path(),
        )
    )
