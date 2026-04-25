# -*- coding: utf-8 -*-
"""Windows 注册表轻量状态读写。"""

import sys

# 只在 Windows 平台导入 winreg
if sys.platform == "win32":
    import winreg
else:
    winreg = None


class RegistryManager:

    REGISTRY_PATH = r"Software\SurveyController"
    REGISTRY_KEY_CONFETTI_PLAYED = "ConfettiPlayed"

    @staticmethod
    def is_confetti_played() -> bool:
        """检查彩带动画是否已播放过"""
        if winreg is None:
            return False
        try:
            hkey = winreg.HKEY_CURRENT_USER
            with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY_CONFETTI_PLAYED)
                return bool(int(value))
        except FileNotFoundError:
            return False
        except Exception:
            return False

    @staticmethod
    def set_confetti_played(played: bool) -> bool:
        """设置彩带动画播放状态"""
        if winreg is None:
            return False
        try:
            hkey = winreg.HKEY_CURRENT_USER
            key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY_CONFETTI_PLAYED, 0, winreg.REG_DWORD, int(played))
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

