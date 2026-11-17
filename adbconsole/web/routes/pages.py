"""页面与静态文件路由。"""

from __future__ import annotations

from flask import Blueprint, render_template, send_from_directory

import adb_core
from adb_core import PULL_DIR, SCREENSHOT_DIR

from ..common import api_route

bp = Blueprint("pages", __name__)


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/favicon.ico")
def favicon():
    return "", int("204")


@bp.get("/api/screenshot/file/<path:name>")
@api_route
def screenshot_file(name):
    adb_core.safe_name(name)
    return send_from_directory(SCREENSHOT_DIR, name, mimetype="image/png")


@bp.get("/api/download/<path:name>")
@api_route
def download_pull(name):
    adb_core.safe_name(name)
    return send_from_directory(PULL_DIR, name, as_attachment=True)
