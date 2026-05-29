from __future__ import annotations

import os
from unittest.mock import patch

import software.app.frozen_runtime as frozen_runtime


class FrozenRuntimeTests:
    def test_prepare_frozen_runtime_noops_outside_frozen_mode(self, monkeypatch) -> None:
        monkeypatch.setenv("PATH", "old-path")
        with patch.object(frozen_runtime.sys, "frozen", False, create=True):
            frozen_runtime.prepare_frozen_runtime()

        assert frozen_runtime.os.environ["PATH"] == "old-path"

    def test_prepare_frozen_runtime_registers_existing_dll_and_qt_paths(self, monkeypatch) -> None:
        monkeypatch.setenv("PATH", "old-path")
        added_dirs: list[str] = []
        loaded_dlls: list[str] = []
        existing = {
            "D:/App/lib/PySide6",
            "D:/App/lib/PySide6/Qt/libexec",
            "D:/App/lib/shiboken6",
            "D:/App/lib/PySide6/plugins",
        }

        def _isdir(path: str) -> bool:
            return path.replace("\\", "/") in existing

        with (
            patch.object(frozen_runtime.sys, "frozen", True, create=True),
            patch.object(frozen_runtime.sys, "executable", "D:/App/lib/SurveyController.exe", create=True),
            patch.object(frozen_runtime.os.path, "isdir", side_effect=_isdir),
            patch.object(frozen_runtime.os, "add_dll_directory", side_effect=lambda path: added_dirs.append(path.replace("\\", "/")), create=True),
        ):
            frozen_runtime.prepare_frozen_runtime()

        expected_prefix = os.pathsep.join(
            [
                "D:/App/lib/PySide6",
                "D:/App/lib/PySide6/Qt/libexec",
                "D:/App/lib/shiboken6",
                "",
            ]
        )
        assert frozen_runtime.os.environ["PATH"].replace("\\", "/").startswith(expected_prefix)
        assert frozen_runtime.os.environ["QT_PLUGIN_PATH"].replace("\\", "/") == "D:/App/lib/PySide6/plugins"
        assert added_dirs == [
            "D:/App/lib/PySide6",
            "D:/App/lib/PySide6/Qt/libexec",
            "D:/App/lib/shiboken6",
        ]
        assert loaded_dlls == []
