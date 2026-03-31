"""Provider 调度入口。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from software.core.engine.provider_common import provider_run_context
from software.providers.common import (
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    normalize_survey_provider,
)
from tencent.provider.parser import parse_qq_survey
from wjx.provider.parser import parse_wjx_survey
from wjx.provider.runtime import brush_wjx


def _resolve_provider(*, provider: Optional[str] = None, ctx: Any = None) -> str:
    if provider is not None:
        return normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    if ctx is not None:
        return normalize_survey_provider(
            getattr(ctx, "survey_provider", None),
            default=SURVEY_PROVIDER_WJX,
        )
    return SURVEY_PROVIDER_WJX


def parse_survey(url: str) -> Tuple[List[Dict[str, Any]], str, str]:
    """解析问卷结构，返回 (questions_info, title, provider)。"""
    provider = detect_survey_provider(url)
    if provider == SURVEY_PROVIDER_QQ:
        info, title = parse_qq_survey(url)
        return info, title, SURVEY_PROVIDER_QQ

    info, title = parse_wjx_survey(url)
    return info, title, SURVEY_PROVIDER_WJX


def fill_survey(
    driver: Any,
    ctx: Any,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
    provider: Optional[str] = None,
) -> bool:
    """Provider 运行时答题分发。"""
    resolved = _resolve_provider(provider=provider, ctx=ctx)
    try:
        ctx.update_thread_status(thread_name, "识别题目", running=True)
    except Exception:
        pass
    with provider_run_context(ctx, psycho_plan=psycho_plan) as resolved_plan:
        if resolved == SURVEY_PROVIDER_QQ:
            from tencent.provider.runtime import brush_qq

            return bool(
                brush_qq(
                    driver,
                    ctx,
                    stop_signal=stop_signal,
                    thread_name=thread_name,
                    psycho_plan=resolved_plan,
                )
            )

        if resolved == SURVEY_PROVIDER_WJX:
            return bool(
                brush_wjx(
                    driver,
                    ctx,
                    stop_signal=stop_signal,
                    thread_name=thread_name,
                    psycho_plan=resolved_plan,
                )
            )

    raise RuntimeError(f"不支持的问卷 provider: {resolved}")


def is_completion_page(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 完成页识别分发。"""
    resolved = _resolve_provider(provider=provider)
    if resolved == SURVEY_PROVIDER_QQ:
        from tencent.provider.runtime import qq_is_completion_page

        return bool(qq_is_completion_page(driver))
    return False


def submission_requires_verification(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 提交后风控/验证识别分发。"""
    resolved = _resolve_provider(provider=provider)
    if resolved == SURVEY_PROVIDER_QQ:
        from tencent.provider.runtime import qq_submission_requires_verification

        return bool(qq_submission_requires_verification(driver))
    if resolved == SURVEY_PROVIDER_WJX:
        from wjx.provider.submission import submission_requires_verification as wjx_submission_requires_verification

        return bool(wjx_submission_requires_verification(driver))
    return False


def submission_validation_message(driver: Any, provider: Optional[str] = None) -> str:
    """Provider 提交后校验文案提取分发。"""
    resolved = _resolve_provider(provider=provider)
    if resolved == SURVEY_PROVIDER_QQ:
        from tencent.provider.runtime import qq_submission_validation_message

        return str(qq_submission_validation_message(driver) or "").strip()
    if resolved == SURVEY_PROVIDER_WJX:
        from wjx.provider.submission import submission_validation_message as wjx_submission_validation_message

        return str(wjx_submission_validation_message(driver) or "").strip()
    return ""


def wait_for_submission_verification(
    driver: Any,
    *,
    provider: Optional[str] = None,
    timeout: int = 3,
    stop_signal: Any = None,
) -> bool:
    """Provider 提交后短时间轮询风控/验证命中。"""
    resolved = _resolve_provider(provider=provider)
    if resolved == SURVEY_PROVIDER_WJX:
        from wjx.provider.submission import wait_for_submission_verification as wait_wjx_submission_verification

        return bool(
            wait_wjx_submission_verification(
                driver,
                timeout=timeout,
                stop_signal=stop_signal,
            )
        )
    return submission_requires_verification(driver, provider=resolved)


def handle_submission_verification_detected(
    ctx: Any,
    gui_instance: Any,
    stop_signal: Any,
    *,
    provider: Optional[str] = None,
) -> None:
    """Provider 提交后命中风控/验证时的后续策略分发。"""
    resolved = _resolve_provider(provider=provider, ctx=ctx)
    if resolved == SURVEY_PROVIDER_WJX:
        from wjx.provider.submission import handle_submission_verification_detected as handle_wjx_submission_verification_detected

        handle_wjx_submission_verification_detected(ctx, gui_instance, stop_signal)


def consume_submission_success_signal(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 提交成功短路标记读取。"""
    resolved = _resolve_provider(provider=provider)
    if resolved == SURVEY_PROVIDER_QQ:
        from tencent.provider.submission import consume_submission_success_signal as consume_qq_submission_success_signal

        return bool(consume_qq_submission_success_signal(driver))
    if resolved == SURVEY_PROVIDER_WJX:
        from wjx.provider.submission import consume_submission_success_signal as consume_wjx_submission_success_signal

        return bool(consume_wjx_submission_success_signal(driver))
    return False


def is_device_quota_limit_page(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 设备次数上限页识别。"""
    resolved = _resolve_provider(provider=provider)
    if resolved == SURVEY_PROVIDER_QQ:
        from tencent.provider.submission import is_device_quota_limit_page as is_qq_device_quota_limit_page

        return bool(is_qq_device_quota_limit_page(driver))
    if resolved == SURVEY_PROVIDER_WJX:
        from wjx.provider.submission import is_device_quota_limit_page as is_wjx_device_quota_limit_page

        return bool(is_wjx_device_quota_limit_page(driver))
    return False


__all__ = [
    "SURVEY_PROVIDER_WJX",
    "SURVEY_PROVIDER_QQ",
    "consume_submission_success_signal",
    "detect_survey_provider",
    "parse_survey",
    "fill_survey",
    "is_completion_page",
    "is_device_quota_limit_page",
    "handle_submission_verification_detected",
    "submission_requires_verification",
    "submission_validation_message",
    "wait_for_submission_verification",
]


