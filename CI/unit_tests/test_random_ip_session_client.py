from __future__ import annotations

import pytest

from software.network.proxy.session import client
from software.network.proxy.session.models import RandomIPAuthError, RandomIPSession


class _Response:
    def __init__(self, payload: object = None, *, status_code: int = 200, headers: dict[str, str] | None = None, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class RandomIPSessionClientTests:
    def test_preview_response_helpers_and_error_payload_cover_masking_and_headers(self) -> None:
        preview = client._preview_text(
            '{"access_token":"abc","password":"xyz","Authorization: Bearer secret"}\nnext',
            limit=120,
        )
        assert "***" in preview
        assert "\\n" in preview
        assert "next" in preview

        response = _Response(
            {"detail": "busy", "retry_after_seconds": "9"},
            status_code=429,
            headers={"content-type": "application/json", "Retry-After": "3", "CF-RAY": "ray-1"},
            text="body",
        )
        assert client._response_content_type(response) == "application/json"
        assert client._response_header_value(response, "CF-RAY") == "ray-1"
        assert client._response_body_preview(response) == "body"

        error = client._extract_error_payload(response)
        assert error.detail == "busy"
        assert error.status_code == 429
        assert error.retry_after_seconds == 9

        assert client._extract_error_payload(_Response(ValueError("bad json"), status_code=503)).detail == "http_503"

    def test_post_json_and_apost_json_wrap_network_errors(self, monkeypatch) -> None:
        monkeypatch.setattr(client, "_build_headers", lambda: {"X-Test": "1"})
        monkeypatch.setattr(client.http_client, "post", lambda url, **kwargs: (url, kwargs))

        async def _apost(url, **kwargs):
            return (url, kwargs)

        monkeypatch.setattr(client.http_client, "apost", _apost)
        monkeypatch.setattr("software.network.proxy.session.auth._endpoint_name", lambda url: f"endpoint:{url}")

        assert client._post_json("https://api.test/x", json_body={"a": 1}, timeout=12) == (
            "https://api.test/x",
            {"json": {"a": 1}, "headers": {"X-Test": "1"}, "timeout": 12},
        )

        import asyncio

        assert asyncio.run(client._apost_json("https://api.test/y", json_body={"b": 2}, timeout=13)) == (
            "https://api.test/y",
            {"json": {"b": 2}, "headers": {"X-Test": "1"}, "timeout": 13},
        )

        monkeypatch.setattr(client.http_client, "post", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("timeout")))
        with pytest.raises(RandomIPAuthError, match="network_error:RuntimeError: timeout"):
            client._post_json("https://api.test/fail", json_body={})

        class EmptyNetworkError(Exception):
            def __str__(self) -> str:
                return ""

        monkeypatch.setattr(client.http_client, "post", lambda *_args, **_kwargs: (_ for _ in ()).throw(EmptyNetworkError()))
        with pytest.raises(RandomIPAuthError, match="network_error:EmptyNetworkError"):
            client._post_json("https://api.test/empty-fail", json_body={})

    def test_parse_extract_payloads_cover_success_and_invalid_paths(self, monkeypatch) -> None:
        logged: list[str] = []
        monkeypatch.setattr(client, "_log_extract_proxy_issue", lambda message, **_kwargs: logged.append(message))
        monkeypatch.setattr(
            "software.network.proxy.session.auth._apply_quota_payload",
            lambda data, **_kwargs: RandomIPSession(
                user_id=9,
                remaining_quota=float(data.get("remaining_quota", 4)),
                total_quota=float(data.get("total_quota", 10)),
                used_quota=float(data.get("used_quota", 6)),
                quota_known=True,
            ),
        )

        item = client._parse_single_extract_payload(
            {
                "host": "1.1.1.1",
                "port": 8000,
                "account": "u",
                "password": "p",
                "expire_at": "2099",
                "quota_cost": "1.5",
                "remaining_quota": 8,
                "total_quota": 10,
                "used_quota": 2,
                "provider": "IDIOT",
            },
            request_body={"num": 1},
            attempt=1,
            response=_Response(),
        )
        assert item == {
            "host": "1.1.1.1",
            "port": 8000,
            "account": "u",
            "password": "p",
            "expire_at": "2099",
            "quota_cost": 1.5,
            "remaining_quota": 8.0,
            "total_quota": 10.0,
            "used_quota": 2.0,
            "provider": "idiot",
        }

        batch = client._parse_batch_extract_payload(
            {
                "items": [
                    {"host": "1.1.1.1", "port": 8000, "account": "u", "password": "p"},
                    {"host": "", "port": 0, "account": "", "password": ""},
                ],
                "returned_count": 9,
                "requested_count": 3,
                "quota_cost_total": "4.5",
                "provider": "default",
            },
            request_body={"num": 2},
            attempt=2,
            response=_Response(),
        )
        assert batch == {
            "items": [
                {
                    "host": "1.1.1.1",
                    "port": 8000,
                    "account": "u",
                    "password": "p",
                    "expire_at": "",
                }
            ],
            "requested_count": 3,
            "returned_count": 1,
            "remaining_quota": 4.0,
            "total_quota": 10.0,
            "used_quota": 6.0,
            "quota_cost_total": 4.5,
            "provider": "default",
        }

        with pytest.raises(RandomIPAuthError, match="invalid_response"):
            client._parse_single_extract_payload({}, request_body={}, attempt=1, response=_Response())
        with pytest.raises(RandomIPAuthError, match="invalid_response"):
            client._parse_batch_extract_payload({"items": []}, request_body={}, attempt=1, response=_Response())
        assert logged == [
            "随机IP提取响应缺少 host/port/account/password",
            "随机IP批量提取响应中无有效 IP",
        ]
