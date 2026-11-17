#!/usr/bin/env python3
"""MCP tool manifest and dispatcher shared by mcp_server.py and Flask."""

from __future__ import annotations

import adb_core
from adb_core import ApiError, result

_SERIAL = {"type": "string", "description": "设备序列号；省略时使用唯一在线设备。"}

_SCHEMAS = {
    "adb_status": {
        "type": "object",
        "properties": {"serial": _SERIAL},
        "additionalProperties": False,
    },
    "adb_devices": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "adb_connect": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "手机 IP 地址。"},
            "port": {"type": ["integer", "string"], "description": "无线调试端口。"},
        },
        "required": ["host", "port"],
        "additionalProperties": False,
    },
    "adb_pair": {
        "type": "object",
        "properties": {
            "host": {"type": "string"},
            "port": {"type": ["integer", "string"], "description": "配对端口，不是连接端口。"},
            "code": {"type": "string", "description": "手机显示的 6 位配对码。"},
        },
        "required": ["host", "port", "code"],
        "additionalProperties": False,
    },
    "adb_disconnect": {
        "type": "object",
        "properties": {"serial": _SERIAL},
        "additionalProperties": False,
    },
    "adb_shell": {
        "type": "object",
        "properties": {
            "cmd": {"type": "string", "description": "在设备上执行的 shell 命令。"},
            "serial": _SERIAL,
            "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "description": "超时秒数。"},
        },
        "required": ["cmd"],
        "additionalProperties": False,
    },
    "adb_install": {
        "type": "object",
        "properties": {
            "apk_path": {"type": "string", "description": "本机 APK 文件路径。"},
            "serial": _SERIAL,
        },
        "required": ["apk_path"],
        "additionalProperties": False,
    },
    "adb_uninstall": {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "应用包名。"},
            "serial": _SERIAL,
        },
        "required": ["package"],
        "additionalProperties": False,
    },
    "adb_launch": {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "应用包名。"},
            "activity": {"type": "string", "description": "可选 Activity，例如 .MainActivity 或 com.app/.MainActivity。"},
            "serial": _SERIAL,
        },
        "required": ["package"],
        "additionalProperties": False,
    },
    "adb_force_stop": {
        "type": "object",
        "properties": {
            "package": {"type": "string"},
            "serial": _SERIAL,
        },
        "required": ["package"],
        "additionalProperties": False,
    },
    "adb_clear_data": {
        "type": "object",
        "properties": {
            "package": {"type": "string"},
            "serial": _SERIAL,
        },
        "required": ["package"],
        "additionalProperties": False,
    },
    "adb_screenshot": {
        "type": "object",
        "properties": {"serial": _SERIAL},
        "additionalProperties": False,
    },
    "adb_logcat": {
        "type": "object",
        "properties": {
            "serial": _SERIAL,
            "lines": {"type": "integer", "minimum": 20, "maximum": 5000, "default": 200},
            "filter": {"type": "string", "description": "可选关键字过滤。"},
        },
        "additionalProperties": False,
    },
    "adb_logcat_clear": {
        "type": "object",
        "properties": {"serial": _SERIAL},
        "additionalProperties": False,
    },
    "adb_processes": {
        "type": "object",
        "properties": {"serial": _SERIAL},
        "additionalProperties": False,
    },
    "adb_package_list": {
        "type": "object",
        "properties": {
            "filter": {"type": "string", "description": "可选包名关键字。"},
            "third_party": {"type": "boolean", "default": False},
            "serial": _SERIAL,
        },
        "additionalProperties": False,
    },
    "adb_device_info": {
        "type": "object",
        "properties": {"serial": _SERIAL},
        "additionalProperties": False,
    },
    "adb_push": {
        "type": "object",
        "properties": {
            "local_path": {"type": "string", "description": "本机文件路径，必须位于项目目录内。"},
            "remote_path": {"type": "string", "description": "设备上的目标路径。"},
            "serial": _SERIAL,
        },
        "required": ["local_path", "remote_path"],
        "additionalProperties": False,
    },
    "adb_pull": {
        "type": "object",
        "properties": {
            "remote_path": {"type": "string", "description": "设备上的文件路径。"},
            "local_name": {"type": "string", "description": "可选保存文件名，保存在 pulls/ 内。"},
            "serial": _SERIAL,
        },
        "required": ["remote_path"],
        "additionalProperties": False,
    },
    "adb_tap": {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "minimum": 0},
            "y": {"type": "integer", "minimum": 0},
            "serial": _SERIAL,
        },
        "required": ["x", "y"],
        "additionalProperties": False,
    },
    "adb_swipe": {
        "type": "object",
        "properties": {
            "x1": {"type": "integer", "minimum": 0},
            "y1": {"type": "integer", "minimum": 0},
            "x2": {"type": "integer", "minimum": 0},
            "y2": {"type": "integer", "minimum": 0},
            "duration_ms": {"type": "integer", "minimum": 50, "maximum": 10000, "default": 300},
            "serial": _SERIAL,
        },
        "required": ["x1", "y1", "x2", "y2"],
        "additionalProperties": False,
    },
    "adb_key": {
        "type": "object",
        "properties": {
            "code": {"type": ["string", "integer"], "description": "home/back/recent/power/volume_up/volume_down 或数字键值。"},
            "serial": _SERIAL,
        },
        "required": ["code"],
        "additionalProperties": False,
    },
    "adb_reboot": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["system", "recovery", "bootloader"], "default": "system"},
            "serial": _SERIAL,
        },
        "additionalProperties": False,
    },
}

_DESCRIPTIONS = {
    "adb_status": "查询 adb 设备状态、mDNS 自动发现和自动连接结果。",
    "adb_devices": "列出 adb 设备与 mDNS 自动发现服务。",
    "adb_connect": "通过 adb connect 连接无线设备。",
    "adb_pair": "通过 adb pair 使用配对端口和 6 位配对码配对无线设备。",
    "adb_disconnect": "断开指定设备或全部无线连接。",
    "adb_shell": "在设备上执行单条 shell 命令。",
    "adb_install": "推送并安装本机 APK，使用 adb install -r。",
    "adb_uninstall": "卸载指定包名的应用。",
    "adb_launch": "启动应用（包名或指定 Activity）。",
    "adb_force_stop": "强制停止应用。",
    "adb_clear_data": "清除应用数据。",
    "adb_screenshot": "截取设备屏幕，保存到 screenshots/，小图附带 base64。",
    "adb_logcat": "读取最近若干行 logcat，可按关键字过滤。",
    "adb_logcat_clear": "清空设备 logcat 缓冲区。",
    "adb_processes": "列出设备进程（PID、名称、RSS 内存）。",
    "adb_package_list": "列出已安装应用包名，可按关键字与第三方筛选。",
    "adb_device_info": "读取型号、系统、电量、存储、内存、网络、屏幕和前台应用。",
    "adb_push": "推送项目目录内的本机文件到设备。",
    "adb_pull": "拉取设备文件到 pulls/ 并返回下载地址。",
    "adb_tap": "在设备坐标发送轻触。",
    "adb_swipe": "在设备坐标发送滑动。",
    "adb_key": "发送按键事件（home/back/recent/power/音量等）。",
    "adb_reboot": "重启设备到系统、恢复模式或引导模式。",
}

_HANDLERS = {
    "adb_status": adb_core.adb_status,
    "adb_devices": adb_core.adb_devices,
    "adb_connect": adb_core.adb_connect,
    "adb_pair": adb_core.adb_pair,
    "adb_disconnect": adb_core.adb_disconnect,
    "adb_shell": adb_core.adb_shell,
    "adb_install": adb_core.adb_install,
    "adb_uninstall": adb_core.adb_uninstall,
    "adb_launch": adb_core.adb_launch,
    "adb_force_stop": adb_core.adb_force_stop,
    "adb_clear_data": adb_core.adb_clear_data,
    "adb_screenshot": adb_core.adb_screenshot,
    "adb_logcat": adb_core.adb_logcat,
    "adb_logcat_clear": adb_core.adb_logcat_clear,
    "adb_processes": adb_core.adb_processes,
    "adb_package_list": adb_core.adb_package_list,
    "adb_device_info": adb_core.adb_device_info,
    "adb_push": adb_core.adb_push,
    "adb_pull": adb_core.adb_pull,
    "adb_tap": adb_core.adb_tap,
    "adb_swipe": adb_core.adb_swipe,
    "adb_key": adb_core.adb_key,
    "adb_reboot": adb_core.adb_reboot,
}


def manifest() -> list[dict]:
    tools = []
    for name, schema in _SCHEMAS.items():
        tools.append(
            {
                "name": name,
                "description": _DESCRIPTIONS.get(name, name),
                "inputSchema": schema,
            }
        )
    return tools


def tool_names() -> list[str]:
    return list(_SCHEMAS)


def call_tool(name: str, arguments=None) -> dict:
    handler = _HANDLERS.get(str(name or ""))
    if handler is None:
        return result(False, "", f"未知工具：{name}", -1, tool=str(name or ""))
    args = arguments if isinstance(arguments, dict) else {}
    try:
        data = handler(**args)
        if not isinstance(data, dict):
            return result(False, "", f"工具 {name} 返回了无效结果。", -1)
        return data
    except ApiError as exc:
        return result(False, "", str(exc), -1, tool=name)
    except TypeError as exc:
        return result(False, "", f"参数不正确：{exc}", -1, tool=name)
    except Exception as exc:  # noqa: BLE001 - tools must never raise
        return result(False, "", f"{type(exc).__name__}: {exc}", -1, tool=name)
