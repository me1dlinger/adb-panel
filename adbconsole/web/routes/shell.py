"""Shell 命令与重启路由。"""

from __future__ import annotations

from flask import Blueprint, jsonify

import adb_core

from ..common import api_route, payload

bp = Blueprint("shell", __name__)


@bp.post("/api/shell")
@api_route
def api_shell():
    data = payload()
    return jsonify(
        adb_core.adb_shell(
            data.get("cmd") or data.get("command"),
            data.get("serial"),
            data.get("timeout"),
        )
    )


@bp.post("/api/reboot")
@api_route
def api_reboot():
    data = payload()
    return jsonify(
        adb_core.adb_reboot(data.get("mode") or "system", data.get("serial"))
    )
