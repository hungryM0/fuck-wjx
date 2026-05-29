"""运行时路径解析 - 仅负责安装目录与包内只读资源。"""
from __future__ import annotations

import os
import sys

from software.app.path_utils import normalize_filesystem_path


def _get_repo_root() -> str:
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def get_runtime_directory() -> str:
    """返回应用运行目录。

    注意：
    - 这里只表示程序安装/运行位置，不再用于用户可写数据
    - 开发环境：仓库根目录
    - 打包环境：exe 所在目录；若 exe 位于 lib 目录，则回退到上一层
    """
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir).lower() == "lib":
            return os.path.dirname(exe_dir)
        return exe_dir
    return _get_repo_root()


def get_bundle_resource_root() -> str:
    """返回包内只读资源根目录。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return normalize_filesystem_path(meipass)
        return os.path.dirname(sys.executable)
    return _get_repo_root()


def get_assets_directory() -> str:
    """返回包内 assets 目录，兼容不同冻结包布局。"""
    bundle_root = get_bundle_resource_root()
    candidates = [os.path.join(bundle_root, "assets")]

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        exe_assets = os.path.join(exe_dir, "assets")
        internal_assets = os.path.join(exe_dir, "_internal", "assets")
        for path in (exe_assets, internal_assets):
            if path not in candidates:
                candidates.append(path)

    for path in candidates:
        if os.path.isdir(path):
            return path

    return os.path.join(bundle_root, "assets")


def get_resource_path(relative_path: str) -> str:
    """返回相对包内资源根目录的资源绝对路径。"""
    return os.path.normpath(os.path.join(get_bundle_resource_root(), relative_path))


__all__ = [
    "get_runtime_directory",
    "get_bundle_resource_root",
    "get_assets_directory",
    "get_resource_path",
]
