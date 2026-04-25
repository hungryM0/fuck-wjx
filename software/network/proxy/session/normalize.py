"""随机 IP 会话数值与状态归一化。"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from .models import RandomIPAuthError, RandomIPSession


def _to_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return max(0, int(default))
    return max(0, parsed)

def _to_decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, Decimal):
        parsed = value
    else:
        try:
            text = str(value).strip()
        except Exception:
            return None
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
    if not parsed.is_finite():
        return None
    return parsed

def _to_non_negative_quota(value: Any, default: float = 0.0) -> float:
    parsed = _to_decimal(value)
    if parsed is None:
        parsed = _to_decimal(default)
    if parsed is None:
        parsed = Decimal("0")
    if parsed < 0:
        return 0.0
    return float(parsed)

def _to_optional_non_negative_quota(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    parsed = _to_decimal(value)
    if parsed is None or parsed < 0:
        return None
    return float(parsed)

def format_quota_value(value: Any) -> str:
    parsed = _to_decimal(value)
    if parsed is None or parsed < 0:
        parsed = Decimal("0")
    normalized = parsed.quantize(Decimal(1)) if parsed == parsed.to_integral() else parsed.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"

def _quota_equals(left: Any, right: Any, *, epsilon: float = 1e-9) -> bool:
    return abs(_to_non_negative_quota(left, 0.0) - _to_non_negative_quota(right, 0.0)) <= epsilon

def _is_valid_user_id(value: Any) -> bool:
    try:
        return int(value) > 0
    except Exception:
        return False

def _require_valid_user_id(value: Any) -> int:
    if not _is_valid_user_id(value):
        raise RandomIPAuthError("invalid_response:user_id_invalid")
    return int(value)

def _to_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None

def _can_trust_quota_numbers(*, total_quota: float, used_quota: float) -> bool:
    return _to_non_negative_quota(total_quota, 0.0) > 0 or _to_non_negative_quota(used_quota, 0.0) > 0

def _normalize_quota_known(
    *,
    user_id: Any,
    total_quota: float,
    used_quota: float,
    quota_known: Optional[bool],
) -> bool:
    if not _is_valid_user_id(user_id):
        return False
    if quota_known is False:
        return False
    return _can_trust_quota_numbers(total_quota=total_quota, used_quota=used_quota)

def _session_state_name(session: RandomIPSession) -> str:
    if _is_valid_user_id(session.user_id):
        return "ready"
    return "anonymous"

def _mask_identifier(value: Any, *, keep: int = 6) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    if len(text) <= keep:
        return text
    return f"{text[:keep]}***"

def _session_log_fields(session: RandomIPSession) -> str:
    remaining_quota, total_quota, used_quota = _normalize_quota_state(
        remaining_quota=session.remaining_quota,
        total_quota=session.total_quota,
        used_quota=session.used_quota,
    )
    return (
        f"state={_session_state_name(session)} "
        f"user_id={int(session.user_id or 0)} "
        f"device={_mask_identifier(session.device_id)} "
        f"remaining={format_quota_value(remaining_quota)} "
        f"total={format_quota_value(total_quota)} "
        f"used={format_quota_value(used_quota)} "
        f"quota_known={bool(session.quota_known)}"
    )

def _normalize_quota_state(
    *,
    remaining_quota: Any = None,
    total_quota: Any = None,
    used_quota: Any = None,
    default_total_quota: float = 0.0,
) -> tuple[float, float, float]:
    has_remaining = remaining_quota is not None
    has_used = used_quota is not None
    remaining = _to_non_negative_quota(remaining_quota, 0.0) if has_remaining else 0.0
    total = _to_non_negative_quota(total_quota, default_total_quota)
    if has_used:
        used = _to_non_negative_quota(used_quota, 0.0)
        total = max(total, used)
        remaining = max(0.0, total - used)
        return remaining, total, used
    if has_remaining:
        total = max(total, remaining)
        used = max(0.0, total - remaining)
        return remaining, total, used
    total = max(0.0, total)
    used = 0.0
    remaining = total
    return remaining, total, used

def _read_payload_quota_number(data: Dict[str, Any], key: str, *, log_context: str) -> Optional[float]:
    if key not in data:
        return None
    value = data.get(key)
    parsed = _to_optional_non_negative_quota(value)
    if parsed is not None:
        return parsed
    logging.warning("%s 中的额度字段无效：field=%s value=%r", log_context, key, value)
    return None

def _resolve_quota_from_payload(
    data: Dict[str, Any],
    *,
    fallback_session: Optional[RandomIPSession],
    log_context: str,
) -> tuple[float, float, float, bool]:
    fallback = fallback_session or RandomIPSession()
    fallback_remaining, fallback_total, fallback_used = _normalize_quota_state(
        remaining_quota=fallback.remaining_quota,
        total_quota=fallback.total_quota,
        used_quota=fallback.used_quota,
    )
    fallback_known = bool(fallback.quota_known)
    remaining_quota = _read_payload_quota_number(data, "remaining_quota", log_context=log_context)
    total_quota = _read_payload_quota_number(data, "total_quota", log_context=log_context)
    used_quota = _read_payload_quota_number(data, "used_quota", log_context=log_context)
    valid_count = sum(value is not None for value in (remaining_quota, total_quota, used_quota))
    quota_keys = ",".join(sorted(str(key) for key in data.keys()))

    candidate: Optional[tuple[float, float, float]] = None
    if valid_count >= 2:
        candidate = _normalize_quota_state(
            remaining_quota=remaining_quota,
            total_quota=total_quota,
            used_quota=used_quota,
            default_total_quota=fallback_total,
        )
    elif valid_count == 1 and fallback_known:
        if remaining_quota is not None:
            candidate = _normalize_quota_state(
                remaining_quota=remaining_quota,
                total_quota=fallback_total,
                default_total_quota=fallback_total,
            )
        elif total_quota is not None:
            candidate = _normalize_quota_state(
                total_quota=total_quota,
                used_quota=fallback_used,
                default_total_quota=total_quota,
            )
        elif used_quota is not None:
            candidate = _normalize_quota_state(
                total_quota=fallback_total,
                used_quota=used_quota,
                default_total_quota=fallback_total,
            )

    if candidate is not None:
        candidate_remaining, candidate_total, candidate_used = candidate
        if _can_trust_quota_numbers(total_quota=candidate_total, used_quota=candidate_used):
            return candidate_remaining, candidate_total, candidate_used, True
        logging.warning("%s 返回了 0/0 额度，保留本地额度并标记待校验：keys=%s", log_context, quota_keys)
        return fallback_remaining, fallback_total, fallback_used, False

    if valid_count <= 0:
        logging.warning("%s 未返回可信额度字段，保留本地额度并标记待校验：keys=%s", log_context, quota_keys)
    else:
        logging.warning("%s 只返回了部分额度字段且本地无可信额度，保留本地额度并标记待校验：keys=%s", log_context, quota_keys)
    return fallback_remaining, fallback_total, fallback_used, False

def _build_quota_snapshot(session: RandomIPSession) -> Dict[str, Any]:
    remaining_quota, total_quota, used_quota = _normalize_quota_state(
        remaining_quota=session.remaining_quota,
        total_quota=session.total_quota,
        used_quota=session.used_quota,
    )
    return {
        "used_quota": used_quota,
        "total_quota": total_quota,
        "remaining_quota": remaining_quota,
        "quota_known": bool(session.quota_known),
    }
