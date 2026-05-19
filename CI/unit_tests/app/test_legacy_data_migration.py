from __future__ import annotations

import json
import os
from types import SimpleNamespace

import software.app.legacy_data_migration as migration


class LegacyDataMigrationTests:
    def _patch_user_dirs(self, monkeypatch, tmp_path) -> dict[str, str]:
        config_root = tmp_path / "roaming" / "SurveyController"
        local_root = tmp_path / "local" / "SurveyController"
        monkeypatch.setattr(migration, "get_default_runtime_config_path", lambda: str(config_root / "config.json"))
        monkeypatch.setattr(migration, "get_user_config_directory", lambda: str(config_root / "configs"))
        monkeypatch.setattr(migration, "get_user_logs_directory", lambda: str(local_root / "logs"))
        monkeypatch.setattr(migration, "get_legacy_migration_marker_path", lambda: str(local_root / "migration" / "legacy_inno_v1.json"))
        monkeypatch.setattr(migration, "ensure_user_data_directories", lambda: ())
        return {
            "config_root": str(config_root),
            "local_root": str(local_root),
        }

    def test_migration_copies_legacy_files_without_overwrite(self, monkeypatch, tmp_path) -> None:
        self._patch_user_dirs(monkeypatch, tmp_path)
        legacy_dir = tmp_path / "legacy"
        (legacy_dir / "configs" / "nested").mkdir(parents=True)
        (legacy_dir / "logs").mkdir(parents=True)
        (legacy_dir / "config.json").write_text('{"old": true}', encoding="utf-8")
        (legacy_dir / "configs" / "default.json").write_text("legacy-config", encoding="utf-8")
        (legacy_dir / "configs" / "nested" / "keep.json").write_text("nested", encoding="utf-8")
        (legacy_dir / "logs" / "session.log").write_text("legacy-log", encoding="utf-8")
        monkeypatch.setattr(migration, "_find_legacy_install_directory", lambda: str(legacy_dir))

        result = migration.ensure_legacy_data_migrated()

        assert result.source_found
        assert result.copied_files >= 4
        assert os.path.exists(migration.get_default_runtime_config_path())
        assert os.path.exists(os.path.join(migration.get_user_config_directory(), "default.json"))
        assert os.path.exists(os.path.join(migration.get_user_logs_directory(), "session.log"))
        with open(migration.get_legacy_migration_marker_path(), "r", encoding="utf-8") as file:
            marker = json.load(file)
        assert marker["source_found"] is True

    def test_migration_skips_missing_source_and_marks_once(self, monkeypatch, tmp_path) -> None:
        self._patch_user_dirs(monkeypatch, tmp_path)
        monkeypatch.setattr(migration, "_find_legacy_install_directory", lambda: "")

        first = migration.ensure_legacy_data_migrated()
        second = migration.ensure_legacy_data_migrated()

        assert not first.already_migrated
        assert not first.source_found
        assert second.already_migrated
        assert os.path.exists(migration.get_legacy_migration_marker_path())

    def test_existing_target_files_are_not_overwritten(self, monkeypatch, tmp_path) -> None:
        self._patch_user_dirs(monkeypatch, tmp_path)
        os.makedirs(os.path.dirname(migration.get_default_runtime_config_path()), exist_ok=True)
        os.makedirs(migration.get_user_config_directory(), exist_ok=True)
        os.makedirs(migration.get_user_logs_directory(), exist_ok=True)
        with open(migration.get_default_runtime_config_path(), "w", encoding="utf-8") as file:
            file.write("current")
        with open(os.path.join(migration.get_user_config_directory(), "default.json"), "w", encoding="utf-8") as file:
            file.write("current-config")

        legacy_dir = tmp_path / "legacy"
        (legacy_dir / "configs").mkdir(parents=True)
        (legacy_dir / "logs").mkdir(parents=True)
        (legacy_dir / "config.json").write_text("legacy", encoding="utf-8")
        (legacy_dir / "configs" / "default.json").write_text("legacy-config", encoding="utf-8")
        monkeypatch.setattr(migration, "_find_legacy_install_directory", lambda: str(legacy_dir))

        migration.ensure_legacy_data_migrated()

        with open(migration.get_default_runtime_config_path(), "r", encoding="utf-8") as file:
            assert file.read() == "current"
        with open(os.path.join(migration.get_user_config_directory(), "default.json"), "r", encoding="utf-8") as file:
            assert file.read() == "current-config"

    def test_helpers_normalize_candidates_and_copy_nested_tree(self, tmp_path) -> None:
        install_exe = tmp_path / "legacy" / "SurveyController.exe"
        install_exe.parent.mkdir()
        install_exe.write_text("exe", encoding="utf-8")

        assert migration._normalize_install_directory(f'"{install_exe}"') == str(install_exe.parent)
        assert migration._normalize_install_directory(str(tmp_path / "missing")) == ""
        assert migration._candidate_matches("{56ED8449-9773-4519-832C-0CD98D8D1F50}_is1", "") is True
        assert migration._candidate_matches("other", "SurveyController") is True
        assert migration._candidate_matches("other", "Other App") is False

        source = tmp_path / "source"
        target = tmp_path / "target"
        (source / "a" / "b").mkdir(parents=True)
        (source / "root.txt").write_text("root", encoding="utf-8")
        (source / "a" / "b" / "nested.txt").write_text("nested", encoding="utf-8")

        copied_files, copied_dirs = migration._copy_tree_if_missing(str(source), str(target))

        assert copied_files == 2
        assert copied_dirs >= 2
        assert (target / "a" / "b" / "nested.txt").read_text(encoding="utf-8") == "nested"
        assert migration._copy_file_if_missing(str(source / "root.txt"), str(target / "root.txt")) == 0
        assert migration._copy_tree_if_missing(str(tmp_path / "none"), str(target)) == (0, 0)

    def test_existing_marker_with_invalid_json_returns_already_migrated_defaults(self, monkeypatch, tmp_path) -> None:
        self._patch_user_dirs(monkeypatch, tmp_path)
        marker = migration.get_legacy_migration_marker_path()
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as file:
            file.write("[not a dict]")

        result = migration.ensure_legacy_data_migrated()

        assert result.already_migrated is True
        assert result.source_found is False
        assert result.copied_files == 0

    def test_find_legacy_install_directory_reads_registry_variants(self, monkeypatch, tmp_path) -> None:
        install_dir = tmp_path / "installed"
        install_dir.mkdir()
        calls = {"opened_app_key": False}

        class _Key:
            def __init__(self, name: str) -> None:
                self.name = name

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class _FakeWinreg:
            HKEY_CURRENT_USER = "HKCU"
            HKEY_LOCAL_MACHINE = "HKLM"
            KEY_READ = 1
            KEY_WOW64_64KEY = 2
            KEY_WOW64_32KEY = 4

            @staticmethod
            def OpenKey(_hive, path, *_args):
                if str(path).endswith("Uninstall"):
                    return _Key("uninstall")
                calls["opened_app_key"] = True
                return _Key("app")

            @staticmethod
            def QueryInfoKey(_key):
                return (2, 0, 0)

            @staticmethod
            def EnumKey(_key, index):
                if index == 0:
                    return "OtherApp"
                return "{56ED8449-9773-4519-832C-0CD98D8D1F50}_is1"

            @staticmethod
            def QueryValueEx(key, value_name):
                if key.name != "app":
                    raise FileNotFoundError
                values = {
                    "DisplayName": "SurveyController",
                    "Inno Setup: App Path": str(install_dir),
                }
                if value_name not in values:
                    raise FileNotFoundError
                return values[value_name], None

        monkeypatch.setattr(migration, "winreg", _FakeWinreg)

        assert migration._find_legacy_install_directory() == str(install_dir)
        assert calls["opened_app_key"] is True

    def test_read_reg_string_handles_missing_and_os_errors(self, monkeypatch) -> None:
        class _FakeWinreg:
            @staticmethod
            def QueryValueEx(_key, value_name):
                if value_name == "missing":
                    raise FileNotFoundError
                if value_name == "bad":
                    raise OSError
                return " value ", None

        monkeypatch.setattr(migration, "winreg", _FakeWinreg)

        assert migration._read_reg_string(SimpleNamespace(), "ok") == "value"
        assert migration._read_reg_string(SimpleNamespace(), "missing") == ""
        assert migration._read_reg_string(SimpleNamespace(), "bad") == ""
