"""Provider 调度入口。"""

from __future__ import annotations

from typing import Any, Optional

from software.core.engine.provider_common import provider_run_context
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.adapter_base import CallableProviderAdapter, ProviderAdapterHooks
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    normalize_survey_provider,
)
from software.providers.contracts import SurveyDefinition, build_survey_definition
from software.providers.survey_cache import parse_survey_with_cache
from credamo.provider.parser import parse_credamo_survey
from tencent.provider.parser import parse_qq_survey
from wjx.provider.parser import parse_wjx_survey


def _resolve_provider(*, provider: Optional[str] = None, ctx: Any = None) -> str:
    if provider is not None:
        return normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    if ctx is not None:
        return normalize_survey_provider(
            getattr(getattr(ctx, "config", ctx), "survey_provider", None),
            default=SURVEY_PROVIDER_WJX,
        )
    return SURVEY_PROVIDER_WJX


def _build_parse_hook(provider: str, parser):
    def _parse(url: str) -> SurveyDefinition:
        info, title = parser(url)
        return build_survey_definition(provider, title, info)

    return _parse


def _fill_wjx(
    driver: Any,
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
) -> bool:
    from wjx.provider.runtime import brush_wjx

    return bool(
        brush_wjx(
            driver,
            config,
            state,
            stop_signal=stop_signal,
            thread_name=thread_name,
            psycho_plan=psycho_plan,
        )
    )


def _fill_qq(
    driver: Any,
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
) -> bool:
    from tencent.provider.runtime import brush_qq

    return bool(
        brush_qq(
            driver,
            config,
            state,
            stop_signal=stop_signal,
            thread_name=thread_name,
            psycho_plan=psycho_plan,
        )
    )


def _fill_credamo(
    driver: Any,
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
) -> bool:
    from credamo.provider.runtime import brush_credamo

    return bool(
        brush_credamo(
            driver,
            config,
            state,
            stop_signal=stop_signal,
            thread_name=thread_name,
            psycho_plan=psycho_plan,
        )
    )


def _wjx_submission_requires_verification(driver: Any) -> bool:
    from wjx.provider.submission import submission_requires_verification

    return bool(submission_requires_verification(driver))


def _wjx_submission_validation_message(driver: Any) -> str:
    from wjx.provider.submission import submission_validation_message

    return str(submission_validation_message(driver) or "").strip()


def _wjx_wait_for_submission_verification(driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
    from wjx.provider.submission import wait_for_submission_verification

    return bool(wait_for_submission_verification(driver, timeout=timeout, stop_signal=stop_signal))


def _wjx_handle_submission_verification_detected(ctx: Any, gui_instance: Any, stop_signal: Any) -> None:
    from wjx.provider.submission import handle_submission_verification_detected

    handle_submission_verification_detected(ctx, gui_instance, stop_signal)


def _wjx_consume_submission_success_signal(driver: Any) -> bool:
    from wjx.provider.submission import consume_submission_success_signal

    return bool(consume_submission_success_signal(driver))


def _wjx_is_device_quota_limit_page(driver: Any) -> bool:
    from wjx.provider.submission import is_device_quota_limit_page

    return bool(is_device_quota_limit_page(driver))


def _qq_is_completion_page(driver: Any) -> bool:
    from tencent.provider.runtime_flow import qq_is_completion_page

    return bool(qq_is_completion_page(driver))


def _qq_submission_requires_verification(driver: Any) -> bool:
    from tencent.provider.runtime_flow import qq_submission_requires_verification

    return bool(qq_submission_requires_verification(driver))


def _qq_submission_validation_message(driver: Any) -> str:
    from tencent.provider.runtime_flow import qq_submission_validation_message

    return str(qq_submission_validation_message(driver) or "").strip()


def _qq_wait_for_submission_verification(driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
    del timeout, stop_signal
    return _qq_submission_requires_verification(driver)


def _qq_handle_submission_verification_detected(ctx: Any, gui_instance: Any, stop_signal: Any) -> None:
    del ctx, gui_instance, stop_signal


def _qq_consume_submission_success_signal(driver: Any) -> bool:
    from tencent.provider.submission import consume_submission_success_signal

    return bool(consume_submission_success_signal(driver))


def _qq_is_device_quota_limit_page(driver: Any) -> bool:
    from tencent.provider.submission import is_device_quota_limit_page

    return bool(is_device_quota_limit_page(driver))


def _credamo_is_completion_page(driver: Any) -> bool:
    from credamo.provider.submission import is_completion_page

    return bool(is_completion_page(driver))


def _credamo_submission_requires_verification(driver: Any) -> bool:
    from credamo.provider.submission import submission_requires_verification

    return bool(submission_requires_verification(driver))


def _credamo_submission_validation_message(driver: Any) -> str:
    from credamo.provider.submission import submission_validation_message

    return str(submission_validation_message(driver) or "").strip()


def _credamo_wait_for_submission_verification(driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
    from credamo.provider.submission import wait_for_submission_verification

    return bool(wait_for_submission_verification(driver, timeout=timeout, stop_signal=stop_signal))


def _credamo_handle_submission_verification_detected(ctx: Any, gui_instance: Any, stop_signal: Any) -> None:
    from credamo.provider.submission import handle_submission_verification_detected

    handle_submission_verification_detected(ctx, gui_instance, stop_signal)


def _credamo_consume_submission_success_signal(driver: Any) -> bool:
    from credamo.provider.submission import consume_submission_success_signal

    return bool(consume_submission_success_signal(driver))


def _credamo_is_device_quota_limit_page(driver: Any) -> bool:
    from credamo.provider.submission import is_device_quota_limit_page

    return bool(is_device_quota_limit_page(driver))


_PROVIDER_REGISTRY = {
    SURVEY_PROVIDER_WJX: CallableProviderAdapter(
        SURVEY_PROVIDER_WJX,
        ProviderAdapterHooks(
            parse_survey=_build_parse_hook(SURVEY_PROVIDER_WJX, parse_wjx_survey),
            fill_survey=_fill_wjx,
            submission_requires_verification=_wjx_submission_requires_verification,
            submission_validation_message=_wjx_submission_validation_message,
            wait_for_submission_verification=_wjx_wait_for_submission_verification,
            handle_submission_verification_detected=_wjx_handle_submission_verification_detected,
            consume_submission_success_signal=_wjx_consume_submission_success_signal,
            is_device_quota_limit_page=_wjx_is_device_quota_limit_page,
        ),
    ),
    SURVEY_PROVIDER_QQ: CallableProviderAdapter(
        SURVEY_PROVIDER_QQ,
        ProviderAdapterHooks(
            parse_survey=_build_parse_hook(SURVEY_PROVIDER_QQ, parse_qq_survey),
            fill_survey=_fill_qq,
            is_completion_page=_qq_is_completion_page,
            submission_requires_verification=_qq_submission_requires_verification,
            submission_validation_message=_qq_submission_validation_message,
            wait_for_submission_verification=_qq_wait_for_submission_verification,
            handle_submission_verification_detected=_qq_handle_submission_verification_detected,
            consume_submission_success_signal=_qq_consume_submission_success_signal,
            is_device_quota_limit_page=_qq_is_device_quota_limit_page,
        ),
    ),
    SURVEY_PROVIDER_CREDAMO: CallableProviderAdapter(
        SURVEY_PROVIDER_CREDAMO,
        ProviderAdapterHooks(
            parse_survey=_build_parse_hook(SURVEY_PROVIDER_CREDAMO, parse_credamo_survey),
            fill_survey=_fill_credamo,
            is_completion_page=_credamo_is_completion_page,
            submission_requires_verification=_credamo_submission_requires_verification,
            submission_validation_message=_credamo_submission_validation_message,
            wait_for_submission_verification=_credamo_wait_for_submission_verification,
            handle_submission_verification_detected=_credamo_handle_submission_verification_detected,
            consume_submission_success_signal=_credamo_consume_submission_success_signal,
            is_device_quota_limit_page=_credamo_is_device_quota_limit_page,
        ),
    ),
}


def _get_provider_adapter(*, provider: Optional[str] = None, ctx: Any = None, url: Optional[str] = None):
    resolved = _resolve_provider(provider=provider, ctx=ctx)
    if url:
        resolved = detect_survey_provider(url)
    adapter = _PROVIDER_REGISTRY.get(resolved)
    if adapter is None:
        raise RuntimeError(f"不支持的问卷 provider: {resolved}")
    return adapter


def parse_survey(url: str) -> SurveyDefinition:
    """解析问卷结构，返回标准化后的 SurveyDefinition。"""
    return parse_survey_with_cache(url, lambda normalized_url: _get_provider_adapter(url=normalized_url).parse_survey(normalized_url))


def fill_survey(
    driver: Any,
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
    provider: Optional[str] = None,
) -> bool:
    """Provider 运行时答题分发。"""
    adapter = _get_provider_adapter(provider=provider, ctx=state)
    try:
        state.update_thread_status(thread_name, "识别题目", running=True)
    except Exception:
        pass
    with provider_run_context(
        config,
        state=state,
        thread_name=thread_name,
        psycho_plan=psycho_plan,
    ) as resolved_plan:
        return bool(
            adapter.fill_survey(
                driver,
                config,
                state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=resolved_plan,
            )
        )


def is_completion_page(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 完成页识别分发。"""
    return bool(_get_provider_adapter(provider=provider).is_completion_page(driver))


def submission_requires_verification(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 提交后风控/验证识别分发。"""
    return bool(_get_provider_adapter(provider=provider).submission_requires_verification(driver))


def submission_validation_message(driver: Any, provider: Optional[str] = None) -> str:
    """Provider 提交后校验文案提取分发。"""
    return str(_get_provider_adapter(provider=provider).submission_validation_message(driver) or "").strip()


def wait_for_submission_verification(
    driver: Any,
    *,
    provider: Optional[str] = None,
    timeout: int = 3,
    stop_signal: Any = None,
) -> bool:
    """Provider 提交后短时间轮询风控/验证命中。"""
    return bool(
        _get_provider_adapter(provider=provider).wait_for_submission_verification(
            driver,
            timeout=timeout,
            stop_signal=stop_signal,
        )
    )


def handle_submission_verification_detected(
    ctx: Any,
    gui_instance: Any,
    stop_signal: Any,
    *,
    provider: Optional[str] = None,
) -> None:
    """Provider 提交后命中风控/验证时的后续策略分发。"""
    _get_provider_adapter(provider=provider, ctx=ctx).handle_submission_verification_detected(
        ctx,
        gui_instance,
        stop_signal,
    )


def consume_submission_success_signal(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 提交成功短路标记读取。"""
    return bool(_get_provider_adapter(provider=provider).consume_submission_success_signal(driver))


def is_device_quota_limit_page(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 设备次数上限页识别。"""
    return bool(_get_provider_adapter(provider=provider).is_device_quota_limit_page(driver))


__all__ = [
    "SURVEY_PROVIDER_WJX",
    "SURVEY_PROVIDER_QQ",
    "SURVEY_PROVIDER_CREDAMO",
    "SurveyDefinition",
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


