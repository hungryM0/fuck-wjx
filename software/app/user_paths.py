"""用户数据路径解析。"""
from __future__ import annotations

import os
import sys

from software.app.settings_store import (
    CONFIG_DIRECTORY_SETTING_KEY,
    app_settings,
    get_str_from_qsettings,
)

_APP_NAME = "SurveyController"


def _expand_home_path(*parts: str) -> str:
    return os.path.abspath(os.path.join(os.path.expanduser("~"), *parts))


def _get_env_path(key: str, *fallback_parts: str) -> str:
    value = str(os.environ.get(key, "") or "").strip()
    if value:
        return os.path.abspath(value)
    return _expand_home_path(*fallback_parts)


def _get_macos_root(*parts: str) -> str:
    return _expand_home_path("Library", *parts)


def get_roaming_app_data_root() -> str:
    """返回用户漫游数据根目录。"""
    if sys.platform == "darwin":
        return _get_macos_root("Application Support")
    return _get_env_path("APPDATA", "AppData", "Roaming")


def get_local_app_data_root() -> str:
    """返回用户本地数据根目录。"""
    if sys.platform == "darwin":
        return _get_macos_root("Caches")
    return _get_env_path("LOCALAPPDATA", "AppData", "Local")


def get_user_config_root() -> str:
    """返回应用配置根目录。"""
    return os.path.join(get_roaming_app_data_root(), _APP_NAME)


def get_default_user_config_directory() -> str:
    """返回默认配置文件目录。"""
    return os.path.join(get_user_config_root(), "configs")


def resolve_user_config_directory(settings=None) -> str:
    """返回当前生效的配置文件目录。"""
    current_settings = settings or app_settings()
    configured_path = get_str_from_qsettings(
        current_settings.value(CONFIG_DIRECTORY_SETTING_KEY),
        "",
    )
    if not configured_path:
        return get_default_user_config_directory()
    return os.path.abspath(os.path.expanduser(configured_path))


def get_user_config_directory() -> str:
    """返回用户配置文件目录。"""
    return resolve_user_config_directory()


def get_user_local_data_root() -> str:
    """返回应用本地数据根目录。"""
    return os.path.join(get_local_app_data_root(), _APP_NAME)


def get_user_logs_directory() -> str:
    """返回日志目录。"""
    if sys.platform == "darwin":
        return os.path.join(_get_macos_root("Logs"), _APP_NAME)
    return os.path.join(get_user_local_data_root(), "logs")


def get_user_cache_directory() -> str:
    """返回缓存根目录。"""
    return os.path.join(get_user_local_data_root(), "cache")


def get_user_updates_directory() -> str:
    """返回更新缓存目录。"""
    return os.path.join(get_user_local_data_root(), "updates")


def get_default_runtime_config_path() -> str:
    """返回默认运行配置文件路径。"""
    return os.path.join(get_user_config_root(), "config.json")


def get_fatal_crash_log_path() -> str:
    """返回原生崩溃日志路径。"""
    return os.path.join(get_user_logs_directory(), "fatal_crash.log")


def get_last_session_log_path() -> str:
    """返回上次会话日志路径。"""
    return os.path.join(get_user_logs_directory(), "last_session.log")


def get_legacy_migration_marker_path() -> str:
    """返回旧版数据迁移标记文件路径。"""
    return os.path.join(get_user_local_data_root(), "migration", "legacy_inno_v1.json")


def ensure_user_data_directories() -> tuple[str, ...]:
    """确保应用用户目录存在。"""
    paths = (
        get_user_config_root(),
        get_user_config_directory(),
        get_user_local_data_root(),
        get_user_logs_directory(),
        get_user_cache_directory(),
        get_user_updates_directory(),
        os.path.dirname(get_legacy_migration_marker_path()),
    )
    for path in paths:
        os.makedirs(path, exist_ok=True)
    return tuple(paths)


__all__ = [
    "ensure_user_data_directories",
    "get_default_runtime_config_path",
    "get_default_user_config_directory",
    "get_fatal_crash_log_path",
    "get_last_session_log_path",
    "get_legacy_migration_marker_path",
    "get_local_app_data_root",
    "get_roaming_app_data_root",
    "get_user_cache_directory",
    "get_user_config_directory",
    "get_user_config_root",
    "get_user_local_data_root",
    "get_user_logs_directory",
    "get_user_updates_directory",
    "resolve_user_config_directory",
]
