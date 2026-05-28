from __future__ import annotations

import software.system.secure_store as secure_store


class _FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, name: str):
        return self.values.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.values[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        self.values.pop((service, name), None)


class SecureStoreTests:
    def test_macos_keychain_read_write_delete(self, monkeypatch) -> None:
        fake = _FakeKeyring()
        monkeypatch.setattr(secure_store.sys, "platform", "darwin")
        monkeypatch.setattr(secure_store, "keyring", fake)

        assert secure_store.read_secret("device").status == "not_found"
        secure_store.set_secret("device", "abc")
        assert secure_store.read_secret("device").value == "abc"
        secure_store.delete_secret("device")
        assert secure_store.read_secret("device").status == "not_found"

    def test_macos_keychain_invalid_key(self, monkeypatch) -> None:
        monkeypatch.setattr(secure_store.sys, "platform", "darwin")
        assert secure_store.read_secret("").status == "invalid_key"
