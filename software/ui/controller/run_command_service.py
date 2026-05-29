from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from software.app.config import (
    STOP_FORCE_WAIT_SECONDS,
    app_settings,
    get_bool_from_qsettings,
)
from software.core.config.schema import RuntimeConfig
from software.core.engine.async_engine import AsyncEngineClient
from software.core.engine.cleanup import CleanupRunner
from software.core.engine.failure_reason import FailureReason
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.io.config.store import load_config, save_config
from software.system.power_management import SystemSleepBlocker
from software.ui.controller.controller_events import event_payload
from software.ui.controller.run_runtime_port import RunRuntimePort
from software.ui.controller.run_state_store import RunStateStore
from software.ui.controller.run_controller_parts.runtime_init_gate import (
    RunControllerInitializationMixin,
)
from software.ui.controller.run_controller_parts.runtime_preparation import (
    PreparedExecutionArtifacts,
    RuntimePreparationError,
    prepare_execution_artifacts,
)
from software.ui.controller.run_controller_parts.runtime_random_ip import (
    RandomIpRuntimeService,
)
from software.ui.controller.run_controller_parts.runtime_shutdown import (
    RuntimeShutdownHelper,
    clear_finished_thread,
)


@dataclass
class _RuntimeLifecycleState:
    paused: bool = False
    stopping: bool = False
    completion_cleanup_done: bool = False
    cleanup_scheduled: bool = False
    stopped_by_stop_run: bool = False
    quick_feedback_prompt_emitted: bool = False
    starting: bool = False
    initializing: bool = False
    init_stage_text: str = ""
    init_steps: List[Dict[str, str]] = field(default_factory=list)
    init_completed_steps: set[str] = field(default_factory=set)
    init_current_step_key: str = ""
    init_gate_stop_event: Optional[threading.Event] = None
    prepared_execution_artifacts: Optional[PreparedExecutionArtifacts] = None


class _RandomIpUiAdapter:
    def __init__(self, service: "RunCommandService") -> None:
        self._service = service

    def show_message_dialog(self, title: str, message: str, *, level: str = "info") -> None:
        self._service.emit_event(
            event_payload(
                "dialog_message",
                title=str(title or ""),
                message=str(message or ""),
                level=str(level or "info"),
            )
        )

    def update_random_ip_counter(self, used: float, total: float, custom_api: bool) -> None:
        self._service.apply_runtime_patch(
            {
                "random_ip": {
                    "used_quota": max(0.0, float(used or 0.0)),
                    "total_quota": max(0.0, float(total or 0.0)),
                    "custom_api": bool(custom_api),
                }
            }
        )

    def set_random_ip_enabled(self, enabled: bool) -> None:
        self._service.sync_random_ip_enabled(bool(enabled))

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self._service.notify_random_ip_loading(bool(loading), str(message or ""))

    def open_quota_request_form(self) -> bool:
        self._service.emit_event(
            event_payload(
                "open_quota_request_form",
                reason="random_ip_required",
                retry_enable_random_ip=True,
            )
        )
        return False


class RunCommandService(RandomIpRuntimeService, RunControllerInitializationMixin):
    def __init__(
        self,
        *,
        state_store: RunStateStore,
        async_engine_client: AsyncEngineClient,
        cleanup_runner: CleanupRunner,
        sleep_blocker: SystemSleepBlocker,
        dispatch_async: Callable[[Callable[[], Any]], None],
        emit_event: Callable[[dict[str, Any]], None],
    ) -> None:
        self._state_store = state_store
        self._async_engine_client = async_engine_client
        self._cleanup_runner = cleanup_runner
        self._sleep_blocker = sleep_blocker
        self._dispatch_to_ui_async = dispatch_async
        self._emit_event = emit_event
        self._runtime = _RuntimeLifecycleState()
        self.stop_event = threading.Event()
        self.worker_threads: List[threading.Thread] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self._init_gate_thread: Optional[threading.Thread] = None
        self._status_snapshot_monitor_thread: Optional[threading.Thread] = None
        self._execution_state: Optional[ExecutionState] = None
        self._close_shutdown_lock = threading.Lock()
        self._close_shutdown_thread: Optional[threading.Thread] = None
        self._random_ip_toggle_lock = threading.Lock()
        self._random_ip_toggle_active = False
        self._random_ip_server_sync_lock = threading.Lock()
        self._random_ip_server_sync_active = False
        self._random_ip_last_server_sync_at = 0.0
        self._random_ip_background_threads: set[threading.Thread] = set()
        self._random_ip_background_threads_lock = threading.Lock()
        self._last_loaded_config = RuntimeConfig()
        self.running = False
        self.runtime_port = RunRuntimePort(
            stop_signal=self.stop_event,
            notify_random_ip_loading=self.notify_random_ip_loading,
            handle_random_ip_submission=self.handle_random_ip_submission,
        )
        self.adapter = _RandomIpUiAdapter(self)

    def parent(self) -> None:
        return None

    @property
    def _starting(self) -> bool:
        return self._runtime.starting

    @_starting.setter
    def _starting(self, value: bool) -> None:
        self._runtime.starting = bool(value)

    @property
    def _initializing(self) -> bool:
        return self._runtime.initializing

    @_initializing.setter
    def _initializing(self, value: bool) -> None:
        self._runtime.initializing = bool(value)

    @property
    def _paused_state(self) -> bool:
        return self._runtime.paused

    @_paused_state.setter
    def _paused_state(self, value: bool) -> None:
        self._runtime.paused = bool(value)

    @property
    def _stopping(self) -> bool:
        return self._runtime.stopping

    @_stopping.setter
    def _stopping(self, value: bool) -> None:
        self._runtime.stopping = bool(value)

    @property
    def _completion_cleanup_done(self) -> bool:
        return self._runtime.completion_cleanup_done

    @_completion_cleanup_done.setter
    def _completion_cleanup_done(self, value: bool) -> None:
        self._runtime.completion_cleanup_done = bool(value)

    @property
    def _cleanup_scheduled(self) -> bool:
        return self._runtime.cleanup_scheduled

    @_cleanup_scheduled.setter
    def _cleanup_scheduled(self, value: bool) -> None:
        self._runtime.cleanup_scheduled = bool(value)

    @property
    def _stopped_by_stop_run(self) -> bool:
        return self._runtime.stopped_by_stop_run

    @_stopped_by_stop_run.setter
    def _stopped_by_stop_run(self, value: bool) -> None:
        self._runtime.stopped_by_stop_run = bool(value)

    @property
    def _quick_feedback_prompt_emitted(self) -> bool:
        return self._runtime.quick_feedback_prompt_emitted

    @_quick_feedback_prompt_emitted.setter
    def _quick_feedback_prompt_emitted(self, value: bool) -> None:
        self._runtime.quick_feedback_prompt_emitted = bool(value)

    @property
    def _init_stage_text(self) -> str:
        return self._runtime.init_stage_text

    @_init_stage_text.setter
    def _init_stage_text(self, value: str) -> None:
        self._runtime.init_stage_text = str(value or "")

    @property
    def _init_steps(self) -> List[Dict[str, str]]:
        return self._runtime.init_steps

    @_init_steps.setter
    def _init_steps(self, value: List[Dict[str, str]]) -> None:
        self._runtime.init_steps = list(value or [])

    @property
    def _init_completed_steps(self) -> set[str]:
        return self._runtime.init_completed_steps

    @_init_completed_steps.setter
    def _init_completed_steps(self, value: set[str]) -> None:
        self._runtime.init_completed_steps = set(value or set())

    @property
    def _init_current_step_key(self) -> str:
        return self._runtime.init_current_step_key

    @_init_current_step_key.setter
    def _init_current_step_key(self, value: str) -> None:
        self._runtime.init_current_step_key = str(value or "")

    @property
    def _init_gate_stop_event(self) -> Optional[threading.Event]:
        return self._runtime.init_gate_stop_event

    @_init_gate_stop_event.setter
    def _init_gate_stop_event(self, value: Optional[threading.Event]) -> None:
        self._runtime.init_gate_stop_event = value

    @property
    def _prepared_execution_artifacts(self) -> Optional[PreparedExecutionArtifacts]:
        return self._runtime.prepared_execution_artifacts

    @_prepared_execution_artifacts.setter
    def _prepared_execution_artifacts(self, value: Optional[PreparedExecutionArtifacts]) -> None:
        self._runtime.prepared_execution_artifacts = value

    def is_initializing(self) -> bool:
        return bool(self._initializing)

    def threads_update_locked(self) -> bool:
        return bool(self.running or self._starting or self._initializing)

    def apply_runtime_patch(self, patch: Dict[str, Any]) -> None:
        self._dispatch_to_ui_async(lambda payload=dict(patch): self._state_store.apply_runtime_patch(payload))

    def emit_event(self, payload: Dict[str, Any]) -> None:
        self._dispatch_to_ui_async(lambda event=dict(payload): self._emit_event(event))

    def sync_random_ip_enabled(self, enabled: bool) -> None:
        self.runtime_port.set_random_ip_enabled(bool(enabled))
        self._dispatch_to_ui_async(
            lambda value=bool(enabled): self._state_store.update_runtime_settings(
                random_ip_enabled=value,
                lock_threads=self.threads_update_locked(),
            )
        )

    def sync_runtime_settings(self, settings: Dict[str, Any]) -> None:
        self.runtime_port.set_random_ip_enabled(bool(settings.get("random_ip_enabled", False)))

    def notify_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.apply_runtime_patch(
            {
                "random_ip": {
                    "loading": bool(loading),
                    "loading_message": str(message or ""),
                }
            }
        )

    def load_saved_config(self, path: Optional[str] = None, *, strict: bool = False) -> RuntimeConfig:
        cfg = load_config(path, strict=strict)
        self._last_loaded_config = cfg
        return cfg

    def save_config(self, config: RuntimeConfig, path: Optional[str] = None) -> str:
        self._last_loaded_config = config
        return save_config(config, path)

    def save_current_config(self, path: Optional[str] = None) -> str:
        return save_config(self._last_loaded_config, path)

    def _should_prevent_sleep_during_run(self) -> bool:
        settings = app_settings()
        return get_bool_from_qsettings(settings.value("prevent_sleep_during_run"), True)

    def _apply_sleep_blocker_for_run_start(self) -> None:
        if not self._should_prevent_sleep_during_run():
            return
        try:
            self._sleep_blocker.acquire()
        except Exception:
            logging.warning("启用阻止自动休眠失败", exc_info=True)

    def _release_sleep_blocker(self) -> None:
        try:
            self._sleep_blocker.release()
        except Exception:
            logging.warning("恢复自动休眠状态失败", exc_info=True)

    def start_run(self, config: RuntimeConfig) -> None:
        if self.running or self._starting or self._initializing or self._stopping:
            logging.warning("任务仍在运行或停止收尾中，忽略重复启动请求")
            return

        self._last_loaded_config = config
        self._state_store.hydrate_from_config(config, emit=True)

        try:
            prepared = prepare_execution_artifacts(
                config,
                fallback_survey_title=str(
                    self._state_store.get_survey_snapshot().get("survey_title") or ""
                ),
            )
        except RuntimePreparationError as exc:
            if exc.detailed:
                logging.error(exc.log_message, exc_info=True)
            else:
                logging.error(exc.log_message)
            self._state_store.apply_runtime_patch(
                {
                    "phase": "failed",
                    "running": False,
                    "paused": False,
                    "stopping": False,
                    "status_text": exc.user_message,
                }
            )
            self.emit_event(event_payload("run_failed", message=exc.user_message))
            return

        self.stop_event = threading.Event()
        self.runtime_port = RunRuntimePort(
            stop_signal=self.stop_event,
            notify_random_ip_loading=self.notify_random_ip_loading,
            handle_random_ip_submission=self.handle_random_ip_submission,
        )
        self.runtime_port.set_random_ip_enabled(bool(config.random_ip_enabled))
        self._prepared_execution_artifacts = prepared
        self._paused_state = False
        self._stopping = False
        self._completion_cleanup_done = False
        self._cleanup_scheduled = False
        self._stopped_by_stop_run = False
        self._quick_feedback_prompt_emitted = False
        self._starting = True
        self._initializing = True
        self._init_stage_text = "正在初始化"
        self._init_steps = []
        self._init_completed_steps = set()
        self._init_current_step_key = ""
        self._init_gate_stop_event = None
        self._state_store.apply_runtime_patch(
            {
                "phase": "initializing",
                "running": False,
                "paused": False,
                "stopping": False,
                "status_text": "正在初始化",
                "initialization": {
                    "active": True,
                    "text": "正在初始化",
                    "logs": self._build_initialization_logs(),
                },
                "terminal_stop": {
                    "category": "",
                    "failure_reason": "",
                    "message": "",
                },
            }
        )
        self._start_with_initialization_gate(config, [])

    def _start_workers_with_proxy_pool(
        self,
        config: RuntimeConfig,
        proxy_pool: List[ProxyLease],
        *,
        emit_run_state: bool = True,
    ) -> None:
        del emit_run_state
        execution_config, execution_state = self._prepare_engine_state(proxy_pool)
        worker_count = max(1, int(execution_config.num_threads or 1))
        execution_state.ensure_worker_threads(worker_count, prefix="Slot")
        execution_state.initialize_reverse_fill_runtime()
        self._execution_state = execution_state
        self._prepared_execution_artifacts = None
        self._last_loaded_config = config

        self._apply_sleep_blocker_for_run_start()
        self.running = True
        self._starting = False
        self._initializing = False
        self._stopping = False
        self._state_store.apply_runtime_patch(
            {
                "phase": "running",
                "running": True,
                "paused": False,
                "stopping": False,
                "initialization": {
                    "active": False,
                    "text": "",
                    "logs": [],
                },
                "threads": {
                    "num_threads": worker_count,
                    "per_thread_target": int(
                        math.ceil(float(max(0, execution_config.target_num or 0)) / float(worker_count))
                    )
                    if int(execution_config.target_num or 0) > 0
                    else 0,
                },
            }
        )
        self._start_status_snapshot_monitor(execution_state)

        run_future = self._async_engine_client.start_run(
            execution_config,
            execution_state,
            runtime_bridge=self.runtime_port,
        )
        runtime_thread = self._async_engine_client.thread
        self.worker_threads = (
            [runtime_thread] if isinstance(runtime_thread, threading.Thread) else []
        )
        monitor = threading.Thread(
            target=self._wait_for_async_run,
            args=(run_future,),
            daemon=True,
            name="Monitor",
        )
        self._monitor_thread = monitor
        monitor.start()
        self.emit_status_snapshot()

    def _start_status_snapshot_monitor(self, execution_state: ExecutionState) -> None:
        previous = self._status_snapshot_monitor_thread
        if isinstance(previous, threading.Thread) and previous.is_alive():
            previous.join(timeout=0.5)

        monitor = threading.Thread(
            target=self._status_snapshot_monitor_loop,
            args=(execution_state, self.stop_event),
            daemon=True,
            name="RuntimeStatusSnapshotMonitor",
        )
        self._status_snapshot_monitor_thread = monitor
        monitor.start()

    def _status_snapshot_monitor_loop(
        self,
        execution_state: ExecutionState,
        stop_signal: threading.Event,
    ) -> None:
        while not stop_signal.is_set():
            try:
                execution_state.wait_for_runtime_change(
                    stop_signal=stop_signal,
                    timeout=0.25,
                )
            except Exception:
                logging.debug("等待运行态变更失败", exc_info=True)
                time.sleep(0.25)
            if self._execution_state is not execution_state:
                break
            try:
                self._dispatch_to_ui_async(self.emit_status_snapshot)
            except Exception:
                logging.debug("派发运行态快照失败", exc_info=True)
        if self._execution_state is execution_state:
            try:
                self._dispatch_to_ui_async(self.emit_status_snapshot)
            except Exception:
                logging.debug("派发最终运行态快照失败", exc_info=True)

    def stop_run(self) -> None:
        ctx = self._execution_state
        if ctx is not None:
            ctx.mark_terminal_stop(
                "user_stopped",
                failure_reason=FailureReason.USER_STOPPED.value,
                message="用户手动停止任务",
            )
        if self._starting and not self.running:
            self.stop_event.set()
            gate_stop = self._init_gate_stop_event
            if gate_stop is not None:
                gate_stop.set()
            self._prepared_execution_artifacts = None
            self._starting = False
            self._initializing = False
            self._state_store.apply_runtime_patch(
                {
                    "phase": "finished",
                    "running": False,
                    "paused": False,
                    "stopping": False,
                    "status_text": "已停止",
                    "initialization": {"active": False, "text": "", "logs": []},
                }
            )
            return
        if not self.running:
            return
        try:
            self._async_engine_client.stop_run()
        except Exception:
            logging.debug("停止 async-first 内核失败", exc_info=True)
        self.stop_event.set()
        gate_stop = self._init_gate_stop_event
        if gate_stop is not None:
            gate_stop.set()
        try:
            self.runtime_port.resume_run()
        except Exception:
            logging.debug("停止时恢复暂停状态失败", exc_info=True)
        try:
            self._async_engine_client.resume_run()
        except Exception:
            logging.debug("停止时恢复 async-first 内核暂停状态失败", exc_info=True)
        self._stopping = True
        self._paused_state = False
        self._stopped_by_stop_run = True
        self._state_store.apply_runtime_patch(
            {
                "phase": "stopping",
                "running": True,
                "paused": False,
                "stopping": True,
            }
        )
        self.emit_status_snapshot()

    def resume_run(self) -> None:
        if not self.running:
            return
        try:
            self._async_engine_client.resume_run()
        except Exception:
            logging.debug("恢复 async-first 内核运行失败", exc_info=True)
        try:
            self.runtime_port.resume_run()
        except Exception:
            logging.debug("恢复运行时清除暂停状态失败", exc_info=True)
        if self._paused_state:
            self._paused_state = False
        self.emit_status_snapshot()

    def _wait_for_async_run(self, run_future: Any) -> None:
        try:
            try:
                run_future.result()
            except Exception:
                logging.warning("async-first 运行内核异常退出", exc_info=True)
                self.emit_event(
                    event_payload("run_failed", message="后台运行内核异常退出，请查看日志")
                )
        finally:
            self._dispatch_to_ui_async(self._on_run_finished)
            self._monitor_thread = None

    def _on_run_finished(self) -> None:
        self._schedule_cleanup()
        was_active = bool(self.running or self._stopping or self._initializing)
        self._stopped_by_stop_run = False
        self._stopping = False
        self._release_sleep_blocker()
        self.running = False
        self._initializing = False
        if was_active:
            self.emit_status_snapshot()
        self._emit_quick_bug_report_suggestion_if_needed()

    def _submit_cleanup_task(self, delay_seconds: float = 0.0) -> None:
        def _cleanup() -> None:
            try:
                self.runtime_port.cleanup_targets()
            except Exception:
                logging.warning("执行运行时清理任务失败", exc_info=True)
            finally:
                self.emit_event(event_payload("cleanup_finished"))

        self._cleanup_runner.submit(_cleanup, delay_seconds=delay_seconds)

    def _schedule_cleanup(self) -> None:
        if self._cleanup_scheduled:
            return
        self._cleanup_scheduled = True
        self._submit_cleanup_task(delay_seconds=STOP_FORCE_WAIT_SECONDS)

    def emit_status_snapshot(self) -> None:
        if self._initializing:
            self._state_store.apply_runtime_patch(
                {
                    "phase": "initializing",
                    "running": False,
                    "paused": False,
                    "stopping": False,
                    "status_text": "正在初始化",
                    "initialization": {
                        "active": True,
                        "text": self._init_stage_text or "正在初始化",
                        "logs": self._build_initialization_logs(),
                    },
                    "threads": {
                        "rows": [],
                        "num_threads": 0,
                        "per_thread_target": 0,
                    },
                }
            )
            return

        ctx = self._execution_state
        current = int(getattr(ctx, "cur_num", 0) or 0)
        target = int(getattr(getattr(ctx, "config", None), "target_num", 0) or 0)
        consecutive_failures = int(getattr(ctx, "cur_fail", 0) or 0)
        device_quota_fail_count = int(getattr(ctx, "device_quota_fail_count", 0) or 0)
        terminal_category = ""
        terminal_failure_reason = ""
        terminal_message = ""
        if ctx is not None:
            try:
                category, failure_reason, message = ctx.get_terminal_stop_snapshot()
                terminal_category = str(category or "").strip()
                terminal_failure_reason = str(failure_reason or "").strip()
                terminal_message = str(message or "").strip()
            except Exception:
                logging.debug("读取终止状态失败", exc_info=True)

        paused = bool(self.runtime_port.is_paused())
        reason = str(self.runtime_port.get_pause_reason() or "")
        if self._stopping:
            status_prefix = "正在停止"
        elif paused:
            status_prefix = "已暂停"
        elif not self.running and terminal_category == "user_stopped":
            status_prefix = "已停止"
        else:
            status_prefix = "已提交"
        status = f"{status_prefix} {current}/{target} 份 | 提交连续失败 {consecutive_failures} 次"
        if device_quota_fail_count > 0:
            status = f"{status} | 设备限制拦截 {device_quota_fail_count} 次"
        if paused and reason:
            status = f"{status} | {reason}"

        thread_rows: list[dict[str, Any]] = []
        num_threads = 0
        per_thread_target = 0
        if ctx is not None:
            try:
                thread_rows = ctx.snapshot_thread_progress()
            except Exception:
                logging.debug("获取线程进度快照失败", exc_info=True)
            try:
                num_threads = max(
                    1,
                    int(getattr(getattr(ctx, "config", None), "num_threads", 1) or 1),
                )
            except Exception:
                num_threads = 1
            if target > 0:
                per_thread_target = int(math.ceil(float(target) / float(num_threads)))

        phase = "running"
        if self._stopping:
            phase = "stopping"
        elif paused:
            phase = "paused"
        elif not self.running:
            if terminal_category in {"", "target_reached", "user_stopped"}:
                phase = "finished"
            else:
                phase = "failed"

        self._state_store.apply_runtime_patch(
            {
                "phase": phase,
                "running": bool(self.running),
                "paused": bool(paused),
                "stopping": bool(self._stopping),
                "status_text": status,
                "progress": {
                    "current": current,
                    "target": target,
                    "consecutive_failures": consecutive_failures,
                    "device_quota_fail_count": device_quota_fail_count,
                },
                "threads": {
                    "rows": thread_rows,
                    "num_threads": int(num_threads or 0),
                    "per_thread_target": int(per_thread_target or 0),
                },
                "initialization": {
                    "active": False,
                    "text": "",
                    "logs": [],
                },
                "terminal_stop": {
                    "category": terminal_category,
                    "failure_reason": terminal_failure_reason,
                    "message": terminal_message,
                },
            }
        )

        should_force_cleanup = target > 0 and current >= target and not self._completion_cleanup_done
        if should_force_cleanup:
            self._completion_cleanup_done = True
            self._schedule_cleanup()

    def request_shutdown_for_close(self, timeout_seconds: float = 5.0) -> None:
        with self._close_shutdown_lock:
            active = self._close_shutdown_thread
            if isinstance(active, threading.Thread) and active.is_alive():
                return

            def _worker() -> None:
                try:
                    self.shutdown_for_close(timeout_seconds=timeout_seconds)
                except Exception:
                    logging.warning("异步关闭收尾失败", exc_info=True)
                finally:
                    with self._close_shutdown_lock:
                        if self._close_shutdown_thread is threading.current_thread():
                            self._close_shutdown_thread = None

            thread = threading.Thread(
                target=_worker,
                daemon=True,
                name="CloseShutdownWorker",
            )
            self._close_shutdown_thread = thread
            thread.start()

    def _collect_shutdown_threads(self) -> List[threading.Thread]:
        return RuntimeShutdownHelper(self).collect_threads()

    def shutdown_for_close(self, timeout_seconds: float = 5.0) -> bool:
        self._cleanup_scheduled = True
        self.stop_run()

        try:
            self.runtime_port.cleanup_targets()
        except Exception:
            logging.warning("关闭窗口时执行运行时兜底清理失败", exc_info=True)

        deadline = time.monotonic() + max(0.0, float(timeout_seconds or 0.0))
        current = threading.current_thread()
        pending = [thread for thread in self._collect_shutdown_threads() if thread is not current]
        while True:
            alive = [thread for thread in pending if thread.is_alive()]
            if not alive:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            slice_timeout = min(0.1, remaining)
            for thread in alive:
                thread.join(timeout=slice_timeout)

        try:
            remaining = max(0.0, deadline - time.monotonic())
            self._async_engine_client.shutdown(timeout=remaining)
        except Exception:
            logging.warning("关闭窗口时停止 async-first 内核失败", exc_info=True)

        self.worker_threads = [thread for thread in self.worker_threads if thread.is_alive()]
        self._monitor_thread = clear_finished_thread(self._monitor_thread)
        self._init_gate_thread = clear_finished_thread(self._init_gate_thread)
        alive = [thread for thread in pending if thread.is_alive()]
        if alive:
            logging.warning(
                "关闭窗口时仍有后台线程未退出：%s",
                ", ".join(thread.name or "UnnamedThread" for thread in alive),
            )
        return not alive

    def request_toggle_random_ip(
        self,
        enabled: bool,
        *,
        on_done: Optional[Callable[[bool], None]] = None,
    ) -> bool:
        with self._random_ip_toggle_lock:
            if self._random_ip_toggle_active:
                return False
            self._random_ip_toggle_active = True

        self.notify_random_ip_loading(True, "正在处理...")

        def _finish(final_enabled: bool) -> None:
            with self._random_ip_toggle_lock:
                self._random_ip_toggle_active = False
            self.notify_random_ip_loading(False, "")
            self.sync_random_ip_enabled(bool(final_enabled))
            if callable(on_done):
                try:
                    on_done(bool(final_enabled))
                except Exception:
                    logging.info("随机IP异步回调执行失败", exc_info=True)
            self.refresh_random_ip_counter()

        try:
            future = self.submit_toggle_random_ip(bool(enabled))
        except Exception:
            logging.warning("随机IP异步切换提交失败", exc_info=True)
            with self._random_ip_toggle_lock:
                self._random_ip_toggle_active = False
            self.notify_random_ip_loading(False, "")
            return False

        def _on_done_callback(done_future: Any) -> None:
            final_enabled = bool(enabled)
            try:
                final_enabled = bool(done_future.result())
            except Exception:
                logging.warning("随机IP异步切换失败", exc_info=True)
                final_enabled = bool(
                    self._state_store.get_runtime_snapshot()
                    .get("settings", {})
                    .get("random_ip_enabled", False)
                )
            self._dispatch_to_ui_async(lambda value=bool(final_enabled): _finish(value))

        future.add_done_callback(_on_done_callback)
        return True

    def _emit_quick_bug_report_suggestion_if_needed(self) -> None:
        if self._quick_feedback_prompt_emitted:
            return
        if self.running or self._starting or self._initializing:
            return
        ctx = self._execution_state
        if ctx is None:
            return
        category, failure_reason, message = ctx.get_terminal_stop_snapshot()
        category = str(category or "").strip()
        failure_reason = str(failure_reason or "").strip()
        if not category:
            return
        if category == "free_ai_unstable":
            self._quick_feedback_prompt_emitted = True
            self.emit_event(event_payload("free_ai_unstable"))
            return
        if category == "submission_verification":
            self._quick_feedback_prompt_emitted = True
            self.emit_event(
                event_payload(
                    "submission_verification_required",
                    message=str(message or "提交触发智能验证，请启用随机 IP 后再试"),
                )
            )
            return
        if category in {"target_reached", "user_stopped"}:
            return
        if failure_reason in {
            FailureReason.DEVICE_QUOTA_LIMIT.value,
            FailureReason.SUBMISSION_VERIFICATION_REQUIRED.value,
            FailureReason.USER_STOPPED.value,
        }:
            return
        self._quick_feedback_prompt_emitted = True
        self.emit_event(event_payload("quick_bug_report_suggested"))


__all__ = ["RunCommandService"]
