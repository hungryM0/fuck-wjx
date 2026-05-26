from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import software.app.settings_store as settings_store


class SettingsStoreTests:
    def test_app_settings_builds_expected_qsettings_scope(self) -> None:
        with (
            patch.dict("os.environ", {"SURVEYCONTROLLER_QSETTINGS_FILE": ""}),
            patch("software.app.settings_store.QSettings", return_value="settings") as qsettings,
        ):
            result = settings_store.app_settings()

        assert result == "settings"
        qsettings.assert_called_once_with("SurveyController", "Settings")

    def test_app_settings_can_use_isolated_ini_file(self, tmp_path) -> None:
        settings_file = tmp_path / "isolated.ini"
        with patch.dict("os.environ", {"SURVEYCONTROLLER_QSETTINGS_FILE": str(settings_file)}):
            result = settings_store.app_settings()

        assert Path(result.fileName()) == settings_file
        assert result.format() == settings_store.QSettings.Format.IniFormat

    def test_get_bool_from_qsettings_accepts_common_true_values(self) -> None:
        for value in (True, "true", "TRUE", "1", "yes", "on", 1):
            assert settings_store.get_bool_from_qsettings(value) is True

    def test_get_bool_from_qsettings_rejects_common_false_and_unknown_values(self) -> None:
        for value in (False, "false", "0", "no", "off", "", 0):
            assert settings_store.get_bool_from_qsettings(value) is False

    def test_get_bool_from_qsettings_uses_default_for_missing_value(self) -> None:
        assert settings_store.get_bool_from_qsettings(None, default=True) is True
        assert settings_store.get_bool_from_qsettings(None, default=False) is False

    def test_get_int_from_qsettings_parses_values_and_clamps_range(self) -> None:
        assert settings_store.get_int_from_qsettings("7") == 7
        assert settings_store.get_int_from_qsettings(3.8) == 3
        assert settings_store.get_int_from_qsettings("-5", minimum=1) == 1
        assert settings_store.get_int_from_qsettings("99", maximum=10) == 10

    def test_get_int_from_qsettings_uses_default_for_empty_or_invalid_values(self) -> None:
        assert settings_store.get_int_from_qsettings(None, default=4) == 4
        assert settings_store.get_int_from_qsettings("", default=5) == 5
        assert settings_store.get_int_from_qsettings("bad", default=6) == 6
        assert settings_store.get_int_from_qsettings(object(), default=7) == 7

    def test_get_str_from_qsettings_uses_default_for_missing_or_blank_values(self) -> None:
        assert settings_store.get_str_from_qsettings(None, default="fallback") == "fallback"
        assert settings_store.get_str_from_qsettings("", default="fallback") == "fallback"
        assert settings_store.get_str_from_qsettings("   ", default="fallback") == "fallback"
        assert settings_store.get_str_from_qsettings(" D:/configs ") == "D:/configs"
