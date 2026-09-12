"""Python sidecar 打包入口（PyInstaller 用）。

等价于 `python -m src.server`，保留包上下文以便相对导入正常工作。
"""
import multiprocessing
import sys

from src.server.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
