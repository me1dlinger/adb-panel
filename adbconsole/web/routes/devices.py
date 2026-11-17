"""设备发现、连接、配对、断开路由。"""

from __future__ import annotations

from flask import Blueprint, jsonify

import adb_core

from ..common import api_route, payload

bp = Blueprint("devices", __name__)


@bp.get("/api/status")
@api_route
def api_status():
    snapshot = adb_core.discover(force=False, connect=True)
    snapshot["adb"] = adb_core.adb_path()
    return jsonify(snapshot)


@bp.get("/api/devices")
@api_route
def api_devices():
    return jsonify(adb_core.adb_devices())


@bp.post("/api/autoconnect")
@api_route
def api_autoconnect():
    return jsonify(adb_core.discover(force=True, connect=True, wait=True))


@bp.post("/api/connect")
@api_route
def api_connect():
    data = payload()
    return jsonify(
        adb_core.adb_connect(data.get("host") or data.get("ip"), data.get("port"))
    )


@bp.post("/api/pair")
@api_route
def api_pair():
    data = payload()
    return jsonify(
        adb_core.adb_pair(
            data.get("host") or data.get("ip"),
            data.get("port") or data.get("pair_port"),
            data.get("code"),
        )
    )


@bp.post("/api/disconnect")
@api_route
def api_disconnect():
    data = payload()
    return jsonify(adb_core.adb_disconnect(data.get("serial")))
