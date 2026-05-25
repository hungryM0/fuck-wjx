"""问卷星原生 HTTP 答题提交。"""

from __future__ import annotations

import logging
import random
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS, DEFAULT_USER_AGENT, USER_AGENT_PRESETS
from software.core.modes.duration_control import sample_answer_duration_seconds
from software.core.persona.context import record_answer
from software.core.questions.distribution import record_pending_distribution_choice
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.answering import AnswerAction
from software.providers.answering.recording import record_answer_action
from software.providers.contracts import SurveyQuestionMeta
from wjx.provider.answering_builders import build_answer_action
from wjx.provider.parser import _parse_wjx_html


def _proxy_arg(proxy_address: str | None) -> Any:
    proxy = str(proxy_address or "").strip()
    return proxy if proxy else {}


def _shortid_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path or ""
    last = path.rstrip("/").rsplit("/", 1)[-1]
    shortid = last.replace(".aspx", "").strip()
    if not shortid:
        raise RuntimeError("问卷星链接缺少 shortid")
    return shortid


def _submit_domain(url: str) -> str:
    host = urlparse(str(url or "").strip()).netloc.lower()
    if "ks.wjx.com" in host:
        return "ks.wjx.com"
    return "v.wjx.cn"


def _format_wjx_starttime(timestamp_seconds: int) -> str:
    dt = datetime.fromtimestamp(int(timestamp_seconds))
    return f"{dt.year}/{dt.month}/{dt.day} {dt.hour}:{dt.minute}:{dt.second}"


def _wechat_user_agent(user_agent: str | None) -> str:
    text = str(user_agent or "").strip()
    if text:
        return text
    return str(USER_AGENT_PRESETS.get("wechat_android", {}).get("ua") or DEFAULT_USER_AGENT)


def _build_jqsign(jqnonce: str, ktimes: int) -> str:
    t_value = 1 if int(ktimes or 0) % 10 == 0 else int(ktimes or 0) % 10
    return "".join(chr(ord(ch) ^ t_value) for ch in jqnonce)


def _question_items(config: ExecutionConfig) -> list[SurveyQuestionMeta]:
    return sorted(
        list((config.questions_metadata or {}).values()),
        key=lambda item: (int(getattr(item, "page", 1) or 1), int(getattr(item, "num", 0) or 0)),
    )


def _format_selected_indices(indices: tuple[int, ...], *, option_fill_texts: tuple[tuple[int, str], ...] = ()) -> str:
    fills = {int(index): str(value or "").strip() for index, value in option_fill_texts if str(value or "").strip()}
    parts: list[str] = []
    for index in indices:
        value = str(int(index) + 1)
        fill = fills.get(int(index), "")
        if fill:
            value = f"{value}!{fill}"
        parts.append(value)
    return "|".join(parts)


def _submitdata_answer(action: AnswerAction) -> str:
    if action.kind in {"choice", "select"}:
        return _format_selected_indices(
            tuple(int(item) for item in action.selected_indices),
            option_fill_texts=action.option_fill_texts,
        )
    if action.kind == "text":
        return "||".join(str(item or "").strip() for item in action.text_values)
    if action.kind == "matrix":
        return ",".join(str(int(item) + 1) for item in action.matrix_indices)
    if action.kind == "slider":
        return str(action.slider_value if action.slider_value is not None else "")
    if action.kind == "order":
        return ",".join(str(int(item) + 1) for item in action.selected_indices)
    return ""


def _submitdata_from_actions(actions: list[AnswerAction]) -> str:
    parts: list[str] = []
    for action in actions:
        question_num = int(action.question_num or 0)
        answer = _submitdata_answer(action)
        if question_num <= 0 or not answer:
            continue
        answer = answer.replace("，", ",")
        parts.append(f"{question_num}${answer}")
    if not parts:
        raise RuntimeError("问卷星没有生成可提交答案")
    return "}".join(parts)


def _record_action(ctx: ExecutionState, action: AnswerAction) -> None:
    record_answer_action(
        ctx,
        action,
        record_answer_fn=record_answer,
        record_pending_distribution_choice_fn=record_pending_distribution_choice,
        default_fill_text="",
    )


async def _load_wjx_page(url: str, *, headers: dict[str, str], proxies: Any) -> None:
    response = await http_client.aget(url, timeout=15, headers=headers, proxies=proxies)
    response.raise_for_status()
    _parse_wjx_html(response.text)


async def _build_actions(
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    psycho_plan: Any,
    stop_signal: Any,
) -> list[AnswerAction]:
    actions: list[AnswerAction] = []
    for question in _question_items(config):
        if stop_signal is not None and stop_signal.is_set():
            return []
        if bool(getattr(question, "unsupported", False)):
            raise RuntimeError(f"问卷星第{question.num}题暂不支持：{question.unsupported_reason or question.type_code}")
        if bool(getattr(question, "has_jump", False)) or bool(getattr(question, "has_dependent_display_logic", False)):
            raise RuntimeError(f"问卷星第{question.num}题包含跳题/显隐逻辑，不能纯 HTTP 提交")
        action = await build_answer_action(None, question, ctx, psycho_plan=psycho_plan)
        if action is None:
            raise RuntimeError(f"问卷星第{question.num}题暂不支持纯 HTTP 提交")
        actions.append(action)
    return actions


def _sample_ktimes(config: ExecutionConfig) -> int:
    try:
        sampled = sample_answer_duration_seconds(config.answer_duration_range_seconds, survey_provider="wjx")
    except Exception:
        sampled = 0.0
    if sampled and sampled > 0:
        return max(1, int(round(sampled)))
    return random.randint(10, 20)


async def brush_wjx_http(
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
    proxy_address: str | None = None,
    user_agent: str | None = None,
) -> bool:
    del thread_name
    if stop_signal is not None and stop_signal.is_set():
        return False

    shortid = _shortid_from_url(config.url)
    proxies = _proxy_arg(proxy_address)
    user_agent_value = _wechat_user_agent(user_agent)
    headers = {
        **DEFAULT_HTTP_HEADERS,
        "User-Agent": user_agent_value,
        "Referer": config.url,
    }
    await _load_wjx_page(config.url, headers=headers, proxies=proxies)

    actions = await _build_actions(config, ctx, psycho_plan=psycho_plan, stop_signal=stop_signal)
    if not actions:
        return False
    for action in actions:
        _record_action(ctx, action)
    submitdata = _submitdata_from_actions(actions)
    if not bool(getattr(config, "submit_enabled", True)):
        logging.info("问卷星 HTTP 单测已生成答案，未提交。")
        return True

    current_ms = int(time.time() * 1000)
    ktimes = _sample_ktimes(config)
    start_seconds = int(current_ms / 1000) - ktimes
    jqnonce = str(uuid.uuid4())
    domain = _submit_domain(config.url)
    submit_url = f"https://{domain}/joinnew/processjq.ashx"
    params = {
        "shortid": shortid,
        "starttime": _format_wjx_starttime(start_seconds),
        "cst": str(start_seconds * 1000),
        "source": "directphone",
        "submittype": "1",
        "ktimes": str(ktimes),
        "rn": str(2000000000 + random.random() * 100000000),
        "jcn": shortid,
        "nw": "1",
        "jwt": "4",
        "jpm": "62",
        "capt": "2",
        "t": str(current_ms),
        "wxfs": "100",
        "jqnonce": jqnonce,
        "jqsign": _build_jqsign(jqnonce, ktimes),
        "access_token": "1",
        "openid": str(random.randint(100000000, 999999999)),
        "unionId": str(random.randint(100000000, 999999999)),
        "wxappid": "wx8fe84c5d52db247a",
        "iwx": "1",
    }
    response = await http_client.apost(
        submit_url,
        params=params,
        data={"submitdata": submitdata, "sceneId": "q0hcfsca"},
        headers={
            **headers,
            "Accept": "text/plain, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": f"https://{domain}",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=20,
        proxies=proxies,
    )
    response.raise_for_status()
    response_text = str(response.text or "").strip()
    lowered = response_text.lower()
    success = (
        "complete.aspx" in lowered
        or "success" in lowered
        or lowered.startswith("10")
        or lowered in {"1", "ok"}
    )
    failure = any(token in response_text for token in ("抱歉", "不符合", "错误", "重新提交", "验证码"))
    if not success or failure:
        raise RuntimeError(f"问卷星提交被拒绝：{response_text[:200]}")
    return True


__all__ = ["brush_wjx_http"]
