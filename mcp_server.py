#!/usr/bin/env python3
"""兼容入口：只给仅支持 stdio 启动方式的 MCP 客户端使用。

主程序（app.py / ADBConsole.exe）已经把 MCP 合并进同一进程，通过
POST http://127.0.0.1:<端口>/mcp 提供，无需再单独启动本文件。
"""

from __future__ import annotations

from adbconsole.mcp.stdio import main

if __name__ == "__main__":
    main()
