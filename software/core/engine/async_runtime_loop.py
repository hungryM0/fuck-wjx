"""Async-first fill runtime loop."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Optional, cast

from software.core.ai.runtime import AIRuntimeError
from software.core.engine.async_events import AsyncRunContext, ThreadEventProxy
from software.core.engine.async_http_submitter import AsyncHttpSubmitter
from software.core.engine.async_proxy_session import AsyncProxySession
from software.core.engine.async_round_resources import (
    AsyncRoundResources,
    JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS,
    JOINT_PRE_ANSWER_TIMEOUT,
)
from software.core.engine.async_scheduler import AsyncScheduler
from software.core.engine.failure_reason import FailureReason
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.engine.runtime_control_port import RuntimeControlPort
from software.core.engine.runtime_error_handlers import handle_ai_runtime_error as _handle_ai_runtime_error_impl
from software.core.engine.runtime_error_handlers import handle_submission_verification_error
from software.core.engine.runtime_error_handlers import handle_survey_provider_unavailable_error
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.errors import SubmissionVerificationRequiredError, SurveyProviderUnavailableAtRuntimeError
import software.network.http as http_client
from software.network.session_policy import (
    _mark_proxy_temporarily_bad,
    _record_bad_proxy_and_maybe_pause,
)
from software.providers.http_progress import update_http_submit_step


class AsyncSlotRunner:
    """One logical slot running repeated fill attempts as coroutines."""

    def __init__(
        self,
        *,
        slot_id: int,
        config: ExecutionConfig,
        state: ExecutionState,
        run_context: AsyncRunContext,
        scheduler: AsyncScheduler,
        runtime_bridge: RuntimeControlPort | None = None,
    ) -> None:
        self.slot_id = max(1, int(slot_id or 1))
        self.slot_label = f"Slot-{self.slot_id}"
        self.config = config
        self.state = state
        self.run_context = run_context
        self.scheduler = scheduler
        self.runtime_bridge = runtime_bridge
        self.stop_proxy = ThreadEventProxy(run_context.stop_event, loop=asyncio.get_running_loop())
        self.stop_policy = RunStopPolicy(config, state, runtime_bridge)
        self.proxy_session = AsyncProxySession(
            config=config,
            state=state,
            slot_label=self.slot_label,
            stop_signal=self.stop_proxy,
            runtime_bridge=runtime_bridge,
            update_step=self._update_step,
        )
        self.round_resources = AsyncRoundResources(
            config=config,
            state=state,
            slot_label=self.slot_label,
            stop_requested=self.run_context.stop_requested,
            should_stop_loop=self._should_stop_loop,
            set_stop_requested=self.run_context.stop_event.set,
            update_status=self._update_status,
        )
        self.http_submitter = AsyncHttpSubmitter(
            config=config,
            state=state,
            slot_label=self.slot_label,
        )
        self._joint_pre_answer_timed_out = False

    def _update_status(self, status_text: str, *, running: bool = True) -> None:
        try:
            self.state.update_thread_status(self.slot_label, status_text, running=running)
        except Exception:
            logging.info("更新 slot 状态失败：%s", status_text, exc_info=True)

    def _update_step(self, status_text: str) -> None:
        try:
            self.state.update_thread_step(self.slot_label, 0, 0, status_text=status_text, running=True)
        except Exception:
            logging.info("更新 slot 步骤失败：%s", status_text, exc_info=True)

    async def _update_http_step(self, status_text: str) -> None:
        await update_http_submit_step(self.state, self.slot_label, status_text)

    async def _should_stop_loop(self) -> bool:
        await self.run_context.wait_if_paused()
        if self.run_context.stop_requested():
            return True
        with self.state.lock:
            target_reached = bool(self.config.target_num > 0 and self.state.cur_num >= self.config.target_num)
        if target_reached:
            self.stop_policy.trigger_target_reached_stop(self.stop_proxy)
            return True
        return False

    async def _sleep_or_stop(self, seconds: float) -> bool:
        delay = max(0.0, float(seconds or 0.0))
        if delay <= 0:
            return self.run_context.stop_requested()
        try:
            await asyncio.wait_for(self.run_context.stop_event.wait(), timeout=delay)
            return True
        except asyncio.TimeoutError:
            return self.run_context.stop_requested()

    def _resolve_dispatch_delay_seconds(self) -> float:
        min_wait, max_wait = self.config.submit_interval_range_seconds
        if max_wait <= 0:
            return 0.0
        if max_wait == min_wait:
            return float(min_wait)
        return float(random.uniform(min_wait, max_wait))

    def _resolve_finished_status_text(self) -> str:
        if self.run_context.stop_requested():
            try:
                terminal_category = str(self.state.get_terminal_stop_snapshot()[0] or "").strip()
            except Exception:
                terminal_category = ""
            if terminal_category == "target_reached":
                return "已完成"
        return "已停止"

    def _requires_joint_sample(self) -> bool:
        return self.round_resources.requires_joint_sample()

    async def _prepare_round_context(self) -> bool:
        return await self.round_resources.prepare_round_context()

    def _release_round_resources(self, *, requeue_reverse_fill: bool) -> None:
        self.round_resources.release_round_resources(requeue_reverse_fill=requeue_reverse_fill)

    async def _select_session_proxy_and_ua(self) -> tuple[Optional[str], Optional[str]]:
        return await self.proxy_session.select_proxy_and_user_agent()

    def _release_session_proxy(self) -> None:
        self.proxy_session.release_current_proxy()

    async def _run_pre_answer_step_with_joint_lease(self, label: str, operation: Any) -> Any:
        return await self.round_resources.run_pre_answer_step_with_joint_lease(label, operation)

    def _handle_proxy_unavailable(self, *, status_text: str, log_message: str) -> bool:
        threshold_getter = getattr(self.stop_policy, "proxy_unavailable_threshold", None)
        threshold_value = threshold_getter() if callable(threshold_getter) else None
        threshold_override = (
            int(cast(int, threshold_value))
            if threshold_value is not None
            else max(1, int(self.config.fail_threshold or 1), int(self.config.num_threads or 1))
        )
        stopped = self.stop_policy.record_failure(
            self.stop_proxy,
            thread_name=self.slot_label,
            failure_reason=FailureReason.PROXY_UNAVAILABLE,
            status_text=status_text,
            log_message=log_message,
            threshold_override=threshold_override,
            terminal_stop_category="proxy_unavailable_threshold",
            consume_reverse_fill_attempt=False,
        )
        if stopped:
            self.run_context.stop_event.set()
            return True
        if self.config.random_proxy_ip_enabled and _record_bad_proxy_and_maybe_pause(self.state, self.runtime_bridge):
            return True
        return False

    async def _handle_ai_runtime_error(self, exc: AIRuntimeError) -> bool:
        return _handle_ai_runtime_error_impl(
            exc,
            self.stop_proxy,
            thread_name=self.slot_label,
            stop_policy=self.stop_policy,
            state=self.state,
        )

    async def _handle_submission_verification_error(self, exc: SubmissionVerificationRequiredError) -> bool:
        return handle_submission_verification_error(
            exc,
            self.stop_proxy,
            thread_name=self.slot_label,
            state=self.state,
        )

    async def _handle_survey_provider_unavailable_error(self, exc: SurveyProviderUnavailableAtRuntimeError) -> bool:
        return handle_survey_provider_unavailable_error(
            exc,
            self.stop_proxy,
            thread_name=self.slot_label,
            state=self.state,
        )

    def _uses_http_runtime(self) -> bool:
        return self.http_submitter.uses_http_runtime()

    def _resolve_http_runtime_block_reason(self) -> str:
        return self.http_submitter.resolve_block_reason()

    def _block_http_runtime(self, reason: str) -> None:
        message = str(reason or "").strip() or "当前问卷不支持纯 HTTP 提交"
        logging.error("会话[%s]已阻止纯 HTTP 提交：%s", self.slot_label, message)
        self._update_status("纯 HTTP 不支持", running=False)
        self.stop_policy.record_failure(
            self.stop_proxy,
            thread_name=self.slot_label,
            failure_reason=FailureReason.FILL_FAILED,
            status_text="纯 HTTP 不支持",
            log_message=message,
            terminal_stop_category="http_runtime_only",
            force_stop_when_threshold_reached=True,
            consume_reverse_fill_attempt=False,
        )
        self.state.mark_terminal_stop(
            "http_runtime_only",
            failure_reason=FailureReason.FILL_FAILED.value,
            message=message,
        )
        self.run_context.stop_event.set()

    def _mark_http_submit_success(self) -> bool:
        self.proxy_session.mark_successful_proxy()
        return self.stop_policy.record_success(self.stop_proxy, thread_name=self.slot_label)

    def _handle_http_transport_error(self, exc: BaseException) -> bool:
        if self.proxy_session.proxy_address:
            try:
                _mark_proxy_temporarily_bad(self.state, self.proxy_session.proxy_address)
            except Exception:
                logging.info("标记 HTTP 代理异常失败", exc_info=True)
        return self._handle_proxy_unavailable(
            status_text="代理连接失败" if self.proxy_session.proxy_address else "网络请求失败",
            log_message=f"HTTP 请求失败，本轮按失败处理：{exc}",
        )

    async def _run_http_runtime(self) -> None:
        block_reason = self._resolve_http_runtime_block_reason()
        if block_reason:
            self._block_http_runtime(block_reason)
            try:
                self.state.release_joint_sample(self.slot_label)
                self.state.release_reverse_fill_sample(self.slot_label, requeue=True)
                self.state.mark_thread_finished(self.slot_label, status_text=self._resolve_finished_status_text())
            except Exception:
                logging.info("阻止纯 HTTP 提交后的收尾状态更新失败", exc_info=True)
            return

        self._update_status("HTTP 会话启动", running=True)
        while True:
            if await self._should_stop_loop():
                break
            token_id = await self.scheduler.acquire()
            if token_id is None:
                break
            should_requeue_dispatch = True
            dispatch_delay_seconds = 0.0
            try:
                self._joint_pre_answer_timed_out = False
                await self._update_http_step("准备请求")
                if not await self._prepare_round_context():
                    should_requeue_dispatch = False
                    break

                proxy_result = await self._run_pre_answer_step_with_joint_lease(
                    "获取代理",
                    self._select_session_proxy_and_ua,
                )
                if proxy_result is JOINT_PRE_ANSWER_TIMEOUT:
                    dispatch_delay_seconds = JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS
                    continue
                proxy_address, ua_value = proxy_result
                if self.run_context.stop_requested():
                    should_requeue_dispatch = False
                    break
                if self.config.random_proxy_ip_enabled and not proxy_address:
                    self._release_round_resources(requeue_reverse_fill=True)
                    continue

                try:
                    marked_answering = self.state.mark_joint_sample_answering(self.slot_label)
                except Exception:
                    logging.info("标记联合信效度槽位进入答题失败", exc_info=True)
                    marked_answering = False
                if self._requires_joint_sample() and not marked_answering:
                    logging.warning("会话[%s]进入 HTTP 答题前发现联合信效度槽位已释放，本轮放弃并重试", self.slot_label)
                    self._release_round_resources(requeue_reverse_fill=True)
                    dispatch_delay_seconds = JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS
                    continue

                finished = await self.http_submitter.submit(
                    stop_signal=self.stop_proxy,
                    proxy_address=proxy_address,
                    user_agent=ua_value,
                )
                if self.run_context.stop_requested() or not finished:
                    self._release_round_resources(requeue_reverse_fill=True)
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue

                should_stop = self._mark_http_submit_success()
                if should_stop:
                    should_requeue_dispatch = False
                    break
                dispatch_delay_seconds = self._resolve_dispatch_delay_seconds()
                if dispatch_delay_seconds > 0:
                    self._update_step("等待提交间隔")
            except AIRuntimeError as exc:
                if await self._handle_ai_runtime_error(exc):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            except SubmissionVerificationRequiredError as exc:
                if await self._handle_submission_verification_error(exc):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            except SurveyProviderUnavailableAtRuntimeError as exc:
                if await self._handle_survey_provider_unavailable_error(exc):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            except (
                http_client.TransportError,
            ) as exc:
                if self._handle_http_transport_error(exc):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            except Exception as exc:
                if self.run_context.stop_requested():
                    should_requeue_dispatch = False
                    break
                logging.exception("HTTP 会话[%s]运行异常", self.slot_label)
                if self.stop_policy.record_failure(
                    self.stop_proxy,
                    thread_name=self.slot_label,
                    failure_reason=FailureReason.FILL_FAILED,
                    log_message=f"HTTP 提交失败，本轮按失败处理：{exc}",
                    consume_reverse_fill_attempt=False,
                ):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            finally:
                self._release_session_proxy()
                await self.scheduler.release(
                    int(token_id),
                    requeue=bool(should_requeue_dispatch and not self.run_context.stop_requested()),
                    delay_seconds=dispatch_delay_seconds,
                )
        try:
            self.state.release_joint_sample(self.slot_label)
            self.state.release_reverse_fill_sample(self.slot_label, requeue=True)
            self.state.mark_thread_finished(self.slot_label, status_text=self._resolve_finished_status_text())
        except Exception:
            logging.info("HTTP slot 收尾状态更新失败", exc_info=True)

    async def run(self) -> None:
        if not self._uses_http_runtime():
            self._block_http_runtime(self._resolve_http_runtime_block_reason())
            return
        await self._run_http_runtime()


__all__ = ["AsyncSlotRunner"]
