"""系统托盘图标：双击/菜单打开控制台，菜单退出程序。

pystray / Pillow 为可选依赖；缺失时 start() 返回 False，程序仍可正常作为网页服务运行。
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Callable

logger = logging.getLogger("adb-console-tray")

ICON_COLOR = "#007aff"


def _make_icon_image():
    """使用纯色方块作为托盘图标，避免依赖绘图细节。"""
    from PIL import Image

    return Image.new("RGBA", (64, 64), ICON_COLOR)


class TrayIcon:
    def __init__(self, url: str, on_quit: Callable[[], None]):
        self.url = url
        self.on_quit = on_quit
        self._icon = None

    def start(self) -> bool:
        """启动托盘；成功返回 True（阻塞在托盘消息循环）。"""
        try:
            import pystray
            from pystray import Menu, MenuItem
        except Exception as exc:  # noqa: BLE001
            logger.warning("托盘不可用（缺少 pystray/Pillow）：%s", exc)
            return False

        try:
            image = _make_icon_image()
        except Exception as exc:  # noqa: BLE001
            logger.warning("无法生成托盘图标：%s", exc)
            return False

        def open_console(icon=None, item=None):
            webbrowser.open(self.url)

        def quit_app(icon=None, item=None):
            try:
                if self._icon is not None:
                    self._icon.stop()
            finally:
                self.on_quit()

        menu = Menu(
            MenuItem("打开控制台", open_console, default=True),
            MenuItem("在浏览器中打开", open_console),
            Menu.SEPARATOR,
            MenuItem("退出 ADB 控制台", quit_app),
        )
        try:
            self._icon = pystray.Icon("adb-console", image, "ADB 控制台", menu)
            self._icon.run()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("启动托盘失败：%s", exc)
            return False

    def start_background(self) -> bool:
        """在后台线程启动托盘（供非 Windows 平台或测试使用）。"""
        try:
            import pystray  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            logger.warning("托盘不可用（缺少 pystray/Pillow）：%s", exc)
            return False
        threading.Thread(target=self.start, daemon=True).start()
        return True
