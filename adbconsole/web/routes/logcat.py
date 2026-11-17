"""日志：logcat 快照、清空、实时流。"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

import adb_core

from ..common import api_route, payload

bp = Blueprint("logcat", __name__)


def _streamer():
    return current_app.extensions["log_streamer"]


@bp.post("/api/logcat")
@api_route
def api_logcat():
    data = payload()
    return jsonify(
        adb_core.adb_logcat(
            data.get("lines", 200), data.get("filter", ""), data.get("serial")
        )
    )


@bp.post("/api/logcat/clear")
@api_route
def api_logcat_clear():
    data = payload()
    _streamer().clear()
    response = adb_core.adb_logcat_clear(data.get("serial"))
    response["cleared_buffer"] = True
    return jsonify(response)


@bp.post("/api/logcat/stream/start")
@api_route
def api_logcat_stream_start():
    data = payload()
    return jsonify(_streamer().start(data.get("serial")))


@bp.post("/api/logcat/stream/stop")
@api_route
def api_logcat_stream_stop():
    return jsonify(_streamer().stop())


@bp.get("/api/logcat/stream")
@api_route
def api_logcat_stream():
    return jsonify(
        _streamer().snapshot(
            since=request.args.get("since", 0),
            filter_text=request.args.get("filter", ""),
            level=request.args.get("level", "V"),
            limit=request.args.get("limit", 500),
        )
    )
