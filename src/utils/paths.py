"""路径工具：兼容源码运行与 PyInstaller 打包后的 exe 运行。"""
import os
import sys


def get_project_root() -> str:
    """返回项目根目录。

    - 源码运行时：src/utils/paths.py 向上三级，即项目根目录
    - PyInstaller 打包后：exe 所在目录（config/、data/ 都放在 exe 旁边）
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
