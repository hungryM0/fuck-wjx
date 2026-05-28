from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from software.providers.answering import AnswerAction
from software.providers.contracts import SurveyQuestionMeta
from software.providers.errors import SubmissionVerificationRequiredError, SurveyProviderUnavailableAtRuntimeError
from credamo.provider import answering_builders as credamo_builders
from credamo.provider import http_runtime as credamo_http
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


def test_wjx_submitdata_keeps_frontend_skip_placeholders() -> None:
    submitdata = wjx_http._submitdata_from_actions(
        [
            AnswerAction(question_num=1, kind="choice", selected_indices=(1,), record_type="single"),
            AnswerAction(question_num=5, kind="choice", selected_indices=(0, 1), record_type="multiple"),
        ],
        questions=[
            SurveyQuestionMeta(num=1, title="单选", type_code="3", option_texts=["A", "B"], options=2),
            SurveyQuestionMeta(num=2, title="排序", type_code="11", option_texts=["A", "B", "C"], options=3),
            SurveyQuestionMeta(num=3, title="量表", type_code="5", option_texts=["1", "2"], options=2),
            SurveyQuestionMeta(num=4, title="填空", type_code="1", options=1),
            SurveyQuestionMeta(num=5, title="多选", type_code="4", option_texts=["A", "B"], options=2),
        ],
        skipped_question_nums=(2, 3, 4),
    )

    assert submitdata == "1$2}2$-3,-3,-3}3$-3}4$(跳过)}5$1|2"


def test_wjx_default_ktimes_uses_90_seconds_with_jitter(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx", answer_duration_range_seconds=(0, 0))
    monkeypatch.setattr(wjx_http.random, "gauss", lambda center, _std: center)

    assert wjx_http._sample_ktimes(config) == 90


def test_wjx_ktimes_sampling_failure_falls_back_to_90(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx", answer_duration_range_seconds=(0, 0))

    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(wjx_http, "sample_answer_duration_seconds", _raise)

    assert wjx_http._sample_ktimes(config) == 90


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


def test_credamo_signature_headers_match_frontend_algorithm() -> None:
    token = "token"
    union_id = "UNION12345"
    nonce = "NONCE1234567890"
    timestamp = "1710000000000"
    headers = credamo_http._build_signature_headers(
        answer_token=token,
        union_id=union_id,
        nonce=nonce,
        timestamp_ms=timestamp,
    )

    inner = credamo_http._sha1_upper(f"{token}{nonce}{timestamp}{union_id}P96D0A7D0M8C3R2D0M1")
    expected = credamo_http._sha1_upper(f"{token}{nonce}{timestamp}{inner}{union_id}P96D0A7D0M8C3R2D0M1")

    assert headers["signature"] == expected
    assert headers["unionId"] == "UNION12345"
    assert headers["nonce"] == "NONCE1234567890"


def test_credamo_question_answer_payload_covers_current_types() -> None:
    raw_by_num = {
        1: {"qstId": "101", "questionType": 2, "selector": 1, "choices": [{"choiceId": "11"}, {"choiceId": "12"}]},
        2: {"qstId": "102", "questionType": 2, "selector": 2, "choices": [{"choiceId": "21"}, {"choiceId": "22"}]},
        3: {"qstId": "103", "questionType": 2, "selector": 3, "choices": [{"choiceId": "31"}, {"choiceId": "32"}]},
        4: {"qstId": "104", "questionType": 11, "choices": [{"choiceId": "41"}, {"choiceId": "42"}]},
        5: {"qstId": "105", "questionType": 6, "choices": [{"choiceId": "51"}, {"choiceId": "52"}]},
        6: {
            "qstId": "106",
            "questionType": 4,
            "choices": [{"choiceId": "61"}, {"choiceId": "62"}],
            "answers": [{"answerId": "71"}, {"answerId": "72"}],
        },
        7: {"qstId": "107", "questionType": 1},
    }
    actions = [
        AnswerAction(question_num=1, kind="single", selected_indices=(1,)),
        AnswerAction(question_num=2, kind="multiple", selected_indices=(0, 1)),
        AnswerAction(question_num=3, kind="select", selected_indices=(0,)),
        AnswerAction(question_num=4, kind="scale", selected_indices=(1,)),
        AnswerAction(question_num=5, kind="order", selected_indices=(1, 0)),
        AnswerAction(question_num=6, kind="matrix", matrix_indices=(0, 1)),
        AnswerAction(question_num=7, kind="text", text_values=("你好",)),
    ]

    items = credamo_http._answer_payload_items(raw_by_num, actions, answer_duration_seconds=70)

    assert items[0]["answerQstChoice"] == {"choiceId": 12, "choiceContent": ""}
    assert items[1]["answerQstChoiceList"] == [{"choiceId": 21, "choiceContent": ""}, {"choiceId": 22, "choiceContent": ""}]
    assert items[2]["answerQstChoice"] == {"choiceId": 31, "choiceContent": ""}
    assert items[3]["answerQstChoice"] == {"choiceId": 42, "choiceContent": ""}
    assert items[4]["answerChoiceContent"] == [{"choiceId": 52, "choiceContent": 1}, {"choiceId": 51, "choiceContent": 2}]
    assert items[5]["answerQstChoiceList"] == [
        {"choiceId": 61, "choiceAnswerList": [{"answerId": 71}]},
        {"choiceId": 62, "choiceAnswerList": [{"answerId": 72}]},
    ]
    assert items[6]["answerContent"] == "你好"
    assert all(item["answerTime"] == 10000 for item in items)


def test_credamo_forced_choice_prefers_text_when_api_choice_order_changes() -> None:
    config = ExecutionConfig(survey_provider="credamo")
    config.questions_metadata = {
        8: SurveyQuestionMeta(
            num=8,
            title="请选择 200",
            provider="credamo",
            options=4,
            forced_option_index=1,
            forced_option_text="200",
        ),
    }
    raw_by_num = {
        8: {
            "qstId": "108",
            "questionType": 2,
            "selector": 1,
            "choices": [
                {"choiceId": "6787", "display": "300"},
                {"choiceId": "6788", "display": "500"},
                {"choiceId": "6789", "display": "200"},
                {"choiceId": "6790", "display": "600"},
            ],
        },
    }
    actions = [AnswerAction(question_num=8, kind="single", selected_indices=(1,))]

    items = credamo_http._answer_payload_items(raw_by_num, actions, config=config, answer_duration_seconds=9)

    assert items[0]["answerQstChoice"] == {"choiceId": 6789, "choiceContent": ""}


@pytest.mark.asyncio
async def test_credamo_save_keeps_encoded_answer_token_verbatim() -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return _FakeResponse(payload={"success": True, "data": {"answerId": 1}})

    await credamo_http._save_answers(
        FakeSession(),
        origin="https://www.credamo.com",
        short_url="A73QR3ano",
        init_data=credamo_http._CredamoAnswerInit("abc%2Bdef%2Fghi%3D", 1710000000000, "device-id"),
        body={"answerQstList": [], "shortUrl": "A73QR3ano"},
        user_agent="UA",
    )

    assert "answerToken=abc%2Bdef%2Fghi%3D" in str(captured["url"])
    assert "%252B" not in str(captured["url"])
    assert captured["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_wjx_http_runtime_uses_proxy_and_posts_submitdata(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
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
async def test_wjx_http_runtime_skips_jump_hidden_questions(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
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

    assert built_questions == [1, 3]
    assert [action.question_num for action in actions] == [1, 3]


@pytest.mark.asyncio
async def test_wjx_http_runtime_passes_slot_label_to_reverse_fill_builder(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"], options=2),
    }
    state = ExecutionState(config=config)
    seen_thread_names: list[str] = []

    async def fake_build_action(_driver, question, _ctx, **kwargs):
        seen_thread_names.append(str(kwargs.get("thread_name") or ""))
        return AnswerAction(
            question_num=int(question.num),
            kind="choice",
            selected_indices=(0,),
            record_type="single",
        )

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(
        config,
        state,
        psycho_plan=None,
        stop_signal=None,
        thread_name="Slot-2",
    )

    assert [action.question_num for action in actions] == [1]
    assert seen_thread_names == ["Slot-2"]


@pytest.mark.asyncio
async def test_wjx_http_runtime_accepts_legacy_saved_jump_rules_without_status(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://v.wjx.cn/vm/tgRSrWd.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="这是一个单选题",
            type_code="3",
            has_jump=True,
            jump_rules=[{"option_index": 1, "jumpto": 5, "option_text": "我才是B"}],
            option_texts=["其他", "我才是B"],
            options=2,
        ),
        2: SurveyQuestionMeta(num=2, title="排序题", type_code="11", option_texts=["A", "B"], options=2),
        3: SurveyQuestionMeta(num=3, title="量表题", type_code="5", option_texts=["0", "1"], options=2),
        4: SurveyQuestionMeta(num=4, title="填空题", type_code="1", options=1),
        5: SurveyQuestionMeta(num=5, title="多选题", type_code="4", option_texts=["A", "B"], options=2),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        question_num = int(question.num)
        built_questions.append(question_num)
        if question_num == 1:
            return AnswerAction(question_num=1, kind="choice", selected_indices=(1,), record_type="single")
        return AnswerAction(question_num=question_num, kind="choice", selected_indices=(0,), record_type="multiple")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)

    assert built_questions == [1, 5]
    assert [action.question_num for action in actions] == [1, 5]


@pytest.mark.asyncio
async def test_wjx_http_runtime_blocks_unparsed_jump_logic(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            type_code="3",
            has_jump=True,
            logic_parse_status="unknown",
            option_texts=["A", "B"],
            options=2,
        ),
        2: SurveyQuestionMeta(num=2, title="Q2", type_code="3", option_texts=["C", "D"], options=2),
    }
    state = ExecutionState(config=config)

    async def fake_build_action(*_args, **_kwargs):
        raise AssertionError("未知跳题逻辑不该生成答案")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    with pytest.raises(RuntimeError, match="第1题逻辑规则未完整解析"):
        await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)


@pytest.mark.asyncio
async def test_wjx_http_runtime_blocks_unparsed_display_logic(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"], options=2),
        2: SurveyQuestionMeta(
            num=2,
            title="Q2",
            type_code="3",
            has_display_condition=True,
            logic_parse_status="unknown",
            option_texts=["C", "D"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)

    async def fake_build_action(*_args, **_kwargs):
        raise AssertionError("未知显隐逻辑不该生成答案")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    with pytest.raises(RuntimeError, match="第2题逻辑规则未完整解析"):
        await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)


@pytest.mark.asyncio
async def test_wjx_http_runtime_requires_all_distinct_display_sources(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
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
async def test_qq_http_runtime_blocks_unparsed_display_logic(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            provider="qq",
            provider_question_id="q1",
            provider_type="radio",
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
            logic_parse_status="unknown",
            option_texts=["C", "D"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)

    async def fake_fetch(*_args, **_kwargs):
        return "sess", {}, [
            {"id": "q1", "type": "radio", "options": [{"id": "o1", "text": "A"}, {"id": "o2", "text": "B"}], "page_id": "p1"},
            {"id": "q2", "type": "radio", "options": [{"id": "o3", "text": "C"}, {"id": "o4", "text": "D"}], "page_id": "p1"},
        ]

    async def fake_build_action(*_args, **_kwargs):
        raise AssertionError("未知显隐逻辑不该生成答案")

    monkeypatch.setattr(qq_http, "_fetch_submit_source", fake_fetch)
    monkeypatch.setattr(qq_http, "build_answer_action", fake_build_action)

    with pytest.raises(RuntimeError, match="第2题逻辑规则未完整解析"):
        await qq_http.brush_qq_http(config, state)


@pytest.mark.asyncio
async def test_qq_http_runtime_skips_description_metadata(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
    )
    config.questions_metadata = {
        5: SurveyQuestionMeta(
            num=5,
            title="模特A：无眼镜",
            provider="qq",
            provider_question_id="q5",
            provider_type="description",
            is_description=True,
        ),
        6: SurveyQuestionMeta(
            num=6,
            title="模特A评分",
            provider="qq",
            provider_question_id="q6",
            provider_type="matrix_star",
            type_code="6",
            option_texts=["1", "2"],
            row_texts=["专业"],
            options=2,
            rows=1,
        ),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []
    captured: dict[str, object] = {}

    async def fake_fetch(*_args, **_kwargs):
        return "sess", {}, [
            {"id": "q5", "type": "description", "title": "模特A", "page_id": "p1"},
            {
                "id": "q6",
                "type": "matrix_star",
                "options": [{"id": "o1", "text": "1"}, {"id": "o2", "text": "2"}],
                "sub_titles": [{"id": "r1", "text": "专业"}],
                "page_id": "p1",
            },
        ]

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        built_questions.append(int(question.num))
        return AnswerAction(
            question_num=int(question.num),
            question_id=str(question.provider_question_id),
            kind="matrix",
            matrix_indices=(0,),
            record_type="matrix",
        )

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(payload={"code": "OK"})

    monkeypatch.setattr(qq_http, "_fetch_submit_source", fake_fetch)
    monkeypatch.setattr(qq_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(qq_http.http_client, "apost", fake_post)

    ok = await qq_http.brush_qq_http(config, state)

    assert ok is True
    assert built_questions == [6]
    submitted_questions = captured["json"]["answer_survey"]["pages"][0]["questions"]
    assert [item["id"] for item in submitted_questions] == ["q6"]


@pytest.mark.asyncio
async def test_credamo_http_runtime_uses_proxy_and_posts_json(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.credamo.com/s/A73QR3ano",
        survey_provider="credamo",
        answer_duration_range_seconds=(70, 70),
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", provider="credamo", options=2, type_code="3"),
    }
    config.question_config_index_map = {1: ("single", 0)}
    config.single_prob = [[1.0, 0.0]]
    state = ExecutionState(config=config)
    captured = SimpleNamespace(fetch_proxy=None, post_kwargs=None)

    class FakeSession:
        def __init__(self, proxy_address=None):
            self.proxy_address = proxy_address

        async def __aenter__(self):
            captured.fetch_proxy = self.proxy_address
            return self

        async def __aexit__(self, *_args):
            return None

    async def fake_fetch(_session, *_args, headers, **_kwargs):
        assert "signature" in headers
        return {
            "blocks": [
                {
                    "blockElements": [
                        {
                            "qstId": "101",
                            "qstNo": "Q1",
                            "questionId": "q1",
                            "questionType": 2,
                            "selector": 1,
                            "choices": [{"choiceId": "11"}, {"choiceId": "12"}],
                        }
                    ]
                }
            ]
        }

    async def fake_init(_session, *_args, **_kwargs):
        return credamo_http._CredamoAnswerInit("answer-token", 1710000000000, "device-id")

    async def fake_save(_session, **kwargs):
        captured.post_kwargs = kwargs
        return {}

    monkeypatch.setattr(credamo_http, "_CredamoHttpSession", FakeSession)
    monkeypatch.setattr(credamo_http, "_fetch_detail", fake_fetch)
    monkeypatch.setattr(credamo_http, "_init_answer", fake_init)
    monkeypatch.setattr(credamo_http, "_save_answers", fake_save)
    monkeypatch.setattr(credamo_builders, "weighted_index", lambda _probs: 0)
    monkeypatch.setattr(credamo_http, "sample_answer_duration_seconds", lambda *_args, **_kwargs: 70.0)

    ok = await credamo_http.brush_credamo_http(
        config,
        state,
        proxy_address="http://1.1.1.1:80",
        user_agent="UA",
    )

    assert ok is True
    assert captured.fetch_proxy == "http://1.1.1.1:80"
    assert captured.post_kwargs["user_agent"] == "UA"
    assert captured.post_kwargs["init_data"].answer_token == "answer-token"
    assert captured.post_kwargs["init_data"].time_code == "device-id"
    assert captured.post_kwargs["body"]["shortUrl"] == "A73QR3ano"
    assert "answerToken" not in captured.post_kwargs["body"]
    assert captured.post_kwargs["body"]["answerStartTime"] == 1710000000000
    assert captured.post_kwargs["body"]["answerEndTime"] == 1710000070000
    assert "answerQstEeg" not in captured.post_kwargs["body"]["answerQstList"][0]
    assert captured.post_kwargs["body"]["answerQstList"][0]["answerTime"] == 70000
    assert captured.post_kwargs["body"]["answerQstList"][0]["answerQstChoice"]["choiceId"] == 11


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
    monkeypatch.setattr(wjx_builders, "resolve_option_fill_text_from_config", _async_result(None))

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
    monkeypatch.setattr(qq_builders, "resolve_option_fill_text_from_config", _async_result(None))

    dropdown_action = await qq_builders.build_answer_action(None, dropdown_question, state, psycho_plan=None)
    matrix_action = await qq_builders.build_answer_action(None, matrix_star_question, state, psycho_plan=None)

    assert dropdown_action is not None
    assert dropdown_action.kind == "select"
    assert dropdown_action.selected_indices == (1,)
    assert matrix_action is not None
    assert matrix_action.kind == "matrix"
    assert matrix_action.matrix_indices == (2,)


def test_credamo_builder_supports_dropdown_and_order_for_http(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="credamo")
    config.droplist_prob = [[0.0, 1.0, 0.0]]
    dropdown_question = SurveyQuestionMeta(num=1, title="Q1", provider="credamo", options=3)
    order_question = SurveyQuestionMeta(num=2, title="Q2", provider="credamo", options=3)

    monkeypatch.setattr(credamo_builders, "weighted_index", lambda _probs: 1)
    monkeypatch.setattr(credamo_builders.random, "shuffle", lambda items: items.reverse())

    dropdown_action = credamo_builders.build_answer_action(
        root_index=0,
        question_num=1,
        entry_type="dropdown",
        config_index=0,
        config=config,
        question_meta=dropdown_question,
    )
    order_action = credamo_builders.build_answer_action(
        root_index=1,
        question_num=2,
        entry_type="order",
        config_index=0,
        config=config,
        question_meta=order_question,
    )

    assert dropdown_action is not None
    assert dropdown_action.kind == "select"
    assert dropdown_action.record_type == "dropdown"
    assert dropdown_action.selected_indices == (1,)
    assert order_action is not None
    assert order_action.kind == "order"
    assert order_action.selected_indices == (2, 1, 0)


def test_wjx_submit_rejected_message_includes_question_title_and_display_num() -> None:
    config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
    config.questions_metadata = {
        10: SurveyQuestionMeta(num=10, display_num=8, title="年龄", type_code="1"),
    }

    with pytest.raises(RuntimeError, match=r"第8题（年龄）.*答案不符合要求"):
        wjx_http._raise_submit_rejected(config, "9〒10〒您提交的答案不符合要求，请检查并修改后重新提交！")


def test_wjx_submit_rejected_detects_submission_verification() -> None:
    config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")

    assert wjx_http.is_wjx_submission_verification_response("7〒需要安全校验，请重新提交！")
    assert not wjx_http.is_wjx_submission_verification_response("请先完成智能验证")
    assert not wjx_http.is_wjx_submission_verification_response("请先完成验证码校验后重新提交")

    with pytest.raises(SubmissionVerificationRequiredError, match="启用随机 IP"):
        wjx_http._raise_submit_rejected(config, "7〒需要安全校验，请重新提交！")


def test_wjx_submit_response_classifier_keeps_verification_strict() -> None:
    assert wjx_http.classify_wjx_submit_response("10〒/joinnew/complete.aspx") == wjx_http.WjxSubmitResult.SUCCESS
    assert wjx_http.classify_wjx_submit_response("success") == wjx_http.WjxSubmitResult.SUCCESS
    assert wjx_http.classify_wjx_submit_response("7〒需要安全校验，请重新提交！") == wjx_http.WjxSubmitResult.VERIFICATION
    assert wjx_http.classify_wjx_submit_response("请先完成智能验证") == wjx_http.WjxSubmitResult.REJECTED
    assert wjx_http.classify_wjx_submit_response("9〒10〒您提交的答案不符合要求，请检查并修改后重新提交！") == wjx_http.WjxSubmitResult.REJECTED


@pytest.mark.asyncio
async def test_wjx_http_runtime_converts_status_page_to_runtime_stop(monkeypatch) -> None:
    async def fake_get(*_args, **_kwargs):
        return _FakeResponse(text="<html><body>此问卷（123）已暂停，不能填写</body></html>")

    monkeypatch.setattr(wjx_http.http_client, "aget", fake_get)

    with pytest.raises(SurveyProviderUnavailableAtRuntimeError, match="问卷已暂停"):
        await wjx_http._load_wjx_page(
            "https://www.wjx.cn/vm/demo.aspx",
            headers={},
            proxies={},
        )


def test_qq_submit_payload_classifier_and_message() -> None:
    assert qq_http.classify_qq_submit_payload({"code": "OK"}) == qq_http.QqSubmitResult.SUCCESS
    assert qq_http.classify_qq_submit_payload({"code": "0"}) == qq_http.QqSubmitResult.SUCCESS
    assert qq_http.classify_qq_submit_payload({"code": "NEED_LOGIN", "message": "需要登录"}) == qq_http.QqSubmitResult.FAILED

    with pytest.raises(RuntimeError, match="需要登录"):
        qq_http._raise_qq_submit_failed({"code": "NEED_LOGIN", "message": "需要登录"})


def test_credamo_api_payload_classifier() -> None:
    assert credamo_http.classify_credamo_api_payload({"success": True}) == credamo_http.CredamoSubmitResult.SUCCESS
    assert credamo_http.classify_credamo_api_payload({"data": {}}) == credamo_http.CredamoSubmitResult.SUCCESS
    assert credamo_http.classify_credamo_api_payload({"success": False}) == credamo_http.CredamoSubmitResult.FAILED


def _async_result(value):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner
