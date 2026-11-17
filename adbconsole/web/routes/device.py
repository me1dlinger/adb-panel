"""设备信息、进程、应用包与安装路由。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

import adb_core

from ..common import api_route, payload, serial_from_request, serial_or_none

bp = Blueprint("device", __name__)


@bp.get("/api/device/info")
@api_route
def api_device_info():
    return jsonify(adb_core.adb_device_info(serial_from_request() or None))


@bp.get("/api/processes")
@api_route
def api_processes():
    return jsonify(adb_core.adb_processes(serial_from_request() or None))


@bp.get("/api/packages")
@api_route
def api_packages():
    return jsonify(
        adb_core.adb_package_list(
            filter=request.args.get("filter") or "",
            third_party=str(request.args.get("third_party") or "").lower()
            in {"1", "true", "yes"},
            serial=serial_from_request() or None,
        )
    )


@bp.post("/api/app/<action>")
@api_route
def api_app_action(action):
    data = payload()
    package = data.get("package")
    serial = serial_or_none(data.get("serial"))
    if action == "start":
        return jsonify(adb_core.adb_launch(package, data.get("activity"), serial))
    if action == "stop":
        return jsonify(adb_core.adb_force_stop(package, serial))
    if action == "clear":
        return jsonify(adb_core.adb_clear_data(package, serial))
    if action == "uninstall":
        return jsonify(adb_core.adb_uninstall(package, serial))
    raise adb_core.ApiError("未知的应用操作。")


@bp.post("/api/install")
@api_route
def api_install():
    data = payload()
    upload = request.files.get("file")
    if upload is not None and upload.filename:
        local = adb_core.save_upload(upload, allowed_ext=(".apk",))
    else:
        local = data.get("local") or data.get("path") or data.get("apk_path")
        if not local:
            raise adb_core.ApiError("请选择 APK 文件或填写本机 APK 路径。")
    return jsonify(adb_core.adb_install(str(local), serial_or_none(data.get("serial"))))
