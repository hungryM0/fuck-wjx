"""Support modules for the WJX automation package."""

# 加载 .env 文件中的环境变量
from dotenv import load_dotenv
load_dotenv()

# 导入子模块使其可以通过 wjx.* 访问
from wjx import (
    boot,
    engine,
    gui,
)

# 从新目录结构导入模块
from wjx.network import browser_driver, random_ip
from wjx.utils import config, load_save, log_utils, registry_manager, updater, version
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
