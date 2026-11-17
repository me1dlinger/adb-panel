"""路由蓝图集合。"""

from . import device, devices, files, logcat, mcp, pages, screen, settings, shell

BLUEPRINTS = (
    pages.bp,
    devices.bp,
    device.bp,
    screen.bp,
    logcat.bp,
    files.bp,
    shell.bp,
    settings.bp,
    mcp.bp,
)

__all__ = ["BLUEPRINTS"]
