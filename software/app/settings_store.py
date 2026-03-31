"""应用级设置访问门面。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings

_SETTINGS_ORG = "SurveyController"
_SETTINGS_APP = "Settings"


def app_settings() -> QSettings:
    """返回应用级 QSettings 实例。"""
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def get_bool_from_qsettings(value: Any, default: bool = False) -> bool:
    """兼容字符串/数值的布尔读取。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes", "on"}
    return bool(value)

