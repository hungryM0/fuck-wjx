from __future__ import annotations

from typing import Any

import pytest

from software.core.ai.runtime import AIRuntimeError
from software.core.questions import runtime_async


class _FakeElement:
    def __init__(self, *, text_value: str = "", attributes: dict[str, Any] | None = None) -> None:
        self._text_value = text_value
        self._attributes = dict(attributes or {})

    async def text(self) -> str:
        return self._text_value

    async def get_attribute(self, name: str) -> Any:
        return self._attributes.get(name)


class _FakeDriver:
    def __init__(self) -> None:
        self.script_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.elements: dict[str, _FakeElement] = {}

    async def execute_script(self, script: str, *args: Any) -> Any:
        self.script_calls.append((script, args))
        return True

    async def find_element(self, _by: str, value: str) -> _FakeElement:
        element = self.elements.get(value)
        if element is None:
            raise RuntimeError("not found")
        return element


class RuntimeAsyncQuestionTests:
    @pytest.mark.asyncio
    async def test_extract_text_from_runtime_element_prefers_async_readers(self) -> None:
        element = _FakeElement(text_value="标题文本", attributes={"value": "备用值"})
        assert await runtime_async.extract_text_from_runtime_element(element) == "标题文本"

    @pytest.mark.asyncio
    async def test_smooth_scroll_and_extract_runtime_question_title_cover_dom_paths(self) -> None:
        driver = _FakeDriver()
        driver.elements["#div3 .topichtml"] = _FakeElement(text_value="第3题")
        await runtime_async.smooth_scroll_to_runtime_element(driver, object())
        title = await runtime_async.extract_runtime_question_title(driver, 3)
        assert "scrollIntoView" in driver.script_calls[0][0]
        assert title == "第3题"

    @pytest.mark.asyncio
    async def test_resolve_runtime_question_title_for_ai_uses_fallback_and_raises_when_missing(self, monkeypatch) -> None:
        driver = _FakeDriver()
        assert await runtime_async.resolve_runtime_question_title_for_ai(driver, 2, fallback_title="备用题干") == "备用题干"
        async def _empty_title(*_args, **_kwargs):
            return ""

        monkeypatch.setattr(runtime_async, "extract_runtime_question_title", _empty_title)
        with pytest.raises(AIRuntimeError, match="无法获取第2题题干"):
            await runtime_async.resolve_runtime_question_title_for_ai(driver, 2)

    @pytest.mark.asyncio
    async def test_resolve_runtime_option_fill_text_from_config_covers_plain_ai_and_missing_context(self, monkeypatch) -> None:
        driver = _FakeDriver()
        monkeypatch.setattr(runtime_async, "get_fill_text_from_config", lambda entries, index: "固定值")
        monkeypatch.setattr(runtime_async, "resolve_dynamic_text_token", lambda value: f"token:{value}")
        assert await runtime_async.resolve_runtime_option_fill_text_from_config(["x"], 0) == "token:固定值"

        monkeypatch.setattr(runtime_async, "get_fill_text_from_config", lambda entries, index: runtime_async.OPTION_FILL_AI_TOKEN)
        with pytest.raises(AIRuntimeError, match="缺少运行时上下文"):
            await runtime_async.resolve_runtime_option_fill_text_from_config(["x"], 0)

        async def _question_title(*_args, **_kwargs):
            return "题干"

        monkeypatch.setattr(runtime_async, "resolve_runtime_question_title_for_ai", _question_title)

        async def _ai_answer(prompt: str, *, question_type: str, blank_count=None):
            del question_type, blank_count
            assert "已选择的选项是：其他" in prompt
            return "AI填写"

        monkeypatch.setattr(runtime_async, "agenerate_ai_answer", _ai_answer)
        result = await runtime_async.resolve_runtime_option_fill_text_from_config(
            ["x"],
            0,
            driver=driver,
            question_number=6,
            option_text="其他",
        )
        assert result == "AI填写"

        async def _ai_fail(*_args, **_kwargs):
            raise AIRuntimeError("boom")

        monkeypatch.setattr(runtime_async, "agenerate_ai_answer", _ai_fail)
        with pytest.raises(AIRuntimeError, match="附加填空 AI 生成失败"):
            await runtime_async.resolve_runtime_option_fill_text_from_config(
                ["x"],
                0,
                driver=driver,
                question_number=6,
            )

    def test_resolve_runtime_text_values_keeps_short_probabilities_aligned(self, monkeypatch) -> None:
        monkeypatch.setattr(runtime_async, "weighted_index", lambda probabilities: probabilities.index(max(probabilities)))
        values = runtime_async.resolve_runtime_text_values_from_config(
            ["甲||乙", "丙||丁"],
            [1.0],
            blank_count=2,
            entry_type="multi_text",
        )
        assert values == ["甲", "乙"]
