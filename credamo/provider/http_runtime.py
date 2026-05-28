"""Credamo 原生 HTTP 答题提交。"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
from software.app.config import DEFAULT_HTTP_HEADERS, DEFAULT_USER_AGENT
from software.core.modes.duration_control import sample_answer_duration_seconds
from software.core.persona.context import record_answer
from software.core.questions.distribution import record_pending_distribution_choice
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.answering import AnswerAction
from software.providers.answering.recording import record_answer_action
from software.providers.contracts import SurveyQuestionMeta
from software.providers.http_logic import build_http_logic_plan
from software.providers.http_progress import update_http_submit_step

from .answering_builders import build_answer_action

_CIPHER = "P96D0A7D0M8C3R2D0M1"
_RANDOM_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
_DEFAULT_ORIGIN = "https://www.credamo.com"
_RESOLUTION = "1920px*1080px"


@dataclass(frozen=True)
class _CredamoAnswerInit:
    answer_token: str
    timestamp_ms: int
    time_code: str


class CredamoSubmitResult:
    SUCCESS = "success"
    FAILED = "failed"


class _CredamoHttpSession:
    def __init__(self, proxy_address: str | None = None) -> None:
        self.proxy_address = str(proxy_address or "").strip()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "_CredamoHttpSession":
        self._client = httpx.AsyncClient(
            proxy=_resolve_httpx_proxy(self.proxy_address),
            follow_redirects=True,
            trust_env=not bool(self.proxy_address),
            timeout=None,
        )
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("见数 HTTP 会话尚未启动")
        return self._client

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._ensure_client().get(url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._ensure_client().post(url, **kwargs)


def _resolve_httpx_proxy(proxy_address: str) -> str | None:
    proxy = str(proxy_address or "").strip()
    return proxy if proxy else None


def _origin_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return _DEFAULT_ORIGIN


def _short_url_from_url(url: str) -> str:
    text = str(url or "").strip()
    parsed = urlparse(text)
    candidates = [parsed.path, parsed.fragment, text]
    for candidate in candidates:
        clean = str(candidate or "").strip().lstrip("#").split("?", 1)[0].rstrip("/")
        if not clean:
            continue
        parts = [part for part in clean.split("/") if part]
        if "s" in parts:
            index = parts.index("s")
            if index + 1 < len(parts):
                return parts[index + 1].strip()
        if re.fullmatch(r"[A-Za-z0-9_]+(?:ano)?", clean):
            return clean
    raise RuntimeError("见数链接缺少短链接编号")


def _noauth_short_url(short_url: str) -> str:
    short = str(short_url or "").strip().rstrip("/")
    if short.endswith("_"):
        return f"{short[:-1]}ano"
    if short.endswith("ano"):
        return short
    raise RuntimeError("见数 HTTP 目前只支持免登录短链接")


def _answer_page_url(origin: str, short_url: str) -> str:
    return f"{origin.rstrip('/')}/answer.html#/s/{short_url}"


def _sha1_upper(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest().upper()


def _random_token(length: int) -> str:
    return "".join(random.choice(_RANDOM_CHARS) for _ in range(max(1, int(length or 1))))


def _new_time_code() -> str:
    return uuid.uuid4().hex


def _build_signature_headers(
    *,
    answer_token: str = "",
    union_id: str | None = None,
    nonce: str | None = None,
    timestamp_ms: int | str | None = None,
) -> dict[str, str]:
    token = str(answer_token or "")
    union = str(union_id or _random_token(10))
    nonce_value = str(nonce or _random_token(16))
    timestamp = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
    inner = _sha1_upper(f"{token}{nonce_value}{timestamp}{union}{_CIPHER}")
    signature = _sha1_upper(f"{token}{nonce_value}{timestamp}{inner}{union}{_CIPHER}")
    return {
        "unionId": union,
        "nonce": nonce_value,
        "timestamp": timestamp,
        "signature": signature,
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def _request_headers(
    *,
    origin: str,
    short_url: str,
    user_agent: str | None = None,
    answer_token: str = "",
    json_body: bool = False,
) -> dict[str, str]:
    headers = {
        **DEFAULT_HTTP_HEADERS,
        "User-Agent": str(user_agent or "").strip() or DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": _answer_page_url(origin, short_url),
        **_build_signature_headers(answer_token=answer_token),
    }
    if json_body:
        headers["Origin"] = origin.rstrip("/")
        headers["Content-Type"] = "application/json"
    return headers


def _json_payload(response: Any, label: str) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except Exception:
        response.raise_for_status()
        raise RuntimeError(f"见数{label}接口返回了非 JSON 内容")
    if getattr(response, "is_error", False):
        message = ""
        if isinstance(payload, Mapping):
            message = str(payload.get("message") or payload.get("msg") or payload.get("code") or "").strip()
        if message:
            raise RuntimeError(f"见数{label}失败：{message}")
        response.raise_for_status()
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"见数{label}接口返回了非 JSON 对象")
    return payload


def _ensure_api_ok(payload: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    if classify_credamo_api_payload(payload) != CredamoSubmitResult.SUCCESS:
        message = str(payload.get("message") or payload.get("msg") or payload.get("code") or payload).strip()
        raise RuntimeError(f"见数{label}失败：{message}")
    data = payload.get("data")
    return data if isinstance(data, Mapping) else payload


def classify_credamo_api_payload(payload: Mapping[str, Any]) -> str:
    if payload.get("success") is False:
        return CredamoSubmitResult.FAILED
    return CredamoSubmitResult.SUCCESS


async def _fetch_detail(
    session: _CredamoHttpSession,
    *,
    origin: str,
    short_url: str,
    headers: dict[str, str],
) -> Mapping[str, Any]:
    response = await session.get(
        f"{origin.rstrip('/')}/v1/survey/noauth/detail/get/{short_url}",
        headers=headers,
        timeout=20,
    )
    return _ensure_api_ok(_json_payload(response, "详情"), "详情")


async def _init_answer(
    session: _CredamoHttpSession,
    *,
    origin: str,
    short_url: str,
    time_code: str,
    headers: dict[str, str],
) -> _CredamoAnswerInit:
    response = await session.get(
        f"{origin.rstrip('/')}/v1/survey/answer/noauth/init/{short_url}",
        params={
            "timeCode": time_code,
            "accountCode": "CDM",
            "resolution": _RESOLUTION,
        },
        headers=headers,
        timeout=20,
    )
    data = _ensure_api_ok(_json_payload(response, "初始化"), "初始化")
    answer_token = str(data.get("answerToken") or "").strip()
    if not answer_token:
        raise RuntimeError("见数初始化接口未返回 answerToken")
    try:
        timestamp_ms = int(data.get("timestamp") or int(time.time() * 1000))
    except Exception:
        timestamp_ms = int(time.time() * 1000)
    return _CredamoAnswerInit(
        answer_token=answer_token,
        timestamp_ms=timestamp_ms,
        time_code=time_code,
    )


def _as_mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _iter_raw_questions(detail_data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    direct_questions = _as_mapping_list(detail_data.get("questions"))
    if direct_questions:
        result.extend(direct_questions)
    for block in _as_mapping_list(detail_data.get("blocks")):
        for element in _as_mapping_list(block.get("blockElements") or block.get("elements")):
            candidates = [
                element.get("question"),
                element.get("qst"),
                element.get("surveyQuestion"),
                element,
            ]
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                if candidate.get("qstId") or candidate.get("questionId") or candidate.get("questionType"):
                    result.append(candidate)
                    break
    return result


def _raw_question_num(raw_question: Mapping[str, Any], fallback_num: int) -> int:
    for key in ("qstNo", "questionNo", "qstNum", "sortNo"):
        match = re.search(r"\d+", str(raw_question.get(key) or ""))
        if match:
            return max(1, int(match.group(0)))
    return max(1, int(fallback_num or 1))


def _raw_questions_by_num(raw_questions: list[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    for index, raw_question in enumerate(raw_questions, start=1):
        result[_raw_question_num(raw_question, index)] = raw_question
    return result


def _raw_question_type(raw_question: Mapping[str, Any]) -> int:
    try:
        return int(raw_question.get("questionType") or 0)
    except Exception:
        return 0


def _raw_selector(raw_question: Mapping[str, Any]) -> int:
    try:
        return int(raw_question.get("selector") or 0)
    except Exception:
        return 0


def _raw_provider_type(raw_question: Mapping[str, Any]) -> str:
    question_type = _raw_question_type(raw_question)
    selector = _raw_selector(raw_question)
    if question_type == 2 and selector == 2:
        return "multiple"
    if question_type == 2 and selector == 3:
        return "dropdown"
    if question_type == 2:
        return "single"
    if question_type == 4:
        return "matrix"
    if question_type == 6:
        return "order"
    if question_type == 11:
        return "scale"
    if question_type == 1:
        return "text"
    return str(question_type or "")


def _raw_option_count(raw_question: Mapping[str, Any]) -> int:
    question_type = _raw_question_type(raw_question)
    if question_type == 4:
        return len(_as_mapping_list(raw_question.get("answers")))
    if question_type == 1:
        return 1
    return len(_as_mapping_list(raw_question.get("choices")))


def _raw_row_count(raw_question: Mapping[str, Any]) -> int:
    if _raw_question_type(raw_question) == 4:
        return max(1, len(_as_mapping_list(raw_question.get("choices"))))
    return 1


def _enrich_question_meta(question: SurveyQuestionMeta, raw_question: Mapping[str, Any]) -> SurveyQuestionMeta:
    question_id = str(raw_question.get("questionId") or raw_question.get("qstId") or question.provider_question_id or "").strip()
    return replace(
        question,
        options=_raw_option_count(raw_question) or int(getattr(question, "options", 0) or 0),
        rows=_raw_row_count(raw_question) or int(getattr(question, "rows", 1) or 1),
        provider_question_id=question_id,
        provider_type=_raw_provider_type(raw_question) or str(getattr(question, "provider_type", "") or ""),
    )


def _question_items(
    config: ExecutionConfig,
    raw_by_num: Mapping[int, Mapping[str, Any]],
) -> list[SurveyQuestionMeta]:
    questions: list[SurveyQuestionMeta] = []
    for question in sorted(
        list((config.questions_metadata or {}).values()),
        key=lambda item: (int(getattr(item, "page", 1) or 1), int(getattr(item, "num", 0) or 0)),
    ):
        question_num = int(getattr(question, "num", 0) or 0)
        raw_question = raw_by_num.get(question_num)
        if raw_question is None:
            raise RuntimeError(f"见数第{question_num}题未在接口详情中找到，无法纯 HTTP 提交")
        questions.append(_enrich_question_meta(question, raw_question))
    return questions


def _config_entry_for_question(config: ExecutionConfig, question: SurveyQuestionMeta) -> tuple[str, int] | None:
    question_num = int(getattr(question, "num", 0) or 0)
    entry = (config.question_config_index_map or {}).get(question_num)
    if entry is not None:
        return entry
    provider_id = str(getattr(question, "provider_question_id", "") or "").strip()
    if provider_id:
        return (config.provider_question_config_index_map or {}).get(provider_id)
    return None


async def _build_actions(
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    raw_by_num: Mapping[int, Mapping[str, Any]],
    psycho_plan: Any,
    stop_signal: Any,
) -> list[AnswerAction]:
    questions = _question_items(config, raw_by_num)
    for question in questions:
        if stop_signal is not None and stop_signal.is_set():
            return []
        if bool(getattr(question, "unsupported", False)):
            raise RuntimeError(f"见数第{question.num}题暂不支持：{question.unsupported_reason or question.type_code}")

    async def _build_action(question: SurveyQuestionMeta) -> AnswerAction | None:
        if stop_signal is not None and stop_signal.is_set():
            return None
        entry = _config_entry_for_question(config, question)
        if entry is None:
            return None
        entry_type, config_index = entry
        return build_answer_action(
            root_index=int(getattr(question, "num", 0) or 0) - 1,
            question_num=int(getattr(question, "num", 0) or 0),
            entry_type=str(entry_type or ""),
            config_index=int(config_index or 0),
            config=config,
            question_meta=question,
            psycho_plan=psycho_plan,
        )

    plan = await build_http_logic_plan(
        questions,
        build_action=_build_action,
    )
    return list(plan.actions)


def _record_action(ctx: ExecutionState, action: AnswerAction) -> None:
    record_answer_action(
        ctx,
        action,
        record_answer_fn=record_answer,
        record_pending_distribution_choice_fn=record_pending_distribution_choice,
        default_fill_text="",
    )


def _normalize_id(value: Any) -> Any:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return int(text)
    except Exception:
        return text


def _sort_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _id_from_mapping(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return _normalize_id(value)
    return ""


def _selected_item(items: list[Mapping[str, Any]], index: int, *, question_num: int, label: str) -> Mapping[str, Any]:
    selected_index = int(index)
    if selected_index < 0 or selected_index >= len(items):
        raise RuntimeError(f"见数第{question_num}题{label}索引越界")
    return items[selected_index]


def _choice_payload(raw_choice: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "choiceId": _id_from_mapping(raw_choice, "choiceId", "id"),
        "choiceContent": "",
    }


def _normalized_choice_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def _choice_index_by_text(choices: list[Mapping[str, Any]], target_text: str) -> int | None:
    normalized_target = _normalized_choice_text(target_text)
    if not normalized_target:
        return None
    for index, choice in enumerate(choices):
        for key in ("display", "choiceContent", "choiceTitle", "content", "text"):
            if _normalized_choice_text(choice.get(key)) == normalized_target:
                return index
    return None


def _forced_index_from_config(
    config: ExecutionConfig | None,
    action: AnswerAction,
    choices: list[Mapping[str, Any]],
) -> int | None:
    if config is None:
        return None
    try:
        question = (config.questions_metadata or {}).get(int(action.question_num or 0))
    except Exception:
        question = None
    if question is None:
        return None
    forced_text = str(getattr(question, "forced_option_text", "") or "").strip()
    by_text = _choice_index_by_text(choices, forced_text)
    if by_text is not None:
        return by_text
    forced_index = getattr(question, "forced_option_index", None)
    if forced_index is None:
        return None
    try:
        index = int(forced_index)
    except Exception:
        return None
    if 0 <= index < len(choices):
        return index
    return None


def _selected_choice_index(
    choices: list[Mapping[str, Any]],
    action: AnswerAction,
    *,
    config: ExecutionConfig | None = None,
) -> int:
    forced = _forced_index_from_config(config, action, choices)
    if forced is not None:
        return forced
    return int(action.selected_indices[0] if action.selected_indices else 0)


def _choice_answer(
    raw_question: Mapping[str, Any],
    action: AnswerAction,
    *,
    config: ExecutionConfig | None = None,
) -> dict[str, Any]:
    choices = _as_mapping_list(raw_question.get("choices"))
    question_num = int(action.question_num or 0)
    question_type = _raw_question_type(raw_question)
    selector = _raw_selector(raw_question)
    item: dict[str, Any] = {
        "qstId": _id_from_mapping(raw_question, "qstId", "id"),
        "answerTime": 0,
        "answerQstEeg": None,
        "answerContent": "",
    }
    if selector == 2 or action.kind == "multiple":
        item["answerQstChoiceList"] = [
            _choice_payload(_selected_item(choices, int(index), question_num=question_num, label="选项"))
            for index in action.selected_indices
        ]
    else:
        selected_index = _selected_choice_index(choices, action, config=config)
        item["answerQstChoice"] = _choice_payload(
            _selected_item(choices, selected_index, question_num=question_num, label="选项")
        )
    try:
        sub_selector = int(raw_question.get("subSelector") or 0)
    except Exception:
        sub_selector = 0
    if question_type == 2 and sub_selector > 0:
        item["questionType"] = 2
        item["subSelector"] = sub_selector
    return item


def _scale_answer(
    raw_question: Mapping[str, Any],
    action: AnswerAction,
    *,
    config: ExecutionConfig | None = None,
) -> dict[str, Any]:
    choices = _as_mapping_list(raw_question.get("choices"))
    selected_index = _selected_choice_index(choices, action, config=config)
    return {
        "qstId": _id_from_mapping(raw_question, "qstId", "id"),
        "answerTime": 0,
        "answerQstEeg": None,
        "answerQstChoice": _choice_payload(
            _selected_item(choices, selected_index, question_num=int(action.question_num or 0), label="选项")
        ),
    }


def _matrix_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    rows = _as_mapping_list(raw_question.get("choices"))
    columns = _as_mapping_list(raw_question.get("answers"))
    question_num = int(action.question_num or 0)
    answer_rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        if row_index >= len(action.matrix_indices):
            continue
        selected_col = int(action.matrix_indices[row_index])
        column = _selected_item(columns, selected_col, question_num=question_num, label="矩阵列")
        answer_rows.append(
            {
                "choiceId": _id_from_mapping(row, "choiceId", "id"),
                "choiceAnswerList": [{"answerId": _id_from_mapping(column, "answerId", "id")}],
            }
        )
    if not answer_rows:
        raise RuntimeError(f"见数第{question_num}题没有生成矩阵答案")
    return {
        "qstId": _id_from_mapping(raw_question, "qstId", "id"),
        "answerTime": 0,
        "answerQstEeg": None,
        "answerContent": "",
        "answerQstChoiceList": answer_rows,
    }


def _order_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    choices = _as_mapping_list(raw_question.get("choices"))
    question_num = int(action.question_num or 0)
    ranked: list[dict[str, Any]] = []
    for rank, selected_index in enumerate(action.selected_indices, start=1):
        choice = _selected_item(choices, int(selected_index), question_num=question_num, label="排序选项")
        ranked.append(
            {
                "choiceId": _id_from_mapping(choice, "choiceId", "id"),
                "choiceContent": rank,
            }
        )
    if not ranked:
        raise RuntimeError(f"见数第{question_num}题没有生成排序答案")
    return {
        "qstId": _id_from_mapping(raw_question, "qstId", "id"),
        "answerTime": 0,
        "answerQstEeg": None,
        "answerContent": "",
        "answerChoiceContent": ranked,
    }


def _text_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    text_values = [str(item or "").strip() for item in action.text_values if str(item or "").strip()]
    return {
        "qstId": _id_from_mapping(raw_question, "qstId", "id"),
        "answerTime": 0,
        "answerQstEeg": None,
        "answerContent": "\n".join(text_values),
    }


def _question_answer(
    raw_question: Mapping[str, Any],
    action: AnswerAction,
    *,
    config: ExecutionConfig | None = None,
) -> dict[str, Any]:
    question_type = _raw_question_type(raw_question)
    if question_type == 1 or action.kind in {"text", "multi_text"}:
        return _text_answer(raw_question, action)
    if question_type == 2 or action.kind in {"single", "multiple", "select"}:
        return _choice_answer(raw_question, action, config=config)
    if question_type == 11 or action.kind == "scale":
        return _scale_answer(raw_question, action, config=config)
    if question_type in {4, 25} or action.kind == "matrix":
        return _matrix_answer(raw_question, action)
    if question_type == 6 or action.kind == "order":
        return _order_answer(raw_question, action)
    raise RuntimeError(f"见数第{action.question_num}题类型暂不支持纯 HTTP 提交：{question_type}")


def _answer_payload_items(
    raw_by_num: Mapping[int, Mapping[str, Any]],
    actions: list[AnswerAction],
    *,
    config: ExecutionConfig | None = None,
    answer_duration_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    per_question_time = 0
    if actions:
        per_question_time = max(1, int(round((float(answer_duration_seconds or 0.0) * 1000) / len(actions))))
    result: list[dict[str, Any]] = []
    for action in actions:
        question_num = int(action.question_num or 0)
        raw_question = raw_by_num.get(question_num)
        if raw_question is None:
            raise RuntimeError(f"见数第{question_num}题缺少接口题目数据")
        item = _question_answer(raw_question, action, config=config)
        item["answerTime"] = per_question_time
        item["_sortNo"] = _sort_value(raw_question.get("sortNo"), fallback=len(result) + 1)
        result.append(item)
    result.sort(key=lambda item: _sort_value(item.get("_sortNo"), fallback=0))
    for item in result:
        item.pop("_sortNo", None)
    return result


def _sample_duration_seconds(config: ExecutionConfig) -> float:
    try:
        sampled = sample_answer_duration_seconds(
            config.answer_duration_range_seconds,
            survey_provider="credamo",
            default_unconfigured_seconds=90,
        )
    except Exception:
        sampled = 0.0
    sampled_seconds = max(0.0, float(sampled or 0.0))
    if sampled_seconds > 0:
        return sampled_seconds
    return 90.0


def _sample_answer_start_time_ms(
    config: ExecutionConfig,
    *,
    init_started_at_ms: int,
    duration_seconds: float,
) -> int:
    window_start_ms, window_end_ms = getattr(config, "answer_datetime_window_ms", (0, 0))
    if window_start_ms <= 0 or window_end_ms <= window_start_ms:
        return int(init_started_at_ms)
    duration_ms = max(1, int(round(float(duration_seconds or 0.0) * 1000)))
    latest_start_ms = int(window_end_ms - duration_ms)
    earliest_start_ms = int(window_start_ms)
    if latest_start_ms <= earliest_start_ms:
        return earliest_start_ms
    return random.randint(earliest_start_ms, latest_start_ms)


def _build_submit_body(
    *,
    short_url: str,
    raw_by_num: Mapping[int, Mapping[str, Any]],
    actions: list[AnswerAction],
    config: ExecutionConfig | None = None,
    answer_started_at_ms: int | None = None,
    duration_seconds: float,
) -> dict[str, Any]:
    started_at = int(answer_started_at_ms or int(time.time() * 1000))
    duration_ms = max(1, int(round(float(duration_seconds or 0.0) * 1000)))
    ended_at = started_at + duration_ms
    body = {
        "answerStartTime": started_at,
        "answerEndTime": ended_at,
        "status": 1,
        "answerQstList": _answer_payload_items(
            raw_by_num,
            actions,
            config=config,
            answer_duration_seconds=duration_seconds,
        ),
        "shortUrl": short_url,
        "resolution": _RESOLUTION,
        "sourceDetail": 1,
    }
    for item in body["answerQstList"]:
        if isinstance(item, dict) and item.get("answerQstEeg") is None:
            item.pop("answerQstEeg", None)
    return body


async def _save_answers(
    session: _CredamoHttpSession,
    *,
    origin: str,
    short_url: str,
    init_data: _CredamoAnswerInit,
    body: dict[str, Any],
    user_agent: str | None,
) -> Mapping[str, Any]:
    answer_token = init_data.answer_token
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    response = await session.post(
        (
            f"{origin.rstrip('/')}/v1/survey/answer/noauth/save"
            f"?timeCode={init_data.time_code}&answerToken={answer_token}"
        ),
        content=content,
        headers=_request_headers(
            origin=origin,
            short_url=short_url,
            user_agent=user_agent,
            answer_token=answer_token,
            json_body=True,
        ),
        timeout=20,
    )
    payload = _json_payload(response, "提交")
    return _ensure_api_ok(payload, "提交")


async def brush_credamo_http(
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

    origin = _origin_from_url(config.url)
    short_url = _noauth_short_url(_short_url_from_url(config.url))
    user_agent_value = str(user_agent or "").strip() or DEFAULT_USER_AGENT
    base_headers = _request_headers(
        origin=origin,
        short_url=short_url,
        user_agent=user_agent_value,
    )
    async with _CredamoHttpSession(proxy_address) as session:
        detail_data = await _fetch_detail(
            session,
            origin=origin,
            short_url=short_url,
            headers=base_headers,
        )
        raw_questions = _iter_raw_questions(detail_data)
        if not raw_questions:
            raise RuntimeError("见数详情接口未返回可提交题目")
        raw_by_num = _raw_questions_by_num(raw_questions)

        await update_http_submit_step(ctx, thread_name, "生成答案")
        actions = await _build_actions(
            config,
            ctx,
            raw_by_num=raw_by_num,
            psycho_plan=psycho_plan,
            stop_signal=stop_signal,
        )
        if not actions:
            return False
        for action in actions:
            _record_action(ctx, action)

        duration_seconds = _sample_duration_seconds(config)
        if not bool(getattr(config, "submit_enabled", True)):
            logging.info("见数 HTTP 单测已生成答案，未提交。")
            return True

        if stop_signal is not None and stop_signal.is_set():
            return False
        await update_http_submit_step(ctx, thread_name, "提交问卷")
        time_code = _new_time_code()
        init_data = await _init_answer(
            session,
            origin=origin,
            short_url=short_url,
            time_code=time_code,
            headers=_request_headers(origin=origin, short_url=short_url, user_agent=user_agent_value),
        )
        body = _build_submit_body(
            short_url=short_url,
            raw_by_num=raw_by_num,
            actions=actions,
            config=config,
            answer_started_at_ms=_sample_answer_start_time_ms(
                config,
                init_started_at_ms=init_data.timestamp_ms,
                duration_seconds=duration_seconds,
            ),
            duration_seconds=duration_seconds,
        )
        await _save_answers(
            session,
            origin=origin,
            short_url=short_url,
            init_data=init_data,
            body=body,
            user_agent=user_agent_value,
        )
        await update_http_submit_step(ctx, thread_name, "校验结果")
    return True


__all__ = ["CredamoSubmitResult", "brush_credamo_http", "classify_credamo_api_payload"]
