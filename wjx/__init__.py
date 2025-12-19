"""Support modules for the WJX automation package."""

# 导入子模块使其可以通过 wjx.* 访问
from wjx import (
    boot,
    browser_driver,
    config,
    engine,
    full_simulation_mode,
    full_simulation_ui,
    gui,
    load_save,
    log_utils,
    random_ip,
    registry_manager,
    runtime,
    updater,
    version,
)

__all__ = [
    "config",
    "full_simulation_mode",
    "full_simulation_ui",
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
    "runtime",
]
