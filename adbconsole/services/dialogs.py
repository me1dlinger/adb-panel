"""通过 tkinter 打开原生文件选择框。

Web 页面无法直接拿到本机路径，因此由本地服务弹出系统对话框，把选择结果返回给页面。
仅在 Windows/macOS/Linux 桌面环境可用；无图形环境时返回明确错误。
"""

from __future__ import annotations

import threading

_DIALOG_LOCK = threading.Lock()


class DialogUnavailable(RuntimeError):
    """当前环境无法弹出原生对话框。"""


def pick_file(title: str, filetypes=None, initialdir: str = "") -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # noqa: BLE001 - 无 tkinter 的打包环境
        raise DialogUnavailable(
            f"当前环境没有可用的图形界面（{type(exc).__name__}），请手动填写路径。"
        ) from exc

    with _DIALOG_LOCK:
        root = None
        try:
            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:  # noqa: BLE001 - 部分平台不支持
                pass
            root.update_idletasks()
            options = {
                "parent": root,
                "title": title,
                "filetypes": filetypes or (("所有文件", "*.*"),),
            }
            if initialdir:
                options["initialdir"] = initialdir
            path = filedialog.askopenfilename(**options)
        except Exception as exc:  # noqa: BLE001 -> 交给调用方展示
            raise DialogUnavailable(f"无法打开文件选择框：{exc}") from exc
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:  # noqa: BLE001
                    pass
    return str(path or "")
