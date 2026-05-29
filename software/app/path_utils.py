"""跨平台路径文本归一化。"""
from __future__ import annotations

import ntpath
import os
import re

_WINDOWS_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def is_windows_absolute_path(path: str) -> bool:
    """判断字符串是否是 Windows 绝对路径。"""
    normalized = str(path or "").strip()
    return bool(_WINDOWS_DRIVE_ABSOLUTE_RE.match(normalized)) or normalized.startswith(("\\\\", "//"))


def normalize_filesystem_path(path: str) -> str:
    """归一化路径，同时保留非 Windows 宿主上的 Windows 绝对路径。"""
    raw_path = str(path or "").strip()
    expanded = os.path.expanduser(raw_path) if raw_path.startswith("~") else raw_path
    if is_windows_absolute_path(expanded):
        return ntpath.normpath(expanded)
    return os.path.abspath(expanded)


__all__ = ["is_windows_absolute_path", "normalize_filesystem_path"]
