"""Async-first fill runtime loop."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Optional, cast

import software.core.modes.timed_mode as timed_mode
from software.core.ai.runtime import AIRuntimeError
from software.core.engine.async_events import AsyncRunContext, ThreadEventProxy
from software.core.engine.async_scheduler import AsyncScheduler
from software.core.engine.failure_reason import FailureReason
from software.core.engine.page_loader import exception_summary as _page_load_exception_summary
from software.core.engine.page_loader import load_survey_page as _page_loader_load_survey_page
from software.core.engine.page_load_probe import wait_for_page_probe
from software.core.engine.provider_common import ensure_joint_psychometric_answer_plan
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.engine.runtime_ui_bridge import (
    handle_random_ip_submission as trigger_random_ip_submission,
)
from software.core.engine.runtime_error_handlers import handle_ai_runtime_error as _handle_ai_runtime_error_impl
from software.core.engine.runtime_error_handlers import handle_proxy_connection_error as _handle_proxy_connection_error_impl
from software.core.engine.submission_service import SubmissionService
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import ProxyConnectionError
from software.network.browser.async_owner_pool import AsyncBrowserOwnerPool, AsyncBrowserSession
from software.network.browser.runtime_async import BrowserDriver as AsyncBrowserDriver
from software.network.browser.startup import BrowserStartupRuntimeError
import software.network.http as http_client
from software.network.proxy.pool import is_proxy_responsive_async
from software.network.session_policy import (
    _discard_unresponsive_proxy,
    _mark_proxy_temporarily_bad,
    _record_bad_proxy_and_maybe_pause,
    _select_proxy_for_session_async,
    _select_user_agent_for_session,
)
from software.providers.common import SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_WJX, normalize_survey_provider
from software.providers.http_logic import get_http_logic_fallback_reason
from software.providers.registry import fill_survey, fill_survey_http
from software.providers.registry import is_device_quota_limit_page as _provider_is_device_quota_limit_page

JOINT_PRE_ANSWER_RESERVATION_LEASE_SECONDS = 45.0
JOINT_SLOT_WAIT_POLL_SECONDS = 0.5
JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS = 0.2
_JOINT_PRE_ANSWER_TIMEOUT = object()


async def _load_survey_page(driver: Any, config: ExecutionConfig, *, phase_updater: Any = None) -> None:
    return await _page_loader_load_survey_page(
        driver,
        config,
        phase_updater=phase_updater,
        probe_waiter=wait_for_page_probe,
    )


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
        browser_pool: AsyncBrowserOwnerPool,
        gui_instance: Any = None,
    ) -> None:
        self.slot_id = max(1, int(slot_id or 1))
        self.slot_label = f"Slot-{self.slot_id}"
        self.config = config
        self.state = state
        self.run_context = run_context
        self.scheduler = scheduler
        self.browser_pool = browser_pool
        self.gui_instance = gui_instance
        self.stop_proxy = ThreadEventProxy(run_context.stop_event, loop=asyncio.get_running_loop())
        self.stop_policy = RunStopPolicy(config, state, gui_instance)
        self.submission_service = SubmissionService(config, state, self.stop_policy)
        self.proxy_address: Optional[str] = None
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

    def _resolve_timed_refresh_interval(self) -> float:
        try:
            refresh_interval = float(self.config.timed_mode_refresh_interval or timed_mode.DEFAULT_REFRESH_INTERVAL)
        except Exception:
            refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
        if refresh_interval <= 0:
            refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
        return refresh_interval

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

    def _expire_stale_joint_reservations(self) -> None:
        try:
            expired_count = self.state.expire_stale_joint_sample_reservations(
                JOINT_PRE_ANSWER_RESERVATION_LEASE_SECONDS,
            )
        except Exception:
            logging.info("清理过期联合信效度槽位租约失败", exc_info=True)
            return
        if expired_count > 0:
            logging.warning("已释放%s个超时未进入答题的联合信效度槽位", expired_count)

    def _requires_joint_sample(self) -> bool:
        joint_answer_plan = ensure_joint_psychometric_answer_plan(self.config)
        if joint_answer_plan is None:
            return False
        sample_count = int(getattr(joint_answer_plan, "sample_count", self.config.target_num) or self.config.target_num)
        return sample_count > 0

    async def _prepare_round_context(self) -> bool:
        try:
            self.state.reset_pending_distribution(self.slot_label)
        except Exception:
            logging.info("重置本轮比例统计缓存失败", exc_info=True)

        joint_answer_plan = ensure_joint_psychometric_answer_plan(self.config)
        sample_count = 0
        if joint_answer_plan is not None:
            sample_count = int(getattr(joint_answer_plan, "sample_count", self.config.target_num) or self.config.target_num)

        while True:
            if self.run_context.stop_requested():
                return False
            if await self._should_stop_loop():
                return False
            self._expire_stale_joint_reservations()

            reserved_sample_index = None
            if sample_count > 0:
                reserved_sample_index = self.state.reserve_joint_sample(sample_count, thread_name=self.slot_label)

            reverse_fill_sample = self.state.acquire_reverse_fill_sample(self.slot_label)

            if sample_count > 0 and reserved_sample_index is None:
                if reverse_fill_sample.status == "acquired":
                    try:
                        self.state.release_reverse_fill_sample(self.slot_label, requeue=True)
                    except Exception:
                        logging.info("等待信效度配额时回收反填样本失败", exc_info=True)
                if self.state.is_joint_sample_quota_exhausted(sample_count):
                    message = "联合信效度样本槽位已全部完成"
                    logging.info("%s，剩余会话自动收尾。", message)
                    self.state.mark_terminal_stop("target_reached", message=message)
                    self.run_context.stop_event.set()
                    self._update_status("信效度配额已完成", running=False)
                    return False
                self._update_status("等待信效度配额槽位")
                await asyncio.sleep(JOINT_SLOT_WAIT_POLL_SECONDS)
                continue

            if reverse_fill_sample.status == "waiting":
                if reserved_sample_index is not None:
                    try:
                        self.state.release_joint_sample(self.slot_label)
                    except Exception:
                        logging.info("等待反填样本时释放联合信效度样本槽位失败", exc_info=True)
                self._update_status("等待反填样本")
                await asyncio.sleep(JOINT_SLOT_WAIT_POLL_SECONDS)
                continue

            if reverse_fill_sample.status == "exhausted":
                message = "反填样本已耗尽，剩余样本不足以完成目标份数"
                if reserved_sample_index is not None:
                    try:
                        self.state.release_joint_sample(self.slot_label)
                    except Exception:
                        logging.info("反填样本耗尽时释放联合信效度样本槽位失败", exc_info=True)
                self.state.mark_terminal_stop(
                    "reverse_fill_exhausted",
                    failure_reason=FailureReason.FILL_FAILED.value,
                    message=message,
                )
                self._update_status("反填样本不足", running=False)
                self.run_context.stop_event.set()
                return False

            if reverse_fill_sample.status == "acquired" and reverse_fill_sample.sample is not None:
                logging.info(
                    "会话[%s]已锁定反填样本：数据行=%s 工作表行=%s",
                    self.slot_label,
                    reverse_fill_sample.sample.data_row_number,
                    reverse_fill_sample.sample.worksheet_row_number,
                )
            return True

    def _release_round_resources(self, *, requeue_reverse_fill: bool) -> None:
        try:
            self.state.release_joint_sample(self.slot_label)
        except Exception:
            logging.info("释放联合信效度样本槽位失败", exc_info=True)
        try:
            self.state.release_reverse_fill_sample(self.slot_label, requeue=requeue_reverse_fill)
        except Exception:
            logging.info("释放反填样本失败", exc_info=True)

    async def _select_session_proxy_and_ua(self) -> tuple[Optional[str], Optional[str]]:
        should_wait_for_proxy = bool(self.config.random_proxy_ip_enabled)
        if self.config.random_proxy_ip_enabled:
            self._update_step("获取代理")
        proxy_address = await _select_proxy_for_session_async(
            self.state,
            self.slot_label,
            stop_signal=self.stop_proxy,
            wait=should_wait_for_proxy,
        )
        if self.config.random_proxy_ip_enabled and not proxy_address:
            if _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance):
                return None, None
        if proxy_address and not await is_proxy_responsive_async(proxy_address):
            logging.warning("提取到的代理质量过低，自动弃用更换下一个")
            _discard_unresponsive_proxy(self.state, proxy_address)
            self.state.release_proxy_in_use(self.slot_label)
            return None, None
        ua_value, _ = _select_user_agent_for_session(self.state)
        return proxy_address, ua_value

    async def _open_session(self) -> Optional[AsyncBrowserSession]:
        if self.run_context.stop_requested():
            return None
        proxy_result = await self._run_pre_answer_step_with_joint_lease(
            "获取代理",
            self._select_session_proxy_and_ua,
        )
        if proxy_result is _JOINT_PRE_ANSWER_TIMEOUT:
            return None
        proxy_address, ua_value = proxy_result
        if self.run_context.stop_requested():
            return None
        if self.config.random_proxy_ip_enabled and not proxy_address:
            return None
        self.proxy_address = proxy_address
        self._update_step("启动浏览器会话")
        session = await self._run_pre_answer_step_with_joint_lease(
            "启动浏览器",
            lambda: self.browser_pool.open_session(proxy_address=proxy_address, user_agent=ua_value),
        )
        if session is _JOINT_PRE_ANSWER_TIMEOUT:
            return None
        driver = session.driver
        driver.thread_name = self.slot_label
        driver.session_state = self.state
        driver.session_proxy_address = proxy_address or ""
        return session

    async def _close_session(self, session: Optional[AsyncBrowserSession]) -> None:
        if session is not None:
            await session.close()
        self._release_session_proxy()

    def _release_session_proxy(self) -> None:
        if self.proxy_address:
            try:
                self.state.release_proxy_in_use(self.slot_label)
            except Exception:
                logging.info("释放代理占用失败", exc_info=True)
        self.proxy_address = None

    async def _load_survey_or_record_failure(self, session: AsyncBrowserSession) -> bool:
        if self.run_context.stop_requested():
            return False
        await self.run_context.wait_if_paused()
        self._update_step("加载问卷")
        try:
            if self.config.timed_mode_enabled:
                ready = await self._run_pre_answer_step_with_joint_lease(
                    "加载问卷",
                    lambda: timed_mode.wait_until_open(
                        cast(AsyncBrowserDriver, session.driver),
                        self.config.url,
                        self.stop_proxy,
                        refresh_interval=self._resolve_timed_refresh_interval(),
                        logger=logging.info,
                    ),
                )
                if ready is _JOINT_PRE_ANSWER_TIMEOUT:
                    return False
                if not ready:
                    self.run_context.stop_event.set()
                    return False
            else:
                async def _load_and_confirm() -> bool:
                    await _load_survey_page(
                        session.driver,
                        self.config,
                        phase_updater=lambda status_text: self._update_step(status_text),
                    )
                    return True

                loaded = await self._run_pre_answer_step_with_joint_lease(
                    "加载问卷",
                    _load_and_confirm,
                )
                if loaded is _JOINT_PRE_ANSWER_TIMEOUT:
                    return False
        except ProxyConnectionError:
            raise
        except Exception as exc:
            self.stop_policy.record_failure(
                self.stop_proxy,
                thread_name=self.slot_label,
                failure_reason=FailureReason.PAGE_LOAD_FAILED,
                status_text="加载问卷失败",
                log_message=f"加载问卷失败，本轮按失败处理：{_page_load_exception_summary(exc)}",
                consume_reverse_fill_attempt=False,
            )
            return False
        return True

    async def _handle_device_quota_limit(self, session: AsyncBrowserSession) -> bool:
        hit = await _provider_is_device_quota_limit_page(
            session.driver,
            provider=self.config.survey_provider,
        )
        if not hit:
            return False
        stopped = self.stop_policy.record_failure(
            self.stop_proxy,
            thread_name=self.slot_label,
            failure_reason=FailureReason.DEVICE_QUOTA_LIMIT,
            status_text="设备达到填写次数上限",
            log_message="设备达到填写次数上限，本轮按失败处理",
            consume_reverse_fill_attempt=False,
        )
        if stopped:
            self.run_context.stop_event.set()
        self._update_status("设备达到填写次数上限")
        if not stopped and not self.run_context.stop_requested() and self.config.random_proxy_ip_enabled:
            trigger_random_ip_submission(self.gui_instance, self.stop_proxy)
        return True

    async def _finalize_after_submit(self, session: AsyncBrowserSession) -> Any:
        return await self.submission_service.finalize_after_submit(
            cast(AsyncBrowserDriver, session.driver),
            stop_signal=self.stop_proxy,
            gui_instance=self.gui_instance,
            thread_name=self.slot_label,
        )

    def _finalize_without_submit(self) -> Any:
        should_stop = self.stop_policy.record_success(
            self.stop_proxy,
            thread_name=self.slot_label,
            status_text="单测完成",
            terminal_message="不提交单测已完成",
        )
        return type(
            "_NoSubmitOutcome",
            (),
            {
                "status": "success",
                "should_rotate_proxy": False,
                "should_stop": should_stop,
            },
        )()

    async def _wait_for_next_unique_proxy(self) -> bool:
        if not self.config.random_proxy_ip_enabled:
            return True
        self._update_status("等待新代理")
        while not self.run_context.stop_requested():
            stopped = await asyncio.to_thread(
                self.state.wait_for_runtime_change,
                stop_signal=self.stop_proxy,
                timeout=0.5,
            )
            if stopped:
                return False
            return True
        return False

    async def _run_pre_answer_step_with_joint_lease(self, label: str, operation: Any) -> Any:
        if self.state.peek_reserved_joint_sample(self.slot_label) is None:
            return await operation()
        try:
            return await asyncio.wait_for(
                operation(),
                timeout=JOINT_PRE_ANSWER_RESERVATION_LEASE_SECONDS,
            )
        except asyncio.TimeoutError:
            logging.warning(
                "会话[%s]在%s阶段超过%.0f秒未进入答题，释放联合信效度槽位",
                self.slot_label,
                label,
                JOINT_PRE_ANSWER_RESERVATION_LEASE_SECONDS,
            )
            self._release_round_resources(requeue_reverse_fill=True)
            self._joint_pre_answer_timed_out = True
            return _JOINT_PRE_ANSWER_TIMEOUT

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
        if self.config.random_proxy_ip_enabled and _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance):
            return True
        return False

    def _handle_proxy_connection_error(self, session: Optional[AsyncBrowserSession]) -> bool:
        holder = type("_AsyncSessionHolder", (), {"proxy_address": self.proxy_address})()
        del session
        return _handle_proxy_connection_error_impl(
            holder,
            self.stop_proxy,
            thread_name=self.slot_label,
            state=self.state,
            config=self.config,
            stop_policy=self.stop_policy,
            update_thread_status=lambda name, status_text: self._update_status(status_text),
            handle_proxy_unavailable=lambda _stop_signal, **kwargs: self._handle_proxy_unavailable(
                status_text=str(kwargs.get("status_text") or "代理不可用"),
                log_message=str(kwargs.get("log_message") or "代理连接失败"),
            ),
            mark_proxy_temporarily_bad=_mark_proxy_temporarily_bad,
        )

    async def _handle_ai_runtime_error(self, exc: AIRuntimeError) -> bool:
        return _handle_ai_runtime_error_impl(
            exc,
            self.stop_proxy,
            thread_name=self.slot_label,
            stop_policy=self.stop_policy,
            state=self.state,
        )

    def _uses_http_runtime(self) -> bool:
        provider = normalize_survey_provider(self.config.survey_provider)
        if not bool(str(self.config.url or "").strip()) or provider not in {SURVEY_PROVIDER_WJX, SURVEY_PROVIDER_QQ}:
            return False
        questions = list((self.config.questions_metadata or {}).values())
        return not bool(get_http_logic_fallback_reason(questions))

    def _mark_http_submit_success(self) -> bool:
        if self.proxy_address:
            try:
                self.state.mark_successful_proxy_address(self.proxy_address)
            except Exception:
                logging.info("记录成功代理失败：%s", self.proxy_address, exc_info=True)
        return self.stop_policy.record_success(self.stop_proxy, thread_name=self.slot_label)

    def _handle_http_transport_error(self, exc: BaseException) -> bool:
        if self.proxy_address:
            try:
                _mark_proxy_temporarily_bad(self.state, self.proxy_address)
            except Exception:
                logging.info("标记 HTTP 代理异常失败", exc_info=True)
        return self._handle_proxy_unavailable(
            status_text="代理连接失败" if self.proxy_address else "网络请求失败",
            log_message=f"HTTP 请求失败，本轮按失败处理：{exc}",
        )

    async def _run_http_runtime(self) -> None:
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
                if not await self._prepare_round_context():
                    should_requeue_dispatch = False
                    break

                proxy_result = await self._run_pre_answer_step_with_joint_lease(
                    "获取代理",
                    self._select_session_proxy_and_ua,
                )
                if proxy_result is _JOINT_PRE_ANSWER_TIMEOUT:
                    dispatch_delay_seconds = JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS
                    continue
                proxy_address, ua_value = proxy_result
                if self.run_context.stop_requested():
                    should_requeue_dispatch = False
                    break
                if self.config.random_proxy_ip_enabled and not proxy_address:
                    self._release_round_resources(requeue_reverse_fill=True)
                    continue
                self.proxy_address = proxy_address

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

                finished = await fill_survey_http(
                    self.config,
                    self.state,
                    stop_signal=self.stop_proxy,
                    thread_name=self.slot_label,
                    provider=self.config.survey_provider,
                    proxy_address=proxy_address,
                    user_agent=ua_value,
                )
                if self.run_context.stop_requested() or not finished:
                    self._release_round_resources(requeue_reverse_fill=True)
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue

                if bool(getattr(self.config, "submit_enabled", True)):
                    should_stop = self._mark_http_submit_success()
                    if should_stop:
                        should_requeue_dispatch = False
                        break
                else:
                    outcome = self._finalize_without_submit()
                    if outcome.should_stop:
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
            except (
                http_client.ConnectTimeout,
                http_client.ReadTimeout,
                http_client.ConnectionError,
                http_client.Timeout,
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

    def _handle_browser_startup_error(self, exc: BrowserStartupRuntimeError) -> bool:
        message = str(exc or "").strip() or "浏览器底座启动失败"
        logging.error("异步浏览器底座启动失败，已停止本次运行，避免继续消耗随机IP：%s", message)
        self.stop_policy.record_failure(
            self.stop_proxy,
            thread_name=self.slot_label,
            failure_reason=FailureReason.BROWSER_START_FAILED,
            status_text="浏览器启动失败",
            log_message=message,
            terminal_stop_category="browser_start_failed",
            force_stop_when_threshold_reached=True,
            consume_reverse_fill_attempt=False,
        )
        self.state.mark_terminal_stop(
            "browser_start_failed",
            failure_reason=FailureReason.BROWSER_START_FAILED.value,
            message=message,
        )
        self.run_context.stop_event.set()
        return True

    async def run(self) -> None:
        if self._uses_http_runtime():
            await self._run_http_runtime()
            return

        self._update_status("会话启动", running=True)
        while True:
            if await self._should_stop_loop():
                break
            token_id = await self.scheduler.acquire()
            if token_id is None:
                break
            session: Optional[AsyncBrowserSession] = None
            keep_session_open = False
            should_requeue_dispatch = True
            dispatch_delay_seconds = 0.0
            try:
                self._joint_pre_answer_timed_out = False
                if not await self._prepare_round_context():
                    should_requeue_dispatch = False
                    break
                session = await self._open_session()
                if session is None:
                    if not self._joint_pre_answer_timed_out:
                        self._release_round_resources(requeue_reverse_fill=True)
                    else:
                        dispatch_delay_seconds = JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue
                if not await self._load_survey_or_record_failure(session):
                    if not self._joint_pre_answer_timed_out:
                        self._release_round_resources(requeue_reverse_fill=True)
                    else:
                        dispatch_delay_seconds = JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue
                if await self._handle_device_quota_limit(session):
                    self._release_round_resources(requeue_reverse_fill=True)
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue
                try:
                    marked_answering = self.state.mark_joint_sample_answering(self.slot_label)
                except Exception:
                    logging.info("标记联合信效度槽位进入答题失败", exc_info=True)
                    marked_answering = False
                if self._requires_joint_sample() and not marked_answering:
                    logging.warning("会话[%s]进入答题前发现联合信效度槽位已释放，本轮放弃并重试", self.slot_label)
                    self._release_round_resources(requeue_reverse_fill=True)
                    dispatch_delay_seconds = JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS
                    continue
                finished = await fill_survey(
                    session.driver,
                    self.config,
                    self.state,
                    stop_signal=self.stop_proxy,
                    thread_name=self.slot_label,
                    provider=self.config.survey_provider,
                )
                if self.run_context.stop_requested() or not finished:
                    self._release_round_resources(requeue_reverse_fill=True)
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue
                outcome = (
                    await self._finalize_after_submit(session)
                    if bool(getattr(self.config, "submit_enabled", True))
                    else self._finalize_without_submit()
                )
                if outcome.status == "success":
                    keep_session_open = not bool(getattr(self.config, "submit_enabled", True))
                    if bool(getattr(outcome, "should_rotate_proxy", False)):
                        await self._close_session(session)
                        session = None
                        keep_session_open = False
                        if not await self._wait_for_next_unique_proxy():
                            should_requeue_dispatch = False
                            break
                    if outcome.should_stop:
                        should_requeue_dispatch = False
                        break
                    dispatch_delay_seconds = self._resolve_dispatch_delay_seconds()
                    if dispatch_delay_seconds > 0:
                        self._update_step("等待提交间隔")
                elif outcome.status == "aborted":
                    self._release_round_resources(requeue_reverse_fill=True)
                    should_requeue_dispatch = False
                    break
                else:
                    dispatch_delay_seconds = self._resolve_dispatch_delay_seconds()
                    if dispatch_delay_seconds > 0:
                        self._update_step("等待提交间隔")
            except AIRuntimeError as exc:
                if await self._handle_ai_runtime_error(exc):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            except ProxyConnectionError:
                if self._handle_proxy_connection_error(session):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            except BrowserStartupRuntimeError as exc:
                if self._handle_browser_startup_error(exc):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            except Exception:
                if self.run_context.stop_requested():
                    should_requeue_dispatch = False
                    break
                logging.exception("异步会话[%s]运行异常", self.slot_label)
                if self.stop_policy.record_failure(
                    self.stop_proxy,
                    thread_name=self.slot_label,
                    failure_reason=FailureReason.FILL_FAILED,
                    consume_reverse_fill_attempt=False,
                ):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            finally:
                if not keep_session_open:
                    await self._close_session(session)
                else:
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
            logging.info("slot 收尾状态更新失败", exc_info=True)


__all__ = ["AsyncSlotRunner"]
