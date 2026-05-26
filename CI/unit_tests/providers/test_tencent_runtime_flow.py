from __future__ import annotations

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from software.providers.contracts import SurveyQuestionMeta
from tencent.provider import runtime_flow


class _FakePage:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls: list[list[str]] = []

    async def evaluate(self, _script: str, markers):
        self.calls.append(list(markers))
        return self.message


class _FakeDriver:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def page(self):
        return self._page


class TencentRuntimeFlowTests:
    @pytest.mark.asyncio
    async def test_submission_validation_message_prefers_verification_markers(self, monkeypatch) -> None:
        page = _FakePage("请先完成验证 | 滑动验证")
        driver = _FakeDriver(page)

        async def _page_factory(_driver):
            return page

        monkeypatch.setattr(runtime_flow, "_page", _page_factory)

        message = await runtime_flow.qq_submission_validation_message(driver)

        assert message == "请先完成验证 | 滑动验证"
        assert page.calls == [list(runtime_flow.QQ_VERIFICATION_MARKERS)]

    def test_group_questions_by_page_keeps_description_only_pages_as_anchors(self) -> None:
        config = ExecutionConfig(survey_provider="qq")
        config.questions_metadata = {
            1: SurveyQuestionMeta(
                num=1,
                title="说明页",
                page=1,
                provider="qq",
                type_code="0",
                provider_question_id="desc-page-1",
                is_description=True,
            ),
            2: SurveyQuestionMeta(
                num=2,
                title="第2页说明",
                page=2,
                provider="qq",
                type_code="0",
                provider_question_id="desc-page-2",
                is_description=True,
            ),
            3: SurveyQuestionMeta(
                num=3,
                title="正式题目",
                page=3,
                provider="qq",
                type_code="3",
                provider_question_id="real-q3",
            ),
        }
        ctx = ExecutionState(config=config)

        groups = runtime_flow._group_questions_by_page(ctx)

        assert [group.page_number for group in groups] == [1, 2, 3]
        assert [group.anchor_question_id for group in groups] == [
            "desc-page-1",
            "desc-page-2",
            "real-q3",
        ]
        assert groups[0].questions == []
        assert groups[1].questions == []
        assert [question.num for question in groups[2].questions] == [3]
