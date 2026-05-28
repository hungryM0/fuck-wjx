from __future__ import annotations

import os

import software.app.user_paths as user_paths


class UserPathsTests:
    def test_windows_user_paths_follow_expected_layout(self, monkeypatch) -> None:
        monkeypatch.setattr(user_paths.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", r"C:\Users\Test\AppData\Roaming")
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Test\AppData\Local")

        assert user_paths.get_user_config_root().replace("\\", "/") == "C:/Users/Test/AppData/Roaming/SurveyController"
        assert user_paths.get_user_config_directory().replace("\\", "/") == "C:/Users/Test/AppData/Roaming/SurveyController/configs"
        assert user_paths.get_user_local_data_root().replace("\\", "/") == "C:/Users/Test/AppData/Local/SurveyController"
        assert user_paths.get_user_logs_directory().replace("\\", "/") == "C:/Users/Test/AppData/Local/SurveyController/logs"
        assert user_paths.get_user_cache_directory().replace("\\", "/") == "C:/Users/Test/AppData/Local/SurveyController/cache"
        assert user_paths.get_user_updates_directory().replace("\\", "/") == "C:/Users/Test/AppData/Local/SurveyController/updates"
        assert user_paths.get_default_runtime_config_path().replace("\\", "/") == "C:/Users/Test/AppData/Roaming/SurveyController/config.json"

    def test_ensure_user_data_directories_creates_expected_tree(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(user_paths.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

        created = user_paths.ensure_user_data_directories()

        assert created
        for path in created:
            assert os.path.isdir(path)

    def test_user_config_directory_can_follow_qsettings_override(self, monkeypatch, tmp_path) -> None:
        override_dir = tmp_path / "custom-configs"

        class _FakeSettings:
            def value(self, key: str):
                if key == user_paths.CONFIG_DIRECTORY_SETTING_KEY:
                    return str(override_dir)
                return None

        monkeypatch.setattr(user_paths, "app_settings", lambda: _FakeSettings())

        assert user_paths.get_user_config_directory() == str(override_dir.resolve())

    def test_macos_user_paths_follow_library_layout(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(user_paths.sys, "platform", "darwin")
        monkeypatch.setattr(user_paths.os.path, "expanduser", lambda _path: str(tmp_path))

        assert user_paths.get_user_config_root().replace("\\", "/").endswith(
            "/Library/Application Support/SurveyController"
        )
        assert user_paths.get_user_logs_directory().replace("\\", "/").endswith(
            "/Library/Logs/SurveyController"
        )
        assert user_paths.get_user_cache_directory().replace("\\", "/").endswith(
            "/Library/Caches/SurveyController/cache"
        )
