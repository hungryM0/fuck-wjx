import os
import sys


def _get_project_root() -> str:
    """获取项目根目录（开发环境：Fuck wjx/；打包后：可执行文件目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # 开发环境：wjx/utils/app/runtime_paths.py -> 向上4层到项目根
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _get_runtime_directory() -> str:
    """获取运行时目录（wjx/ 包目录）- 已废弃，建议使用 _get_project_root()"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_resource_path(relative_path: str) -> str:
    """
    获取资源文件的完整路径。
    在 PyInstaller 打包时，资源会被提取到 sys._MEIPASS 目录。
    在开发时，资源位于项目根目录。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后，资源在 _MEIPASS 目录中
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # 开发环境，资源在项目根目录（wjx 目录的上一级）
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    return os.path.join(base_path, relative_path)
