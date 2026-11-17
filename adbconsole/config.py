"""配置读写：与 adb_core 共用 config.json，保留已有字段。"""

from __future__ import annotations

import json
import re
import secrets
import threading

import adb_core

_LOCK = threading.RLock()
_HEADER_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
TOKEN_MIN_LENGTH = 8
TOKEN_MAX_LENGTH = 256

# MCP 默认关闭：AI 客户端接入等于把设备控制权交给第三方程序。
DEFAULTS = {
    "mcp_enabled": False,
    "mcp_auth_token": "",
    "mcp_auth_header": "Authorization",
}


def load_settings() -> dict:
    """读取 config.json 并补全默认值；损坏时按默认值处理。"""
    with _LOCK:
        try:
            raw = adb_core.CONFIG_PATH.read_text("utf-8")
            data = json.loads(raw)
        except Exception:  # noqa: BLE001 - 配置损坏不应阻止启动
            data = {}
    if not isinstance(data, dict):
        data = {}
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save_settings(updates: dict) -> dict:
    """合并写入 config.json（保留 adb_path 等其它字段）。"""
    if not isinstance(updates, dict):
        return load_settings()
    with _LOCK:
        try:
            data = json.loads(adb_core.CONFIG_PATH.read_text("utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:  # noqa: BLE001
            data = {}
        data.update(updates)
        adb_core.CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
        )
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def mcp_enabled() -> bool:
    return bool(load_settings().get("mcp_enabled"))


def set_mcp_enabled(enabled: bool) -> bool:
    return bool(save_settings({"mcp_enabled": bool(enabled)}).get("mcp_enabled"))


# --------------------------------------------------------------------------- #
# MCP 请求头鉴权
# --------------------------------------------------------------------------- #


def mcp_auth_token() -> str:
    return str(load_settings().get("mcp_auth_token") or "").strip()


def mcp_auth_header() -> str:
    return str(load_settings().get("mcp_auth_header") or "Authorization").strip()


def set_mcp_auth_token(token: str) -> str:
    token = str(token or "").strip()
    if token and not (TOKEN_MIN_LENGTH <= len(token) <= TOKEN_MAX_LENGTH):
        raise adb_core.ApiError(
            f"MCP 令牌长度需在 {TOKEN_MIN_LENGTH} 到 {TOKEN_MAX_LENGTH} 个字符之间。"
        )
    save_settings({"mcp_auth_token": token})
    return token


def set_mcp_auth_header(name: str) -> str:
    name = str(name or "").strip()
    if not _HEADER_RE.match(name):
        raise adb_core.ApiError("请求头名称只能包含字母、数字和连字符，长度 1-64。")
    save_settings({"mcp_auth_header": name})
    return name


def rotate_mcp_token() -> str:
    return set_mcp_auth_token(secrets.token_urlsafe(32))


def ensure_mcp_token() -> str:
    """确保已存在访问令牌；没有则自动生成。"""
    token = mcp_auth_token()
    if token:
        return token
    return rotate_mcp_token()


def mcp_auth_example() -> dict:
    token = mcp_auth_token()
    value = f"Bearer {token}" if token else "Bearer <token>"
    return {mcp_auth_header(): value}
