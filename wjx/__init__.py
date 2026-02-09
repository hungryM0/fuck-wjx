"""Support modules for the WJX automation package."""

# 导入子模块使其可以通过 wjx.* 访问
from wjx import (
    boot,
    engine,
    gui,
)

# 从新目录结构导入模块
from wjx.network import browser_driver, random_ip
from wjx.utils.app import config, version
from wjx.utils.io import load_save
from wjx.utils.logging import log_utils
from wjx.utils.system import registry_manager
from wjx.utils.update import updater
from wjx.modes import timed_mode

__all__ = [
    "config",
    "timed_mode",
    "log_utils",
    "random_ip",
    "registry_manager",
    "updater",
    "version",
    "engine",
    "gui",
    "boot",
    "browser_driver",
    "load_save",
]
