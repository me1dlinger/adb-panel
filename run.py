#!/usr/bin/env python3
"""桌面 / PyInstaller 入口：后台运行 Web 服务，主线程运行托盘图标。

- 托盘菜单：打开控制台 / 退出。
- MCP 与网页共用同一进程（POST /mcp），不再单独启动 mcp_server.py。
- 关闭浏览器不会结束程序；请通过托盘菜单退出。
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

from werkzeug.serving import make_server

import adb_core
from adbconsole.services.tray import TrayIcon
from adbconsole.web import create_app, discovery_loop, find_port


def open_browser_when_ready(port: int) -> None:
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.2)
    webbrowser.open(url)


def _warn_without_tray(url: str) -> None:
    message = (
        f"ADB 控制台已在后台运行：{url}\n\n"
        "未安装 pystray/Pillow，因此没有托盘图标。\n"
        "请访问上面的地址使用控制台；关闭程序请在任务管理器中结束 ADBConsole。"
    )
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "ADB 控制台", 0x40)
    except Exception:  # noqa: BLE001 - 非 Windows
        print(message)


def main() -> None:
    app = create_app()
    port = find_port(5010)
    url = f"http://127.0.0.1:{port}"
    server = make_server("127.0.0.1", port, app, threaded=True)

    threading.Thread(target=discovery_loop, args=(app,), daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if "--no-browser" not in sys.argv:
        threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()

    app.logger.info("ADB 控制台已启动：%s", url)
    app.logger.info("MCP endpoint: %s/mcp（默认关闭）", url)
    print("ADB 控制台")
    print(f"  adb 路径 : {adb_core.adb_path()}")
    print(f"  数据目录 : {adb_core.BASE_DIR}")
    print(f"  访问地址 : {url}")
    print(f"  MCP 地址 : {url}/mcp（默认关闭）")

    if "--tray-selftest" in sys.argv:
        # 打包后自检：确认 pystray/Pillow 被正确包含。
        tray = TrayIcon(url, lambda: None)
        ok = tray.start_background()
        time.sleep(2)
        app.logger.info("TRAY_SELFTEST OK=%s", ok)
        print(f"TRAY_SELFTEST OK={ok}")
        if tray._icon is not None:
            tray._icon.stop()
            time.sleep(0.5)
        os._exit(0 if ok else 1)

    def quit_app() -> None:
        app.logger.info("正在退出 ADB 控制台")
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)

    if "--no-tray" in sys.argv:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            quit_app()
        return

    tray = TrayIcon(url, quit_app)
    if not tray.start():
        # 托盘不可用：保持服务运行，并提示用户如何访问。
        if getattr(sys, "frozen", False):
            _warn_without_tray(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            quit_app()
        return

    # pystray 的 run() 在 icon.stop() 后返回，说明用户选择了退出。
    quit_app()


if __name__ == "__main__":
    main()
