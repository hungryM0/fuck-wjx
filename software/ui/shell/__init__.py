"""界面外壳。"""

from software.ui.shell.boot import BootSplash, create_boot_splash, finish_boot_splash, get_boot_splash
from software.ui.shell.main_window import MainWindow, create_window

__all__ = [
    "BootSplash",
    "MainWindow",
    "create_boot_splash",
    "create_window",
    "finish_boot_splash",
    "get_boot_splash",
]

