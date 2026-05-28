from __future__ import annotations

import software.system.device_fingerprint as device_fingerprint


class _Secret:
    def __init__(self, value: str = "", status: str = "not_found") -> None:
        self.value = value
        self.status = status


class DeviceFingerprintTests:
    def test_build_stable_device_id_reads_existing_secret(self, monkeypatch) -> None:
        monkeypatch.setattr(device_fingerprint, "read_secret", lambda _key: _Secret("sc-v2-existing", "ok"))
        assert device_fingerprint.build_stable_device_id() == "sc-v2-existing"

    def test_build_stable_device_id_generates_and_persists_uuid(self, monkeypatch) -> None:
        stored = {"value": ""}

        def _read(_key: str) -> _Secret:
            return _Secret(stored["value"], "ok" if stored["value"] else "not_found")

        def _set(_key: str, value: str) -> None:
            stored["value"] = value

        monkeypatch.setattr(device_fingerprint, "read_secret", _read)
        monkeypatch.setattr(device_fingerprint, "set_secret", _set)
        monkeypatch.setattr(
            device_fingerprint.uuid,
            "uuid4",
            lambda: type("UUID", (), {"hex": "1234567890abcdef1234567890abcdef"})(),
        )

        first = device_fingerprint.build_stable_device_id()
        second = device_fingerprint.build_stable_device_id()

        assert first == "sc-v2-1234567890abcdef1234567890abcdef"
        assert second == first
