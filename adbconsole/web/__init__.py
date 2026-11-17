"""Flask 应用工厂与后台任务。

页面层只负责路由注册；具体功能拆分在 routes/ 下的各个蓝图，
桌面能力（托盘、原生对话框）放在 services/，MCP 协议在 mcp/。
"""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import socket
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

import adb_core
from adb_core import BASE_DIR, result

from .routes import BLUEPRINTS

# 打包后静态资源位于 _MEIPASS；源码运行时使用项目目录。
_RESOURCE_DIR = (
    Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else BASE_DIR
)

MAX_UPLOAD = int("2") * 1024 * 1024 * 1024


def setup_logging(app: Flask) -> None:
    """按日轮转写入 logs/app.log，保留 14 天。"""
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    adb_core.LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        adb_core.LOG_DIR / "app.log",
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(file_handler)
    root.addHandler(console)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.logger.setLevel(logging.INFO)
    app.logger.info("日志初始化完成，日志目录：%s", adb_core.LOG_DIR)


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(_RESOURCE_DIR / "static"),
        template_folder=str(_RESOURCE_DIR / "templates"),
    )
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    setup_logging(app)

    log_streamer = adb_core.LogcatStreamer()
    app.extensions["log_streamer"] = log_streamer
    atexit.register(log_streamer.stop)

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(RequestEntityTooLarge)
    def payload_too_large(error):
        return jsonify(result(False, "", "上传文件超过 2 GB 限制。", -1)), error.code

    return app


def discovery_loop(app: Flask | None = None) -> None:
    logger = app.logger if app is not None else logging.getLogger("adb-console")
    while True:
        try:
            adb_core.discover(force=True, connect=True)
        except Exception as exc:  # noqa: BLE001 - 后台线程需保持存活
            logger.warning("设备自动发现失败：%s", exc)
        time.sleep(6)


def find_port(preferred: int = 5010) -> int:
    for port in range(preferred, preferred + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit("5010 到 5049 之间没有可用端口。")


__all__ = ["create_app", "discovery_loop", "find_port", "setup_logging"]
