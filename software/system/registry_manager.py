# -*- coding: utf-8 -*-
"""
跨平台持久化存储管理

Windows: 使用注册表
macOS/Linux: 使用 JSON 文件 (~/Library/Application Support/SurveyController/)
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

# 只在 Windows 平台导入 winreg
if sys.platform == "win32":
    import winreg
else:
    winreg = None


def _get_mac_data_dir() -> Path:
    """获取 macOS 应用数据目录"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SurveyController"
    elif sys.platform == "linux":
        xdg = os.environ.get("XDG_DATA_HOME", "")
        if xdg:
            return Path(xdg) / "SurveyController"
        return Path.home() / ".local" / "share" / "SurveyController"
    return Path.home() / ".surveycontroller"


_DATA_FILE_NAME = "registry_data.json"


class _JsonStore:
    """简单的 JSON 文件存储，替代 Windows 注册表"""

    def __init__(self):
        self._data_dir = _get_mac_data_dir()
        self._data_file = self._data_dir / _DATA_FILE_NAME
        self._cache: Optional[dict] = None

    def _load(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            if self._data_file.exists():
                with open(self._data_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                    return self._cache
        except Exception as exc:
            logging.warning("读取数据文件失败: %s", exc)
        self._cache = {}
        return self._cache

    def _save(self) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            with open(self._data_file, "w", encoding="utf-8") as f:
                json.dump(self._cache or {}, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logging.warning("保存数据文件失败: %s", exc)

    def read(self, key: str, default: Any = None) -> Any:
        data = self._load()
        return data.get(key, default)

    def write(self, key: str, value: Any) -> bool:
        data = self._load()
        data[key] = value
        self._cache = data
        self._save()
        return True


# 全局实例（仅非 Windows 平台使用）
_json_store: Optional[_JsonStore] = None


def _get_json_store() -> _JsonStore:
    global _json_store
    if _json_store is None:
        _json_store = _JsonStore()
    return _json_store


class RegistryManager:

    REGISTRY_PATH = r"Software\SurveyController"
    REGISTRY_KEY = "RandomIPSubmitCount"
    REGISTRY_KEY_LIMIT = "RandomIPQuotaLimit"
    REGISTRY_KEY_CONFETTI_PLAYED = "ConfettiPlayed"

    @staticmethod
    def read_submit_count() -> int:
        if winreg is not None:
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
        else:
            store = _get_json_store()
            value = store.read(RegistryManager.REGISTRY_KEY, 0)
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

    @staticmethod
    def write_submit_count(count: int) -> bool:
        if winreg is not None:
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
        else:
            store = _get_json_store()
            return store.write(RegistryManager.REGISTRY_KEY, int(count))

    @staticmethod
    def increment_submit_count(step: int = 1) -> int:
        current = RegistryManager.read_submit_count()
        safe_step = max(1, int(step or 1))
        new_count = current + safe_step
        RegistryManager.write_submit_count(new_count)
        return new_count

    @staticmethod
    def read_quota_limit(default: int = 20) -> int:
        if winreg is not None:
            try:
                hkey = winreg.HKEY_CURRENT_USER
                with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                    value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY_LIMIT)
                    limit = int(value)
                    return limit if limit > 0 else default
            except FileNotFoundError:
                return default
            except Exception as e:
                logging.info(f"读取额度上限失败: {e}")
                return default
        else:
            store = _get_json_store()
            value = store.read(RegistryManager.REGISTRY_KEY_LIMIT, default)
            try:
                limit = int(value)
                return limit if limit > 0 else default
            except (TypeError, ValueError):
                return default

    @staticmethod
    def write_quota_limit(limit: int) -> bool:
        if winreg is not None:
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
        else:
            limit_val = max(1, int(limit))
            store = _get_json_store()
            result = store.write(RegistryManager.REGISTRY_KEY_LIMIT, limit_val)
            if result:
                logging.info(f"随机IP额度上限已设置为 {limit_val}")
            return result

    @staticmethod
    def is_confetti_played() -> bool:
        """检查彩带动画是否已播放过"""
        if winreg is not None:
            try:
                hkey = winreg.HKEY_CURRENT_USER
                with winreg.OpenKey(hkey, RegistryManager.REGISTRY_PATH) as key:
                    value, _ = winreg.QueryValueEx(key, RegistryManager.REGISTRY_KEY_CONFETTI_PLAYED)
                    return bool(int(value))
            except FileNotFoundError:
                return False
            except Exception:
                return False
        else:
            store = _get_json_store()
            value = store.read(RegistryManager.REGISTRY_KEY_CONFETTI_PLAYED, False)
            return bool(value)

    @staticmethod
    def set_confetti_played(played: bool) -> bool:
        """设置彩带动画播放状态"""
        if winreg is not None:
            try:
                hkey = winreg.HKEY_CURRENT_USER
                key = winreg.CreateKeyEx(hkey, RegistryManager.REGISTRY_PATH, 0, winreg.KEY_WRITE)
                winreg.SetValueEx(key, RegistryManager.REGISTRY_KEY_CONFETTI_PLAYED, 0, winreg.REG_DWORD, int(played))
                winreg.CloseKey(key)
                return True
            except Exception:
                return False
        else:
            store = _get_json_store()
            return store.write(RegistryManager.REGISTRY_KEY_CONFETTI_PLAYED, bool(played))
