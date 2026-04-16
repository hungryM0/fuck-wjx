"""运行停止策略。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from software.core.engine.failure_reason import FailureReason
from software.core.task import EVENT_TARGET_REACHED, ExecutionConfig, ExecutionState, bus as _event_bus


class RunStopPolicy:
    """统一处理暂停、成功、失败、达标停止等策略。"""

    def __init__(self, config: ExecutionConfig, state: ExecutionState, gui_instance: Optional[Any] = None):
        self.config = config
        self.state = state
        self.gui_instance = gui_instance

    def wait_if_paused(self, stop_signal: Optional[threading.Event]) -> None:
        try:
            if self.gui_instance:
                self.gui_instance.wait_if_paused(stop_signal)
        except Exception:
            logging.info("暂停等待失败", exc_info=True)

    def record_failure(
        self,
        stop_signal: Optional[threading.Event],
        thread_name: Optional[str] = None,
        *,
        failure_reason: FailureReason = FailureReason.FILL_FAILED,
        status_text: str = "失败重试",
        log_message: str = "",
    ) -> bool:
        with self.state.lock:
            self.state.cur_fail += 1
            if failure_reason == FailureReason.DEVICE_QUOTA_LIMIT:
                self.state.device_quota_fail_count = max(0, int(self.state.device_quota_fail_count or 0)) + 1
            message = str(log_message or "").strip()
            if message:
                logging.warning("%s", message)
            if self.config.stop_on_fail_enabled:
                logging.warning(
                    "已连续失败%s次，连续失败达到%s次将强制停止",
                    self.state.cur_fail,
                    int(self.config.fail_threshold),
                )
            else:
                logging.warning("已连续失败%s次（失败止损已关闭）", self.state.cur_fail)
        if thread_name:
            try:
                self.state.release_joint_sample(thread_name)
            except Exception:
                logging.info("失败后释放联合信效度样本槽位失败", exc_info=True)
            try:
                self.state.increment_thread_fail(thread_name, status_text=status_text)
            except Exception:
                logging.info("更新线程失败计数失败", exc_info=True)
        if self.config.stop_on_fail_enabled and self.state.cur_fail >= self.config.fail_threshold:
            logging.critical("连续失败次数过多，强制停止，请检查配置是否正确")
            if stop_signal:
                stop_signal.set()
            return True
        return False

    def record_success(self, stop_signal: threading.Event, thread_name: Optional[str] = None) -> bool:
        should_handle_random_ip = False
        trigger_target_stop = False
        should_break = False
        record_thread_success = False
        previous_consecutive_failures = 0

        with self.state.lock:
            if self.config.target_num <= 0 or self.state.cur_num < self.config.target_num:
                previous_consecutive_failures = int(self.state.cur_fail or 0)
                self.state.cur_num += 1
                self.state.cur_fail = 0
                record_thread_success = True
                logging.info(
                    "[OK] 已填写%s份 - 连续失败%s次 - %s",
                    self.state.cur_num,
                    self.state.cur_fail,
                    time.strftime("%H:%M:%S", time.localtime(time.time())),
                )
                if previous_consecutive_failures > 0:
                    logging.info("提交成功，连续失败计数已清零（重置前=%s）", previous_consecutive_failures)
                should_handle_random_ip = self.config.random_proxy_ip_enabled
                if self.config.target_num > 0 and self.state.cur_num >= self.config.target_num:
                    trigger_target_stop = True
            else:
                should_break = True

        if record_thread_success and thread_name:
            try:
                self.state.commit_joint_sample(thread_name)
            except Exception:
                logging.info("提交成功后核销联合信效度样本槽位失败", exc_info=True)
            try:
                self.state.commit_pending_distribution(thread_name)
            except Exception:
                logging.info("提交成功后写入比例统计失败", exc_info=True)
            try:
                self.state.increment_thread_success(thread_name, status_text="提交成功")
            except Exception:
                logging.info("更新线程成功计数失败", exc_info=True)
        if should_break:
            stop_signal.set()
        if trigger_target_stop:
            self.trigger_target_reached_stop(stop_signal)
        if should_handle_random_ip:
            handler = getattr(self.gui_instance, "handle_random_ip_submission", None)
            if callable(handler):
                handler(stop_signal)
        return should_break or trigger_target_stop

    def trigger_target_reached_stop(self, stop_signal: Optional[threading.Event]) -> None:
        with self.state._target_reached_stop_lock:
            if self.state._target_reached_stop_triggered:
                if stop_signal:
                    stop_signal.set()
                return
            self.state._target_reached_stop_triggered = True
        if stop_signal:
            stop_signal.set()
        _event_bus.emit(EVENT_TARGET_REACHED, state=self.state, config=self.config)


__all__ = ["RunStopPolicy"]
