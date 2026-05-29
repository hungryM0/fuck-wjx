from __future__ import annotations

import asyncio

import pytest

from software.network.proxy.session import auth
from software.network.proxy.session.models import RandomIPAuthError, RandomIPSession


@pytest.fixture(autouse=True)
def isolate_random_ip_auth_storage(monkeypatch: pytest.MonkeyPatch):
    settings = _Settings()
    secrets: dict[str, str] = {}

    def read_secret(key: str) -> _Secret:
        value = secrets.get(key, "")
        return _Secret(value, "ok" if value else "not_found")

    monkeypatch.setattr(auth, "_get_settings", lambda: settings)
    monkeypatch.setattr(auth, "read_secret", read_secret)
    monkeypatch.setattr(auth, "set_secret", lambda key, value: secrets.__setitem__(key, str(value or "")))
    auth._session_loaded = False
    auth._session = RandomIPSession()
    yield settings, secrets
    auth._session_loaded = False
    auth._session = RandomIPSession()


class _Settings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.removed: list[str] = []
        self.synced = 0

    def value(self, key: str):
        return self.values.get(key)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def remove(self, key: str) -> None:
        self.removed.append(key)
        self.values.pop(key, None)

    def sync(self) -> None:
        self.synced += 1


class _Secret:
    def __init__(self, value: str = "", status: str = "not_found") -> None:
        self.value = value
        self.status = status


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _reset_auth_state(session: RandomIPSession | None = None) -> None:
    auth._session_loaded = True
    auth._session = session or RandomIPSession(device_id="device-1")


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("bonus_already_claimed", "彩蛋已触发"),
        ("device_id_required", "设备标识缺失"),
        ("trial_already_claimed", "已领取过免费试用"),
        ("trial_rate_limited", "领取试用过于频繁"),
        ("session_persist_failed:settings.user_id", "没能安全保存"),
        ("device_banned", "当前设备已被封禁"),
        ("user_expired", "随机IP账号已过期"),
        ("invalid_user_id", "用户ID无效"),
        ("minute_not_supported_for_idiot", "限时福利代理源只支持"),
        ("insufficient_quota", "已达到上限"),
        ("network_error: timeout", "网络请求失败：timeout"),
        ("invalid_response:user_id_invalid", "无效的随机IP用户ID"),
        ("invalid_response:bad", "服务端返回格式异常"),
        ("http_503", "503"),
        ("unmapped_detail", "unmapped_detail"),
    ],
)
def test_format_random_ip_error_maps_backend_details(detail: str, expected: str) -> None:
    exc = RandomIPAuthError(detail, retry_after_seconds=9)
    assert expected in auth.format_random_ip_error(exc)


class RandomIPSessionAuthTests:
    def test_ensure_loaded_builds_stable_device_id_and_reads_quota_from_settings(self, patch_attrs) -> None:
        settings = _Settings()
        settings.values = {
            auth._settings_key("user_id"): "12",
            auth._settings_key("remaining_quota"): "3",
            auth._settings_key("total_quota"): "10",
            auth._settings_key("used_quota"): "7",
            auth._settings_key("quota_known"): True,
        }
        secrets: dict[str, str] = {}
        auth._session_loaded = False
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "read_secret", lambda _key: _Secret("", "not_found")),
            (auth, "set_secret", lambda key, value: secrets.setdefault(key, value)),
            (auth, "build_stable_device_id", lambda: "sc-v2-generated-device"),
        )

        auth._ensure_loaded()

        assert auth._session.device_id == "sc-v2-generated-device"
        assert auth._session.user_id == 12
        assert auth._session.remaining_quota == 3.0
        assert auth._session.total_quota == 10.0
        assert auth._session.used_quota == 7.0
        assert secrets[auth._DEVICE_SECRET_KEY] == "sc-v2-generated-device"

    def test_ensure_loaded_keeps_existing_secret_device_id(self, patch_attrs) -> None:
        settings = _Settings()
        settings.values = {
            auth._settings_key("device_id"): "settings-device",
            auth._settings_key("user_id"): "38852",
        }
        auth._session_loaded = False
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "read_secret", lambda _key: _Secret("existing-secret-device", "ok")),
            (auth, "build_stable_device_id", lambda: "sc-v2-should-not-be-used"),
        )

        auth._ensure_loaded()

        assert auth._session.device_id == "existing-secret-device"
        assert auth._session.user_id == 38852

    def test_ensure_loaded_keeps_existing_settings_device_id(self, patch_attrs) -> None:
        settings = _Settings()
        settings.values = {
            auth._settings_key("device_id"): "existing-settings-device",
            auth._settings_key("user_id"): "38852",
        }
        auth._session_loaded = False
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "read_secret", lambda _key: _Secret("", "not_found")),
            (auth, "build_stable_device_id", lambda: "sc-v2-should-not-be-used"),
        )

        auth._ensure_loaded()

        assert auth._session.device_id == "existing-settings-device"
        assert auth._session.user_id == 38852

    def test_set_session_persists_normalized_quota_and_snapshot(self, patch_attrs) -> None:
        settings = _Settings()
        secrets: dict[str, str] = {}
        _reset_auth_state(RandomIPSession(device_id="old-device"))
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "read_secret", lambda _key: _Secret("device-2", "ok")),
            (auth, "set_secret", lambda key, value: secrets.setdefault(key, value)),
        )

        session = auth._set_session(
            RandomIPSession(
                device_id="device-2",
                user_id=9,
                remaining_quota=2,
                total_quota=5,
                used_quota=3,
                quota_known=True,
            ),
            verify_auth_persistence=True,
        )

        assert session.user_id == 9
        assert settings.values[auth._settings_key("user_id")] == 9
        assert settings.values[auth._settings_key("remaining_quota")] == "2"
        assert secrets[auth._DEVICE_SECRET_KEY] == "device-2"
        snapshot = auth.get_session_snapshot()
        assert snapshot["authenticated"] is True
        assert snapshot["remaining_quota"] == 2.0

    def test_set_session_allows_unsupported_secure_store_when_settings_persisted(self, patch_attrs) -> None:
        settings = _Settings()
        _reset_auth_state(RandomIPSession(device_id="old-device"))
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "read_secret", lambda _key: _Secret("", "unsupported")),
            (auth, "set_secret", lambda *_args, **_kwargs: None),
        )

        session = auth._set_session(
            RandomIPSession(
                device_id="device-linux",
                user_id=9,
                remaining_quota=2,
                total_quota=5,
                used_quota=3,
                quota_known=True,
            ),
            verify_auth_persistence=True,
        )

        assert session.device_id == "device-linux"
        assert settings.values[auth._settings_key("device_id")] == "device-linux"
        assert settings.synced == 1

    def test_clear_session_preserves_device_id_and_removes_quota_fields(self, patch_attrs) -> None:
        settings = _Settings()
        _reset_auth_state(RandomIPSession(device_id="device-3", user_id=10, total_quota=1, used_quota=1, quota_known=True))
        patch_attrs((auth, "_get_settings", lambda: settings))

        auth.clear_session(reason="unit")

        assert auth._session == RandomIPSession(device_id="device-3")
        assert auth._settings_key("user_id") in settings.removed
        assert settings.synced == 1

    def test_parse_session_payload_requires_user_id_and_keeps_fallback_quota(self) -> None:
        with pytest.raises(RandomIPAuthError, match="user_id_missing"):
            auth._parse_session_payload({}, device_id="device-4")
        with pytest.raises(RandomIPAuthError, match="user_id_invalid"):
            auth._parse_session_payload({"user_id": 0}, device_id="device-4")

        session = auth._parse_session_payload(
            {"user_id": "15", "used_quota": 4},
            device_id="device-4",
            fallback_session=RandomIPSession(user_id=15, remaining_quota=8, total_quota=10, used_quota=2, quota_known=True),
        )

        assert session.user_id == 15
        assert session.remaining_quota == 6.0
        assert session.total_quota == 10.0
        assert session.used_quota == 4.0

    def test_extract_proxy_builds_request_body_and_parses_batch_payload(self, patch_attrs) -> None:
        _reset_auth_state(RandomIPSession(device_id="device-5", user_id=33, total_quota=10, quota_known=True))
        posted: list[dict[str, object]] = []

        async def fake_post(_url: str, *, json_body: dict[str, object], timeout: float = 10):
            posted.append({"body": json_body, "timeout": timeout})
            return _Response(
                {
                    "provider": "default",
                    "items": [
                        {
                            "host": "8.8.8.8",
                            "port": 8000,
                            "account": "u",
                            "password": "p",
                            "expire_at": "2099-01-01T00:00:00+00:00",
                        }
                    ],
                }
            )

        patch_attrs((auth, "_apost_json", fake_post))

        payload = asyncio.run(
            auth.extract_proxy_async(minute=3, pool="quality", area="110100", num=2, upstream="benefit")
        )

        assert posted == [
            {
                "body": {
                    "user_id": 33,
                    "minute": 3,
                    "pool": "quality",
                    "upstream": "benefit",
                    "num": 2,
                    "area": "110100",
                },
                "timeout": 12.0,
            }
        ]
        assert payload["items"][0]["host"] == "8.8.8.8"

    def test_extract_request_timeout_scales_for_batch_request(self) -> None:
        assert auth._extract_request_timeout_seconds(1) == 10.0
        assert auth._extract_request_timeout_seconds(16) == 40.0
        assert auth._extract_request_timeout_seconds(999) == 60.0

    def test_claim_bonus_updates_quota_snapshot(self, patch_attrs) -> None:
        _reset_auth_state(RandomIPSession(device_id="device-6", user_id=44, remaining_quota=1, total_quota=2, used_quota=1, quota_known=True))
        settings = _Settings()
        async def fake_bonus_post(*_args, **_kwargs):
            return _Response(
                {
                    "claimed": True,
                    "bonus_quota": 5,
                    "remaining_quota": 6,
                    "total_quota": 7,
                    "used_quota": 1,
                    "detail": "ok",
                }
            )
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "set_secret", lambda *_args, **_kwargs: None),
            (auth, "_apost_json", fake_bonus_post),
        )

        result = asyncio.run(auth.claim_easter_egg_bonus_async())

        assert result["claimed"] is True
        assert result["bonus_quota"] == 5.0
        assert result["remaining_quota"] == 6.0
        assert auth._session.total_quota == 7.0

    def test_redeem_card_updates_quota_snapshot(self, patch_attrs) -> None:
        _reset_auth_state(
            RandomIPSession(
                device_id="device-7",
                user_id=55,
                remaining_quota=1,
                total_quota=2,
                used_quota=1,
                quota_known=True,
            )
        )
        settings = _Settings()

        async def fake_redeem_post(_url: str, *, json_body: dict[str, object]):
            assert json_body == {"user_id": 55, "card_code": "abc123"}
            return _Response(
                {
                    "redeemed": True,
                    "card_quota": 400,
                    "remaining_quota": 401,
                    "total_quota": 402,
                    "used_quota": 1,
                    "detail": "redeem_card_redeemed",
                }
            )

        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "set_secret", lambda *_args, **_kwargs: None),
            (auth, "_apost_json", fake_redeem_post),
        )

        result = asyncio.run(auth.redeem_card_async("abc123"))

        assert result["redeemed"] is True
        assert result["card_quota"] == 400.0
        assert result["remaining_quota"] == 401.0
        assert auth._session.total_quota == 402.0
