from __future__ import annotations

from typing import Any

import pytest

from tencent.provider import runtime_interactions


class _Candidate:
    def __init__(self, text: str, *, visible: bool = True, click_failures: int = 0) -> None:
        self._text = text
        self._visible = visible
        self._click_failures = click_failures
        self.click_calls = 0

    async def is_visible(self) -> bool:
        return self._visible

    async def inner_text(self) -> str:
        return self._text

    async def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        del timeout

    async def click(self, timeout: int = 0, force: bool = False) -> None:
        del timeout, force
        self.click_calls += 1
        if self.click_calls <= self._click_failures:
            raise RuntimeError("click failed")


class _Locator:
    def __init__(
        self,
        *,
        count: int = 1,
        candidates: list[_Candidate] | None = None,
        child_locator: "_Locator | None" = None,
    ) -> None:
        self._count = count
        self._candidates = candidates or []
        self._child_locator = child_locator
        self.wait_calls: list[tuple[str, int]] = []

    @property
    def first(self) -> "_Locator":
        return self

    async def count(self) -> int:
        return len(self._candidates) if self._candidates else self._count

    async def wait_for(self, *, state: str, timeout: int) -> None:
        self.wait_calls.append((state, timeout))

    def locator(self, _selector: str) -> "_Locator":
        return self._child_locator or self

    def nth(self, index: int) -> _Candidate | "_Locator":
        if self._child_locator is not None:
            return self
        if self._candidates:
            return self._candidates[index]
        return self


class _Page:
    def __init__(self) -> None:
        self.evaluate_results: list[Any] = []
        self.locators: dict[str, _Locator] = {}
        self.selector_visible: dict[str, bool] = {}
        self.timeout_calls: list[int] = []

    async def evaluate(self, _script: str, *args: Any) -> Any:
        del args
        if self.evaluate_results:
            result = self.evaluate_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return None

    async def wait_for_selector(self, selector: str, *, state: str, timeout: int) -> None:
        del state, timeout
        if not self.selector_visible.get(selector, True):
            raise RuntimeError("not visible")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.timeout_calls.append(timeout)

    def locator(self, selector: str) -> _Locator:
        return self.locators.setdefault(selector, _Locator())


class _Driver:
    def __init__(self, page: _Page | None = None, *, page_error: Exception | None = None) -> None:
        self._page = page
        self._page_error = page_error

    async def page(self) -> Any:
        if self._page_error is not None:
            raise self._page_error
        return self._page


class TencentRuntimeInteractionsTests:
    @pytest.mark.asyncio
    async def test_page_visibility_and_wait_helpers_cover_snapshot_paths(self, monkeypatch) -> None:
        page = _Page()
        page.evaluate_results = [
            {
                "q1": {"attached": True, "visible": False},
                "q2": {"attached": True, "visible": True},
            },
            {"q1": {"attached": True, "visible": False}},
            {"q1": {"attached": True, "visible": True}},
            {"q1": {"attached": True, "visible": True}},
        ]
        page.selector_visible['section.question[data-question-id="q1"]'] = True
        driver = _Driver(page)
        monkeypatch.setattr(runtime_interactions, "sleep_or_stop", _async_result(None))

        assert await runtime_interactions._page(driver) is page
        assert await runtime_interactions._supports_page_snapshot(driver) is True
        assert await runtime_interactions._supports_page_snapshot(_Driver(page_error=RuntimeError("boom"))) is False
        snapshot = await runtime_interactions._collect_question_visibility_map(driver, [" q1 ", "", "q2"])
        assert snapshot == {
            "q1": {"attached": True, "visible": False},
            "q2": {"attached": True, "visible": True},
        }
        waited = await runtime_interactions._wait_for_question_visibility_map(driver, ["q1"], timeout_ms=120, poll_ms=20)
        assert waited == {"q1": {"attached": True, "visible": True}}
        assert await runtime_interactions._wait_for_question_visible(driver, "q1", timeout_ms=50) is True
        assert await runtime_interactions._is_question_visible(driver, "q1") is True
        assert page.timeout_calls

    def test_normalize_selected_indices_and_apply_multiple_constraints_cover_main_rules(self) -> None:
        assert runtime_interactions._normalize_selected_indices([2, "1", 2, -1, "x", 4], 4) == [1, 2]
        assert runtime_interactions._apply_multiple_constraints(
            selected_indices=[4, 2, 2, 1],
            option_count=5,
            min_required=3,
            max_allowed=3,
            required_indices=[0, 4],
            blocked_indices=[2],
            positive_priority_indices=[3, 1],
        ) == [0, 1, 4]

    @pytest.mark.asyncio
    async def test_dropdown_helpers_cover_popup_lookup_and_option_selection(self, monkeypatch) -> None:
        page = _Page()
        page.evaluate_results = [1, 1, 1]
        option_locator = _Locator(
            candidates=[
                _Candidate("忽略项", visible=False),
                _Candidate("目标选项"),
            ]
        )
        popup_locator = _Locator(child_locator=option_locator)
        page.locators[".t-popup.t-select__dropdown"] = popup_locator
        driver = _Driver(page)
        waits: list[tuple[str, str, int]] = []

        async def _wait_dropdown_value(*_args, **_kwargs):
            waits.append(("wait", _args[1], _kwargs.get("timeout_ms", 0)))
            return True

        monkeypatch.setattr(runtime_interactions, "_wait_dropdown_value", _wait_dropdown_value)
        monkeypatch.setattr(runtime_interactions, "sleep_or_stop", _async_result(None))

        assert await runtime_interactions._wait_dropdown_popup_index(driver, "q8", timeout_ms=80) == 1
        assert await runtime_interactions._select_dropdown_option(driver, "q8", "目标") is True
        assert waits == [("wait", "q8", 1200)]


def _async_result(value):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner
