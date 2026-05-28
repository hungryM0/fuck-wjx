from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.modes import duration_control
from software.providers.common import SURVEY_PROVIDER_CREDAMO, SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_WJX


class _Driver:
    def __init__(self, *, url: str = "", div_text: str = "", page_text: str = "", action_visible: bool = False) -> None:
        self._url = url
        self.div_text = div_text
        self.page_text = page_text
        self.action_visible = action_visible
        self.scripts: list[str] = []

    async def current_url(self) -> str:
        return self._url

    async def find_element(self, by, value):
        if (by, value) == ("id", "divdsc") and self.div_text:
            async def _is_displayed() -> bool:
                return True

            async def _text() -> str:
                return self.div_text

            return SimpleNamespace(
                is_displayed=_is_displayed,
                text=_text,
            )
        raise RuntimeError("not found")

    async def execute_script(self, script: str):
        self.scripts.append(script)
        if "innerText" in script:
            return self.page_text
        return self.action_visible


class DurationControlTests:
    def test_has_configured_answer_duration_accepts_any_positive_bound(self) -> None:
        assert not duration_control.has_configured_answer_duration((0, 0))
        assert not duration_control.has_configured_answer_duration(("bad",))
        assert duration_control.has_configured_answer_duration((0, 5))
        assert duration_control.has_configured_answer_duration((3, 0))

    @pytest.mark.asyncio
    async def test_simulate_answer_duration_delay_skips_when_unconfigured(self, patch_attrs) -> None:
        slept: list[float] = []

        async def _fake_sleep_or_stop(_stop_signal, seconds: float) -> bool:
            slept.append(seconds)
            return False

        patch_attrs((duration_control, "sleep_or_stop", _fake_sleep_or_stop))

        assert not await duration_control.simulate_answer_duration_delay(answer_duration_range_seconds=(0, 0))
        assert slept == []

    @pytest.mark.asyncio
    async def test_simulate_answer_duration_delay_uses_wait_on_stop_signal(self, make_mock_event, patch_attrs) -> None:
        stop_signal = make_mock_event(wait_return=True, is_set=True)
        patch_attrs(
            (duration_control.random, "gauss", lambda center, _std: center),
        )

        interrupted = await duration_control.simulate_answer_duration_delay(
            stop_signal=stop_signal,
            answer_duration_range_seconds=(20, 80),
        )

        assert interrupted is True
        waited = stop_signal.wait.call_args.args[0]
        assert 20 <= waited <= 80

    @pytest.mark.asyncio
    async def test_simulate_answer_duration_delay_expands_equal_bounds_and_sleeps(self, patch_attrs) -> None:
        slept: list[float] = []

        async def _fake_sleep_or_stop(_stop_signal, seconds: float) -> bool:
            slept.append(seconds)
            return False

        patch_attrs(
            (duration_control.random, "gauss", lambda center, _std: center),
            (duration_control, "sleep_or_stop", _fake_sleep_or_stop),
        )

        assert not await duration_control.simulate_answer_duration_delay(answer_duration_range_seconds=(10, 10))
        assert slept == [10.0]

    def test_sample_answer_duration_seconds_keeps_qq_unclamped(self, patch_attrs) -> None:
        patch_attrs((duration_control.random, "gauss", lambda center, _std: center))
        waited = duration_control.sample_answer_duration_seconds(
            (250, 250),
            survey_provider=SURVEY_PROVIDER_QQ,
        )
        assert waited == 250.0

    def test_sample_answer_duration_seconds_keeps_wjx_unclamped(self, patch_attrs) -> None:
        patch_attrs((duration_control.random, "gauss", lambda center, _std: center))
        waited = duration_control.sample_answer_duration_seconds(
            (250, 250),
            survey_provider=SURVEY_PROVIDER_WJX,
        )
        assert waited == 250.0

    def test_sample_answer_duration_seconds_keeps_credamo_unclamped(self, patch_attrs) -> None:
        patch_attrs((duration_control.random, "gauss", lambda center, _std: center))
        waited = duration_control.sample_answer_duration_seconds(
            (250, 250),
            survey_provider=SURVEY_PROVIDER_CREDAMO,
        )
        assert waited == 250.0

    def test_sample_answer_duration_seconds_uses_default_with_jitter_when_unconfigured(self, patch_attrs) -> None:
        patch_attrs((duration_control.random, "gauss", lambda center, _std: center))
        waited = duration_control.sample_answer_duration_seconds(
            (0, 0),
            survey_provider=SURVEY_PROVIDER_WJX,
            default_unconfigured_seconds=90,
        )
        assert waited == 90.0

    @pytest.mark.asyncio
    async def test_completion_page_detects_complete_url_and_provider_signal(self, patch_attrs) -> None:
        assert await duration_control.is_survey_completion_page(_Driver(url="https://example.com/complete"))

        patch_attrs(
            (
                duration_control,
                "_COMPLETION_MARKERS",
                duration_control._COMPLETION_MARKERS,
            )
        )

    @pytest.mark.asyncio
    async def test_completion_page_detects_div_marker(self, patch_attrs) -> None:
        patch_attrs(
            (
                duration_control,
                "log_suppressed_exception",
                lambda *_args, **_kwargs: None,
            )
        )

        assert await duration_control.is_survey_completion_page(_Driver(div_text="问卷提交成功"))

    @pytest.mark.asyncio
    async def test_completion_page_uses_body_marker_only_when_no_action_button_visible(self) -> None:
        assert await duration_control.is_survey_completion_page(_Driver(page_text="感谢您的参与", action_visible=False))
        assert not await duration_control.is_survey_completion_page(_Driver(page_text="感谢您的参与", action_visible=True))
        assert not await duration_control.is_survey_completion_page(_Driver(page_text="继续填写"))

    @pytest.mark.asyncio
    async def test_completion_page_body_text_script_tolerates_empty_body(self) -> None:
        driver = _Driver()

        assert not await duration_control.is_survey_completion_page(driver)
        assert any("document.body && document.body.innerText" in script for script in driver.scripts)

    @pytest.mark.asyncio
    async def test_completion_page_retries_navigation_transient_error_without_warning(self, patch_attrs) -> None:
        class _NavigatingDriver(_Driver):
            def __init__(self) -> None:
                super().__init__(page_text="感谢您的参与", action_visible=False)
                self.calls = 0

            async def execute_script(self, script: str):
                self.calls += 1
                if "innerText" in script and self.calls == 1:
                    raise RuntimeError(
                        "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
                    )
                return await super().execute_script(script)

        warnings: list[str] = []

        async def _no_sleep(_stop_signal, _seconds: float) -> bool:
            return False

        patch_attrs(
            (duration_control, "sleep_or_stop", _no_sleep),
            (duration_control, "log_suppressed_exception", lambda context, *_args, **_kwargs: warnings.append(context)),
        )

        driver = _NavigatingDriver()

        assert await duration_control.is_survey_completion_page(driver)
        assert driver.calls >= 2
        assert warnings == []
