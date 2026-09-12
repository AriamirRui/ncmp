"""兼容层：旧的 Tkinter 界面通过这里访问运行历史（实现已迁移至 src/store/history.py）。"""
from ..store.history import HISTORY_DIR, PROJECT_ROOT, RunHistory

__all__ = ["HISTORY_DIR", "PROJECT_ROOT", "RunHistory"]
