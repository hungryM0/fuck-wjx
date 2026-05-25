from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from software.providers.answering import AnswerAction
from software.providers.contracts import SurveyQuestionMeta
from tencent.provider import http_runtime as qq_http
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

    assert submitdata == "1$1}2$1|3}3$甲||乙}4$2,3}5$66.0"


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
async def test_qq_http_runtime_uses_proxy_and_answer_session(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
        submit_enabled=True,
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
