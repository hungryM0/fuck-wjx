# -*- coding: utf-8 -*-
"""
Windows 注册表管理模块，用于管理随机IP提交计数器
有能力看懂源码，说明你也有能力轻易破解这个卡密验证，很简单的逻辑，随机ip是你应得的♥

但请希望不要滥用

"""

import logging
import sys
from typing import Optional

# 只在 Windows 平台导入 winreg
if sys.platform == "win32":
    import winreg
else:
    winreg = None


class RegistryManager:

    REGISTRY_PATH = r"Software\FuckWJX"
    REGISTRY_PATH = r"Software\FuckWJX"
    REGISTRY_KEY = "RandomIPSubmitCount"
    REGISTRY_KEY_UNLIMITED = "UnlimitedQuota"
    REGISTRY_KEY_LIMIT = "RandomIPQuotaLimit"
    REGISTRY_KEY_CARD_VERIFIED = "CardVerified"
    
    @staticmethod
    def read_submit_count() -> int:
        if winreg is None:
            return 0
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY)
                count = int(value) if value is not None else 0
                return count
        except FileNotFoundError:
            return 0
        except (OSError, ValueError):
            return 0
        except Exception:
            return 0
    
    @staticmethod
    def write_submit_count(count: int) -> bool:
        if winreg is None:
            return False
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY, 0, winreg.REG_DWORD, int(count))
            winreg.CloseKey(key)
            return True
        except OSError:
            return False
        except Exception:
            return False
    
    @staticmethod
    def increment_submit_count() -> int:
        current = RegistryManager.read_submit_count()
        new_count = current + 1
        RegistryManager.write_submit_count(new_count)
        return new_count
    
    @staticmethod
    def is_quota_unlimited() -> bool:
        if winreg is None:
            return False
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY_UNLIMITED)
                result = bool(int(value))
                return result
        except FileNotFoundError:
            return False
        except Exception as e:
            return False
    
    @staticmethod
    def set_quota_unlimited(unlimited: bool) -> bool:
        if winreg is None:
            return False
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY_UNLIMITED, 0, winreg.REG_DWORD, int(unlimited))
            winreg.CloseKey(key)
            return True
        except Exception as e:
            return False

    @staticmethod
    def read_quota_limit(default: int = 20) -> int:
        if winreg is None:
            return default
        try:
            hkey = winreg.HKEY_CURRENT_USER
            with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY_LIMIT)
                limit = int(value)
                return limit if limit > 0 else default
        except FileNotFoundError:
            return default
        except Exception as e:
            logging.debug(f"读取额度上限失败: {e}")
            return default

    @staticmethod
    def write_quota_limit(limit: int) -> bool:
        if winreg is None:
            return False
        try:
            limit_val = max(1, int(limit))
            hkey = winreg.HKEY_CURRENT_USER
            key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY_LIMIT, 0, winreg.REG_DWORD, limit_val)
            winreg.CloseKey(key)
            logging.info(f"随机IP额度上限已设置为 {limit_val}")
            return True
        except Exception as e:
            logging.warning(f"写入额度上限失败: {e}")
            return False

    @staticmethod
    def is_card_verified() -> bool:
        """检查是否已验证过卡密"""
        if winreg is None:
            return False

        try:
            hkey = winreg.HKEY_CURRENT_USER
            with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY_CARD_VERIFIED)
                result = bool(int(value))
                return result
        except FileNotFoundError:
            return False
        except Exception:
            return False

    @staticmethod
    def set_card_verified(verified: bool) -> bool:
        """设置卡密验证状态"""
        if winreg is None:
            return False

        try:
            hkey = winreg.HKEY_CURRENT_USER
            key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY_CARD_VERIFIED, 0, winreg.REG_DWORD, int(verified))
            winreg.CloseKey(key)
            return True
        except Exception:
            return False
