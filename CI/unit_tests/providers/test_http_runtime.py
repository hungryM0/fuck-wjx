from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from software.providers.answering import AnswerAction
from software.providers.contracts import SurveyQuestionMeta
from tencent.provider import answering_builders as qq_builders
from tencent.provider import http_runtime as qq_http
from wjx.provider import answering_builders as wjx_builders
from wjx.provider import http_runtime as wjx_http


class _FakeResponse:
    def __init__(self, *, text: str = "success", payload=None) -> None:
        self.text = text
        self._payload = payload if payload is not None else {"code": "OK"}

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_wjx_submitdata_formats_common_actions() -> None:
    submitdata = wjx_http._submitdata_from_actions(
        [
            AnswerAction(question_num=1, kind="choice", selected_indices=(0,), record_type="single"),
            AnswerAction(question_num=2, kind="choice", selected_indices=(0, 2), record_type="multiple"),
            AnswerAction(question_num=3, kind="text", text_values=("甲", "乙"), record_type="text"),
            AnswerAction(question_num=4, kind="matrix", matrix_indices=(1, 2), record_type="matrix"),
            AnswerAction(question_num=5, kind="slider", slider_value=66.0, record_type="slider"),
        ]
    )

    assert submitdata == "1$1}2$1|3}3$甲^乙}4$1!2,2!3}5$66.0"


def test_qq_question_answer_builders_cover_choice_text_and_matrix() -> None:
    choice = qq_http._question_answer(
        {"id": "q1", "type": "radio", "options": [{"id": "o1", "text": "A"}, {"id": "o2", "text": "B"}]},
        AnswerAction(question_id="q1", kind="choice", selected_indices=(1,)),
    )
    text = qq_http._question_answer(
        {"id": "q2", "type": "text"},
        AnswerAction(question_id="q2", kind="text", text_values=("hello",)),
    )
    matrix = qq_http._question_answer(
        {
            "id": "q3",
            "type": "matrix_radio",
            "options": [{"id": "o1", "text": "A"}, {"id": "o2", "text": "B"}],
            "sub_titles": [{"id": "r1", "text": "R1"}],
        },
        AnswerAction(question_id="q3", kind="matrix", matrix_indices=(0,)),
    )

    assert choice["options"][1]["checked"] == 1
    assert text["text"] == "hello"
    assert matrix["sub_titles"][0]["options"][0]["checked"] == 1


@pytest.mark.asyncio
async def test_wjx_http_runtime_uses_proxy_and_posts_submitdata(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
        submit_enabled=True,
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2, option_texts=["A", "B"]),
    }
    state = ExecutionState(config=config)
    captured: dict[str, object] = {}

    async def fake_load(*_args, **_kwargs):
        return None

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(question_num=1, kind="choice", selected_indices=(0,), record_type="single")

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(text="success")

    monkeypatch.setattr(wjx_http, "_load_wjx_page", fake_load)
    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(wjx_http.http_client, "apost", fake_post)

    ok = await wjx_http.brush_wjx_http(
        config,
        state,
        proxy_address="http://1.1.1.1:80",
        user_agent="UA",
    )

    assert ok is True
    assert captured["proxies"] == "http://1.1.1.1:80"
    assert captured["data"] == {"submitdata": "1$1", "sceneId": "q0hcfsca"}


@pytest.mark.asyncio
async def test_wjx_http_runtime_builds_only_visible_questions_after_logic(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
        submit_enabled=True,
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            type_code="3",
            has_jump=True,
            logic_parse_status="complete",
            jump_rules=[{"option_index": 1, "jumpto": 3}],
            option_texts=["A", "B"],
            options=2,
        ),
        2: SurveyQuestionMeta(
            num=2,
            title="Q2",
            type_code="3",
            has_display_condition=True,
            logic_parse_status="complete",
            display_conditions=[{"condition_question_num": 1, "condition_mode": "selected", "condition_option_indices": [0]}],
            option_texts=["C", "D"],
            options=2,
        ),
        3: SurveyQuestionMeta(num=3, title="Q3", type_code="3", option_texts=["E", "F"], options=2),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        built_questions.append(int(question.num))
        if int(question.num) == 1:
            return AnswerAction(question_num=1, kind="choice", selected_indices=(1,), record_type="single")
        if int(question.num) == 3:
            return AnswerAction(question_num=3, kind="choice", selected_indices=(0,), record_type="single")
        raise AssertionError("隐藏题不该进 HTTP 构建")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)

    assert built_questions == [1, 3]
    assert [action.question_num for action in actions] == [1, 3]


@pytest.mark.asyncio
async def test_wjx_http_runtime_keeps_jump_skipped_questions_in_final_submit(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
        submit_enabled=True,
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            type_code="3",
            has_jump=True,
            logic_parse_status="complete",
            jump_rules=[{"option_index": 1, "jumpto": 3}],
            option_texts=["A", "B"],
            options=2,
        ),
        2: SurveyQuestionMeta(
            num=2,
            title="Q2",
            type_code="3",
            option_texts=["C", "D"],
            options=2,
        ),
        3: SurveyQuestionMeta(
            num=3,
            title="Q3",
            type_code="3",
            option_texts=["E", "F"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        built_questions.append(int(question.num))
        if int(question.num) == 1:
            return AnswerAction(question_num=1, kind="choice", selected_indices=(1,), record_type="single")
        return AnswerAction(question_num=int(question.num), kind="choice", selected_indices=(0,), record_type="single")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)

    assert built_questions == [1, 2, 3]
    assert [action.question_num for action in actions] == [1, 2, 3]


@pytest.mark.asyncio
async def test_wjx_http_runtime_requires_all_distinct_display_sources(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
        submit_enabled=True,
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"], options=2),
        2: SurveyQuestionMeta(num=2, title="Q2", type_code="3", option_texts=["C", "D"], options=2),
        3: SurveyQuestionMeta(
            num=3,
            title="Q3",
            type_code="3",
            has_display_condition=True,
            logic_parse_status="complete",
            display_conditions=[
                {"condition_question_num": 1, "condition_mode": "selected", "condition_option_indices": [0]},
                {"condition_question_num": 2, "condition_mode": "selected", "condition_option_indices": [1]},
            ],
            option_texts=["E", "F"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        built_questions.append(int(question.num))
        if int(question.num) == 1:
            return AnswerAction(question_num=1, kind="choice", selected_indices=(0,), record_type="single")
        if int(question.num) == 2:
            return AnswerAction(question_num=2, kind="choice", selected_indices=(0,), record_type="single")
        raise AssertionError("Q3 不该可见")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)

    assert built_questions == [1, 2]
    assert [action.question_num for action in actions] == [1, 2]


@pytest.mark.asyncio
async def test_qq_http_runtime_uses_proxy_and_answer_session(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
        submit_enabled=True,
        answer_duration_range_seconds=(480, 480),
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", provider="qq", provider_question_id="q1", provider_type="radio"),
    }
    state = ExecutionState(config=config)
    captured = SimpleNamespace(fetch_proxies=None, post_kwargs=None)

    async def fake_fetch(*_args, headers, proxies, **_kwargs):
        captured.fetch_proxies = proxies
        headers["X-Answer-Session"] = "sess"
        return "sess", {}, [{"id": "q1", "type": "radio", "options": [{"id": "o1", "text": "A"}], "page_id": "p1"}]

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(question_num=1, question_id="q1", kind="choice", selected_indices=(0,), record_type="single")

    async def fake_post(*_args, **kwargs):
        captured.post_kwargs = kwargs
        return _FakeResponse(payload={"code": "OK"})

    monkeypatch.setattr(qq_http, "_fetch_submit_source", fake_fetch)
    monkeypatch.setattr(qq_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(qq_http.http_client, "apost", fake_post)
    monkeypatch.setattr(qq_http, "sample_answer_duration_seconds", lambda *_args, **_kwargs: 480.0)

    ok = await qq_http.brush_qq_http(
        config,
        state,
        proxy_address="http://1.1.1.1:80",
        user_agent="UA",
    )

    assert ok is True
    assert captured.fetch_proxies == "http://1.1.1.1:80"
    assert captured.post_kwargs["proxies"] == "http://1.1.1.1:80"
    assert captured.post_kwargs["headers"]["X-Answer-Session"] == "sess"
    assert captured.post_kwargs["json"]["answer_survey"]["duration"] == 480


@pytest.mark.asyncio
async def test_qq_http_runtime_submits_only_visible_questions_grouped_by_page(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
        submit_enabled=True,
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            provider="qq",
            provider_question_id="q1",
            provider_type="radio",
            has_jump=True,
            logic_parse_status="complete",
            jump_rules=[{"option_index": 1, "jumpto": 3}],
            option_texts=["A", "B"],
            options=2,
        ),
        2: SurveyQuestionMeta(
            num=2,
            title="Q2",
            provider="qq",
            provider_question_id="q2",
            provider_type="radio",
            has_display_condition=True,
            logic_parse_status="complete",
            display_conditions=[{"condition_question_num": 1, "condition_mode": "selected", "condition_option_indices": [0]}],
            option_texts=["C", "D"],
            options=2,
        ),
        3: SurveyQuestionMeta(
            num=3,
            title="Q3",
            provider="qq",
            provider_question_id="q3",
            provider_type="radio",
            option_texts=["E", "F"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)
    captured: dict[str, object] = {}

    async def fake_fetch(*_args, **_kwargs):
        return "sess", {}, [
            {"id": "q1", "type": "radio", "options": [{"id": "o1", "text": "A"}, {"id": "o2", "text": "B"}], "page_id": "p1"},
            {"id": "q2", "type": "radio", "options": [{"id": "o3", "text": "C"}, {"id": "o4", "text": "D"}], "page_id": "p1"},
            {"id": "q3", "type": "radio", "options": [{"id": "o5", "text": "E"}, {"id": "o6", "text": "F"}], "page_id": "p2"},
        ]

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        if int(question.num) == 1:
            return AnswerAction(question_num=1, question_id="q1", kind="choice", selected_indices=(1,), record_type="single")
        if int(question.num) == 3:
            return AnswerAction(question_num=3, question_id="q3", kind="choice", selected_indices=(0,), record_type="single")
        raise AssertionError("隐藏题不该进 HTTP 构建")

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(payload={"code": "OK"})

    monkeypatch.setattr(qq_http, "_fetch_submit_source", fake_fetch)
    monkeypatch.setattr(qq_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(qq_http.http_client, "apost", fake_post)

    ok = await qq_http.brush_qq_http(config, state)

    assert ok is True
    pages = captured["json"]["answer_survey"]["pages"]
    assert [page["id"] for page in pages] == ["p1", "p2"]
    assert [[question["id"] for question in page["questions"]] for page in pages] == [["q1"], ["q3"]]


@pytest.mark.asyncio
async def test_wjx_builder_allows_logic_question_for_http(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx")
    config.question_config_index_map = {1: ("single", 0)}
    config.single_prob = [[0.0, 1.0]]
    config.single_option_fill_texts = [None]
    state = ExecutionState(config=config)
    question = SurveyQuestionMeta(
        num=1,
        title="Q1",
        type_code="3",
        has_jump=True,
        logic_parse_status="complete",
        jump_rules=[{"option_index": 1, "jumpto": 2}],
        option_texts=["A", "B"],
        options=2,
    )

    monkeypatch.setattr(wjx_builders, "weighted_index", lambda _probs: 1)
    monkeypatch.setattr(wjx_builders, "resolve_runtime_option_fill_text_from_config", _async_result(None))

    action = await wjx_builders.build_answer_action(None, question, state, psycho_plan=None)

    assert action is not None
    assert action.selected_indices == (1,)


@pytest.mark.asyncio
async def test_qq_builder_supports_dropdown_and_matrix_star_for_http(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="qq")
    config.question_config_index_map = {
        1: ("dropdown", 0),
        2: ("matrix", 0),
    }
    config.droplist_prob = [[0.0, 1.0, 0.0]]
    config.droplist_option_fill_texts = [None]
    config.matrix_prob = [[0.0, 0.0, 1.0]]
    state = ExecutionState(config=config)

    dropdown_question = SurveyQuestionMeta(
        num=1,
        title="Q1",
        provider="qq",
        provider_question_id="q1",
        provider_type="select",
        type_code="7",
        has_jump=True,
        logic_parse_status="complete",
        jump_rules=[{"option_index": 1, "jumpto": 2}],
        option_texts=["A", "B", "C"],
        options=3,
    )
    matrix_star_question = SurveyQuestionMeta(
        num=2,
        title="Q2",
        provider="qq",
        provider_question_id="q2",
        provider_type="matrix_star",
        type_code="6",
        rows=1,
        options=3,
    )

    monkeypatch.setattr(qq_builders, "weighted_index", lambda _probs: 1)
    monkeypatch.setattr(qq_builders, "get_tendency_index", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr(qq_builders, "resolve_runtime_option_fill_text_from_config", _async_result(None))

    dropdown_action = await qq_builders.build_answer_action(None, dropdown_question, state, psycho_plan=None)
    matrix_action = await qq_builders.build_answer_action(None, matrix_star_question, state, psycho_plan=None)

    assert dropdown_action is not None
    assert dropdown_action.kind == "select"
    assert dropdown_action.selected_indices == (1,)
    assert matrix_action is not None
    assert matrix_action.kind == "matrix"
    assert matrix_action.matrix_indices == (2,)


def test_wjx_submit_rejected_message_includes_question_title_and_display_num() -> None:
    config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
    config.questions_metadata = {
        10: SurveyQuestionMeta(num=10, display_num=8, title="年龄", type_code="1"),
    }

    with pytest.raises(RuntimeError, match=r"第8题（年龄）.*答案不符合要求"):
        wjx_http._raise_submit_rejected(config, "9〒10〒您提交的答案不符合要求，请检查并修改后重新提交！")


def _async_result(value):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner
