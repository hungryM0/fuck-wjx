# type: ignore
from __future__ import annotations

"""
启动界面模块（已弃用）。
启动界面现在集成在 main_window.py 中使用 QFluentWidgets 的 SplashScreen 组件。
此文件保留以兼容旧代码引用。
"""

from typing import Optional


_boot_root: Optional[object] = None
_boot_splash: Optional[object] = None


def preload_boot_splash(**kwargs) -> None:
    """已弃用：启动画面现在由 MainWindow 内部管理。"""
    pass


def update_boot_splash(percent: int, message: Optional[str] = None) -> None:
    """已弃用：启动画面现在由 MainWindow 内部管理。"""
    pass


def get_boot_root() -> Optional[object]:
    """已弃用。"""
    return _boot_root


def get_boot_splash() -> Optional[object]:
    """已弃用。"""
    return _boot_splash


def close_boot_splash() -> None:
    """已弃用：启动画面现在由 MainWindow 内部管理。"""
    pass
