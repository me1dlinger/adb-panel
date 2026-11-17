"""配置读写：与 adb_core 共用 config.json，保留已有字段。"""

from __future__ import annotations

import json
import threading

import adb_core

_LOCK = threading.RLock()

# MCP 默认关闭：AI 客户端接入等于把设备控制权交给第三方程序。
DEFAULTS = {
    "mcp_enabled": False,
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
