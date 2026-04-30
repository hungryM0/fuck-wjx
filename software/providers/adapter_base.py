"""Provider 适配层公共壳。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from software.core.task import ExecutionConfig, ExecutionState
from software.providers.contracts import SurveyDefinition

ParseSurveyHook = Callable[[str], SurveyDefinition]
FillSurveyHook = Callable[..., bool]
PagePredicateHook = Callable[[Any], bool]
ValidationMessageHook = Callable[[Any], str]
WaitVerificationHook = Callable[..., bool]
VerificationDetectedHook = Callable[[Any, Any, Any], None]


def _return_false(*_args: Any, **_kwargs: Any) -> bool:
    return False


def _return_empty_text(*_args: Any, **_kwargs: Any) -> str:
    return ""


def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


@dataclass(frozen=True)
class ProviderAdapterHooks:
    parse_survey: ParseSurveyHook
    fill_survey: FillSurveyHook
    is_completion_page: PagePredicateHook = _return_false
    submission_requires_verification: PagePredicateHook = _return_false
    submission_validation_message: ValidationMessageHook = _return_empty_text
    wait_for_submission_verification: WaitVerificationHook = _return_false
    handle_submission_verification_detected: VerificationDetectedHook = _noop
    consume_submission_success_signal: PagePredicateHook = _return_false
    is_device_quota_limit_page: PagePredicateHook = _return_false


class CallableProviderAdapter:
    def __init__(self, provider: str, hooks: ProviderAdapterHooks) -> None:
        self.provider = str(provider or "").strip()
        self._hooks = hooks

    def parse_survey(self, url: str) -> SurveyDefinition:
        return self._hooks.parse_survey(url)

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
            self._hooks.fill_survey(
                driver,
                config,
                state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=psycho_plan,
            )
        )

    def is_completion_page(self, driver: Any) -> bool:
        return bool(self._hooks.is_completion_page(driver))

    def submission_requires_verification(self, driver: Any) -> bool:
        return bool(self._hooks.submission_requires_verification(driver))

    def submission_validation_message(self, driver: Any) -> str:
        return str(self._hooks.submission_validation_message(driver) or "").strip()

    def wait_for_submission_verification(self, driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
        return bool(
            self._hooks.wait_for_submission_verification(
                driver,
                timeout=timeout,
                stop_signal=stop_signal,
            )
        )

    def handle_submission_verification_detected(self, ctx: Any, gui_instance: Any, stop_signal: Any) -> None:
        self._hooks.handle_submission_verification_detected(ctx, gui_instance, stop_signal)

    def consume_submission_success_signal(self, driver: Any) -> bool:
        return bool(self._hooks.consume_submission_success_signal(driver))

    def is_device_quota_limit_page(self, driver: Any) -> bool:
        return bool(self._hooks.is_device_quota_limit_page(driver))


__all__ = [
    "CallableProviderAdapter",
    "ProviderAdapterHooks",
]
