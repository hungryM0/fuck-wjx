"""联系表单发送前校验。"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from software.ui.helpers.contact_api import format_quota_value

from .constants import DONATION_AMOUNT_BLOCK_MESSAGE, MAX_REQUEST_QUOTA
from .rules import is_amount_allowed, normalize_quantity_text, parse_quantity_value


@dataclass(frozen=True)
class QuotaRequestValidationInputs:
    email: str
    amount_text: str
    quantity_text: str
    payment_method: str
    donated: bool


@dataclass(frozen=True)
class QuotaRequestValidationResult:
    error_message: Optional[str]
    normalized_quota_text: str
    amount_rule_blocked: bool = False


def validate_email(email: str) -> bool:
    if not email:
        return True
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None


def validate_quota_request(
    inputs: QuotaRequestValidationInputs,
) -> QuotaRequestValidationResult:
    normalized_quota_text = normalize_quantity_text(inputs.quantity_text)

    if not inputs.payment_method:
        return QuotaRequestValidationResult("请选择你刚刚使用的支付方式", normalized_quota_text)
    if not inputs.amount_text:
        return QuotaRequestValidationResult("请输入支付金额", normalized_quota_text)
    if not inputs.donated:
        return QuotaRequestValidationResult(
            "请先勾选“我已完成支付”后再发送申请",
            normalized_quota_text,
        )
    if not inputs.quantity_text:
        return QuotaRequestValidationResult("请输入申请额度", normalized_quota_text)

    quantity_value = parse_quantity_value(inputs.quantity_text)
    if quantity_value is None:
        return QuotaRequestValidationResult(
            "申请额度必须 >= 0，且只能填 0.5 的倍数",
            normalized_quota_text,
        )
    if quantity_value > Decimal(str(MAX_REQUEST_QUOTA)):
        quota_text = format_quota_value(MAX_REQUEST_QUOTA)
        return QuotaRequestValidationResult(
            f"申请额度不能超过 {quota_text}",
            normalized_quota_text,
        )
    if inputs.amount_text and not is_amount_allowed(inputs.amount_text, inputs.quantity_text):
        return QuotaRequestValidationResult(
            DONATION_AMOUNT_BLOCK_MESSAGE,
            normalized_quota_text,
            amount_rule_blocked=True,
        )
    return QuotaRequestValidationResult(None, normalized_quota_text)


def compute_send_timeout_fallback_ms(
    *,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    grace_ms: int,
) -> int:
    total_seconds = connect_timeout_seconds + read_timeout_seconds + read_timeout_seconds
    return int(total_seconds * 1000 + grace_ms)
