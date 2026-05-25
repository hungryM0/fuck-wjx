"""Provider 调度入口。"""

from __future__ import annotations

from typing import Any, Optional

from software.core.engine.provider_common import provider_run_context
from software.core.engine.runtime_actions import RuntimeActionResult
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.adapter_base import CallableProviderAdapter, ProviderAdapterHooks
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    normalize_survey_provider,
)
from software.providers.contracts import SurveyDefinition
from software.providers.hooks import (
    HookTarget,
    build_action_hook,
    build_fill_http_hook,
    build_fill_hook,
    build_parse_hook,
    build_predicate_hook,
    build_submission_recovery_hook,
    build_text_hook,
    build_wait_from_predicate_hook,
    build_wait_hook,
)
from software.providers.survey_cache import parse_survey_with_cache

def _resolve_provider(*, provider: Optional[str] = None, ctx: Any = None) -> str:
    if provider is not None:
        return normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    if ctx is not None:
        return normalize_survey_provider(
            getattr(getattr(ctx, "config", ctx), "survey_provider", None),
            default=SURVEY_PROVIDER_WJX,
        )
    return SURVEY_PROVIDER_WJX


_WJX_PARSE: HookTarget = ("wjx.provider.parser", "parse_wjx_survey")
_QQ_PARSE: HookTarget = ("tencent.provider.parser", "parse_qq_survey")
_CREDAMO_PARSE: HookTarget = ("credamo.provider.parser", "parse_credamo_survey")

_WJX_FILL: HookTarget = ("wjx.provider.runtime", "brush_wjx")
_QQ_FILL: HookTarget = ("tencent.provider.runtime", "brush_qq")
_CREDAMO_FILL: HookTarget = ("credamo.provider.runtime", "brush_credamo")
_WJX_FILL_HTTP: HookTarget = ("wjx.provider.http_runtime", "brush_wjx_http")
_QQ_FILL_HTTP: HookTarget = ("tencent.provider.http_runtime", "brush_qq_http")

_WJX_IS_COMPLETION_PAGE: HookTarget = ("wjx.provider.submission_pages", "is_completion_page")
_WJX_SUBMISSION_REQUIRES_VERIFICATION: HookTarget = ("wjx.provider.submission", "submission_requires_verification")
_WJX_SUBMISSION_VALIDATION_MESSAGE: HookTarget = ("wjx.provider.submission", "submission_validation_message")
_WJX_WAIT_FOR_SUBMISSION_VERIFICATION: HookTarget = ("wjx.provider.submission", "wait_for_submission_verification")
_WJX_HANDLE_SUBMISSION_VERIFICATION_DETECTED: HookTarget = ("wjx.provider.submission", "handle_submission_verification_detected")
_WJX_ATTEMPT_SUBMISSION_RECOVERY: HookTarget = ("wjx.provider.submission", "attempt_submission_recovery")
_WJX_IS_DEVICE_QUOTA_LIMIT_PAGE: HookTarget = ("wjx.provider.submission", "is_device_quota_limit_page")

_QQ_IS_COMPLETION_PAGE: HookTarget = ("tencent.provider.runtime_flow", "qq_is_completion_page")
_QQ_SUBMISSION_REQUIRES_VERIFICATION: HookTarget = ("tencent.provider.runtime_flow", "qq_submission_requires_verification")
_QQ_SUBMISSION_VALIDATION_MESSAGE: HookTarget = ("tencent.provider.runtime_flow", "qq_submission_validation_message")
_QQ_CONSUME_SUBMISSION_SUCCESS_SIGNAL: HookTarget = ("tencent.provider.submission", "consume_submission_success_signal")
_QQ_ATTEMPT_SUBMISSION_RECOVERY: HookTarget = ("tencent.provider.submission", "attempt_submission_recovery")
_QQ_IS_DEVICE_QUOTA_LIMIT_PAGE: HookTarget = ("tencent.provider.submission", "is_device_quota_limit_page")

_CREDAMO_IS_COMPLETION_PAGE: HookTarget = ("credamo.provider.submission", "is_completion_page")
_CREDAMO_SUBMISSION_REQUIRES_VERIFICATION: HookTarget = ("credamo.provider.submission", "submission_requires_verification")
_CREDAMO_SUBMISSION_VALIDATION_MESSAGE: HookTarget = ("credamo.provider.submission", "submission_validation_message")
_CREDAMO_WAIT_FOR_SUBMISSION_VERIFICATION: HookTarget = ("credamo.provider.submission", "wait_for_submission_verification")
_CREDAMO_HANDLE_SUBMISSION_VERIFICATION_DETECTED: HookTarget = ("credamo.provider.submission", "handle_submission_verification_detected")
_CREDAMO_CONSUME_SUBMISSION_SUCCESS_SIGNAL: HookTarget = ("credamo.provider.submission", "consume_submission_success_signal")
_CREDAMO_ATTEMPT_SUBMISSION_RECOVERY: HookTarget = ("credamo.provider.submission", "attempt_submission_recovery")
_CREDAMO_IS_DEVICE_QUOTA_LIMIT_PAGE: HookTarget = ("credamo.provider.submission", "is_device_quota_limit_page")


_PROVIDER_REGISTRY = {
    SURVEY_PROVIDER_WJX: CallableProviderAdapter(
        SURVEY_PROVIDER_WJX,
        ProviderAdapterHooks(
            parse_survey=build_parse_hook(SURVEY_PROVIDER_WJX, _WJX_PARSE),
            fill_survey=build_fill_hook(_WJX_FILL),
            fill_survey_http=build_fill_http_hook(_WJX_FILL_HTTP),
            is_completion_page=build_predicate_hook(_WJX_IS_COMPLETION_PAGE),
            submission_requires_verification=build_predicate_hook(_WJX_SUBMISSION_REQUIRES_VERIFICATION),
            submission_validation_message=build_text_hook(_WJX_SUBMISSION_VALIDATION_MESSAGE),
            wait_for_submission_verification=build_wait_hook(_WJX_WAIT_FOR_SUBMISSION_VERIFICATION),
            handle_submission_verification_detected=build_action_hook(_WJX_HANDLE_SUBMISSION_VERIFICATION_DETECTED),
            attempt_submission_recovery=build_submission_recovery_hook(_WJX_ATTEMPT_SUBMISSION_RECOVERY),
            is_device_quota_limit_page=build_predicate_hook(_WJX_IS_DEVICE_QUOTA_LIMIT_PAGE),
        ),
    ),
    SURVEY_PROVIDER_QQ: CallableProviderAdapter(
        SURVEY_PROVIDER_QQ,
        ProviderAdapterHooks(
            parse_survey=build_parse_hook(SURVEY_PROVIDER_QQ, _QQ_PARSE),
            fill_survey=build_fill_hook(_QQ_FILL),
            fill_survey_http=build_fill_http_hook(_QQ_FILL_HTTP),
            is_completion_page=build_predicate_hook(_QQ_IS_COMPLETION_PAGE),
            submission_requires_verification=build_predicate_hook(_QQ_SUBMISSION_REQUIRES_VERIFICATION),
            submission_validation_message=build_text_hook(_QQ_SUBMISSION_VALIDATION_MESSAGE),
            wait_for_submission_verification=build_wait_from_predicate_hook(_QQ_SUBMISSION_REQUIRES_VERIFICATION),
            attempt_submission_recovery=build_submission_recovery_hook(_QQ_ATTEMPT_SUBMISSION_RECOVERY),
            consume_submission_success_signal=build_predicate_hook(_QQ_CONSUME_SUBMISSION_SUCCESS_SIGNAL),
            is_device_quota_limit_page=build_predicate_hook(_QQ_IS_DEVICE_QUOTA_LIMIT_PAGE),
        ),
    ),
    SURVEY_PROVIDER_CREDAMO: CallableProviderAdapter(
        SURVEY_PROVIDER_CREDAMO,
        ProviderAdapterHooks(
            parse_survey=build_parse_hook(SURVEY_PROVIDER_CREDAMO, _CREDAMO_PARSE),
            fill_survey=build_fill_hook(_CREDAMO_FILL),
            is_completion_page=build_predicate_hook(_CREDAMO_IS_COMPLETION_PAGE),
            submission_requires_verification=build_predicate_hook(_CREDAMO_SUBMISSION_REQUIRES_VERIFICATION),
            submission_validation_message=build_text_hook(_CREDAMO_SUBMISSION_VALIDATION_MESSAGE),
            wait_for_submission_verification=build_wait_hook(_CREDAMO_WAIT_FOR_SUBMISSION_VERIFICATION),
            handle_submission_verification_detected=build_action_hook(_CREDAMO_HANDLE_SUBMISSION_VERIFICATION_DETECTED),
            attempt_submission_recovery=build_submission_recovery_hook(_CREDAMO_ATTEMPT_SUBMISSION_RECOVERY),
            consume_submission_success_signal=build_predicate_hook(_CREDAMO_CONSUME_SUBMISSION_SUCCESS_SIGNAL),
            is_device_quota_limit_page=build_predicate_hook(_CREDAMO_IS_DEVICE_QUOTA_LIMIT_PAGE),
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


async def parse_survey(url: str) -> SurveyDefinition:
    """解析问卷结构，返回标准化后的 SurveyDefinition。"""
    return await parse_survey_with_cache(
        url,
        lambda normalized_url: _get_provider_adapter(url=normalized_url).parse_survey_async(normalized_url),
    )


async def fill_survey(
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
            await adapter.fill_survey_async(
                driver,
                config,
                state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=resolved_plan,
            )
        )


async def fill_survey_http(
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
    provider: Optional[str] = None,
    proxy_address: str | None = None,
    user_agent: str | None = None,
) -> bool:
    """Provider 原生 HTTP 答题提交分发。"""
    adapter = _get_provider_adapter(provider=provider, ctx=state)
    try:
        state.update_thread_status(thread_name, "构造答案", running=True)
    except Exception:
        pass
    with provider_run_context(
        config,
        state=state,
        thread_name=thread_name,
        psycho_plan=psycho_plan,
    ) as resolved_plan:
        return bool(
            await adapter.fill_survey_http_async(
                config,
                state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=resolved_plan,
                proxy_address=proxy_address,
                user_agent=user_agent,
            )
        )


async def is_completion_page(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 完成页识别分发。"""
    return bool(await _get_provider_adapter(provider=provider).is_completion_page_async(driver))


async def submission_requires_verification(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 提交后风控/验证识别分发。"""
    return bool(await _get_provider_adapter(provider=provider).submission_requires_verification_async(driver))


async def submission_validation_message(driver: Any, provider: Optional[str] = None) -> str:
    """Provider 提交后校验文案提取分发。"""
    return str(await _get_provider_adapter(provider=provider).submission_validation_message_async(driver) or "").strip()


async def wait_for_submission_verification(
    driver: Any,
    *,
    provider: Optional[str] = None,
    timeout: int = 3,
    stop_signal: Any = None,
) -> bool:
    """Provider 提交后短时间轮询风控/验证命中。"""
    return bool(
        await _get_provider_adapter(provider=provider).wait_for_submission_verification_async(
            driver,
            timeout=timeout,
            stop_signal=stop_signal,
        )
    )


async def attempt_submission_recovery(
    driver: Any,
    ctx: Any,
    gui_instance: Any,
    stop_signal: Any,
    *,
    provider: Optional[str] = None,
    thread_name: str = "",
) -> bool:
    return bool(
        await _get_provider_adapter(provider=provider).attempt_submission_recovery_async(
            driver,
            ctx,
            gui_instance,
            stop_signal,
            thread_name=thread_name,
        )
    )


async def handle_submission_verification_detected(
    ctx: Any,
    stop_signal: Any,
    *,
    provider: Optional[str] = None,
) -> RuntimeActionResult:
    """Provider 提交后命中风控/验证时的后续策略分发。"""
    return await _get_provider_adapter(provider=provider, ctx=ctx).handle_submission_verification_detected_async(
        ctx,
        stop_signal,
    )


async def consume_submission_success_signal(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 提交成功短路标记读取。"""
    return bool(await _get_provider_adapter(provider=provider).consume_submission_success_signal_async(driver))


async def is_device_quota_limit_page(driver: Any, provider: Optional[str] = None) -> bool:
    """Provider 设备次数上限页识别。"""
    return bool(await _get_provider_adapter(provider=provider).is_device_quota_limit_page_async(driver))


__all__ = [
    "SURVEY_PROVIDER_WJX",
    "SURVEY_PROVIDER_QQ",
    "SURVEY_PROVIDER_CREDAMO",
    "SurveyDefinition",
    "consume_submission_success_signal",
    "detect_survey_provider",
    "parse_survey",
    "attempt_submission_recovery",
    "fill_survey",
    "fill_survey_http",
    "is_completion_page",
    "is_device_quota_limit_page",
    "handle_submission_verification_detected",
    "submission_requires_verification",
    "submission_validation_message",
    "wait_for_submission_verification",
]


