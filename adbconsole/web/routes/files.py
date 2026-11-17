"""文件推送、拉取与已拉取文件列表。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

import adb_core

from ..common import api_route, payload

bp = Blueprint("files", __name__)


@bp.post("/api/push")
@api_route
def api_push():
    data = payload()
    remote = data.get("remote")
    upload = request.files.get("file")
    if upload is not None and upload.filename:
        local = adb_core.save_upload(upload)
    else:
        local = data.get("local") or data.get("path")
        if not local:
            raise adb_core.ApiError("请选择文件或填写项目目录内的本机路径。")
    return jsonify(adb_core.adb_push(str(local), remote, data.get("serial")))


@bp.post("/api/pull")
@api_route
def api_pull():
    data = payload()
    return jsonify(
        adb_core.adb_pull(
            data.get("remote") or data.get("path"),
            data.get("local_name"),
            data.get("serial"),
        )
    )


@bp.get("/api/pulls")
@api_route
def api_pulls():
    return jsonify(adb_core.list_pulls())
