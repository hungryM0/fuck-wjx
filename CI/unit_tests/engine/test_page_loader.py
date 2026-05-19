from __future__ import annotations

from types import SimpleNamespace

import pytest

import software.core.engine.page_loader as page_loader
from software.core.engine.page_load_probe import (
    PAGE_LOAD_PROBE_ANSWERABLE,
    PAGE_LOAD_PROBE_BUSINESS_PAGE,
    PAGE_LOAD_PROBE_PROXY_UNUSABLE,
    PageLoadProbeResult,
)
from software.network.browser import ProxyConnectionError


class _AsyncDriver:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.calls: list[tuple[str, int, str]] = []

    async def get(self, url: str, *, timeout: int, wait_until: str) -> None:
        self.calls.append((url, timeout, wait_until))
        if self.failures:
            raise self.failures.pop(0)


def _config(**updates) -> SimpleNamespace:
    cfg = SimpleNamespace(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
        random_proxy_ip_enabled=False,
    )
    for key, value in updates.items():
        setattr(cfg, key, value)
    return cfg


class PageLoaderTests:
    def test_small_helpers_cover_proxy_markers_attempts_and_phase_errors(self) -> None:
        assert page_loader.exception_summary(RuntimeError("")) == "RuntimeError"
        assert page_loader.looks_like_proxy_page_load_failure(RuntimeError("ERR_PROXY_CONNECTION_FAILED"))
        assert not page_loader.looks_like_proxy_page_load_failure(RuntimeError("normal timeout"))
        assert page_loader.random_proxy_probe_succeeded(PAGE_LOAD_PROBE_ANSWERABLE)
        assert page_loader.random_proxy_probe_succeeded(PAGE_LOAD_PROBE_BUSINESS_PAGE)
        assert not page_loader.random_proxy_probe_succeeded(PAGE_LOAD_PROBE_PROXY_UNUSABLE)

        wjx_attempts = page_loader.build_page_load_attempts(_config(survey_provider="wjx"))
        credamo_attempts = page_loader.build_page_load_attempts(_config(survey_provider="credamo"))
        assert wjx_attempts[0] == (page_loader.DEFAULT_PAGE_LOAD_TIMEOUT_MS, "domcontentloaded")
        assert credamo_attempts[0] == (page_loader.CREDAMO_PAGE_LOAD_TIMEOUT_MS, "domcontentloaded")

        calls: list[str] = []
        page_loader.notify_page_load_phase(calls.append, "加载")
        page_loader.notify_page_load_phase(lambda _text: (_ for _ in ()).throw(RuntimeError("boom")), "失败")
        page_loader.notify_page_load_phase(None, "忽略")
        assert calls == ["加载"]

    def test_random_proxy_grace_decision_handles_details_and_last_exception(self) -> None:
        loading = PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="page_still_loading")
        hard_error = PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="proxy_error_page")

        assert page_loader.should_keep_waiting_random_proxy_page(loading)
        assert not page_loader.should_keep_waiting_random_proxy_page(hard_error)

    @pytest.mark.asyncio
    async def test_load_survey_page_succeeds_first_try_and_retries_normal_failure(self, monkeypatch) -> None:
        sleeps: list[float] = []

        async def _sleep_or_stop(_stop, seconds: float) -> bool:
            sleeps.append(seconds)
            return False

        monkeypatch.setattr(page_loader, "sleep_or_stop", _sleep_or_stop)
        driver = _AsyncDriver()

        await page_loader.load_survey_page(driver, _config())

        assert driver.calls == [
            ("https://www.wjx.cn/vm/demo.aspx", page_loader.DEFAULT_PAGE_LOAD_TIMEOUT_MS, "domcontentloaded")
        ]

        retry_driver = _AsyncDriver([RuntimeError("first fail")])
        await page_loader.load_survey_page(retry_driver, _config())

        assert len(retry_driver.calls) == 2
        assert sleeps == [page_loader.PAGE_LOAD_RETRY_DELAYS_SECONDS[0]]

    @pytest.mark.asyncio
    async def test_load_survey_page_raises_proxy_error_when_random_proxy_navigation_fails(self, monkeypatch) -> None:
        async def _sleep_or_stop(_stop, _seconds: float) -> bool:
            return False

        monkeypatch.setattr(page_loader, "sleep_or_stop", _sleep_or_stop)
        driver = _AsyncDriver([RuntimeError("ERR_PROXY_CONNECTION_FAILED"), RuntimeError("ERR_PROXY_CONNECTION_FAILED")])

        with pytest.raises(ProxyConnectionError, match="ERR_PROXY_CONNECTION_FAILED"):
            await page_loader.load_survey_page(driver, _config(random_proxy_ip_enabled=True, survey_provider="credamo"))

    @pytest.mark.asyncio
    async def test_random_proxy_fast_probe_success_returns_without_reload(self) -> None:
        driver = _AsyncDriver()
        probe_calls: list[dict] = []

        async def _probe(_driver, **kwargs):
            probe_calls.append(kwargs)
            return PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail="ready")

        await page_loader.load_survey_page_with_random_proxy(driver, _config(), probe_waiter=_probe)

        assert len(driver.calls) == 1
        assert driver.calls[0][2] == "commit"
        assert probe_calls[0]["timeout_ms"] == page_loader.RANDOM_PROXY_FAST_PROBE_TIMEOUT_MS

    @pytest.mark.asyncio
    async def test_random_proxy_loading_grace_succeeds_before_reload(self) -> None:
        driver = _AsyncDriver()
        results = iter(
            [
                PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="blank_page", retryable=True),
                PageLoadProbeResult(PAGE_LOAD_PROBE_BUSINESS_PAGE, detail="quota"),
            ]
        )

        async def _probe(_driver, **_kwargs):
            return next(results)

        await page_loader.load_survey_page_with_random_proxy(driver, _config(), probe_waiter=_probe)

        assert len(driver.calls) == 1

    @pytest.mark.asyncio
    async def test_random_proxy_navigation_failure_marks_proxy_error_without_reload(self) -> None:
        driver = _AsyncDriver([RuntimeError("commit failed")])

        with pytest.raises(ProxyConnectionError, match="commit failed"):
            await page_loader.load_survey_page_with_random_proxy(driver, _config())

        assert len(driver.calls) == 1

    @pytest.mark.asyncio
    async def test_random_proxy_slow_page_keeps_waiting_without_reload(self) -> None:
        driver = _AsyncDriver()
        probe_calls: list[dict] = []
        results = iter(
            [
                PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="blank_page", retryable=True),
                PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="page_still_loading", retryable=True),
                PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail="ready"),
            ]
        )

        async def _probe(_driver, **kwargs):
            probe_calls.append(kwargs)
            return next(results)

        await page_loader.load_survey_page_with_random_proxy(driver, _config(), probe_waiter=_probe)

        assert len(driver.calls) == 1
        assert probe_calls[-1]["timeout_ms"] == page_loader.RANDOM_PROXY_SLOW_PROBE_TIMEOUT_MS

    @pytest.mark.asyncio
    async def test_load_survey_page_delegates_random_proxy_for_wjx(self) -> None:
        calls: list[object] = []

        async def _probe(_driver, **_kwargs):
            calls.append(_kwargs)
            return PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail="ready")

        driver = _AsyncDriver()
        await page_loader.load_survey_page(
            driver,
            _config(random_proxy_ip_enabled=True, survey_provider="wjx"),
            phase_updater=lambda text: calls.append(SimpleNamespace(text=text)),
            probe_waiter=_probe,
        )

        assert driver.calls[0][2] == "commit"
        assert any(getattr(item, "text", "") == "探测页面" for item in calls)
