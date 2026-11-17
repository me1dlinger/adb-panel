"""可选的 stdio 传输层。

主程序默认通过 POST /mcp 提供 MCP，无需单独启动本进程。
仅给只支持 stdio 启动方式的客户端保留一个兼容入口（mcp_server.py）。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime

import adb_core

from .gateway import McpGateway

LOG_PATH = adb_core.LOG_DIR / "mcp_server.log"


def _configure_streams() -> None:
    for stream, kwargs in (
        (sys.stdin, {"encoding": "utf-8", "errors": "replace"}),
        (sys.stdout, {"encoding": "utf-8", "newline": "\n"}),
        (sys.stderr, {"encoding": "utf-8", "errors": "replace"}),
    ):
        try:
            stream.reconfigure(**kwargs)
        except Exception:  # noqa: BLE001
            pass


def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("adb-console-mcp-stdio")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except OSError:
        pass
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)
    return logger


def main() -> None:
    _configure_streams()
    logger = _setup_logger()
    gateway = McpGateway()
    logger.info("MCP stdio started at %s", datetime.now().isoformat(timespec="seconds"))
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"JSON 解析失败：{exc.msg}"},
                }
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                continue
            _, body = gateway.dispatch(payload)
            if body is None:
                continue
            messages = body if isinstance(body, list) else [body]
            for message in messages:
                sys.stdout.write(
                    json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
            sys.stdout.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        logger.info("MCP stdio stopped")


if __name__ == "__main__":
    main()
