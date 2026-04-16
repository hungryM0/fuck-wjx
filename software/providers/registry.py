"""Provider 调度入口。"""

from __future__ import annotations

from typing import Any, Optional

from software.core.engine.provider_common import provider_run_context
from software.providers.common import (
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    normalize_survey_provider,
)
from software.providers.contracts import SurveyDefinition, build_survey_definition
from software.core.task import ExecutionConfig, ExecutionState
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


class _WjxProviderAdapter:
    provider = SURVEY_PROVIDER_WJX

    def parse_survey(self, url: str) -> SurveyDefinition:
        info, title = parse_wjx_survey(url)
        return build_survey_definition(self.provider, title, info)

    def fill_survey(
        self,
        driver: Any,
        config: ExecutionConfig,
        state: ExecutionState,
        *,
        stop_signal: Any = None,
        thread_name: str = "",
        psycho_plan: Any = None,
    ) -> bool:
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

    def is_completion_page(self, driver: Any) -> bool:
        return False

    def submission_requires_verification(self, driver: Any) -> bool:
        from wjx.provider.submission import submission_requires_verification as wjx_submission_requires_verification

        return bool(wjx_submission_requires_verification(driver))

    def submission_validation_message(self, driver: Any) -> str:
        from wjx.provider.submission import submission_validation_message as wjx_submission_validation_message

        return str(wjx_submission_validation_message(driver) or "").strip()

    def wait_for_submission_verification(self, driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
        from wjx.provider.submission import wait_for_submission_verification as wait_wjx_submission_verification

        return bool(
            wait_wjx_submission_verification(
                driver,
                timeout=timeout,
                stop_signal=stop_signal,
            )
        )

    def handle_submission_verification_detected(self, ctx: Any, gui_instance: Any, stop_signal: Any) -> None:
        from wjx.provider.submission import handle_submission_verification_detected as handle_wjx_submission_verification_detected

        handle_wjx_submission_verification_detected(ctx, gui_instance, stop_signal)

    def consume_submission_success_signal(self, driver: Any) -> bool:
        from wjx.provider.submission import consume_submission_success_signal as consume_wjx_submission_success_signal

        return bool(consume_wjx_submission_success_signal(driver))

    def is_device_quota_limit_page(self, driver: Any) -> bool:
        from wjx.provider.submission import is_device_quota_limit_page as is_wjx_device_quota_limit_page

        return bool(is_wjx_device_quota_limit_page(driver))


class _QqProviderAdapter:
    provider = SURVEY_PROVIDER_QQ

    def parse_survey(self, url: str) -> SurveyDefinition:
        info, title = parse_qq_survey(url)
        return build_survey_definition(self.provider, title, info)

    def fill_survey(
        self,
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

    def is_completion_page(self, driver: Any) -> bool:
        from tencent.provider.runtime import qq_is_completion_page

        return bool(qq_is_completion_page(driver))

    def submission_requires_verification(self, driver: Any) -> bool:
        from tencent.provider.runtime import qq_submission_requires_verification

        return bool(qq_submission_requires_verification(driver))

    def submission_validation_message(self, driver: Any) -> str:
        from tencent.provider.runtime import qq_submission_validation_message

        return str(qq_submission_validation_message(driver) or "").strip()

    def wait_for_submission_verification(self, driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
        del timeout, stop_signal
        return self.submission_requires_verification(driver)

    def handle_submission_verification_detected(self, ctx: Any, gui_instance: Any, stop_signal: Any) -> None:
        del ctx, gui_instance, stop_signal

    def consume_submission_success_signal(self, driver: Any) -> bool:
        from tencent.provider.submission import consume_submission_success_signal as consume_qq_submission_success_signal

        return bool(consume_qq_submission_success_signal(driver))

    def is_device_quota_limit_page(self, driver: Any) -> bool:
        from tencent.provider.submission import is_device_quota_limit_page as is_qq_device_quota_limit_page

        return bool(is_qq_device_quota_limit_page(driver))


_PROVIDER_REGISTRY = {
    SURVEY_PROVIDER_WJX: _WjxProviderAdapter(),
    SURVEY_PROVIDER_QQ: _QqProviderAdapter(),
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
    return _get_provider_adapter(url=url).parse_survey(url)


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


