"""Helpers for structured user-facing action logs."""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Mapping, Optional


def _normalize_token(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    return "_".join(text.split())


def _normalize_payload_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return "_".join(text.split())


def _normalize_payload(payload: Optional[Mapping[str, Any]]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not isinstance(payload, Mapping):
        return normalized
    for key, value in payload.items():
        normalized_key = _normalize_token(key, "field").lower()
        normalized_value = _normalize_payload_value(value)
        if normalized_key and normalized_value:
            normalized[normalized_key] = normalized_value
    return normalized


def _normalize_detail(detail: Any) -> str:
    text = str(detail or "").replace("\r", " ").replace("\n", " ").strip()
    return " ".join(text.split())


def log_action(
    scope: str,
    event: str,
    target: str,
    page: str,
    *,
    result: str = "requested",
    level: int = logging.INFO,
    detail: Any = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> None:
    """Emit a structured action log using stable key-value fields."""

    normalized_scope = _normalize_token(scope, "UI").upper()
    normalized_event = _normalize_token(event, "unknown").lower()
    normalized_target = _normalize_token(target, "unknown").lower()
    normalized_page = _normalize_token(page, "unknown").lower()
    normalized_result = _normalize_token(result, "unknown").lower()
    normalized_payload = _normalize_payload(payload)
    normalized_detail = _normalize_detail(detail)

    message_parts = [
        f"[{normalized_scope}]",
        f"event={normalized_event}",
        f"target={normalized_target}",
        f"page={normalized_page}",
        f"result={normalized_result}",
    ]
    message_parts.extend(
        f"{key}={value}" for key, value in normalized_payload.items()
    )
    if normalized_detail:
        escaped_detail = normalized_detail.replace('"', "'")
        message_parts.append(f'detail="{escaped_detail}"')

    extra: dict[str, Any] = {
        "event": normalized_event,
        "target": normalized_target,
        "page": normalized_page,
        "result": normalized_result,
        "log_scope": normalized_scope,
    }
    if normalized_payload:
        extra["event_payload"] = dict(normalized_payload)

    logging.log(level, " ".join(message_parts), extra=extra)


def bind_logged_action(
    signal: Any,
    callback: Callable[..., Any],
    *,
    scope: str,
    event: str,
    target: str,
    page: str,
    result: str = "requested",
    level: int = logging.INFO,
    detail: Any = None,
    payload_factory: Optional[Callable[..., Optional[Mapping[str, Any]]]] = None,
    forward_signal_args: bool = True,
) -> Callable[..., Any]:
    """Wrap a Qt signal connection so the user action is logged before execution."""

    @functools.wraps(callback)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        payload: Optional[Mapping[str, Any]] = None
        if payload_factory is not None:
            try:
                payload = payload_factory(*args, **kwargs)
            except Exception as exc:
                logging.debug("bind_logged_action payload_factory failed: %s", exc, exc_info=True)
        log_action(
            scope,
            event,
            target,
            page,
            result=result,
            level=level,
            detail=detail,
            payload=payload,
        )
        if forward_signal_args:
            return callback(*args, **kwargs)
        return callback()

    signal.connect(_wrapped)
    return _wrapped

