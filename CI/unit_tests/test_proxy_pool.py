from __future__ import annotations

import asyncio
import time

from software.core.task import ProxyLease
from software.network.proxy.pool import pool
from software.providers.common import SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_WJX


class _Response:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class ProxyPoolTests:
    def test_normalize_and_coerce_proxy_lease_variants(self) -> None:
        assert pool.normalize_proxy_address(None) is None
        assert pool.normalize_proxy_address(" 1.1.1.1:8000 ") == "http://1.1.1.1:8000"
        assert pool.normalize_proxy_address("https://1.1.1.1:8000") == "https://1.1.1.1:8000"

        lease = pool.coerce_proxy_lease("2.2.2.2:9000", source="custom")
        assert lease == ProxyLease(address="http://2.2.2.2:9000", source="custom")

        existing = ProxyLease(address="3.3.3.3:7000", expire_at="bad", expire_ts=123, poolable=False, source="old")
        assert pool.coerce_proxy_lease(existing) == ProxyLease(
            address="http://3.3.3.3:7000",
            expire_at="bad",
            expire_ts=123,
            poolable=False,
            source="old",
        )

        assert pool.coerce_proxy_lease({"host": "4.4.4.4", "port": 6000, "poolable": False, "source": "dict"}) == ProxyLease(
            address="http://4.4.4.4:6000",
            poolable=False,
            source="dict",
        )
        assert pool.coerce_proxy_lease({"address": ""}) is None
        assert pool.coerce_proxy_lease(object()) is None

    def test_mask_proxy_for_log_hides_credentials_for_official_sources(self, patch_attrs) -> None:
        patch_attrs((pool, "get_proxy_source", lambda: pool.PROXY_SOURCE_DEFAULT))

        assert pool.mask_proxy_for_log("http://user:pass@1.1.1.1:8000") == "1.1.1.1:8000"
        assert pool.mask_proxy_for_log("http://user:pass@[2001:db8::1]:8080") == "[2001:db8::1]:8080"
        assert pool.mask_proxy_for_log("") == ""

    def test_mask_proxy_for_log_hides_credentials_for_custom_sources_too(self, patch_attrs) -> None:
        patch_attrs((pool, "get_proxy_source", lambda: "custom"))

        assert pool.mask_proxy_for_log("http://user:pass@9.9.9.9:8080") == "9.9.9.9:8080"

    def test_build_default_proxy_leases_handles_missing_and_batch_payloads(self) -> None:
        assert pool._build_default_proxy_lease({}) is None

        missing_expire = pool._build_default_proxy_lease({"host": "1.1.1.1", "port": 8000})
        assert missing_expire is not None
        assert missing_expire.poolable is False

        leases = pool._build_default_proxy_leases_from_batch(
            {
                "items": [
                    {
                        "host": "2.2.2.2",
                        "port": 9000,
                        "account": "u",
                        "password": "p",
                        "expire_at": "2099-01-01T00:00:00+00:00",
                    },
                    {"host": "", "port": 0},
                    "bad",
                ]
            }
        )

        assert [lease.address for lease in leases] == ["http://u:p@2.2.2.2:9000"]
        assert leases[0].expire_ts > 0

    def test_proxy_ttl_helpers(self, patch_attrs) -> None:
        assert pool.get_proxy_required_ttl_seconds(None) == pool.PROXY_TTL_GRACE_SECONDS
        assert pool.get_proxy_required_ttl_seconds((10, 20)) == 20 + pool.PROXY_TTL_GRACE_SECONDS
        assert pool.get_proxy_required_ttl_seconds((10, 20), survey_provider=SURVEY_PROVIDER_QQ) == 60
        assert pool.get_proxy_required_ttl_seconds((250, 250), survey_provider=SURVEY_PROVIDER_QQ) == 60
        assert pool.get_proxy_required_ttl_seconds((250, 250), survey_provider=SURVEY_PROVIDER_WJX) == 0
        assert pool.proxy_lease_has_sufficient_ttl(None, required_ttl_seconds=1) is False
        assert pool.proxy_lease_has_sufficient_ttl(ProxyLease(address="x"), required_ttl_seconds=99999) is True

        patch_attrs((pool.time, "time", lambda: 100.0))
        assert pool.proxy_lease_has_sufficient_ttl(ProxyLease(address="x", expire_ts=200.0), required_ttl_seconds=99)
        assert not pool.proxy_lease_has_sufficient_ttl(ProxyLease(address="x", expire_ts=120.0), required_ttl_seconds=30)

    def test_proxy_responsive_skips_official_source_and_checks_custom_source(self, patch_attrs) -> None:
        log_messages: list[str] = []
        patch_attrs(
            (pool, "get_proxy_source", lambda: pool.PROXY_SOURCE_DEFAULT),
            (pool, "is_official_proxy_source", lambda _source: True),
            (pool.logging, "info", lambda message, *args, **_kwargs: log_messages.append(str(message % args if args else message))),
        )
        assert pool.is_proxy_responsive("1.1.1.1:8000", skip_for_default=True)
        assert log_messages == []

        calls: list[dict[str, object]] = []

        def fake_get(_url: str, **kwargs):
            calls.append(kwargs)
            return _Response(200)

        patch_attrs(
            (pool, "get_proxy_source", lambda: "custom"),
            (pool, "is_official_proxy_source", lambda _source: False),
            (pool.http_client, "get", fake_get),
            (pool.time, "perf_counter", iter([1.0, 1.2]).__next__),
        )

        assert pool.is_proxy_responsive("5.5.5.5:9000", skip_for_default=True)
        assert calls[0]["proxies"] == {"http": "http://5.5.5.5:9000", "https": "http://5.5.5.5:9000"}

    def test_proxy_responsive_rejects_empty_error_and_http_error(self, patch_attrs) -> None:
        patch_attrs(
            (pool, "get_proxy_source", lambda: "custom"),
            (pool, "is_official_proxy_source", lambda _source: False),
        )
        assert not pool.is_proxy_responsive("", skip_for_default=False)

        patch_attrs((pool.http_client, "get", lambda *_args, **_kwargs: _Response(500)))
        assert not pool.is_proxy_responsive("1.1.1.1:8000", skip_for_default=False)

        patch_attrs((pool.http_client, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("down"))))
        assert not pool.is_proxy_responsive("1.1.1.1:8000", skip_for_default=False)

    def test_proxy_responsive_async_uses_async_http_client(self, patch_attrs) -> None:
        patch_attrs(
            (pool, "get_proxy_source", lambda: "custom"),
            (pool, "is_official_proxy_source", lambda _source: False),
        )
        calls: list[dict[str, object]] = []

        async def fake_aget(_url: str, **kwargs):
            calls.append(kwargs)
            return _Response(204)

        patch_attrs(
            (pool.http_client, "aget", fake_aget),
            (pool.time, "perf_counter", iter([1.0, 1.2]).__next__),
        )

        result = asyncio.run(pool.is_proxy_responsive_async("1.1.1.1:8000", skip_for_default=False))

        assert result is True
        assert calls[0]["proxies"] == {"http": "http://1.1.1.1:8000", "https": "http://1.1.1.1:8000"}

    def test_parse_expire_at_handles_naive_aware_and_bad_values(self) -> None:
        assert pool._parse_expire_at_to_ts("") == 0.0
        assert pool._parse_expire_at_to_ts("bad") == 0.0
        assert pool._parse_expire_at_to_ts("2099-01-01T00:00:00+00:00") > time.time()
