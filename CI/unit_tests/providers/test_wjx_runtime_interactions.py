from __future__ import annotations

from typing import Any

import pytest

from wjx.provider import runtime_interactions


class _Locator:
    def __init__(self, *, count: int = 1, click_failures: int = 0, fill_failures: int = 0) -> None:
        self._count = count
        self._click_failures = click_failures
        self._fill_failures = fill_failures
        self.click_calls = 0
        self.fill_calls: list[str] = []
        self.type_calls: list[str] = []
        self.scroll_calls = 0

    @property
    def first(self) -> "_Locator":
        return self

    async def count(self) -> int:
        return self._count

    async def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        del timeout
        self.scroll_calls += 1

    async def click(self, timeout: int = 0, force: bool = False) -> None:
        del timeout, force
        self.click_calls += 1
        if self.click_calls <= self._click_failures:
            raise RuntimeError("click failed")

    async def fill(self, value: str, timeout: int = 0) -> None:
        del timeout
        self.fill_calls.append(value)
        if len(self.fill_calls) <= self._fill_failures:
            raise RuntimeError("fill failed")

    async def type(self, value: str, delay: int = 0, timeout: int = 0) -> None:
        del delay, timeout
        self.type_calls.append(value)

    def nth(self, _index: int) -> "_Locator":
        return self


class _Page:
    def __init__(self) -> None:
        self.selector_counts: dict[str, int] = {}
        self.click_failures: dict[str, int] = {}
        self.fill_failures: dict[str, int] = {}
        self.waited_selectors: list[str] = []
        self.timeout_calls: list[int] = []
        self.locators: dict[str, _Locator] = {}

    async def wait_for_selector(self, selector: str, *, state: str, timeout: int) -> None:
        del state, timeout
        self.waited_selectors.append(selector)
        if self.selector_counts.get(selector, 1) <= 0:
            raise RuntimeError("missing")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.timeout_calls.append(timeout)

    def locator(self, selector: str) -> _Locator:
        locator = self.locators.get(selector)
        if locator is None:
            locator = _Locator(
                count=self.selector_counts.get(selector, 1),
                click_failures=self.click_failures.get(selector, 0),
                fill_failures=self.fill_failures.get(selector, 0),
            )
            self.locators[selector] = locator
        return locator


class _Driver:
    def __init__(self, page: _Page | None = None) -> None:
        self._page = page
        self.script_results: list[Any] = []
        self.script_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def page(self) -> Any:
        return self._page

    async def execute_script(self, script: str, *args: Any) -> Any:
        self.script_calls.append((script, args))
        if self.script_results:
            result = self.script_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return None


class WjxRuntimeInteractionsTests:
    @pytest.mark.asyncio
    async def test_page_wait_and_snapshot_helpers_cover_success_and_fallback_paths(self, monkeypatch) -> None:
        page = _Page()
        driver = _Driver(page)
        driver.script_results = [True, {"1": {"visible": True, "type": "3", "text": "Q1"}}, {"1": {"visible": True, "type": "3", "text": "Q1"}}]

        assert await runtime_interactions._page(driver) is page
        assert await runtime_interactions._wait_for_question_root(driver, 1)
        snapshot = await runtime_interactions._collect_visible_question_snapshot(driver)
        assert snapshot == {1: {"visible": True, "type": "3", "text": "Q1"}}
        waited = await runtime_interactions._wait_for_any_visible_questions(driver, timeout_ms=200, poll_ms=30)
        assert waited[1]["visible"] is True

        monkeypatch.setattr(runtime_interactions, "sleep_or_stop", lambda *_args, **_kwargs: None)
        assert not await runtime_interactions._wait_for_question_root(driver, 0)

    @pytest.mark.asyncio
    async def test_prepare_and_click_helpers_cover_locator_and_js_fallbacks(self, monkeypatch) -> None:
        page = _Page()
        driver = _Driver(page)
        async def _wait_for_question_root(*_args, **_kwargs):
            return True

        monkeypatch.setattr(runtime_interactions, "_wait_for_question_root", _wait_for_question_root)
        assert await runtime_interactions._prepare_question_interaction(driver, 3)

        driver.script_results = [True, True]
        assert await runtime_interactions._click_js(driver, "#a", verify_selector="#b")

        fallback_page = _Page()
        fallback_page.click_failures["#div2 .ui-controlgroup > div:nth-child(2)"] = 2
        fallback_driver = _Driver(fallback_page)
        fallback_driver.script_results = [True, True]
        assert await runtime_interactions._click_choice_input(fallback_driver, 2, "radio", 1)

        fallback_driver.script_results = [False]
        assert not await runtime_interactions._click_choice_input(fallback_driver, 0, "radio", 1)

    @pytest.mark.asyncio
    async def test_select_and_text_fill_helpers_cover_locator_and_script_paths(self) -> None:
        page = _Page()
        driver = _Driver(page)
        driver.script_results = [True, True, True]

        assert await runtime_interactions._set_select_value(driver, 3, "乙", option_index=1)

        page.selector_counts["#div4 input[id^='q4_']"] = 1
        assert await runtime_interactions._fill_text_input(driver, 4, "文本", blank_index=0)
        assert not await runtime_interactions._fill_text_input(driver, 0, "文本")

        assert await runtime_interactions._fill_choice_option_additional_text(driver, 5, 1, "补充", input_type="checkbox")
        assert not await runtime_interactions._fill_choice_option_additional_text(driver, 5, 1, "", input_type="checkbox")

    @pytest.mark.asyncio
    async def test_fill_text_input_falls_back_to_gapfill_contenteditable(self) -> None:
        page = _Page()
        for selector in (
            "#div11 input[id^='q11_']",
            "#div11 textarea[id^='q11_']",
            "#div11 input[type='text']",
            "#div11 textarea",
            "#div11 input",
            "#q11",
        ):
            page.selector_counts[selector] = 0
        driver = _Driver(page)
        driver.script_results = [True]

        assert await runtime_interactions._fill_text_input(driver, 11, "测试文本", blank_index=2)
        script, args = driver.script_calls[-1]
        assert ".textCont[contenteditable=\"true\"]" in script
        assert "q${questionNumber}_" in script
        assert args == (11, "测试文本", 2)

    @pytest.mark.asyncio
    async def test_slider_matrix_page_meta_and_submit_helpers_cover_main_paths(self, monkeypatch) -> None:
        page = _Page()
        driver = _Driver(page)
        monkeypatch.setattr(runtime_interactions, "sleep_or_stop", lambda *_args, **_kwargs: _async_result(None))
        driver.script_results = [
            True,
            True,
            2,
            1,
            "题目文本",
            ["选项1", "选项2"],
            3,
            2,
            True,
        ]

        assert await runtime_interactions._set_slider_value(driver, 6, 55.0)
        assert await runtime_interactions._click_matrix_cell(driver, 6, 0, 1)
        assert await runtime_interactions._resolve_current_page_number(driver) == 2
        assert await runtime_interactions._wait_for_page_number_change(driver, 3, timeout_ms=80, poll_ms=20)
        assert await runtime_interactions._question_text(driver, 6) == "题目文本"
        assert await runtime_interactions._question_option_texts(driver, 6) == ["选项1", "选项2"]
        assert await runtime_interactions._visible_matrix_row_count(driver, 6) == 3
        assert await runtime_interactions._visible_text_input_count(driver, 6) == 2
        page.selector_counts["#div6 li[serial='3']"] = 1
        page.selector_counts["#div6 li[serial='1']"] = 1
        page.selector_counts["#div6 li[serial='2']"] = 1
        driver.script_results.extend([0, 3])
        assert await runtime_interactions._click_reorder_sequence(driver, 6, [2, 0, 1])
        assert page.locators["#div6 li[serial='3']"].click_calls == 1
        assert page.locators["#div6 li[serial='1']"].click_calls == 1
        assert page.locators["#div6 li[serial='2']"].click_calls == 1

        submit_page = _Page()
        submit_page.selector_counts["#ctlNext"] = 1
        submit_driver = _Driver(submit_page)
        assert await runtime_interactions._click_submit_button(submit_driver)

        failing_submit_page = _Page()
        for selector in (
            "#ctlNext",
            "#submit_button",
            "#SubmitBtnGroup .submitbtn",
            ".submitbtn.mainBgColor",
            "#SM_BTN_1",
            "#divSubmit",
            ".btn-submit",
            "button[type='submit']",
            "a.button.mainBgColor",
        ):
            failing_submit_page.selector_counts[selector] = 0
        failing_submit_driver = _Driver(failing_submit_page)
        failing_submit_driver.script_results = [True]
        assert await runtime_interactions._click_submit_button(failing_submit_driver)

    @pytest.mark.asyncio
    async def test_confirm_location_picker_clicks_wjx_button_a(self) -> None:
        page = _Page()
        page.selector_counts[".layui-layer .button_a"] = 1
        driver = _Driver(page)

        assert await runtime_interactions._confirm_location_picker(driver)
        assert page.locators[".layui-layer .button_a"].click_calls == 1


def _async_result(value):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner
