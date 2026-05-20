"""旧版 Inno Setup 数据迁移。"""
from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any, cast

from software.app.user_paths import (
    ensure_user_data_directories,
    get_default_runtime_config_path,
    get_legacy_migration_marker_path,
    get_user_config_directory,
    get_user_logs_directory,
)

try:  # pragma: no cover - 非 Windows 环境没有 winreg
    import winreg
except Exception:  # pragma: no cover
    winreg = None


LEGACY_INNO_APP_ID = "{56ED8449-9773-4519-832C-0CD98D8D1F50}"
LEGACY_APP_NAME = "SurveyController"
_UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


@dataclass(frozen=True)
class LegacyMigrationResult:
    already_migrated: bool
    source_found: bool
    source_directory: str
    copied_files: int
    copied_directories: int
    marker_path: str


def _read_json_file(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    return payload if isinstance(payload, dict) else {}


def _require_winreg():
    if winreg is None:  # pragma: no cover - 非 Windows 环境不会走到这里
        raise RuntimeError("winreg is unavailable on this platform")
    return cast(Any, winreg)


def _read_reg_string(key, value_name: str) -> str:
    registry = _require_winreg()
    try:
        value, _ = registry.QueryValueEx(key, value_name)
    except FileNotFoundError:
        return ""
    except OSError:
        return ""
    return str(value or "").strip()


def _normalize_install_directory(path: str) -> str:
    candidate = os.path.abspath(str(path or "").strip().strip('"'))
    if not candidate:
        return ""
    if os.path.isfile(candidate):
        candidate = os.path.dirname(candidate)
    return candidate if os.path.isdir(candidate) else ""


def _candidate_matches(subkey_name: str, display_name: str) -> bool:
    normalized_guid = LEGACY_INNO_APP_ID.strip("{}").lower()
    normalized_key = str(subkey_name or "").strip().lower()
    normalized_display = str(display_name or "").strip().lower()
    return normalized_guid in normalized_key or normalized_display == LEGACY_APP_NAME.lower()


def _iter_uninstall_subkeys():
    if winreg is None:  # pragma: no cover - 非 Windows 环境直接跳过
        return
    registry = _require_winreg()

    access_variants = [registry.KEY_READ]
    if hasattr(registry, "KEY_WOW64_64KEY"):
        access_variants.append(registry.KEY_READ | registry.KEY_WOW64_64KEY)
    if hasattr(registry, "KEY_WOW64_32KEY"):
        access_variants.append(registry.KEY_READ | registry.KEY_WOW64_32KEY)

    for hive in (registry.HKEY_CURRENT_USER, registry.HKEY_LOCAL_MACHINE):
        for access in access_variants:
            try:
                with registry.OpenKey(hive, _UNINSTALL_ROOT, 0, access) as uninstall_key:
                    subkey_count = registry.QueryInfoKey(uninstall_key)[0]
                    for index in range(subkey_count):
                        try:
                            yield hive, registry.EnumKey(uninstall_key, index), access
                        except OSError:
                            continue
            except OSError:
                continue


def _find_legacy_install_directory() -> str:
    registry = _require_winreg()
    for hive, subkey_name, access in _iter_uninstall_subkeys() or ():
        try:
            with registry.OpenKey(hive, fr"{_UNINSTALL_ROOT}\{subkey_name}", 0, access) as app_key:
                display_name = _read_reg_string(app_key, "DisplayName")
                if not _candidate_matches(subkey_name, display_name):
                    continue

                for value_name in ("Inno Setup: App Path", "InstallLocation", "DisplayIcon"):
                    install_directory = _normalize_install_directory(_read_reg_string(app_key, value_name))
                    if install_directory:
                        return install_directory
        except OSError:
            continue
    return ""


def _copy_file_if_missing(source_path: str, target_path: str) -> int:
    if not os.path.isfile(source_path) or os.path.exists(target_path):
        return 0
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    shutil.copy2(source_path, target_path)
    return 1


def _copy_tree_if_missing(source_dir: str, target_dir: str) -> tuple[int, int]:
    if not os.path.isdir(source_dir):
        return 0, 0

    copied_files = 0
    copied_directories = 0
    for root, directories, files in os.walk(source_dir):
        relative_root = os.path.relpath(root, source_dir)
        target_root = target_dir if relative_root == "." else os.path.join(target_dir, relative_root)
        if not os.path.isdir(target_root):
            os.makedirs(target_root, exist_ok=True)
            copied_directories += 1

        for directory_name in directories:
            candidate_dir = os.path.join(target_root, directory_name)
            if not os.path.isdir(candidate_dir):
                os.makedirs(candidate_dir, exist_ok=True)
                copied_directories += 1

        for file_name in files:
            source_path = os.path.join(root, file_name)
            target_path = os.path.join(target_root, file_name)
            copied_files += _copy_file_if_missing(source_path, target_path)

    return copied_files, copied_directories


def _write_marker(
    marker_path: str,
    *,
    source_directory: str,
    copied_files: int,
    copied_directories: int,
) -> None:
    os.makedirs(os.path.dirname(marker_path), exist_ok=True)
    payload = {
        "source_directory": str(source_directory or ""),
        "source_found": bool(source_directory),
        "copied_files": int(copied_files),
        "copied_directories": int(copied_directories),
    }
    with open(marker_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def ensure_legacy_data_migrated() -> LegacyMigrationResult:
    """把旧版 Inno 安装目录下的数据复制到新的用户目录。"""
    ensure_user_data_directories()
    marker_path = get_legacy_migration_marker_path()

    if os.path.isfile(marker_path):
        payload = {}
        try:
            payload = _read_json_file(marker_path)
        except Exception:
            payload = {}
        return LegacyMigrationResult(
            already_migrated=True,
            source_found=bool(payload.get("source_found", False)),
            source_directory=str(payload.get("source_directory", "") or ""),
            copied_files=int(payload.get("copied_files", 0) or 0),
            copied_directories=int(payload.get("copied_directories", 0) or 0),
            marker_path=marker_path,
        )

    source_directory = _find_legacy_install_directory()
    copied_files = 0
    copied_directories = 0

    if source_directory:
        copied_files += _copy_file_if_missing(
            os.path.join(source_directory, "config.json"),
            get_default_runtime_config_path(),
        )

        files, directories = _copy_tree_if_missing(
            os.path.join(source_directory, "configs"),
            get_user_config_directory(),
        )
        copied_files += files
        copied_directories += directories

        files, directories = _copy_tree_if_missing(
            os.path.join(source_directory, "logs"),
            get_user_logs_directory(),
        )
        copied_files += files
        copied_directories += directories

    _write_marker(
        marker_path,
        source_directory=source_directory,
        copied_files=copied_files,
        copied_directories=copied_directories,
    )

    if source_directory:
        logging.info(
            "旧版数据迁移完成: source=%s, copied_files=%s, copied_directories=%s",
            source_directory,
            copied_files,
            copied_directories,
        )
    else:
        logging.info("未发现旧版 Inno 安装目录，跳过数据迁移")

    return LegacyMigrationResult(
        already_migrated=False,
        source_found=bool(source_directory),
        source_directory=source_directory,
        copied_files=copied_files,
        copied_directories=copied_directories,
        marker_path=marker_path,
    )


__all__ = [
    "LEGACY_APP_NAME",
    "LEGACY_INNO_APP_ID",
    "LegacyMigrationResult",
    "ensure_legacy_data_migrated",
]
