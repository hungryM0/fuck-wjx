from __future__ import annotations

import os
import sys


def get_project_root() -> str:
    """Return the repository root directory when running from source."""
    return os.path.dirname(os.path.abspath(os.path.dirname(__file__)))


def get_runtime_directory() -> str:
    """Return the directory used to read/write runtime files (config, logs, etc.)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return get_project_root()


def get_resource_path(relative_path: str) -> str:
    """Resolve a resource path for both source runs and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_path = get_project_root()
    return os.path.join(base_path, relative_path)

