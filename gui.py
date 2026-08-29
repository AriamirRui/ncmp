"""ncmp 图形界面入口。

用法:
    python gui.py
    或
    python main.py --gui
"""
import sys


def _enable_high_dpi() -> None:
    """在 Windows 上启用高 DPI 感知，避免界面模糊。"""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def run_gui() -> None:
    _enable_high_dpi()
    try:
        from src.ui.app import NcmpApp
    except ImportError as e:
        print(f"启动图形界面失败：无法导入 Tkinter 模块。\n"
              f"请确认当前 Python 环境已安装 tkinter（Windows 官方安装包自带）。\n"
              f"详细信息: {e}")
        sys.exit(1)

    app = NcmpApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
