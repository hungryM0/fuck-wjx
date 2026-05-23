from __future__ import annotations

from types import SimpleNamespace

import credamo.provider
import pytest

from credamo.provider import runtime_answerers
from software.core.questions import runtime_async


class _FakeElement:
    def __init__(self, *, text: str = "", checked: bool = False, value: str = "", selectors=None, click_ok: bool = True) -> None:
        self.text = text
        self.checked = checked
        self.value = value
        self.selectors = dict(selectors or {})
        self.click_ok = click_ok
        self.filled: list[str] = []
        self.typed: list[str] = []
        self.clicked = 0
        self.fill_should_fail = False

    async def query_selector_all(self, selector: str):
        return list(self.selectors.get(selector, []))

    async def query_selector(self, selector: str):
        items = list(self.selectors.get(selector, []))
        return items[0] if items else None

    async def fill(self, value: str, timeout: int = 0) -> None:
        del timeout
        if self.fill_should_fail:
            raise RuntimeError("fill failed")
        self.filled.append(value)
        self.value = value

    async def type(self, value: str, timeout: int = 0) -> None:
        del timeout
        self.typed.append(value)
        self.value = value

    async def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        del timeout

    async def click(self, timeout: int = 0, force: bool = False) -> None:
        del timeout, force
        self.clicked += 1
        if not self.click_ok:
            raise RuntimeError("click failed")
        self.checked = True

    async def text_content(self, timeout: int = 0) -> str:
        del timeout
        return self.text

    async def focus(self) -> None:
        return None

    async def bounding_box(self):
        return {"width": 12, "height": 12}

    async def element_handle(self, timeout: int = 0):
        del timeout
        return self


class _FakeLocator:
    def __init__(self, items: list[_FakeElement]) -> None:
        self.items = items

    async def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> _FakeElement:
        return self.items[index]


class _FakeHandle:
    def __init__(self, items: list[_FakeElement]) -> None:
        self.items = items

    def get_properties(self):
        return {str(index): SimpleNamespace(as_element=lambda item=item: item) for index, item in enumerate(self.items)}

    def dispose(self) -> None:
        return None


class _FakeKeyboard:
    def __init__(self, input_element: _FakeElement) -> None:
        self.input_element = input_element
        self.arrow_down = 0

    async def press(self, key: str) -> None:
        if key == "ArrowDown":
            self.arrow_down += 1
        if key == "Enter" and self.arrow_down > 0:
            self.input_element.value = f"选项 {self.arrow_down}"


class _FakePage:
    def __init__(self, *, visible_options: list[_FakeElement] | None = None, locator_items: list[_FakeElement] | None = None, input_element: _FakeElement | None = None) -> None:
        self.visible_options = list(visible_options or [])
        self.locator_items = list(locator_items or [])
        self.input_element = input_element
        self.keyboard = _FakeKeyboard(input_element or _FakeElement())

    async def evaluate(self, _script, element):
        if hasattr(element, "checked"):
            element.checked = True
            return True
        return True

    async def evaluate_handle(self, _script):
        return _FakeHandle(self.visible_options)

    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    def locator(self, _selector: str):
        return _FakeLocator(self.locator_items)

    async def query_selector_all(self, _selector: str):
        return list(self.visible_options)


class CredamoRuntimeAnswerersTests:
    @pytest.mark.asyncio
    async def test_resolve_forced_choice_index_handles_parser_results_and_bounds(self, monkeypatch) -> None:
        page = object()
        root = object()
        parser_module = SimpleNamespace(
            _extract_force_select_option=lambda *_args, **_kwargs: (1, "B"),
            _extract_arithmetic_option=lambda *_args, **_kwargs: (0, "A"),
        )
        async def _question_title_text(*_args, **_kwargs):
            return "标题"
        async def _root_text(*_args, **_kwargs):
            return "题面"
        monkeypatch.setattr(runtime_answerers, "_question_title_text", _question_title_text)
        monkeypatch.setattr(runtime_answerers, "_root_text", _root_text)
        monkeypatch.setitem(__import__("sys").modules, "credamo.provider.parser", parser_module)
        monkeypatch.setattr(credamo.provider, "parser", parser_module, raising=False)

        assert await runtime_answerers._resolve_forced_choice_index(page, root, ["A", "B"]) == 1

        parser_module2 = SimpleNamespace(
            _extract_force_select_option=lambda *_args, **_kwargs: (None, None),
            _extract_arithmetic_option=lambda *_args, **_kwargs: (5, "Z"),
        )
        monkeypatch.setitem(__import__("sys").modules, "credamo.provider.parser", parser_module2)
        monkeypatch.setattr(credamo.provider, "parser", parser_module2, raising=False)
        assert await runtime_answerers._resolve_forced_choice_index(page, root, ["A", "B"]) is None

    @pytest.mark.asyncio
    async def test_single_choice_helpers_cover_row_and_input_fallbacks(self, monkeypatch) -> None:
        radio = _FakeElement(text="选项A", checked=False)
        row = _FakeElement(text="选项A", selectors={"input[type='radio'], [role='radio']": [radio]})
        root = _FakeElement(selectors={".single-choice .choice-row": [row]})
        async def _element_text(_page, element):
            return element.text
        async def _option_inputs(_root, _kind):
            return [radio]
        monkeypatch.setattr(runtime_answerers, "_element_text", _element_text)

        options = await runtime_answerers._single_choice_options(object(), root)
        assert len(options) == 1

        root_fallback = _FakeElement()
        monkeypatch.setattr(runtime_answerers, "_option_inputs", _option_inputs)
        options = await runtime_answerers._single_choice_options(object(), root_fallback)
        assert options[0][0] is radio

    @pytest.mark.asyncio
    async def test_click_single_choice_option_uses_click_and_js_fallback(self, monkeypatch) -> None:
        input_element = _FakeElement(checked=False, click_ok=False)
        click_target = _FakeElement(click_ok=False)
        page = _FakePage()
        async def _click_element(_page, element):
            return not getattr(element, "click_ok", False) and False
        async def _is_checked(_page, element):
            return element.checked
        monkeypatch.setattr(runtime_answerers, "_click_element", _click_element)
        monkeypatch.setattr(runtime_answerers, "_is_checked", _is_checked)

        option = (input_element, click_target, "A")
        assert await runtime_answerers._click_single_choice_option(page, option)

    @pytest.mark.asyncio
    async def test_answer_single_like_prefers_forced_choice_then_weighted_choice(self, monkeypatch) -> None:
        option_a = (_FakeElement(checked=False), _FakeElement(), "A")
        option_b = (_FakeElement(checked=False), _FakeElement(), "B")
        async def _single_choice_options(*_args, **_kwargs):
            return [option_a, option_b]
        async def _resolve_forced_choice_index(*_args, **_kwargs):
            return 1
        async def _click_single_choice_option(_page, option):
            return option is option_b
        monkeypatch.setattr(runtime_answerers, "_single_choice_options", _single_choice_options)
        monkeypatch.setattr(runtime_answerers, "_resolve_forced_choice_index", _resolve_forced_choice_index)
        monkeypatch.setattr(runtime_answerers, "_click_single_choice_option", _click_single_choice_option)

        assert await runtime_answerers._answer_single_like(object(), object(), [10, 90], 2)

        async def _resolve_none(*_args, **_kwargs):
            return None
        async def _click_option_a(_page, option):
            return option is option_a
        monkeypatch.setattr(runtime_answerers, "_resolve_forced_choice_index", _resolve_none)
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [1.0, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 0)
        monkeypatch.setattr(runtime_answerers, "_click_single_choice_option", _click_option_a)
        assert await runtime_answerers._answer_single_like(object(), object(), [10, 90], 2)

    @pytest.mark.asyncio
    async def test_resolve_multi_select_limits_and_answer_multiple_cover_fallbacks(self, monkeypatch) -> None:
        parser_module = SimpleNamespace(_extract_multi_select_limits=lambda *_args, **_kwargs: (2, 3))
        monkeypatch.setitem(__import__("sys").modules, "credamo.provider.parser", parser_module)
        monkeypatch.setattr(credamo.provider, "parser", parser_module, raising=False)
        async def _question_title_text(*_args, **_kwargs):
            return "标题"
        async def _root_text(*_args, **_kwargs):
            return "题面"
        async def _option_inputs(_root, _kind):
            return inputs
        async def _option_click_targets(_root, _kind):
            return []
        async def _click_element(_page, element):
            element.checked = True
            return True
        async def _is_checked(_page, element):
            return element.checked
        async def _resolve_limits(*_args, **_kwargs):
            return (1, 2)
        monkeypatch.setattr(runtime_answerers, "_question_title_text", _question_title_text)
        monkeypatch.setattr(runtime_answerers, "_root_text", _root_text)
        assert await runtime_answerers._resolve_multi_select_limits(object(), object(), 4) == (2, 3)

        inputs = [_FakeElement(checked=False), _FakeElement(checked=False)]
        root = object()
        page = _FakePage()
        monkeypatch.setattr(runtime_answerers, "_option_inputs", _option_inputs)
        monkeypatch.setattr(runtime_answerers, "_option_click_targets", _option_click_targets)
        monkeypatch.setattr(runtime_answerers, "_positive_multiple_indexes_with_limits", lambda *_args, **_kwargs: [0, 1])
        monkeypatch.setattr(runtime_answerers, "_click_element", _click_element)
        monkeypatch.setattr(runtime_answerers, "_is_checked", _is_checked)
        monkeypatch.setattr(runtime_answerers, "_resolve_multi_select_limits", _resolve_limits)

        assert await runtime_answerers._answer_multiple(page, root, [100, 100], min_limit=None, max_limit=None)

    @pytest.mark.asyncio
    async def test_answer_text_uses_fill_then_type_fallback(self, monkeypatch) -> None:
        good = _FakeElement()
        bad = _FakeElement()
        bad.fill_should_fail = True
        root = object()
        async def _text_inputs(_root):
            return [good, bad]
        monkeypatch.setattr(runtime_answerers, "_text_inputs", _text_inputs)

        assert await runtime_answerers._answer_text(root, ["甲", "乙"], [1, 0])
        assert good.filled == ["甲"]
        assert bad.typed == ["甲"]

    @pytest.mark.asyncio
    async def test_answer_text_resolves_dynamic_tokens_and_random_answer_list(self, monkeypatch) -> None:
        first = _FakeElement()
        second = _FakeElement()
        root = object()
        async def _text_inputs(_root):
            return [first, second]
        monkeypatch.setattr(runtime_answerers, "_text_inputs", _text_inputs)
        monkeypatch.setattr(runtime_async, "weighted_index", lambda _probs: 1)

        assert await runtime_answerers._answer_text(
            root,
            ["甲||乙", "__RANDOM_INT__:3:9||__RANDOM_NAME__"],
            [0, 1],
            entry_type="multi_text",
        )

        assert first.filled[0].isdigit()
        assert 3 <= int(first.filled[0]) <= 9
        assert second.filled[0] != "__RANDOM_NAME__"
        assert second.filled[0]

    @pytest.mark.asyncio
    async def test_answer_dropdown_uses_visible_option_then_keyboard_and_locator_fallback(self, monkeypatch) -> None:
        trigger = _FakeElement()
        value_input = _FakeElement(value="")
        visible_a = _FakeElement(text="选项 1")
        visible_b = _FakeElement(text="选项 2")
        page = _FakePage(visible_options=[visible_a, visible_b], locator_items=[visible_a, visible_b], input_element=value_input)
        root = _FakeElement(selectors={".pc-dropdown .el-input": [trigger], ".el-input__inner": [value_input]})
        async def _click_element(_page, element):
            value_input.value = getattr(element, "text", "") or "clicked"
            return True
        async def _input_value(_page, element):
            return element.value
        async def _element_text(_page, element):
            return element.text
        async def _resolve_none(*_args, **_kwargs):
            return None
        monkeypatch.setattr(runtime_answerers, "_click_element", _click_element)
        monkeypatch.setattr(runtime_answerers, "_input_value", _input_value)
        monkeypatch.setattr(runtime_answerers, "_element_text", _element_text)
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.0, 100.0][:count])
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 1)
        monkeypatch.setattr(runtime_answerers, "_resolve_forced_choice_index", _resolve_none)

        assert await runtime_answerers._answer_dropdown(page, root, [0, 100])

        value_input.value = ""
        page.visible_options = []
        async def _click_trigger_only(_page, element):
            return True if element is trigger else False
        monkeypatch.setattr(
            runtime_answerers,
            "_click_element",
            _click_trigger_only,
        )
        assert await runtime_answerers._answer_dropdown(page, root, [0, 100])

    @pytest.mark.asyncio
    async def test_answer_dropdown_accepts_same_selected_value_after_click(self, monkeypatch) -> None:
        trigger = _FakeElement()
        value_input = _FakeElement(value="选项 1")
        visible_option = _FakeElement(text="选项 1")
        page = _FakePage(visible_options=[visible_option], locator_items=[visible_option], input_element=value_input)
        root = _FakeElement(selectors={".pc-dropdown .el-input": [trigger], ".el-input__inner": [value_input]})

        async def _click_element(_page, _element):
            return True

        async def _input_value(_page, element):
            return element.value

        async def _element_text(_page, element):
            return element.text

        async def _resolve_none(*_args, **_kwargs):
            return None

        monkeypatch.setattr(runtime_answerers, "_click_element", _click_element)
        monkeypatch.setattr(runtime_answerers, "_input_value", _input_value)
        monkeypatch.setattr(runtime_answerers, "_element_text", _element_text)
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [1.0][:count])
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 0)
        monkeypatch.setattr(runtime_answerers, "_resolve_forced_choice_index", _resolve_none)

        assert await runtime_answerers._answer_dropdown(page, root, [100])

    @pytest.mark.asyncio
    async def test_answer_scale_matrix_and_order_cover_success_and_empty_paths(self, monkeypatch) -> None:
        scale_option = _FakeElement()
        root_scale = _FakeElement(selectors={".scale .nps-item, .nps-item, .el-rate__item": [scale_option]})
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [1.0][:count])
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 0)
        async def _click_element(_page, element):
            return True
        async def _click_element_fail(_page, element):
            return False
        monkeypatch.setattr(runtime_answerers, "_click_element", _click_element)
        assert await runtime_answerers._answer_scale(object(), root_scale, [100])
        assert not await runtime_answerers._answer_scale(object(), _FakeElement(), [100])

        radio_a = _FakeElement()
        radio_b = _FakeElement()
        row = _FakeElement(selectors={"input[type='radio'], [role='radio'], .el-radio, .el-radio__input": [radio_a, radio_b]})
        root_matrix = _FakeElement(selectors={"tbody tr": [row]})
        monkeypatch.setattr(runtime_answerers, "_click_element", _click_element_fail)
        page = _FakePage()
        assert await runtime_answerers._answer_matrix(page, root_matrix, [100, 0])

        items = [_FakeElement(), _FakeElement(), _FakeElement()]
        root_order = _FakeElement(selectors={".rank-order .choice-row, .choice-row": items})
        monkeypatch.setattr(runtime_answerers.random, "shuffle", lambda values: values.reverse())
        monkeypatch.setattr(runtime_answerers, "_click_element", _click_element)
        assert await runtime_answerers._answer_order(object(), root_order)

    @pytest.mark.asyncio
    async def test_build_answer_action_and_apply_batch_failure_path(self, monkeypatch) -> None:
        config = SimpleNamespace(
            single_prob=[[0, 100]],
            multiple_prob=[[100, 0]],
            scale_prob=[[0, 100]],
            matrix_prob=[[100, 0], [0, 100]],
            texts=[["文本"]],
            texts_prob=[[1.0]],
            multi_text_blank_modes=[[]],
            multi_text_blank_int_ranges=[[]],
        )
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda probs: 1 if len(probs) > 1 and probs[1] else 0)

        action = runtime_answerers.build_answer_action(
            root_index=0,
            question_num=3,
            entry_type="single",
            config_index=0,
            config=config,
            question_meta=SimpleNamespace(options=2),
        )

        assert action is not None
        assert action.selected_indices == (1,)

        plan_action = runtime_answerers.build_answer_action(
            root_index=0,
            question_num=3,
            entry_type="single",
            config_index=0,
            config=config,
            question_meta=SimpleNamespace(options=2),
            psycho_plan=SimpleNamespace(get_choice=lambda *_args: 0),
        )

        assert plan_action is not None
        assert plan_action.selected_indices == (0,)

        class _FailPage:
            async def evaluate(self, *_args):
                raise RuntimeError("js boom")

        result = await runtime_answerers.apply_answer_actions(_FailPage(), [action])
        assert result.failed == (3,)
