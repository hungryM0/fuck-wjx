from __future__ import annotations

import os
from pathlib import Path

import software.app.user_paths as user_paths


class _FakeSettings:
    def __init__(self, configured_path: str = "") -> None:
        self._configured_path = configured_path

    def value(self, key: str):
        if key == user_paths.CONFIG_DIRECTORY_SETTING_KEY:
            return self._configured_path
        return None


class UserPathsTests:
    def test_standard_roots_strip_qt_app_suffix(self, monkeypatch, tmp_path) -> None:
        config_root = tmp_path / "config-root" / "SurveyController" / "Settings"
        local_root = tmp_path / "local-root" / "SurveyController" / "Settings"

        monkeypatch.setattr(user_paths, "configure_qt_application_metadata", lambda: None)
        monkeypatch.setattr(user_paths.QCoreApplication, "applicationName", lambda: "Settings")
        monkeypatch.setattr(user_paths.QCoreApplication, "organizationName", lambda: "SurveyController")

        def fake_writable_location(location) -> str:
            if location == user_paths.QStandardPaths.StandardLocation.AppDataLocation:
                return str(config_root)
            if location == user_paths.QStandardPaths.StandardLocation.AppLocalDataLocation:
                return str(local_root)
            raise AssertionError(f"unexpected location: {location}")

        monkeypatch.setattr(user_paths.QStandardPaths, "writableLocation", fake_writable_location)

        assert user_paths.get_roaming_app_data_root() == str(config_root.parent.parent)
        assert user_paths.get_local_app_data_root() == str(local_root.parent.parent)
        assert user_paths.get_user_config_root() == str(config_root.parent)
        assert user_paths.get_user_local_data_root() == str(local_root.parent)
        assert user_paths.get_user_logs_directory() == str(local_root.parent / "logs")
        assert user_paths.get_user_cache_directory() == str(local_root.parent / "cache")
        assert user_paths.get_user_updates_directory() == str(local_root.parent / "updates")
        assert user_paths.get_default_runtime_config_path() == str(config_root.parent / "config.json")

    def test_standard_roots_fall_back_to_home_when_qt_returns_empty(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(user_paths, "configure_qt_application_metadata", lambda: None)
        monkeypatch.setattr(user_paths.QStandardPaths, "writableLocation", lambda _location: "")
        monkeypatch.setattr(user_paths.os.path, "expanduser", lambda _path: str(tmp_path))

        assert user_paths.get_roaming_app_data_root() == str(tmp_path / "AppData" / "Roaming")
        assert user_paths.get_local_app_data_root() == str(tmp_path / "AppData" / "Local")

    def test_ensure_user_data_directories_creates_expected_tree(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(user_paths, "get_user_config_root", lambda: str(tmp_path / "config-root"))
        monkeypatch.setattr(user_paths, "get_user_config_directory", lambda: str(tmp_path / "config-root" / "configs"))
        monkeypatch.setattr(user_paths, "get_user_local_data_root", lambda: str(tmp_path / "local-root"))
        monkeypatch.setattr(user_paths, "get_user_logs_directory", lambda: str(tmp_path / "local-root" / "logs"))
        monkeypatch.setattr(user_paths, "get_user_cache_directory", lambda: str(tmp_path / "local-root" / "cache"))
        monkeypatch.setattr(user_paths, "get_user_updates_directory", lambda: str(tmp_path / "local-root" / "updates"))

        created = user_paths.ensure_user_data_directories()

        assert created
        for path in created:
            assert os.path.isdir(path)

    def test_user_config_directory_can_follow_qsettings_override(self, tmp_path) -> None:
        override_dir = tmp_path / "custom-configs"

        assert user_paths.resolve_user_config_directory(_FakeSettings(str(override_dir))) == str(override_dir.resolve())

    def test_default_user_config_directory_uses_standard_config_root(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(user_paths, "get_user_config_root", lambda: str(tmp_path / "SurveyController"))

        assert user_paths.get_default_user_config_directory() == str(tmp_path / "SurveyController" / "configs")
