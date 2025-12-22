# -*- coding: utf-8 -*-
"""
Windows 注册表管理模块，用于管理随机IP提交计数器
有能力看懂源码，说明你也有能力轻易破解这个卡密验证，很简单的逻辑，随机ip是你应得的♥

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
    REGISTRY_KEY_CARD = "CardValidateResult"
    REGISTRY_KEY_UNLIMITED = "UnlimitedQuota"
    REGISTRY_KEY_LIMIT = "RandomIPQuotaLimit"
    
    @staticmethod
    def _get_registry_hkey() -> Optional[int]:
        if winreg is None:
            return None
        return winreg.HKEY_CURRENT_USER
    
    @staticmethod
    def read_submit_count() -> int:
        if winreg is None:
            logging.debug("当前不在Windows系统，跳过注册表读取")
            return 0
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY)
                count = int(value) if value is not None else 0
                logging.debug(f"从注册表读取随机IP计数: {count}")
                return count
        except FileNotFoundError:
            logging.debug(f"注册表键 {RegistryManager.REGISTRY_PATH} 不存在，返回计数 0")
            return 0
        except (OSError, ValueError) as e:
            logging.warning(f"读取注册表计数失败: {e}")
            return 0
        except Exception as e:
            logging.error(f"读取注册表出现未预期的错误: {e}")
            return 0
    
    @staticmethod
    def write_submit_count(count: int) -> bool:
        if winreg is None:
            logging.debug("当前不在Windows系统，跳过注册表写入")
            return False
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY, 0, winreg.REG_DWORD, int(count))
            winreg.CloseKey(key)
            logging.debug(f"已将随机IP计数写入注册表: {count}")
            return True
        except OSError as e:
            logging.warning(f"写入注册表计数失败: {e}")
            return False
        except Exception as e:
            logging.error(f"写入注册表出现未预期的错误: {e}")
            return False
    
    @staticmethod
    def increment_submit_count() -> int:
        current = RegistryManager.read_submit_count()
        new_count = current + 1
        RegistryManager.write_submit_count(new_count)
        logging.info(f"随机IP提交计数已更新: {current} → {new_count}")
        return new_count
    
    @staticmethod
    def reset_submit_count() -> bool:
        result = RegistryManager.write_submit_count(0)
        if result:
            logging.info("随机IP提交计数已重置为 0")
        return result
    
    @staticmethod
    def read_card_validate_result() -> bool:
        if winreg is None:
            return False
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY_CARD)
                result = bool(int(value))
                logging.debug(f"从注册表读取卡密验证结果: {result}")
                return result
        except FileNotFoundError:
            logging.debug("注册表卡密验证记录不存在")
            return False
        except Exception as e:
            logging.debug(f"读取卡密验证结果失败: {e}")
            return False
    
    @staticmethod
    def write_card_validate_result(validated: bool) -> bool:
        if winreg is None:
            return False
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY_CARD, 0, winreg.REG_DWORD, int(validated))
            winreg.CloseKey(key)
            logging.debug(f"已将卡密验证结果写入注册表: {validated}")
            return True
        except Exception as e:
            logging.warning(f"写入卡密验证结果失败: {e}")
            return False
    
    @staticmethod
    def is_quota_unlimited() -> bool:
        if winreg is None:
            return False
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY_UNLIMITED)
                result = bool(int(value))
                logging.debug(f"无限额度状态: {result}")
                return result
        except FileNotFoundError:
            logging.debug("无限额度标记不存在，返回False")
            return False
        except Exception as e:
            logging.debug(f"读取无限额度状态失败: {e}")
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
            status = "启用" if unlimited else "禁用"
            logging.info(f"无限额度已{status}")
            return True
        except Exception as e:
            logging.warning(f"设置无限额度失败: {e}")
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
