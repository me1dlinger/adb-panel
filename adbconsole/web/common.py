"""路由公共工具：统一错误包装、JSON/表单载荷、设备序列号解析。"""

from __future__ import annotations

from functools import wraps

from flask import current_app, jsonify, request

from adb_core import ApiError, result


def api_route(fn):
    """把 ApiError 与未预期异常转换为统一的 JSON 结果。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ApiError as exc:
            return jsonify(result(False, "", str(exc), -1))
        except Exception as exc:  # noqa: BLE001 - 接口必须返回统一结构
            current_app.logger.exception("Unhandled error in %s", request.path)
            return jsonify(result(False, "", f"{type(exc).__name__}: {exc}", -1))

    return wrapper


def payload() -> dict:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return request.form.to_dict()
    return {}


def serial_from_request() -> str:
    return str(request.args.get("serial") or "").strip()


def serial_or_none(value):
    text = str(value or "").strip()
    return text or None
