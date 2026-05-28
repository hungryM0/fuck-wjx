# -*- coding: utf-8 -*-
"""轻量状态读写。"""

from __future__ import annotations

from software.app.settings_store import app_settings, get_bool_from_qsettings


class RegistryManager:
    """兼容旧调用名，底层改走 QSettings。"""

    REGISTRY_PATH = "system_state"
    REGISTRY_KEY_CONFETTI_PLAYED = "ConfettiPlayed"

    @classmethod
    def _settings_key(cls) -> str:
        return f"{cls.REGISTRY_PATH}/{cls.REGISTRY_KEY_CONFETTI_PLAYED}"

    @staticmethod
    def is_confetti_played() -> bool:
        """检查彩带动画是否已播放过。"""
        try:
            settings = app_settings()
            return get_bool_from_qsettings(
                settings.value(RegistryManager._settings_key()),
                False,
            )
        except Exception:
            return False

    @staticmethod
    def set_confetti_played(played: bool) -> bool:
        """设置彩带动画播放状态。"""
        try:
            settings = app_settings()
            settings.setValue(RegistryManager._settings_key(), bool(played))
            settings.sync()
            return True
        except Exception:
            return False
