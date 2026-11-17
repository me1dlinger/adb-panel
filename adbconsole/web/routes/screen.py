"""实时屏幕：取帧、MJPEG 流、启停、截图。"""

from __future__ import annotations

import time

from flask import Blueprint, Response, jsonify, request

import adb_core

from ..common import api_route, payload, serial_from_request, serial_or_none

bp = Blueprint("screen", __name__)


@bp.get("/api/screen/frame")
@api_route
def api_screen_frame():
    serial = serial_from_request() or None
    mirror = adb_core.screen_mirror
    mirror.start(serial)
    cached = mirror.latest(serial)
    if cached and cached["data"]:
        headers = {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Device-Width": str(cached["width"] or ""),
            "X-Device-Height": str(cached["height"] or ""),
            "X-Capture-Ms": str(cached["capture_ms"] or ""),
            "X-Frame-Ts": str(cached["ts"] or ""),
        }
        return Response(cached["data"], mimetype="image/png", headers=headers)
    data, width, height, capture_ms, failure = adb_core.capture_png(serial)
    if failure is not None:
        failure["serial"] = adb_core.resolve_serial(serial)
        return jsonify(failure)
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "X-Device-Width": str(width or ""),
        "X-Device-Height": str(height or ""),
        "X-Capture-Ms": str(capture_ms),
    }
    return Response(data, mimetype="image/png", headers=headers)


@bp.get("/api/screen/stream")
def api_screen_stream():
    """MJPEG 实时流，由后台取帧线程供帧。"""
    serial = adb_core.resolve_serial(serial_from_request() or None)
    mirror = adb_core.screen_mirror

    def generate():
        mirror.start(serial)
        last_ts = 0.0
        empty_wait = 0.0
        try:
            while True:
                mirror.touch(serial)
                frame = mirror.latest(serial)
                if not frame or not frame["data"]:
                    empty_wait += 0.05
                    if empty_wait > 15:
                        return
                    time.sleep(0.05)
                    continue
                empty_wait = 0.0
                if frame["ts"] == last_ts:
                    time.sleep(float("0.02"))
                    continue
                last_ts = frame["ts"]
                chunk = frame["data"]
                yield (
                    b"--adbframe\r\nContent-Type: image/png\r\n"
                    + b"Content-Length: "
                    + str(len(chunk)).encode("ascii")
                    + b"\r\nX-Device-Width: "
                    + str(frame["width"] or "").encode("ascii")
                    + b"\r\nX-Device-Height: "
                    + str(frame["height"] or "").encode("ascii")
                    + b"\r\n\r\n"
                    + chunk
                    + b"\r\n"
                )
        finally:
            mirror.touch(serial)

    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=adbframe",
        headers=headers,
    )


@bp.post("/api/screen/start")
@api_route
def api_screen_start():
    serial = serial_from_request() or None
    adb_core.screen_mirror.start(serial)
    return jsonify(adb_core.result(True, "屏幕镜像已启动。", "", 0))


@bp.get("/api/screen/stats")
@api_route
def api_screen_stats():
    serial = serial_from_request() or None
    return jsonify(adb_core.screen_mirror.stats(serial))


@bp.post("/api/screen/stop")
@api_route
def api_screen_stop():
    serial = serial_from_request() or None
    adb_core.screen_mirror.stop(serial)
    return jsonify(adb_core.result(True, "屏幕镜像已停止。", "", 0))


@bp.get("/api/screen/size")
@api_route
def api_screen_size():
    return jsonify(adb_core.screen_size(serial_from_request() or None))


@bp.post("/api/screenshot")
@api_route
def api_screenshot():
    data = payload()
    return jsonify(adb_core.adb_screenshot(serial_or_none(data.get("serial"))))


@bp.post("/api/tap")
@api_route
def api_tap():
    data = payload()
    return jsonify(
        adb_core.adb_tap(data.get("x"), data.get("y"), serial_or_none(data.get("serial")))
    )


@bp.post("/api/swipe")
@api_route
def api_swipe():
    data = payload()
    return jsonify(
        adb_core.adb_swipe(
            data.get("x1"),
            data.get("y1"),
            data.get("x2"),
            data.get("y2"),
            data.get("duration_ms", 300),
            serial_or_none(data.get("serial")),
        )
    )


@bp.post("/api/key")
@api_route
def api_key():
    data = payload()
    return jsonify(
        adb_core.adb_key(data.get("code"), serial_or_none(data.get("serial")))
    )
