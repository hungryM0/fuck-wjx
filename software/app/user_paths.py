"""用户数据路径解析。"""
from __future__ import annotations

import os

from PySide6.QtCore import QCoreApplication, QStandardPaths

from software.app.path_utils import normalize_filesystem_path
from software.app.settings_store import (
    CONFIG_DIRECTORY_SETTING_KEY,
    app_settings,
    configure_qt_application_metadata,
    get_str_from_qsettings,
)

_APP_NAME = "SurveyController"


def _normalize_path(path: str) -> str:
    return normalize_filesystem_path(str(path or "").strip())


def _strip_qt_app_suffix(path: str) -> str:
    normalized = _normalize_path(path)
    if not normalized:
        return normalized
    current = normalized
    app_name = str(QCoreApplication.applicationName() or "").strip()
    org_name = str(QCoreApplication.organizationName() or "").strip()
    for name in (app_name, org_name):
        if not name:
            continue
        if os.path.basename(current).strip().lower() == name.lower():
            current = os.path.dirname(current)
    return current


def _get_standard_base_root(location: QStandardPaths.StandardLocation, *fallback_parts: str) -> str:
    configure_qt_application_metadata()
    path = str(QStandardPaths.writableLocation(location) or "").strip()
    if path:
        stripped = _strip_qt_app_suffix(path)
        if stripped:
            return stripped
    return _normalize_path(os.path.join(os.path.expanduser("~"), *fallback_parts))


def get_roaming_app_data_root() -> str:
    """返回用户漫游数据根目录。"""
    return _get_standard_base_root(
        QStandardPaths.StandardLocation.AppDataLocation,
        "AppData",
        "Roaming",
    )


def get_local_app_data_root() -> str:
    """返回用户本地数据根目录。"""
    return _get_standard_base_root(
        QStandardPaths.StandardLocation.AppLocalDataLocation,
        "AppData",
        "Local",
    )


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
    return _normalize_path(os.path.expanduser(configured_path))


def get_user_config_directory() -> str:
    """返回用户配置文件目录。"""
    return resolve_user_config_directory()


def get_user_local_data_root() -> str:
    """返回应用本地数据根目录。"""
    return os.path.join(get_local_app_data_root(), _APP_NAME)


def get_user_logs_directory() -> str:
    """返回日志目录。"""
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


def ensure_user_data_directories() -> tuple[str, ...]:
    """确保应用用户目录存在。"""
    paths = (
        get_user_config_root(),
        get_user_config_directory(),
        get_user_local_data_root(),
        get_user_logs_directory(),
        get_user_cache_directory(),
        get_user_updates_directory(),
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
