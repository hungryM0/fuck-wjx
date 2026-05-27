"""腾讯问卷原生 HTTP 答题提交。"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from typing import Any, Mapping

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS, DEFAULT_USER_AGENT
from software.core.modes.duration_control import sample_answer_duration_seconds
from software.core.persona.context import record_answer
from software.core.questions.distribution import record_pending_distribution_choice
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.answering import AnswerAction
from software.providers.answering.recording import record_answer_action
from software.providers.http_logic import build_http_logic_plan
from software.providers.http_progress import update_http_submit_step
from software.providers.contracts import SurveyQuestionMeta
from tencent.provider.answering_builders import build_answer_action
from tencent.provider.parser import (
    _build_qq_api_headers,
    _build_qq_survey_page_url,
    _ensure_qq_api_ok,
    _extract_qq_identifiers,
    _request_qq_api,
)


def _proxy_arg(proxy_address: str | None) -> Any:
    proxy = str(proxy_address or "").strip()
    return proxy if proxy else {}


def _headers(page_url: str, user_agent: str | None = None) -> dict[str, str]:
    headers = _build_qq_api_headers(page_url)
    headers["User-Agent"] = str(user_agent or "").strip() or DEFAULT_USER_AGENT
    return headers


def _metadata_by_provider_id(config: ExecutionConfig) -> dict[str, SurveyQuestionMeta]:
    result: dict[str, SurveyQuestionMeta] = {}
    for item in (config.questions_metadata or {}).values():
        if bool(getattr(item, "is_description", False)):
            continue
        question_id = str(getattr(item, "provider_question_id", "") or "").strip()
        if question_id:
            result[question_id] = item
    return result


def _raw_questions_by_id(questions: list[Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in questions:
        if not isinstance(item, Mapping):
            continue
        question_id = str(item.get("id") or "").strip()
        if question_id:
            result[question_id] = item
    return result


def _option_items(raw_question: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    options = raw_question.get("options")
    if not isinstance(options, list):
        return []
    return [item for item in options if isinstance(item, Mapping)]


def _option_answer(raw_option: Mapping[str, Any], *, checked: bool) -> dict[str, Any]:
    return {
        "id": str(raw_option.get("id") or "").strip(),
        "text": str(raw_option.get("text") or "").strip(),
        "checked": 1 if checked else 0,
    }


def _choice_question_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    selected = {int(item) for item in action.selected_indices}
    options = [
        _option_answer(option, checked=index in selected)
        for index, option in enumerate(_option_items(raw_question))
    ]
    return {
        "id": str(raw_question.get("id") or action.question_id).strip(),
        "type": str(raw_question.get("type") or "").strip(),
        "blanks": [],
        "options": options,
    }


def _text_question_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    text_values = [str(item or "").strip() for item in action.text_values if str(item or "").strip()]
    return {
        "id": str(raw_question.get("id") or action.question_id).strip(),
        "type": str(raw_question.get("type") or "text").strip(),
        "text": "\n".join(text_values),
    }


def _matrix_question_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    rows = raw_question.get("sub_titles")
    normalized_rows: list[dict[str, Any]] = []
    if isinstance(rows, list):
        option_template = _option_items(raw_question)
        for row_index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            selected_index = action.matrix_indices[row_index] if row_index < len(action.matrix_indices) else -1
            normalized_rows.append(
                {
                    "id": str(row.get("id") or "").strip(),
                    "text": str(row.get("text") or "").strip(),
                    "options": [
                        _option_answer(option, checked=index == int(selected_index))
                        for index, option in enumerate(option_template)
                    ],
                }
            )
    return {
        "id": str(raw_question.get("id") or action.question_id).strip(),
        "type": str(raw_question.get("type") or "").strip(),
        "sub_titles": normalized_rows,
    }


def _question_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    provider_type = str(raw_question.get("type") or "").strip()
    if action.kind == "text" or provider_type in {"text", "textarea", "number"}:
        return _text_question_answer(raw_question, action)
    if action.kind == "matrix" or provider_type.startswith("matrix_"):
        return _matrix_question_answer(raw_question, action)
    return _choice_question_answer(raw_question, action)


def _record_action(ctx: ExecutionState, action: AnswerAction) -> None:
    record_answer_action(
        ctx,
        action,
        record_answer_fn=record_answer,
        record_pending_distribution_choice_fn=record_pending_distribution_choice,
        default_fill_text="",
    )


async def _fetch_submit_source(
    survey_id: str,
    hash_value: str,
    *,
    headers: dict[str, str],
    proxies: Any,
) -> tuple[str, dict[str, Any], list[Any]]:
    session_payload = await _request_qq_api(survey_id, "session", hash_value=hash_value, headers=headers, proxies=proxies)
    session_data = _ensure_qq_api_ok(session_payload, "session")
    answer_session_id = str(session_data.get("answer_session_id") or "").strip()
    if answer_session_id:
        headers["X-Answer-Session"] = answer_session_id

    questions_payload = await _request_qq_api(
        survey_id,
        "questions",
        hash_value=hash_value,
        headers=headers,
        extra_params={"locale": "zhs"},
        proxies=proxies,
    )
    questions_data = _ensure_qq_api_ok(questions_payload, "questions")
    raw_questions = questions_data.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise RuntimeError("腾讯问卷题目接口未返回可提交题目")
    return answer_session_id, session_data, raw_questions


async def brush_qq_http(
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
    proxy_address: str | None = None,
    user_agent: str | None = None,
) -> bool:
    if stop_signal is not None and stop_signal.is_set():
        return False

    survey_id, hash_value = _extract_qq_identifiers(config.url)
    page_url = _build_qq_survey_page_url(survey_id, hash_value)
    headers = _headers(page_url, user_agent)
    proxies = _proxy_arg(proxy_address)
    answer_session_id, _session_data, raw_questions = await _fetch_submit_source(
        survey_id,
        hash_value,
        headers=headers,
        proxies=proxies,
    )

    metadata = _metadata_by_provider_id(config)
    raw_by_id = _raw_questions_by_id(raw_questions)
    questions = [
        question
        for raw_question in raw_questions
        for question_id in [str(raw_question.get("id") or "").strip() if isinstance(raw_question, Mapping) else ""]
        for question in [metadata.get(question_id)]
        if question is not None
    ]

    await update_http_submit_step(ctx, thread_name, "生成答案")
    for question in questions:
        if stop_signal is not None and stop_signal.is_set():
            return False
        if bool(getattr(question, "unsupported", False)):
            raise RuntimeError(f"腾讯问卷第{question.num}题暂不支持：{question.unsupported_reason or question.type_code}")

    async def _build_action(question: SurveyQuestionMeta) -> AnswerAction | None:
        if stop_signal is not None and stop_signal.is_set():
            return None
        return await build_answer_action(None, question, ctx, psycho_plan=psycho_plan)

    plan = await build_http_logic_plan(
        questions,
        build_action=_build_action,
    )
    actions = list(plan.actions)
    action_by_question_id = {
        str(action.question_id or "").strip(): action
        for action in actions
        if str(action.question_id or "").strip()
    }
    if not action_by_question_id:
        raise RuntimeError("腾讯问卷没有生成可提交答案")

    page_questions: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for raw_question in raw_questions:
        if stop_signal is not None and stop_signal.is_set():
            return False
        question_id = str(raw_question.get("id") or "").strip() if isinstance(raw_question, Mapping) else ""
        if not question_id:
            continue
        action = action_by_question_id.get(question_id)
        if action is None:
            continue
        raw_source = raw_by_id.get(question_id, raw_question)
        page_id = str((raw_source.get("page_id") if isinstance(raw_source, Mapping) else "") or "").strip() or "p-1-abcd"
        page_questions.setdefault(page_id, []).append(_question_answer(raw_source, action))

    if not page_questions:
        raise RuntimeError("腾讯问卷没有生成可提交答案")

    for action in actions:
        _record_action(ctx, action)

    try:
        duration = int(sample_answer_duration_seconds(config.answer_duration_range_seconds, survey_provider="qq") or 60)
    except Exception:
        duration = 60
    duration = max(1, duration)
    user_agent_value = str(user_agent or "").strip() or DEFAULT_USER_AGENT
    submit_body = {
        "survey_id": int(survey_id),
        "hash": hash_value,
        "answer_survey": {
            "duration": duration,
            "ua": user_agent_value,
            "referrer": "",
            "uid": str(uuid.uuid4()),
            "sid": str(uuid.uuid4()),
            "openid": "",
            "latitude": None,
            "longitude": None,
            "is_update": False,
            "locale": "zhs",
            "pages": [
                {
                    "id": page_id,
                    "questions": questions_on_page,
                }
                for page_id, questions_on_page in page_questions.items()
            ],
        },
    }
    if not bool(getattr(config, "submit_enabled", True)):
        logging.info("腾讯问卷 HTTP 单测已生成答案，未提交。")
        return True

    submit_headers = {
        **DEFAULT_HTTP_HEADERS,
        "User-Agent": user_agent_value,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://wj.qq.com",
        "Referer": page_url,
    }
    if answer_session_id:
        submit_headers["X-Answer-Session"] = answer_session_id
    await update_http_submit_step(ctx, thread_name, "提交问卷")
    response = await http_client.apost(
        f"https://wj.qq.com/api/v2/respondent/surveys/{survey_id}/answers",
        params={"pv_uid": str(uuid.uuid4()), "hash": hash_value, "_": str(int(time.time() * 1000))},
        json=submit_body,
        headers=submit_headers,
        timeout=20,
        proxies=proxies,
    )
    response.raise_for_status()
    await update_http_submit_step(ctx, thread_name, "校验结果")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("腾讯问卷提交返回了非 JSON 对象")
    code = str(payload.get("code") or "").upper()
    if code not in {"OK", "0"}:
        raise RuntimeError(f"腾讯问卷提交失败：{payload.get('code') or payload}")
    return True


__all__ = ["brush_qq_http"]
