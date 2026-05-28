from __future__ import annotations

import software.system.registry_manager as registry_manager


class _FakeSettings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.synced = 0

    def value(self, key: str):
        return self.values.get(key)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def sync(self) -> None:
        self.synced += 1


class RegistryManagerTests:
    def test_is_confetti_played_returns_false_by_default(self, monkeypatch) -> None:
        monkeypatch.setattr(registry_manager, "app_settings", lambda: _FakeSettings())
        assert registry_manager.RegistryManager.is_confetti_played() is False

    def test_is_confetti_played_reads_qsettings_value(self, monkeypatch) -> None:
        settings = _FakeSettings()
        settings.values[registry_manager.RegistryManager._settings_key()] = True
        monkeypatch.setattr(registry_manager, "app_settings", lambda: settings)
        assert registry_manager.RegistryManager.is_confetti_played() is True

    def test_set_confetti_played_writes_qsettings_value(self, monkeypatch) -> None:
        settings = _FakeSettings()
        monkeypatch.setattr(registry_manager, "app_settings", lambda: settings)
        assert registry_manager.RegistryManager.set_confetti_played(True) is True
        assert settings.values[registry_manager.RegistryManager._settings_key()] is True
        assert settings.synced == 1
