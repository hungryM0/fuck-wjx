# -*- coding: utf-8 -*-
"""
跨平台配置存储管理模块，用于管理随机IP提交计数器
有能力看懂源码，说明你也有能力轻易破解这个卡密验证，很简单的逻辑，随机ip是你应得的♥

但请希望不要滥用

Windows: 使用注册表存储
macOS/Linux: 使用 JSON 文件存储 (~/.fuckwjx/config.json)
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

# 平台检测
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

# 只在 Windows 平台导入 winreg
if IS_WINDOWS:
    import winreg
else:
    winreg = None


def _get_config_dir() -> Path:
    """获取配置目录路径"""
    if IS_MACOS:
        # macOS: ~/Library/Application Support/FuckWJX
        base = Path.home() / "Library" / "Application Support" / "FuckWJX"
    elif IS_WINDOWS:
        # Windows: %APPDATA%\FuckWJX (备用，主要用注册表)
        base = Path(os.environ.get("APPDATA", Path.home())) / "FuckWJX"
    else:
        # Linux: ~/.config/fuckwjx
        base = Path.home() / ".config" / "fuckwjx"
    return base


def _get_config_file() -> Path:
    """获取配置文件路径"""
    return _get_config_dir() / "config.json"


def _read_json_config() -> dict:
    """读取 JSON 配置文件"""
    config_file = _get_config_file()
    if not config_file.exists():
        return {}
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _write_json_config(config: dict) -> bool:
    """写入 JSON 配置文件"""
    config_file = _get_config_file()
    try:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except (IOError, OSError) as e:
        logging.warning(f"写入配置文件失败: {e}")
        return False


def _get_json_value(key: str, default: Any = None) -> Any:
    """从 JSON 配置获取值"""
    config = _read_json_config()
    return config.get(key, default)


def _set_json_value(key: str, value: Any) -> bool:
    """设置 JSON 配置值"""
    config = _read_json_config()
    config[key] = value
    return _write_json_config(config)


class RegistryManager:
    
    REGISTRY_PATH = r"Software\FuckWJX"
    REGISTRY_KEY = "RandomIPSubmitCount"
    REGISTRY_KEY_CARD = "CardValidateResult"
    REGISTRY_KEY_UNLIMITED = "UnlimitedQuota"
    REGISTRY_KEY_LIMIT = "RandomIPQuotaLimit"
    
    # JSON 配置键名 (用于 macOS/Linux)
    JSON_KEY_SUBMIT_COUNT = "random_ip_submit_count"
    JSON_KEY_CARD = "card_validate_result"
    JSON_KEY_UNLIMITED = "unlimited_quota"
    JSON_KEY_LIMIT = "quota_limit"
    
    @staticmethod
    def _get_registry_hkey() -> Optional[int]:
        if winreg is None:
            return None
        return winreg.HKEY_CURRENT_USER
    
    @staticmethod
    def read_submit_count() -> int:
        if not IS_WINDOWS:
            # macOS/Linux: 使用 JSON 文件
            return int(_get_json_value(RegistryManager.JSON_KEY_SUBMIT_COUNT, 0))
        
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
        if not IS_WINDOWS:
            # macOS/Linux: 使用 JSON 文件
            return _set_json_value(RegistryManager.JSON_KEY_SUBMIT_COUNT, int(count))
        
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
    def reset_submit_count() -> bool:
        result = RegistryManager.write_submit_count(0)
        if result:
            logging.info("随机IP提交计数已重置为 0")
        return result
    
    @staticmethod
    def read_card_validate_result() -> bool:
        if not IS_WINDOWS:
            # macOS/Linux: 使用 JSON 文件
            return bool(_get_json_value(RegistryManager.JSON_KEY_CARD, False))
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY_CARD)
                result = bool(int(value))
                return result
        except FileNotFoundError:
            return False
        except Exception:
            return False
    
    @staticmethod
    def write_card_validate_result(validated: bool) -> bool:
        if not IS_WINDOWS:
            # macOS/Linux: 使用 JSON 文件
            return _set_json_value(RegistryManager.JSON_KEY_CARD, bool(validated))
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY_CARD, 0, winreg.REG_DWORD, int(validated))
            winreg.CloseKey(key)
            return True
        except Exception:
            return False
    
    @staticmethod
    def is_quota_unlimited() -> bool:
        if not IS_WINDOWS:
            # macOS/Linux: 使用 JSON 文件
            result = bool(_get_json_value(RegistryManager.JSON_KEY_UNLIMITED, False))
            logging.debug(f"无限额度状态: {result}")
            return result
        
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
        if not IS_WINDOWS:
            # macOS/Linux: 使用 JSON 文件
            result = _set_json_value(RegistryManager.JSON_KEY_UNLIMITED, bool(unlimited))
            if result:
                status = "启用" if unlimited else "禁用"
                logging.info(f"无限额度已{status}")
            return result
        
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
        if not IS_WINDOWS:
            # macOS/Linux: 使用 JSON 文件
            limit = int(_get_json_value(RegistryManager.JSON_KEY_LIMIT, default))
            return limit if limit > 0 else default
        
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
        limit_val = max(1, int(limit))
        
        if not IS_WINDOWS:
            # macOS/Linux: 使用 JSON 文件
            result = _set_json_value(RegistryManager.JSON_KEY_LIMIT, limit_val)
            if result:
                logging.info(f"随机IP额度上限已设置为 {limit_val}")
            return result
        
        try:
            hkey = winreg.HKEY_CURRENT_USER
            key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY_LIMIT, 0, winreg.REG_DWORD, limit_val)
            winreg.CloseKey(key)
            logging.info(f"随机IP额度上限已设置为 {limit_val}")
            return True
        except Exception as e:
            logging.warning(f"写入额度上限失败: {e}")
            return False
