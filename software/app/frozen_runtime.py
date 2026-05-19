"""冻结包启动前的 DLL 与 Qt 路径准备。"""
from __future__ import annotations

import os
import sys
from typing import Iterable


def _iter_existing_directories(paths: Iterable[str]) -> list[str]:
    return [path for path in paths if os.path.isdir(path)]


def _prepend_path_entries(paths: list[str]) -> None:
    if not paths:
        return
    os.environ["PATH"] = os.pathsep.join(paths) + os.pathsep + os.environ.get("PATH", "")


def _add_dll_directories(paths: list[str]) -> None:
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return
    for path in paths:
        try:
            add_dll_directory(path)
        except OSError:
            pass


def prepare_frozen_runtime() -> None:
    """在导入 PySide6 前准备冻结包运行环境。"""
    if not getattr(sys, "frozen", False):
        return

    app_dir = os.path.dirname(sys.executable)
    pyside6_dir = os.path.join(app_dir, "PySide6")
    shiboken6_dir = os.path.join(app_dir, "shiboken6")
    qt_libexec_dir = os.path.join(pyside6_dir, "Qt", "libexec")

    dll_search_dirs = _iter_existing_directories(
        (pyside6_dir, qt_libexec_dir, shiboken6_dir)
    )
    _prepend_path_entries(dll_search_dirs)
    _add_dll_directories(dll_search_dirs)

    plugins_dir = os.path.join(pyside6_dir, "plugins")
    if os.path.isdir(plugins_dir):
        os.environ["QT_PLUGIN_PATH"] = plugins_dir


__all__ = ["prepare_frozen_runtime"]
