#!/usr/bin/env python3
"""源码运行入口（兼容旧命令 `python app.py`）。

桌面 / exe 入口请使用 run.py（带托盘图标）。页面与接口实现在 adbconsole/web/。
"""

from __future__ import annotations

import threading

import adb_core
from adbconsole.web import create_app, discovery_loop, find_port

app = create_app()


def main() -> None:
    port = find_port(5010)
    threading.Thread(target=discovery_loop, args=(app,), daemon=True).start()
    print("ADB 控制台")
    print(f"  adb 路径 : {adb_core.adb_path()}")
    print(f"  项目目录 : {adb_core.BASE_DIR}")
    print(f"  访问地址 : http://127.0.0.1:{port}")
    print(f"  MCP 地址 : http://127.0.0.1:{port}/mcp（默认关闭，页面设置中开启）")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
