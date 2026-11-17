"""单实例控制：重复启动时不再新增服务进程与端口。

Windows 使用命名互斥量（同一用户会话内唯一）；其它平台使用文件锁。
运行时把实际端口写入 logs/runtime.json，第二个实例读取后直接打开已有页面。
"""

from __future__ import annotations

import hashlib
import json
import os
import time

import adb_core

RUNTIME_PATH = adb_core.LOG_DIR / "runtime.json"
LOCK_PATH = adb_core.LOG_DIR / "instance.lock"
ERROR_ALREADY_EXISTS = 183


def _mutex_name() -> str:
    """按数据目录生成互斥量名称，不同安装目录可各自运行。"""
    digest = hashlib.sha1(str(adb_core.BASE_DIR).lower().encode("utf-8")).hexdigest()[:16]
    return f"Local\\AdbPanel-{digest}"


class SingleInstance:
    def __init__(self) -> None:
        self._handle = None
        self._file = None

    def acquire(self) -> bool:
        """尝试成为唯一实例；已有实例返回 False。"""
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.CreateMutexW(None, False, _mutex_name())
            if not handle:
                raise OSError(ctypes.get_last_error(), "无法创建单实例互斥量")
            if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(handle)
                return False
            self._handle = handle
            return True

        import fcntl

        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(LOCK_PATH, "a+")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            self._file = None
            return False
        return True

    def release(self) -> None:
        if self._handle is not None:
            import ctypes

            ctypes.WinDLL("kernel32").CloseHandle(self._handle)
            self._handle = None
        if self._file is not None:
            try:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except Exception:  # noqa: BLE001 - 退出路径不阻塞
                pass
            self._file.close()
            self._file = None


def write_runtime(port: int) -> None:
    """原子写入当前实例的访问地址，供后续启动复用。"""
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "port": port,
        "url": f"http://127.0.0.1:{port}",
    }
    temp = RUNTIME_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, RUNTIME_PATH)


def clear_runtime() -> None:
    try:
        RUNTIME_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def read_runtime_url(timeout: float = 6.0) -> str:
    """读取已有实例地址；端口未就绪时短暂重试。返回空串表示未找到。"""
    deadline = time.time() + timeout
    import urllib.request

    while time.time() < deadline:
        try:
            data = json.loads(RUNTIME_PATH.read_text("utf-8"))
            url = str(data.get("url") or "")
            port = int(data.get("port") or 0)
            if url and port:
                with urllib.request.urlopen(url + "/api/meta", timeout=0.8) as response:
                    meta = json.loads(response.read().decode("utf-8"))
                    if meta.get("version"):
                        return url
        except Exception:  # noqa: BLE001 - 首个实例可能仍在启动
            pass
        time.sleep(0.25)
    return ""
