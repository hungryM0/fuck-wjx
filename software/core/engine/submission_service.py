"""提交结果判定服务。"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any, Optional

import software.core.modes.duration_control as duration_control
from software.app.config import (
    HEADLESS_POST_SUBMIT_CLOSE_GRACE_SECONDS,
    POST_SUBMIT_CLOSE_GRACE_SECONDS,
    POST_SUBMIT_URL_MAX_WAIT,
    POST_SUBMIT_URL_POLL_INTERVAL,
)
from software.core.engine.failure_reason import FailureReason
from software.core.engine.runtime_actions import RuntimeActionResult
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.engine.stop_signal import StopSignalLike
from software.core.engine.async_wait import sleep_or_stop
from software.core.task import ExecutionConfig, ExecutionState
from software.logging.log_utils import log_suppressed_exception
from software.network.browser.runtime_async import BrowserDriver
from software.providers.registry import (
    attempt_submission_recovery as _provider_attempt_submission_recovery,
    handle_submission_verification_detected as _provider_handle_submission_verification_detected,
    submission_requires_verification as _provider_submission_requires_verification,
    submission_validation_message as _provider_submission_validation_message,
    wait_for_submission_verification as _provider_wait_for_submission_verification,
)

_WJX_POST_SUBMIT_MIN_WAIT_SECONDS = 5.0
_NON_WJX_POST_SUBMIT_MIN_WAIT_SECONDS = 3.0
_RECOVERY_POST_SUBMIT_MIN_WAIT_SECONDS = 5.0


@dataclass(frozen=True)
class SubmissionOutcome:
    status: str
    failure_reason: Optional[FailureReason]
    message: str
    completion_detected: bool
    should_stop: bool
    should_rotate_proxy: bool


class SubmissionService:
    """统一处理提交后的成功、验证、完成页与失败归因。"""

    def __init__(self, config: ExecutionConfig, state: ExecutionState, stop_policy: RunStopPolicy):
        self.config = config
        self.state = state
        self.stop_policy = stop_policy

    def _resolve_post_submit_close_grace_seconds(self) -> float:
        if bool(self.config.headless_mode):
            return float(HEADLESS_POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
        return float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)

    def _survey_provider_key(self) -> str:
        return str(self.config.survey_provider or "wjx").strip().lower()

    def _is_wjx_provider(self) -> bool:
        return self._survey_provider_key() == "wjx"

    def _mark_successful_submit_proxies(self, driver: BrowserDriver) -> None:
        for proxy_address in (
            str(getattr(driver, "session_proxy_address", "") or "").strip(),
            str(getattr(driver, "submit_proxy_address", "") or "").strip(),
        ):
            if not proxy_address:
                continue
            try:
                self.state.mark_successful_proxy_address(proxy_address)
            except Exception as exc:
                log_suppressed_exception(
                    "SubmissionService._mark_successful_submit_proxies",
                    exc,
                    level=logging.WARNING,
                )
        try:
            thread_name = str(getattr(driver, "thread_name", "") or "").strip()
            if thread_name:
                self.state.release_proxy_in_use(thread_name)
        except Exception as exc:
            log_suppressed_exception(
                "SubmissionService._mark_successful_submit_proxies release_proxy_in_use",
                exc,
                level=logging.WARNING,
            )

    async def _build_success_outcome(
        self,
        driver: BrowserDriver,
        stop_signal: StopSignalLike,
        *,
        thread_name: str,
    ) -> SubmissionOutcome:
        self._mark_successful_submit_proxies(driver)
        grace_seconds = self._resolve_post_submit_close_grace_seconds()
        if grace_seconds > 0 and await sleep_or_stop(stop_signal, grace_seconds):
            return SubmissionOutcome("aborted", FailureReason.USER_STOPPED, "任务已停止", False, True, False)
        should_stop = self.stop_policy.record_success(stop_signal, thread_name=thread_name)
        return SubmissionOutcome("success", None, "提交成功", True, should_stop, self.config.random_proxy_ip_enabled)

    async def _detect_completion_once(self, driver: BrowserDriver) -> bool:
        try:
            current_url = await driver.current_url()
        except Exception:
            current_url = ""
        if "complete" in str(current_url).lower():
            return True
        try:
            return bool(await duration_control.is_survey_completion_page(driver, provider=self.config.survey_provider))
        except Exception as exc:
            log_suppressed_exception("SubmissionService._detect_completion_once", exc, level=logging.WARNING)
            return False

    async def _wait_for_completion_page(
        self,
        driver: BrowserDriver,
        stop_signal: StopSignalLike,
        max_wait_seconds: float,
        poll_interval: float,
    ) -> bool:
        deadline = asyncio.get_running_loop().time() + max_wait_seconds
        while asyncio.get_running_loop().time() < deadline:
            if stop_signal.is_set():
                return False
            try:
                current_url = await driver.current_url()
            except Exception:
                current_url = ""
            if "complete" in str(current_url).lower():
                return True
            try:
                if await duration_control.is_survey_completion_page(driver, provider=self.config.survey_provider):
                    return True
            except Exception as exc:
                log_suppressed_exception("SubmissionService._wait_for_completion_page", exc, level=logging.WARNING)
            if await sleep_or_stop(stop_signal, poll_interval):
                return False
        return False

    async def _handle_detected_submission_verification(
        self,
        driver: BrowserDriver,
        stop_signal: StopSignalLike,
        gui_instance: Any,
        thread_name: Optional[str] = None,
    ) -> SubmissionOutcome:
        survey_provider = self._survey_provider_key()
        fallback_message = "提交命中平台安全验证，当前版本暂不支持自动处理"
        message = await _provider_submission_validation_message(driver, provider=survey_provider) or fallback_message
        logging.warning("%s", message)
        self.state.mark_terminal_stop(
            "submission_verification",
            failure_reason=FailureReason.SUBMISSION_VERIFICATION_REQUIRED.value,
            message=message,
        )
        stopped = self.stop_policy.record_failure(
            stop_signal,
            thread_name=thread_name,
            failure_reason=FailureReason.SUBMISSION_VERIFICATION_REQUIRED,
            status_text="腾讯安全验证" if survey_provider == "qq" else "智能验证",
            log_message=message,
            consume_reverse_fill_attempt=False,
        )
        action_result = await _provider_handle_submission_verification_detected(
            self.state,
            stop_signal,
            provider=survey_provider,
        )
        self._dispatch_runtime_actions(gui_instance, action_result)
        return SubmissionOutcome(
            status="failure",
            failure_reason=FailureReason.SUBMISSION_VERIFICATION_REQUIRED,
            message=message,
            completion_detected=False,
            should_stop=bool(stopped or stop_signal.is_set()),
            should_rotate_proxy=False,
        )

    def _dispatch_runtime_actions(self, gui_instance: Any, action_result: RuntimeActionResult) -> None:
        handler = getattr(gui_instance, "handle_runtime_actions", None)
        if not callable(handler):
            return
        try:
            handler(action_result)
        except Exception:
            logging.info("派发运行时动作失败", exc_info=True)

    async def _check_submission_verification_after_submit(
        self,
        driver: BrowserDriver,
        stop_signal: StopSignalLike,
        gui_instance: Any,
        thread_name: Optional[str] = None,
    ) -> Optional[SubmissionOutcome]:
        survey_provider = self._survey_provider_key()
        if survey_provider == "qq":
            if await _provider_submission_requires_verification(driver, provider=survey_provider):
                return await self._handle_detected_submission_verification(driver, stop_signal, gui_instance, thread_name=thread_name)
            return None
        try:
            detected = await _provider_wait_for_submission_verification(
                driver,
                provider=survey_provider,
                timeout=3,
                stop_signal=stop_signal,
            )
            if detected:
                return await self._handle_detected_submission_verification(driver, stop_signal, gui_instance, thread_name=thread_name)
        except Exception as exc:
            logging.warning("提交后安全验证检测过程出现异常：%s", exc)
        return None

    async def _attempt_submission_recovery(
        self,
        driver: BrowserDriver,
        stop_signal: StopSignalLike,
        gui_instance: Any,
        *,
        thread_name: str,
    ) -> bool:
        try:
            recovered = await _provider_attempt_submission_recovery(
                driver,
                self.state,
                gui_instance,
                stop_signal,
                provider=self.config.survey_provider,
                thread_name=thread_name,
            )
        except Exception as exc:
            logging.warning("提交后自动补答恢复失败：%s", exc)
            return False
        if recovered:
            logging.info("提交后自动补答已执行，准备重新等待完成页。")
        return bool(recovered)

    async def finalize_after_submit(
        self,
        driver: BrowserDriver,
        *,
        stop_signal: StopSignalLike,
        gui_instance: Any,
        thread_name: str,
    ) -> SubmissionOutcome:
        if await sleep_or_stop(stop_signal, random.uniform(0.2, 0.6)):
            return SubmissionOutcome("aborted", FailureReason.USER_STOPPED, "任务已停止", False, True, False)

        if self._is_wjx_provider():
            if await self._detect_completion_once(driver):
                return await self._build_success_outcome(driver, stop_signal, thread_name=thread_name)
            wait_seconds = max(_WJX_POST_SUBMIT_MIN_WAIT_SECONDS, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 2.0)
        else:
            verification_outcome = await self._check_submission_verification_after_submit(
                driver,
                stop_signal,
                gui_instance,
                thread_name=thread_name,
            )
            if verification_outcome is not None:
                return verification_outcome

            if not stop_signal.is_set() and await _provider_submission_requires_verification(
                driver,
                provider=self.config.survey_provider,
            ):
                return await self._handle_detected_submission_verification(driver, stop_signal, gui_instance, thread_name=thread_name)

            wait_seconds = max(_NON_WJX_POST_SUBMIT_MIN_WAIT_SECONDS, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 6.0)

        poll_interval = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
        completion_detected = await self._wait_for_completion_page(driver, stop_signal, wait_seconds, poll_interval)

        if completion_detected:
            return await self._build_success_outcome(driver, stop_signal, thread_name=thread_name)

        if not completion_detected and not stop_signal.is_set():
            verification_outcome = await self._check_submission_verification_after_submit(
                driver,
                stop_signal,
                gui_instance,
                thread_name=thread_name,
            )
            if verification_outcome is not None:
                return verification_outcome

        if not completion_detected and not stop_signal.is_set():
            if await _provider_submission_requires_verification(driver, provider=self.config.survey_provider):
                return await self._handle_detected_submission_verification(driver, stop_signal, gui_instance, thread_name=thread_name)

        if not completion_detected and not stop_signal.is_set():
            recovered = await self._attempt_submission_recovery(
                driver,
                stop_signal,
                gui_instance,
                thread_name=thread_name,
            )
            if recovered and not stop_signal.is_set():
                recovery_wait_seconds = max(_RECOVERY_POST_SUBMIT_MIN_WAIT_SECONDS, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 4.0)
                recovery_poll = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
                completion_detected = await self._wait_for_completion_page(
                    driver,
                    stop_signal,
                    recovery_wait_seconds,
                    recovery_poll,
                )
                if not completion_detected and not stop_signal.is_set():
                    verification_outcome = await self._check_submission_verification_after_submit(
                        driver,
                        stop_signal,
                        gui_instance,
                        thread_name=thread_name,
                    )
                    if verification_outcome is not None:
                        return verification_outcome

        if not completion_detected:
            stopped = self.stop_policy.record_failure(
                stop_signal,
                thread_name=thread_name,
                failure_reason=FailureReason.FILL_FAILED,
                status_text="提交未完成",
                log_message="提交后未检测到完成页，本轮按失败处理",
                consume_reverse_fill_attempt=False,
            )
            return SubmissionOutcome(
                status="failure",
                failure_reason=FailureReason.FILL_FAILED,
                message="提交后未检测到完成页",
                completion_detected=False,
                should_stop=bool(stopped or stop_signal.is_set()),
                should_rotate_proxy=False,
            )

        return await self._build_success_outcome(driver, stop_signal, thread_name=thread_name)


__all__ = ["SubmissionOutcome", "SubmissionService"]
