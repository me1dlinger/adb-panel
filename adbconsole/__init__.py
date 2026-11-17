"""ADB 控制台应用包。

层次：
    adb_core.py            adb 引擎层（设备、屏幕、日志、文件）
    mcp_tools.py           MCP 工具清单（工具层）
    adbconsole.config      配置读写（MCP 开关等）
    adbconsole.mcp         MCP 协议网关（进程内，随主程序启动）
    adbconsole.services    托盘、原生对话框等桌面服务
    adbconsole.web         Flask 应用工厂与路由蓝图（页面层）
"""

__version__ = "2.0.0"
