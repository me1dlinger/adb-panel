#!/usr/bin/env python3
"""Shared adb backend used by the Flask app and the MCP server.

Every public operation returns a dict shaped like:
    {"ok": bool, "stdout": str, "stderr": str, "code": int, ...}

adb is always executed with a fixed argv list (no shell=True). The device-side
shell is only used where the feature explicitly runs commands on the device.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from werkzeug.utils import secure_filename

# --------------------------------------------------------------------------- #
# Paths and constants
# --------------------------------------------------------------------------- #

# 源码运行时为项目目录；PyInstaller onefile 打包后为 exe 所在目录（数据可持久化）。
IS_FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = (
    Path(sys.executable).resolve().parent
    if IS_FROZEN
    else Path(__file__).resolve().parent
)
SCREENSHOT_DIR = BASE_DIR / "screenshots"
PULL_DIR = BASE_DIR / "pulls"
UPLOAD_DIR = BASE_DIR / "uploads"
LOG_DIR = BASE_DIR / "logs"
for _folder in (SCREENSHOT_DIR, PULL_DIR, UPLOAD_DIR, LOG_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

ADB_EXE = os.environ.get("ADB_PATH", "").strip() or shutil.which("adb") or "adb"
KNOWN_PATH = BASE_DIR / "known_devices.json"
CONFIG_PATH = BASE_DIR / "config.json"

_adb_path_lock = threading.Lock()
_adb_path = ADB_EXE


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text("utf-8"))
    except Exception:
        return {}


def adb_path() -> str:
    """当前使用的 adb 可执行文件路径（优先级：config.json > 环境变量 > PATH 探测）。"""
    global _adb_path
    with _adb_path_lock:
        if _adb_path == ADB_EXE:  # 首次访问时合并持久化配置
            saved = str(_load_config().get("adb_path") or "").strip()
            if saved:
                _adb_path = saved
        return _adb_path


def set_adb_path(path: str, persist: bool = True) -> dict:
    """校验 adb 可执行文件路径；persist=True 时切换并持久化到 config.json。"""
    global _adb_path
    path = str(path or "").strip()
    if not path:
        raise ApiError("adb 路径不能为空。")
    candidate = Path(path)
    if not candidate.is_absolute():
        found = shutil.which(path)
        if not found:
            raise ApiError(f"未在 PATH 中找到可执行文件：{path}")
        candidate = Path(found)
    if not candidate.exists():
        raise ApiError(f"文件不存在：{candidate}")
    if candidate.is_dir():
        candidate = candidate / ("adb.exe" if os.name == "nt" else "adb")
        if not candidate.exists():
            raise ApiError(f"目录下未找到 adb 可执行文件：{candidate}")
    try:
        proc = subprocess.run(
            [str(candidate), "version"],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        raise ApiError(f"无法执行该文件：{exc}")
    if proc.returncode != 0:
        raise ApiError(
            f"adb version 校验失败：{_clean_text(proc.stderr) or _clean_text(proc.stdout)}"
        )
    with _adb_path_lock:
        if persist:
            _adb_path = str(candidate)
            config = _load_config()
            config["adb_path"] = str(candidate)
            CONFIG_PATH.write_text(
                json.dumps(config, ensure_ascii=False, indent=2), "utf-8"
            )
    version_line = next(
        (
            line
            for line in _clean_text(proc.stdout).splitlines()
            if "version" in line.lower()
        ),
        "",
    )
    return result(
        True,
        stdout=_clean_text(proc.stdout),
        adb_path=str(candidate),
        version=version_line,
    )


logger = logging.getLogger("adb-console-core")

TIMEOUT_SHORT = 20
TIMEOUT_NORMAL = 30
TIMEOUT_LONG = 120

_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_SLOTS = threading.BoundedSemaphore(4)
_SLOT_WAIT = 15

_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$")
_HOST_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
_CODE_RE = re.compile(r"^\d{6}$")
_PNG_SIG = b"\x89PNG\r\n\x1a\n"

MAX_BASE64_BYTES = 256 * 1024

STATE_TEXT = {
    "device": "已连接",
    "unauthorized": "未授权",
    "offline": "离线",
    "no permissions": "无权限",
    "connecting": "连接中",
    "bootloader": "引导模式",
    "recovery": "恢复模式",
}

KEY_CODES = {
    "home": 3,
    "back": 4,
    "recent": 187,
    "recents": 187,
    "power": 26,
    "volume_up": 24,
    "volume_down": 25,
    "enter": 66,
    "menu": 82,
    "wakeup": 224,
}


class ApiError(Exception):
    """Validation error shown directly to the user."""


# --------------------------------------------------------------------------- #
# Low-level execution
# --------------------------------------------------------------------------- #


def _clean_text(raw) -> str:
    if raw is None:
        return ""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def result(ok: bool, stdout="", stderr="", code=0, **extra) -> dict:
    payload = {
        "ok": bool(ok),
        "stdout": _clean_text(stdout),
        "stderr": _clean_text(stderr),
        "code": int(code),
    }
    payload.update(extra)
    return payload


def _cmd(args, serial=None) -> list[str]:
    cmd = [adb_path()]
    if serial:
        cmd += ["-s", str(serial)]
    cmd += [str(a) for a in args]
    return cmd


def _acquire_slot():
    if not _SLOTS.acquire(timeout=_SLOT_WAIT):
        raise ApiError("adb 正忙，请稍后重试。")


def _run_bytes(args, timeout=TIMEOUT_NORMAL, serial=None):
    cmd = _cmd(args, serial)
    _acquire_slot()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=_CREATIONFLAGS,
        )
    except subprocess.TimeoutExpired:
        return (
            None,
            "",
            -1,
            result(
                False, "", f"adb 在 {timeout} 秒后超时。", -1, command=" ".join(cmd)
            ),
        )
    except FileNotFoundError:
        return None, "", -1, result(False, "", f"未找到 adb：{ADB_EXE}", -1)
    except OSError as exc:
        return None, "", -1, result(False, "", f"无法启动 adb：{exc}", -1)
    finally:
        _SLOTS.release()
    return proc.stdout, _clean_text(proc.stderr), proc.returncode, None


def run_adb(args, timeout=TIMEOUT_NORMAL, serial=None) -> dict:
    cmd = _cmd(args, serial)
    stdout, stderr, code, failure = _run_bytes(args, timeout=timeout, serial=serial)
    if failure is not None:
        return failure
    return result(code == 0, stdout, stderr, code, command=" ".join(cmd))


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def require_text(value, message: str) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        raise ApiError(message)
    if any(ch in text for ch in ("\x00", "\n", "\r")):
        raise ApiError("输入内容包含不支持的字符。")
    return text


def validate_host(raw) -> str:
    host = require_text(raw, "请输入手机 IP 地址。")
    if not _HOST_RE.match(host):
        raise ApiError("IP 地址包含不允许的字符。")
    return host


def validate_port(raw, label="端口") -> str:
    text = require_text(raw, f"请输入{label}。")
    if not text.isdigit():
        raise ApiError(f"{label}必须是数字。")
    port = int(text)
    if not 1 <= port <= 65535:
        raise ApiError(f"{label}必须在 1 到 65535 之间。")
    return str(port)


def validate_code(raw) -> str:
    code = require_text(raw, "请输入手机显示的 6 位配对码。")
    if not _CODE_RE.match(code):
        raise ApiError("配对码必须是 6 位数字。")
    return code


def validate_package(raw) -> str:
    package = require_text(raw, "请输入应用包名。")
    if not _PACKAGE_RE.match(package):
        raise ApiError("包名格式不正确，例如 com.example.app。")
    return package


def validate_remote_path(raw) -> str:
    remote = require_text(raw, "请输入设备上的路径。")
    if len(remote) > 4096:
        raise ApiError("设备路径过长。")
    return remote


def validate_activity(raw) -> str:
    if raw is None:
        return ""
    activity = str(raw).strip()
    if not activity:
        return ""
    if not re.match(r"^[A-Za-z0-9_.$/]+$", activity):
        raise ApiError("Activity 名称包含不允许的字符。")
    return activity


def int_value(raw, label: str, minimum: int, maximum: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError(f"{label}必须是整数。")
    if not minimum <= value <= maximum:
        raise ApiError(f"{label}必须在 {minimum} 到 {maximum} 之间。")
    return value


def safe_local_path(raw, must_be_inside=True) -> Path:
    text = require_text(raw, "请输入本机文件路径。")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        raise ApiError("无法解析本机路径。")
    if must_be_inside:
        try:
            resolved.relative_to(BASE_DIR)
        except ValueError:
            raise ApiError(f"本机路径必须位于项目目录内：{BASE_DIR}")
    if not resolved.is_file():
        raise ApiError(f"本机文件不存在：{resolved}")
    return resolved


def safe_name(name: str) -> str:
    if not name or Path(name).name != name or name in (".", ".."):
        raise ApiError("文件名不合法。")
    return name


def unique_path(folder: Path, filename: str) -> Path:
    target = folder / filename
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    index = 1
    while True:
        target = folder / f"{stem}-{index}{suffix}"
        if not target.exists():
            return target
        index += 1


def save_upload(file_storage, allowed_ext: tuple[str, ...] = ()) -> Path:
    raw_name = file_storage.filename or ""
    extension = Path(raw_name).suffix.lower()
    if allowed_ext and extension not in allowed_ext:
        raise ApiError(f"文件类型必须是：{', '.join(allowed_ext)}")
    original = secure_filename(raw_name)
    if not original:
        original = "upload" + (extension if extension else ".bin")
    target = unique_path(UPLOAD_DIR, original)
    file_storage.save(str(target))
    return target


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #


def parse_devices(stdout: str) -> list[dict]:
    devices = []
    for raw_line in _clean_text(stdout).splitlines():
        line = raw_line.strip()
        if (
            not line
            or line.startswith("List of devices")
            or line.startswith("*")
            or line.startswith("adb server")
        ):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        props = {}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                if key in {"model", "product", "device", "transport_id", "usb"}:
                    props[key] = value
        devices.append(
            {
                "serial": serial,
                "state": state,
                "state_text": STATE_TEXT.get(state, state),
                "model": props.get("model", ""),
                "product": props.get("product", ""),
                "device": props.get("device", ""),
                "transport_id": props.get("transport_id", ""),
                "usb": props.get("usb", ""),
                "raw": line,
            }
        )
    return devices


def list_devices() -> dict:
    res = run_adb(["devices", "-l"], timeout=TIMEOUT_SHORT)
    devices = parse_devices(res["stdout"]) if res["ok"] else []
    ready = [d for d in devices if d["state"] == "device"]
    res["devices"] = devices
    res["ready"] = len(ready)
    res["unauthorized"] = [d for d in devices if d["state"] == "unauthorized"]
    res["default_serial"] = ready[0]["serial"] if len(ready) == 1 else None
    return res


def resolve_serial(serial=None):
    text = str(serial or "").strip()
    if text:
        return text
    res = run_adb(["devices"], timeout=TIMEOUT_SHORT)
    ready = [d for d in parse_devices(res["stdout"]) if d["state"] == "device"]
    return ready[0]["serial"] if len(ready) == 1 else None


def _normalize_connect(res: dict) -> dict:
    text = f"{res.get('stdout', '')}\n{res.get('stderr', '')}".lower()
    if any(
        phrase in text
        for phrase in (
            "failed to connect",
            "cannot connect",
            "unable to connect",
            "connection refused",
            "no route to host",
            "failed to authenticate",
            "timed out",
            "超时",
            "offline",
        )
    ):
        if res.get("code") == 0:
            res["ok"] = False
            res["interpreted"] = "adb 退出码为 0，但输出内容表示连接失败。"
    elif "connected to" in text or "already connected" in text:
        res["ok"] = True
    res["explanation"] = connect_explanation(
        res.get("ok"), f"{res.get('stdout', '')}\n{res.get('stderr', '')}"
    )
    return res


def _normalize_pair(res: dict) -> dict:
    text = f"{res.get('stdout', '')}\n{res.get('stderr', '')}".lower()
    if res.get("code") == 0 and any(
        phrase in text
        for phrase in ("failed", "error:", "cannot pair", "unable to pair")
    ):
        res["ok"] = False
        res["interpreted"] = "adb 退出码为 0，但输出内容表示配对失败。"
    res["explanation"] = pair_explanation(
        res.get("ok"), f"{res.get('stdout', '')}\n{res.get('stderr', '')}"
    )
    return res


def connect_explanation(ok, text: str) -> str:
    if ok:
        return "连接成功。"
    lower = str(text or "").lower()
    if "unauthorized" in lower:
        return "设备未授权。请在设备屏幕上允许调试授权后再试。"
    if "failed to authenticate" in lower:
        return "设备要求调试授权。请在设备屏幕上确认 RSA 指纹后重试。"
    if "超时" in lower or "timed out" in lower:
        return "连接超时。请确认手机与电脑在同一 Wi-Fi、手机已开启无线调试、端口正确；若尚未配对，请先使用配对表单。"
    if any(
        p in lower for p in ("failed to connect", "cannot connect", "unable to connect")
    ):
        return "连接失败。通常表示手机尚未完成无线调试配对，或无线调试端口已变化。请先使用配对表单完成配对。"
    return "连接失败，请查看下方 adb 的原始输出。"


def pair_explanation(ok, text: str) -> str:
    if ok:
        return "配对成功。请使用手机“无线调试”界面显示的端口进行连接。"
    lower = str(text or "").lower()
    if "protocol fault" in lower:
        return "配对协议错误。请确认配对端口来自当前手机上的配对弹窗，且配对码未过期，然后重新配对。"
    if "timed out" in lower:
        return "配对超时。请确认手机与电脑在同一网络，并重新打开手机上的配对弹窗。"
    if "failed" in lower or "error:" in lower:
        return "配对失败。请核对配对端口与 6 位配对码，并确保电脑能访问手机。"
    return "配对未成功，请查看下方 adb 的原始输出。"


def adb_connect(host, port) -> dict:
    host = validate_host(host)
    port = validate_port(port, "连接端口")
    res = run_adb(["connect", f"{host}:{port}"], timeout=TIMEOUT_NORMAL)
    _normalize_connect(res)
    record_known(f"{host}:{port}", source="manual", res=res)
    return res


def adb_pair(host, port, code) -> dict:
    host = validate_host(host)
    port = validate_port(port, "配对端口")
    code = validate_code(code)
    res = run_adb(["pair", f"{host}:{port}", code], timeout=TIMEOUT_NORMAL)
    _normalize_pair(res)
    record_known(f"{host}:{port}", source="manual_pair", res=res, pairing=True)
    return res


def adb_disconnect(serial=None) -> dict:
    target = str(serial or "").strip()
    if target:
        return run_adb(["disconnect", target], timeout=TIMEOUT_NORMAL)
    return run_adb(["disconnect"], timeout=TIMEOUT_NORMAL)


# --------------------------------------------------------------------------- #
# Discovery (USB + mDNS + known addresses)
# --------------------------------------------------------------------------- #

_KNOWN_LOCK = threading.RLock()
_DISCOVERY_LOCK = threading.Lock()
_CACHE_LOCK = threading.RLock()
_ATTEMPT_LOCK = threading.Lock()
_ATTEMPT_DATA_LOCK = threading.RLock()
_ATTEMPT_THREAD = None
_CACHE: dict = {}
_LAST_ATTEMPTS: dict[str, dict] = {}
_AUTO_MIN_INTERVAL = 10.0
_AUTO_CONNECT_TIMEOUT = 8
_DISCOVERY_MAX_AGE = 5.0

_SEED_ADDRESSES = {"192.168.31.208:35221": "seed"}


def _load_known() -> dict:
    with _KNOWN_LOCK:
        try:
            data = json.loads(KNOWN_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        entries = data.get("devices") if isinstance(data.get("devices"), dict) else {}
        changed = False
        for address, source in _SEED_ADDRESSES.items():
            if address not in entries:
                entries[address] = {
                    "address": address,
                    "source": source,
                    "last_seen": 0,
                    "last_attempt": 0,
                    "last_ok": None,
                    "last_output": "",
                }
                changed = True
        if changed:
            _write_known_locked(entries)
        return entries


def _write_known_locked(entries: dict):
    try:
        tmp = KNOWN_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"devices": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, KNOWN_PATH)
    except OSError:
        pass


def record_known(
    address: str, source: str = "manual", res: dict | None = None, pairing=False
):
    if not address:
        return
    with _KNOWN_LOCK:
        entries = _load_known()
        entry = entries.get(address) or {
            "address": address,
            "source": source,
            "last_seen": 0,
        }
        entry["source"] = source or entry.get("source", "manual")
        entry["last_seen"] = time.time()
        if res is not None:
            entry["last_attempt"] = time.time()
            entry["last_ok"] = bool(res.get("ok"))
            text = (res.get("stdout", "") + "\n" + res.get("stderr", "")).strip()
            entry["last_output"] = text[:2000]
        entries[address] = entry
        _write_known_locked(entries)


def parse_mdns(stdout: str) -> list[dict]:
    services = []
    for line in _clean_text(stdout).splitlines():
        line = line.strip()
        if not line or line.startswith("List of discovered"):
            continue
        match = re.match(r"^(\S+)\s+(_[A-Za-z0-9._-]+)\s+(\S+:\d+)$", line)
        if not match:
            parts = line.split()
            if len(parts) < 3:
                continue
            name, service, address = parts[0], parts[1], parts[-1]
        else:
            name, service, address = match.groups()
        if service == "_adb-tls-pairing._tcp":
            kind = "pairing"
        elif service == "_adb-tls-connect._tcp":
            kind = "connect"
        elif service == "_adb._tcp":
            kind = "legacy"
        else:
            kind = "other"
        services.append(
            {
                "name": name,
                "service": service,
                "address": address,
                "kind": kind,
                "service_text": {
                    "pairing": "配对服务",
                    "connect": "无线调试",
                    "legacy": "传统无线调试",
                    "other": "其他服务",
                }.get(kind, "其他服务"),
            }
        )
    return services


def _public_cache(cache: dict) -> dict:
    return {k: v for k, v in cache.items() if not k.startswith("_")}


def _build_discovery_snapshot(
    devices_res: dict, mdns_res: dict, scanning: bool = False
) -> dict:
    devices = (
        parse_devices(devices_res.get("stdout", "")) if devices_res.get("ok") else []
    )
    ready = [d for d in devices if d["state"] == "device"]
    mdns = parse_mdns(mdns_res.get("stdout", "")) if mdns_res.get("ok") else []

    with _KNOWN_LOCK:
        known_entries = _load_known()
        now_wall = time.time()
        for service in mdns:
            address = service["address"]
            entry = known_entries.get(address) or {
                "address": address,
                "source": "mdns",
                "last_seen": 0,
                "last_attempt": 0,
                "last_ok": None,
                "last_output": "",
            }
            entry["source"] = "mdns"
            entry["last_seen"] = now_wall
            entry["service"] = service["service"]
            entry["kind"] = service["kind"]
            known_entries[address] = entry
        if mdns:
            _write_known_locked(known_entries)
        known_snapshot = list(known_entries.values())

    with _ATTEMPT_DATA_LOCK:
        attempt_records = [dict(record) for record in _LAST_ATTEMPTS.values()]
    attempts = []
    for record in attempt_records:
        attempts.append({k: v for k, v in record.items() if not k.startswith("_")})
    attempts.sort(key=lambda item: item.get("at", ""), reverse=True)
    attempts = attempts[:20]
    attempts_by_address = {
        item["address"]: item for item in attempts if item.get("address")
    }

    known_view = []
    for entry in known_snapshot:
        address = entry.get("address", "")
        device = next((d for d in devices if d["serial"] == address), None)
        last = attempts_by_address.get(address)
        item = dict(entry)

        if last:
            item["last_ok"] = last.get("ok")
            item["last_output"] = (
                f"{last.get('stdout', '')}\n{last.get('stderr', '')}".strip()
            )
            item["explanation"] = last.get("explanation", "")
            item["last_at"] = last.get("at", "")
        elif entry.get("last_output") and entry.get("last_ok") is not True:
            item["last_ok"] = False
            item["explanation"] = connect_explanation(
                False, entry.get("last_output", "")
            )
        else:
            item["last_ok"] = None
            item["last_output"] = ""
            item["explanation"] = ""

        if device:
            item["state"] = device["state"]
            item["state_text"] = STATE_TEXT.get(device["state"], device["state"])
        else:
            item["state"] = "idle"
            item["state_text"] = (
                "已连接"
                if item.get("last_ok") is True
                else "连接失败"
                if item.get("last_ok") is False
                else "待连接"
            )
        known_view.append(item)

    errors = []
    if not devices_res.get("ok"):
        errors.append(
            devices_res.get("stderr")
            or devices_res.get("stdout")
            or "adb devices 失败。"
        )
    if not mdns_res.get("ok"):
        errors.append(f"mDNS 扫描：{mdns_res.get('stderr') or mdns_res.get('stdout')}")

    snapshot = result(
        bool(devices_res.get("ok")),
        devices_res.get("stdout", ""),
        "\n".join(errors).strip(),
        devices_res.get("code", 0),
        devices=devices,
        ready=len(ready),
        default_serial=ready[0]["serial"] if len(ready) == 1 else None,
        mdns=mdns,
        known=known_view,
        attempts=attempts,
        last_run=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        adb=ADB_EXE,
        base_dir=str(BASE_DIR),
        scanning=bool(scanning),
    )
    snapshot["_ts"] = time.time()
    return snapshot


def _auto_connect_candidates(snapshot: dict) -> dict:
    candidates: dict[str, str] = {}
    for service in snapshot.get("mdns", []):
        if service.get("kind") in {"connect", "legacy"}:
            candidates.setdefault(service["address"], service["kind"])
    for entry in snapshot.get("known", []):
        address = entry.get("address")
        if address and address not in candidates:
            candidates[address] = "known"
    return candidates


def _auto_connect_worker(snapshot: dict):
    try:
        present = {d["serial"] for d in snapshot.get("devices", [])}
        candidates = _auto_connect_candidates(snapshot)
        attempted = 0
        for address, kind in list(candidates.items())[:8]:
            if address in present:
                continue
            with _ATTEMPT_DATA_LOCK:
                previous = _LAST_ATTEMPTS.get(address, {})
                if time.monotonic() - previous.get("_mono", 0) < _AUTO_MIN_INTERVAL:
                    continue

            attempt = run_adb(["connect", address], timeout=_AUTO_CONNECT_TIMEOUT)
            _normalize_connect(attempt)
            record = {
                "address": address,
                "kind": kind,
                "ok": bool(attempt.get("ok")),
                "code": int(attempt.get("code", -1)),
                "stdout": attempt.get("stdout", ""),
                "stderr": attempt.get("stderr", ""),
                "explanation": attempt.get("explanation", ""),
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "_mono": time.monotonic(),
            }
            with _ATTEMPT_DATA_LOCK:
                _LAST_ATTEMPTS[address] = record
            record_known(address, source=kind, res=attempt)
            if attempt.get("ok"):
                present.add(address)
            attempted += 1
            time.sleep(0.2)
        discover(force=True, connect=False)
    except Exception as exc:  # noqa: BLE001 - discovery must never crash the server
        logger.warning("自动连接任务失败：%s", exc)
    finally:
        with _ATTEMPT_LOCK:
            global _ATTEMPT_THREAD
            if _ATTEMPT_THREAD is threading.current_thread():
                _ATTEMPT_THREAD = None


def _kick_auto_connect(snapshot: dict, wait: bool = False) -> dict:
    global _ATTEMPT_THREAD
    with _ATTEMPT_LOCK:
        thread = _ATTEMPT_THREAD
        if thread is None or not thread.is_alive():
            thread = threading.Thread(
                target=_auto_connect_worker,
                args=(snapshot,),
                daemon=True,
                name="adb-autoconnect",
            )
            _ATTEMPT_THREAD = thread
            thread.start()
    if wait:
        thread.join(timeout=12)
        with _CACHE_LOCK:
            if _CACHE:
                return _public_cache(_CACHE)
    return _public_cache(snapshot)


def discover(force: bool = False, connect: bool = True, wait: bool = False) -> dict:
    """Return devices + mDNS quickly; run slow auto-connect attempts in the background."""
    now = time.time()
    with _CACHE_LOCK:
        if not force and _CACHE and now - _CACHE.get("_ts", 0) < _DISCOVERY_MAX_AGE:
            return _public_cache(_CACHE)

    got_lock = _DISCOVERY_LOCK.acquire(timeout=2.0)
    if got_lock:
        try:
            devices_res = run_adb(["devices", "-l"], timeout=10)
            mdns_res = run_adb(["mdns", "services"], timeout=8)
            snapshot = _build_discovery_snapshot(devices_res, mdns_res)
            with _CACHE_LOCK:
                _CACHE.clear()
                _CACHE.update(snapshot)
        finally:
            _DISCOVERY_LOCK.release()
    else:
        with _CACHE_LOCK:
            if _CACHE:
                snapshot = _public_cache(_CACHE)
            else:
                devices_res = run_adb(["devices", "-l"], timeout=5)
                snapshot = _build_discovery_snapshot(
                    devices_res, result(True, "", "", 0), scanning=True
                )
                _CACHE.clear()
                _CACHE.update(snapshot)

    if connect:
        snapshot = _kick_auto_connect(snapshot, wait=wait)
    return snapshot


def adb_status(serial=None) -> dict:
    snap = discover(force=False, connect=True)
    if serial:
        snap["target_serial"] = str(serial)
    return snap


def adb_devices() -> dict:
    snap = discover(force=False, connect=True)
    return {
        "ok": snap.get("ok", False),
        "stdout": snap.get("stdout", ""),
        "stderr": snap.get("stderr", ""),
        "code": snap.get("code", 0),
        "devices": snap.get("devices", []),
        "ready": snap.get("ready", 0),
        "default_serial": snap.get("default_serial"),
        "mdns": snap.get("mdns", []),
        "known": snap.get("known", []),
        "attempts": snap.get("attempts", []),
        "last_run": snap.get("last_run", ""),
    }


# --------------------------------------------------------------------------- #
# Shell / apps / packages
# --------------------------------------------------------------------------- #


def adb_shell(cmd, serial=None, timeout=None) -> dict:
    command = require_text(cmd, "请输入要执行的命令。")
    try:
        seconds = int(timeout) if timeout not in (None, "") else TIMEOUT_NORMAL
    except (TypeError, ValueError):
        raise ApiError("超时时间必须是整数秒。")
    seconds = max(1, min(seconds, 300))
    target = resolve_serial(serial)
    res = run_adb(["shell", command], timeout=seconds, serial=target)
    res["serial"] = target
    return res


def adb_install(apk_path, serial=None) -> dict:
    raw = require_text(apk_path, "请输入本机 APK 路径。")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        path = path.resolve()
    except OSError:
        raise ApiError("无法解析 APK 路径。")
    if not path.is_file():
        raise ApiError(f"APK 文件不存在：{path}")
    if path.suffix.lower() != ".apk":
        raise ApiError("所选文件不是 .apk 文件。")

    target = resolve_serial(serial)
    remote_name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name) or "package.apk"
    remote = f"/data/local/tmp/{remote_name}"
    push = run_adb(["push", str(path), remote], timeout=TIMEOUT_LONG, serial=target)
    if not push["ok"]:
        push.update(local=str(path), remote=remote, serial=target, stage="push")
        return push
    install = run_adb(["install", "-r", remote], timeout=TIMEOUT_LONG, serial=target)
    stdout = "\n".join(
        part
        for part in (
            f"$ adb push {path.name} {remote}",
            push["stdout"].strip(),
            "",
            f"$ adb install -r {remote}",
            install["stdout"].strip(),
        )
        if part is not None
    ).strip()
    stderr = "\n".join(
        part for part in (push["stderr"].strip(), install["stderr"].strip()) if part
    )
    return result(
        push["ok"] and install["ok"],
        stdout,
        stderr,
        install["code"],
        local=str(path),
        remote=remote,
        serial=target,
        steps=[
            {"name": "push", "ok": push["ok"], "code": push["code"]},
            {"name": "install", "ok": install["ok"], "code": install["code"]},
        ],
    )


def adb_uninstall(package, serial=None) -> dict:
    package = validate_package(package)
    target = resolve_serial(serial)
    res = run_adb(
        ["shell", "pm", "uninstall", package], timeout=TIMEOUT_NORMAL, serial=target
    )
    res.update(package=package, serial=target)
    return res


def adb_launch(package, activity=None, serial=None) -> dict:
    package = validate_package(package)
    activity = validate_activity(activity)
    target = resolve_serial(serial)
    if activity:
        component = activity if "/" in activity else f"{package}/{activity}"
        args = ["shell", "am", "start", "-W", "-n", component]
    else:
        args = [
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ]
    res = run_adb(args, timeout=TIMEOUT_NORMAL, serial=target)
    res.update(package=package, serial=target)
    return res


def adb_force_stop(package, serial=None) -> dict:
    package = validate_package(package)
    target = resolve_serial(serial)
    res = run_adb(
        ["shell", "am", "force-stop", package], timeout=TIMEOUT_NORMAL, serial=target
    )
    res.update(package=package, serial=target)
    return res


def adb_clear_data(package, serial=None) -> dict:
    package = validate_package(package)
    target = resolve_serial(serial)
    res = run_adb(
        ["shell", "pm", "clear", package], timeout=TIMEOUT_NORMAL, serial=target
    )
    res.update(package=package, serial=target)
    return res


def adb_package_list(filter="", third_party=False, serial=None) -> dict:
    target = resolve_serial(serial)
    if not isinstance(third_party, bool):
        third_party = str(third_party).strip().lower() in {"1", "true", "yes", "on"}
    args = ["shell", "pm", "list", "packages"]
    if third_party:
        args.append("-3")
    res = run_adb(args, timeout=TIMEOUT_NORMAL, serial=target)
    packages = []
    if res["ok"]:
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line[len("package:") :])
    text = str(filter or "").strip().lower()
    if text:
        packages = [p for p in packages if text in p.lower()]
    packages.sort()
    res.update(
        packages=packages,
        count=len(packages),
        serial=target,
        third_party=bool(third_party),
    )
    return res


def adb_processes(serial=None) -> dict:
    target = resolve_serial(serial)
    res = run_adb(["shell", "ps", "-A"], timeout=TIMEOUT_NORMAL, serial=target)
    if not res["ok"] and res.get("code") not in (0,):
        fallback = run_adb(["shell", "ps"], timeout=TIMEOUT_NORMAL, serial=target)
        if fallback["ok"]:
            res = fallback
    processes = []
    if res["ok"]:
        lines = [line for line in res["stdout"].splitlines() if line.strip()]
        header = lines[0].split() if lines else []
        lower = [h.upper() for h in header]
        idx_pid = lower.index("PID") if "PID" in lower else 1
        idx_rss = lower.index("RSS") if "RSS" in lower else None
        idx_name = lower.index("NAME") if "NAME" in lower else None
        idx_user = lower.index("USER") if "USER" in lower else None
        for line in lines[1:]:
            parts = line.split()
            if len(parts) <= max(idx_pid, idx_rss or 0, idx_name or 0):
                continue
            try:
                pid = int(parts[idx_pid])
            except (ValueError, IndexError):
                continue
            name = (
                parts[idx_name]
                if idx_name is not None and idx_name < len(parts)
                else parts[-1]
            )
            try:
                rss = (
                    int(parts[idx_rss])
                    if idx_rss is not None and idx_rss < len(parts)
                    else 0
                )
            except ValueError:
                rss = 0
            user = (
                parts[idx_user]
                if idx_user is not None and idx_user < len(parts)
                else ""
            )
            processes.append({"pid": pid, "name": name, "rss_kb": rss, "user": user})
        processes.sort(key=lambda item: item["rss_kb"], reverse=True)
    res.update(processes=processes, count=len(processes), serial=target)
    return res


# --------------------------------------------------------------------------- #
# Screenshot / screen
# --------------------------------------------------------------------------- #


def png_size(data: bytes):
    if len(data) >= 24 and data[:8] == _PNG_SIG and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    return None, None


def capture_png(serial=None, timeout=TIMEOUT_NORMAL):
    """Return (data, width, height, capture_ms, error_result)."""
    started = time.perf_counter()
    target = resolve_serial(serial)
    data, stderr, code, failure = _run_bytes(
        ["exec-out", "screencap", "-p"], timeout=timeout, serial=target
    )
    if failure is not None:
        return None, None, None, 0, failure
    if data and data.startswith(_PNG_SIG):
        width, height = png_size(data)
        return data, width, height, int((time.perf_counter() - started) * 1000), None

    remote = f"/sdcard/_adb_console_{int(time.time() * 1000)}.png"
    shot = run_adb(["shell", "screencap", "-p", remote], timeout=timeout, serial=target)
    if not shot["ok"]:
        if not shot["stderr"]:
            shot["stderr"] = shot["stdout"] or "设备未能生成截图。"
        return None, None, None, 0, shot
    tmp = SCREENSHOT_DIR / f".frame-{int(time.time() * 1000)}.png"
    pulled = run_adb(["pull", remote, str(tmp)], timeout=timeout, serial=target)
    run_adb(["shell", "rm", "-f", remote], timeout=TIMEOUT_SHORT, serial=target)
    if not pulled["ok"]:
        tmp.unlink(missing_ok=True)
        return None, None, None, 0, pulled
    data = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    if not data.startswith(_PNG_SIG):
        return (
            None,
            None,
            None,
            0,
            result(
                False,
                pulled.get("stdout", ""),
                "设备返回的数据不是 PNG 图片。",
                pulled.get("code", code or -1),
                serial=target,
            ),
        )
    width, height = png_size(data)
    return data, width, height, int((time.perf_counter() - started) * 1000), None


class ScreenMirror:
    """Background frame capturer keeping the latest PNG per device serial.

    A worker thread continuously runs ``adb exec-out screencap -p`` and caches
    the newest frame, so HTTP consumers never wait for a fresh capture unless
    the cache is empty. Workers stop automatically after a few seconds without
    any consumer activity.
    """

    IDLE_TIMEOUT = 6.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: dict[str, dict] = {}

    def _loop(self, serial: str) -> None:
        while True:
            with self._lock:
                state = self._workers.get(serial)
                if not state or not state["running"]:
                    return
                if time.time() - state["last_touch"] > self.IDLE_TIMEOUT:
                    state["running"] = False
                    return
            data, width, height, capture_ms, failure = capture_png(serial, timeout=8)
            with self._lock:
                state = self._workers.get(serial)
                if not state or not state["running"]:
                    return
                if failure is None and data:
                    state["frame"] = data
                    state["width"] = width or 0
                    state["height"] = height or 0
                    state["capture_ms"] = capture_ms
                    state["ts"] = time.time()
                    window = state.setdefault("window", [])
                    window.append(state["ts"])
                    if len(window) > 10:
                        del window[:-10]
                    state["failures"] = 0
                    state["error"] = ""
                else:
                    state["failures"] = state.get("failures", 0) + 1
                    state["error"] = (failure or {}).get("stderr", "") or "取帧失败"
            time.sleep(0.03)

    def start(self, serial: str) -> None:
        serial = resolve_serial(serial)
        with self._lock:
            state = self._workers.get(serial)
            if state and state["running"]:
                state["last_touch"] = time.time()
                return
            state = {
                "running": True,
                "frame": None,
                "width": 0,
                "height": 0,
                "capture_ms": 0,
                "ts": 0.0,
                "failures": 0,
                "error": "",
                "last_touch": time.time(),
                "captured": 0,
            }
            self._workers[serial] = state
            threading.Thread(target=self._loop, args=(serial,), daemon=True).start()

    def touch(self, serial: str) -> None:
        serial = resolve_serial(serial)
        with self._lock:
            state = self._workers.get(serial)
            if state:
                state["last_touch"] = time.time()

    def latest(self, serial: str) -> dict | None:
        serial = resolve_serial(serial)
        with self._lock:
            state = self._workers.get(serial)
            if not state:
                return None
            return {
                "data": state["frame"],
                "width": state["width"],
                "height": state["height"],
                "capture_ms": state["capture_ms"],
                "ts": state["ts"],
                "error": state["error"],
            }

    def stats(self, serial: str) -> dict:
        serial = resolve_serial(serial)
        with self._lock:
            state = self._workers.get(serial)
            if not state:
                return {
                    "running": False,
                    "fps": 0,
                    "capture_ms": 0,
                    "width": 0,
                    "height": 0,
                    "error": "",
                }
            window = state.get("window") or []
            fps = 0.0
            if len(window) >= 2:
                span = window[-1] - window[0]
                if span > 0:
                    fps = (len(window) - 1) / span
            return {
                "running": state["running"],
                "fps": round(fps, 1),
                "capture_ms": state["capture_ms"],
                "width": state["width"],
                "height": state["height"],
                "error": state["error"],
            }

    def stop(self, serial: str) -> None:
        serial = resolve_serial(serial)
        with self._lock:
            state = self._workers.get(serial)
            if state:
                state["running"] = False


screen_mirror = ScreenMirror()


def adb_screenshot(serial=None) -> dict:
    data, width, height, capture_ms, failure = capture_png(serial)
    target = resolve_serial(serial)
    if failure is not None:
        failure["serial"] = target
        return failure
    name = f"screenshot-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.png"
    path = unique_path(SCREENSHOT_DIR, name)
    path.write_bytes(data)
    payload = result(
        True,
        f"截图已保存：{path}",
        "",
        0,
        file=path.name,
        path=str(path),
        url=f"/api/screenshot/file/{path.name}",
        size=len(data),
        width=width,
        height=height,
        capture_ms=capture_ms,
        serial=target,
    )
    if len(data) <= MAX_BASE64_BYTES:
        payload["base64"] = base64.b64encode(data).decode("ascii")
        payload["base64_included"] = True
    else:
        payload["base64_included"] = False
    return payload


def screen_size(serial=None) -> dict:
    target = resolve_serial(serial)
    res = run_adb(["shell", "wm", "size"], timeout=TIMEOUT_NORMAL, serial=target)
    width = height = None
    if res["ok"]:
        override = re.search(r"Override size:\s*(\d+)x(\d+)", res["stdout"])
        physical = re.search(r"Physical size:\s*(\d+)x(\d+)", res["stdout"])
        match = override or physical
        if match:
            width, height = int(match.group(1)), int(match.group(2))
    res.update(width=width, height=height, serial=target)
    return res


# --------------------------------------------------------------------------- #
# Logcat (dump)
# --------------------------------------------------------------------------- #


def adb_logcat(lines=200, filter="", serial=None) -> dict:
    try:
        count = int(lines)
    except (TypeError, ValueError):
        raise ApiError("日志行数必须是整数。")
    count = max(20, min(count, 5000))
    target = resolve_serial(serial)
    res = run_adb(
        ["logcat", "-d", "-t", str(count)], timeout=TIMEOUT_SHORT, serial=target
    )
    text = str(filter or "").strip()
    res.update(serial=target, requested_lines=count)
    if res["ok"] and text:
        wanted = text.lower()
        original = res["stdout"].splitlines()
        kept = [line for line in original if wanted in line.lower()]
        res["total_lines"] = len(original)
        res["matched_lines"] = len(kept)
        res["stdout"] = (
            "\n".join(kept)
            if kept
            else f"最近 {len(original)} 行日志中没有匹配“{text}”的内容。"
        )
    return res


def adb_logcat_clear(serial=None) -> dict:
    target = resolve_serial(serial)
    res = run_adb(["logcat", "-c"], timeout=8, serial=target)
    res["serial"] = target
    return res


# --------------------------------------------------------------------------- #
# Device info
# --------------------------------------------------------------------------- #


_DEVICE_INFO_CMD = (
    "printf '__ADB_PROP__\\n'; "
    "getprop ro.product.manufacturer; "
    "getprop ro.product.model; "
    "getprop ro.build.version.release; "
    "getprop ro.build.version.sdk; "
    "getprop ro.serialno; "
    "printf '__ADB_BAT__\\n'; dumpsys battery; "
    "printf '__ADB_MEM__\\n'; cat /proc/meminfo; "
    "printf '__ADB_DF__\\n'; df -h /data 2>/dev/null || df -h /sdcard; "
    "printf '__ADB_NET__\\n'; ip route 2>/dev/null; "
    "printf '__ADB_WIFI__\\n'; cmd wifi status 2>/dev/null | head -n 25; "
    "printf '__ADB_TELE__\\n'; getprop gsm.network.type; "
    "printf '__ADB_POWER__\\n'; dumpsys power | grep -E 'mWakefulness=|Display Power' | head -n 8; "
    "printf '__ADB_FOCUS__\\n'; dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp' | head -n 6; "
    "printf '__ADB_WM__\\n'; wm size; wm density; "
    "printf '__ADB_UPTIME__\\n'; cat /proc/uptime; "
    "printf '__ADB_END__\\n';"
)

_STATUS_BATTERY = {
    "1": "未知",
    "2": "充电中",
    "3": "放电中",
    "4": "未充电",
    "5": "已充满",
}


def _sections(raw: str) -> dict:
    out = {}
    current = None
    for line in raw.splitlines():
        match = re.fullmatch(r"__ADB_([A-Z]+)__", line.strip())
        if match:
            current = match.group(1)
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def _first_match(pattern, text, default=""):
    match = re.search(pattern, text or "", re.MULTILINE)
    return match.group(1).strip() if match else default


def _network_info(sections: dict) -> dict:
    route = "\n".join(sections.get("NET", []))
    wifi = "\n".join(sections.get("WIFI", []))
    tele = "\n".join(sections.get("TELE", [])).strip()
    interface = ""
    for line in route.splitlines():
        match = re.search(r"\bdev\s+([A-Za-z0-9_.-]+)", line)
        if match:
            interface = match.group(1)
            if line.strip().startswith("default"):
                break
    ssid = ""
    for line in wifi.splitlines():
        match = re.search(r'SSID:\s*"?([^",]+)"?', line)
        if match and match.group(1).strip():
            ssid = match.group(1).strip()
            break
    if interface.startswith("wlan"):
        kind = "无线网络（Wi-Fi）"
        if ssid:
            detail = ssid
        elif wifi.strip():
            detail = wifi.strip().splitlines()[0]
        else:
            detail = "已连接"
    elif interface.startswith(("rmnet", "ccmni", "pdp", "wwan")):
        kind = "移动网络"
        detail = tele or interface
    elif interface.startswith(("eth", "usb", "rndis")):
        kind = "有线网络"
        detail = interface
    elif "wifi is enabled" in wifi.lower() or "connected" in wifi.lower():
        kind = "无线网络（Wi-Fi）"
        detail = ssid or wifi.strip().splitlines()[0]
    else:
        kind = "未知"
        detail = interface or tele or ""
    return {
        "type": kind,
        "detail": detail,
        "interface": interface,
        "ssid": ssid,
        "telephony": tele,
        "route": route,
    }


def _focus_info(sections: dict) -> dict:
    text = "\n".join(sections.get("FOCUS", []))
    component = ""
    match = re.search(r"([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)", text)
    if match:
        component = f"{match.group(1)}/{match.group(2)}"
    package = component.split("/", 1)[0] if component else ""
    return {"component": component, "package": package}


def _human_uptime(seconds) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days} 天")
    if hours or days:
        parts.append(f"{hours} 小时")
    parts.append(f"{minutes} 分钟")
    return " ".join(parts)


def adb_device_info(serial=None) -> dict:
    target = resolve_serial(serial)
    res = run_adb(["shell", _DEVICE_INFO_CMD], timeout=TIMEOUT_NORMAL, serial=target)
    if not res["ok"]:
        res.update(info={}, serial=target)
        return res

    raw = res["stdout"]
    sections = _sections(raw)

    prop_lines = [line.strip() for line in sections.get("PROP", [])]
    prop_lines += [""] * (5 - len(prop_lines))
    manufacturer = prop_lines[0]
    model = prop_lines[1]
    android = prop_lines[2]
    sdk = prop_lines[3]
    prop_serial = prop_lines[4]

    battery_text = "\n".join(sections.get("BAT", []))
    level = _first_match(r"level:\s*(\d+)", battery_text)
    status_raw = _first_match(r"status:\s*(\d+)", battery_text)
    temperature = _first_match(r"temperature:\s*(\d+)", battery_text)
    battery = {
        "level": int(level) if level.isdigit() else None,
        "status": _STATUS_BATTERY.get(status_raw, "未知" if status_raw else ""),
        "status_code": int(status_raw) if status_raw.isdigit() else None,
        "temperature_c": round(int(temperature) / 10, 1)
        if temperature.isdigit()
        else None,
    }

    mem_text = "\n".join(sections.get("MEM", []))
    total_kb = _first_match(r"MemTotal:\s*(\d+)\s*kB", mem_text)
    avail_kb = _first_match(r"MemAvailable:\s*(\d+)\s*kB", mem_text)
    memory = {}
    if total_kb.isdigit():
        total = int(total_kb)
        available = int(avail_kb) if avail_kb.isdigit() else None
        used = total - available if available is not None else None
        memory = {
            "total_mb": round(total / 1024, 1),
            "available_mb": round(available / 1024, 1)
            if available is not None
            else None,
            "used_mb": round(used / 1024, 1) if used is not None else None,
            "used_percent": round(used * 100 / total, 1)
            if used is not None and total
            else None,
        }
    memory["text"] = (
        f"{memory.get('used_mb')} MB / {memory.get('total_mb')} MB（{memory.get('used_percent')}%）"
        if memory.get("used_mb") is not None
        else "—"
    )

    storage = {}
    for line in sections.get("DF", []):
        parts = line.split()
        if len(parts) >= 6 and parts[-1] in {"/data", "/sdcard"}:
            storage = {
                "size": parts[-5],
                "used": parts[-4],
                "available": parts[-3],
                "use_percent": parts[-2],
                "mount": parts[-1],
            }
            break
    if not storage:
        storage = {
            "size": "—",
            "used": "—",
            "available": "—",
            "use_percent": "—",
            "mount": "/data",
        }
    storage["text"] = (
        f"已用 {storage['used']} / {storage['size']}（{storage['use_percent']}），可用 {storage['available']}"
    )

    network = _network_info(sections)

    power_text = "\n".join(sections.get("POWER", []))
    wakefulness = _first_match(r"mWakefulness=(\w+)", power_text)
    if wakefulness == "Awake":
        screen_state = "亮屏"
    elif wakefulness == "Asleep":
        screen_state = "息屏"
    elif wakefulness == "Dozing":
        screen_state = "休眠"
    elif "OFF" in power_text.upper():
        screen_state = "息屏"
    elif "ON" in power_text.upper():
        screen_state = "亮屏"
    else:
        screen_state = wakefulness or "—"

    wm_text = "\n".join(sections.get("WM", []))
    override_size = re.search(r"Override size:\s*(\d+)x(\d+)", wm_text)
    physical_size = re.search(r"Physical size:\s*(\d+)x(\d+)", wm_text)
    size_match = override_size or physical_size
    resolution = f"{size_match.group(1)}x{size_match.group(2)}" if size_match else ""
    density = _first_match(r"Physical density:\s*(\d+)", wm_text)

    focus = _focus_info(sections)
    uptime_text = "\n".join(sections.get("UPTIME", [])).strip().split()
    uptime = _human_uptime(uptime_text[0]) if uptime_text else ""

    info = {
        "manufacturer": manufacturer,
        "model": model,
        "android": android,
        "sdk": sdk,
        "serial": prop_serial or target or "",
        "battery": battery,
        "storage": storage,
        "memory": memory,
        "network": network,
        "screen": {"state": screen_state, "resolution": resolution, "density": density},
        "focus": focus,
        "uptime": uptime,
    }

    summary = "\n".join(
        line
        for line in (
            f"型号：{manufacturer} {model}".strip(),
            f"系统：Android {android}（SDK {sdk}）",
            f"序列号：{info['serial']}",
            f"电量：{battery['level'] if battery['level'] is not None else '—'}%（{battery['status']}，{battery['temperature_c'] if battery['temperature_c'] is not None else '—'}°C）",
            f"存储：{storage['text']}",
            f"内存：{memory.get('text', '—')}",
            f"网络：{network['type']}"
            + (f"（{network['detail']}）" if network.get("detail") else ""),
            f"屏幕：{screen_state}" + (f"，{resolution}" if resolution else ""),
            f"前台应用：{focus['component'] or '—'}",
            f"运行时间：{uptime or '—'}",
        )
        if line
    )
    res.update(info=info, serial=target, stdout=summary)
    return res


# --------------------------------------------------------------------------- #
# File transfer
# --------------------------------------------------------------------------- #


def adb_push(local_path, remote_path, serial=None) -> dict:
    local = safe_local_path(local_path, must_be_inside=True)
    remote = validate_remote_path(remote_path)
    target = resolve_serial(serial)
    res = run_adb(["push", str(local), remote], timeout=TIMEOUT_LONG, serial=target)
    res.update(
        local=str(local), remote=remote, serial=target, bytes=local.stat().st_size
    )
    return res


def adb_pull(remote_path, local_name=None, serial=None) -> dict:
    remote = validate_remote_path(remote_path)
    if remote.endswith("/"):
        raise ApiError("请输入文件路径，而不是目录（路径末尾不能是斜杠）。")
    target_serial = resolve_serial(serial)

    if local_name:
        candidate = Path(str(local_name).replace("\\", "/")).name
        filename = secure_filename(candidate)
        if not filename:
            suffix = Path(candidate).suffix
            if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
                suffix = ""
            filename = "pulled-file" + suffix
    else:
        remote_name = Path(remote.replace("\\", "/")).name
        filename = secure_filename(remote_name)
        if not filename:
            suffix = Path(remote_name).suffix
            if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
                suffix = ""
            filename = "pulled-file" + suffix

    target = unique_path(PULL_DIR, filename)
    res = run_adb(
        ["pull", remote, str(target)], timeout=TIMEOUT_LONG, serial=target_serial
    )
    res.update(remote=remote, serial=target_serial, local=str(target))
    if not res["ok"]:
        if target.exists() and target.is_file():
            target.unlink(missing_ok=True)
        return res
    if not target.is_file():
        return result(
            False,
            res.get("stdout", ""),
            "adb 报告成功，但没有生成文件。暂不支持拉取目录。",
            res.get("code", -1),
        )
    res.update(
        name=target.name, size=target.stat().st_size, url=f"/api/download/{target.name}"
    )
    return res


def list_pulls() -> dict:
    files = []
    for path in sorted(
        PULL_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        if not path.is_file() or path.name.startswith("."):
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "url": f"/api/download/{path.name}",
            }
        )
    return result(True, "", "", 0, files=files, folder=str(PULL_DIR))


# --------------------------------------------------------------------------- #
# Input and reboot
# --------------------------------------------------------------------------- #


def adb_tap(x, y, serial=None) -> dict:
    px = int_value(x, "X 坐标", 0, 100000)
    py = int_value(y, "Y 坐标", 0, 100000)
    target = resolve_serial(serial)
    res = run_adb(
        ["shell", "input", "tap", str(px), str(py)],
        timeout=TIMEOUT_NORMAL,
        serial=target,
    )
    res.update(x=px, y=py, serial=target)
    return res


def adb_swipe(x1, y1, x2, y2, duration_ms=300, serial=None) -> dict:
    ax = int_value(x1, "起点 X 坐标", 0, 100000)
    ay = int_value(y1, "起点 Y 坐标", 0, 100000)
    bx = int_value(x2, "终点 X 坐标", 0, 100000)
    by = int_value(y2, "终点 Y 坐标", 0, 100000)
    duration = int_value(
        duration_ms if duration_ms is not None else 300, "滑动时长", 50, 10000
    )
    target = resolve_serial(serial)
    res = run_adb(
        ["shell", "input", "swipe", str(ax), str(ay), str(bx), str(by), str(duration)],
        timeout=TIMEOUT_NORMAL,
        serial=target,
    )
    res.update(x1=ax, y1=ay, x2=bx, y2=by, duration_ms=duration, serial=target)
    return res


def adb_key(code, serial=None) -> dict:
    raw = str(code if code is not None else "").strip().lower()
    if raw in KEY_CODES:
        key_code = KEY_CODES[raw]
    else:
        try:
            key_code = int(raw)
        except (TypeError, ValueError):
            raise ApiError("按键必须是名称或数字键值，例如 home、back 或 3。")
        if not 0 <= key_code <= 942:
            raise ApiError("按键键值超出范围。")
    target = resolve_serial(serial)
    res = run_adb(
        ["shell", "input", "keyevent", str(key_code)],
        timeout=TIMEOUT_NORMAL,
        serial=target,
    )
    res.update(key=raw, key_code=key_code, serial=target)
    return res


def adb_reboot(mode="system", serial=None) -> dict:
    mode = str(mode or "system").strip().lower()
    if mode not in {"system", "recovery", "bootloader"}:
        raise ApiError("重启模式必须是 system、recovery 或 bootloader。")
    target = resolve_serial(serial)
    args = ["reboot"] if mode == "system" else ["reboot", mode]
    res = run_adb(args, timeout=TIMEOUT_NORMAL, serial=target)
    res.update(mode=mode, serial=target)
    return res


# --------------------------------------------------------------------------- #
# Live logcat buffer
# --------------------------------------------------------------------------- #


class LogcatStreamer:
    """A single long-running `adb logcat -v time` process with a ring buffer."""

    def __init__(self, max_lines=6000):
        self._lock = threading.RLock()
        self._lines = []
        self._max_lines = max_lines
        self._next_index = 1
        self._proc = None
        self._thread = None
        self._err_thread = None
        self.running = False
        self.error = ""
        self.serial = None
        self.command = ""
        self.started_at = 0.0
        self._stderr_buffer = []

    def _append(self, text: str):
        level = self._line_level(text)
        with self._lock:
            self._lines.append({"i": self._next_index, "text": text, "level": level})
            self._next_index += 1
            if len(self._lines) > self._max_lines:
                self._lines = self._lines[-self._max_lines :]

    @staticmethod
    def _line_level(text: str) -> str:
        match = re.match(
            r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\d+\s+\d+\s+([VDIWEFA])\s", text
        )
        return match.group(1) if match else "V"

    def _read_stdout(self, proc):
        try:
            for line in proc.stdout:
                text = line.rstrip("\r\n")
                if text:
                    self._append(text)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.error = f"读取日志失败：{exc}"
        finally:
            with self._lock:
                self.running = False
                if self._proc is proc and not self.error and self._stderr_buffer:
                    self.error = "\n".join(self._stderr_buffer).strip()

    def _read_stderr(self, proc):
        try:
            for line in proc.stderr:
                text = line.rstrip("\r\n")
                if text:
                    with self._lock:
                        self._stderr_buffer.append(text)
                        self._stderr_buffer = self._stderr_buffer[-40:]
                        if not self._lines:
                            self.error = "\n".join(self._stderr_buffer).strip()
        except Exception:
            pass

    def start(self, serial=None) -> dict:
        target = resolve_serial(serial)
        self.stop()
        cmd = _cmd(["logcat", "-v", "time"], target)
        self.serial = target
        self.command = " ".join(cmd)
        self.error = ""
        self._stderr_buffer = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=_CREATIONFLAGS,
            )
        except FileNotFoundError:
            with self._lock:
                self.error = f"未找到 adb：{ADB_EXE}"
                self.running = False
            return self.status()
        except OSError as exc:
            with self._lock:
                self.error = f"无法启动日志进程：{exc}"
                self.running = False
            return self.status()

        with self._lock:
            self._proc = proc
            self.running = True
            self.started_at = time.time()
            self._lines = []
        self._thread = threading.Thread(
            target=self._read_stdout, args=(proc,), daemon=True
        )
        self._err_thread = threading.Thread(
            target=self._read_stderr, args=(proc,), daemon=True
        )
        self._thread.start()
        self._err_thread.start()
        time.sleep(0.35)
        with self._lock:
            if proc.poll() is not None:
                self.running = False
                if not self.error:
                    self.error = (
                        "\n".join(self._stderr_buffer).strip() or "日志进程已退出。"
                    )
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except OSError:
                pass
        with self._lock:
            self.running = False
        for thread in (self._thread, self._err_thread):
            if thread and thread.is_alive():
                thread.join(timeout=1)
        return self.status()

    def clear(self):
        with self._lock:
            self._lines = []
            self.error = ""

    def status(self) -> dict:
        with self._lock:
            healthy = bool(self.running) or bool(self._lines) or not bool(self.error)
            return {
                "ok": healthy,
                "stdout": "",
                "stderr": self.error,
                "code": 0 if healthy else 1,
                "running": self.running,
                "waiting": "waiting for device" in self.error.lower(),
                "serial": self.serial,
                "command": self.command,
                "total": len(self._lines),
                "started_at": self.started_at,
            }

    def snapshot(self, since=0, filter_text="", level="V", limit=500) -> dict:
        try:
            since = max(0, int(since))
        except (TypeError, ValueError):
            since = 0
        try:
            limit = max(1, min(int(limit), 2000))
        except (TypeError, ValueError):
            limit = 500
        wanted = str(filter_text or "").strip().lower()
        threshold = str(level or "V").upper()
        level_map = {"V": 0, "D": 1, "I": 2, "W": 3, "E": 4, "F": 5, "A": 6}
        min_level = level_map.get(threshold, 0)

        with self._lock:
            lines = list(self._lines)
            total = len(self._lines)
            running = self.running
            error = self.error
            serial = self.serial
            next_index = self._next_index

        selected = []
        last_scanned = since
        for item in lines:
            if item["i"] <= since:
                continue
            last_scanned = item["i"]
            if level_map.get(item["level"], 0) < min_level:
                continue
            if wanted and wanted not in item["text"].lower():
                continue
            selected.append(item)
            if len(selected) >= limit:
                break

        next_cursor = selected[-1]["i"] if selected else last_scanned
        if not selected and since >= next_index - 1:
            next_cursor = max(since, next_index - 1)

        return {
            "ok": bool(running) or bool(selected) or not bool(error),
            "stdout": "",
            "stderr": error,
            "code": 0 if (bool(running) or bool(selected) or not bool(error)) else 1,
            "lines": selected,
            "next": next_cursor,
            "running": running,
            "waiting": "waiting for device" in error.lower(),
            "serial": serial,
            "total": total,
            "filter": filter_text or "",
            "level": threshold,
        }
