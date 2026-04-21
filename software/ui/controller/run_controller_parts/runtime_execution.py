"""RunController 启停、线程和收尾逻辑。"""
from __future__ import annotations

import logging
import math
import threading
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QCoreApplication

from software.app.config import STOP_FORCE_WAIT_SECONDS
from software.core.engine.runner import run
from software.core.questions.config import configure_probabilities, validate_question_config
from software.core.task import EVENT_TASK_STARTED, EVENT_TASK_STOPPED, ExecutionConfig, ExecutionState, ProxyLease
from software.core.task import bus as _event_bus
from software.io.config import RuntimeConfig
from software.network.proxy import set_proxy_occupy_minute_by_answer_duration


class RunControllerExecutionMixin:
    if TYPE_CHECKING:
        _engine_adapter_cls: Any
        _cleanup_runner: Any
        _status_timer: Any
        runFailed: Any
        runStateChanged: Any
        statusUpdated: Any
        threadProgressUpdated: Any
        pauseStateChanged: Any
        cleanupFinished: Any
        quota_request_form_opener: Optional[Callable[[], bool]]
        on_ip_counter: Optional[Callable[[float, float, bool], None]]
        on_random_ip_loading: Optional[Callable[[bool, str], None]]
        message_dialog_handler: Optional[Callable[[str, str, str], None]]
        confirm_dialog_handler: Optional[Callable[[str, str], bool]]
        stop_event: threading.Event
        worker_threads: List[threading.Thread]
        adapter: Any
        config: RuntimeConfig
        running: bool
        _starting: bool
        _initializing: bool
        _paused_state: bool
        _completion_cleanup_done: bool
        _cleanup_scheduled: bool
        _stopped_by_stop_run: bool
        _probe_hit_device_quota: bool
        _probe_failure_message: str
        _init_stage_text: str
        _init_steps: List[Dict[str, str]]
        _init_completed_steps: set[str]
        _init_current_step_key: str
        _init_gate_stop_event: Optional[threading.Event]
        _pending_execution_config: Optional[ExecutionConfig]
        _execution_state: Optional[ExecutionState]
        survey_provider: str
        question_entries: List[Any]
        questions_info: List[Dict[str, Any]]

        def _dispatch_to_ui_async(self, callback: Callable[[], Any]) -> None: ...
        def _sync_adapter_ui_bridge(self, adapter: Optional[Any] = None) -> None: ...
        def sync_runtime_ui_state_from_config(self, config: RuntimeConfig, *, emit: bool = True) -> Dict[str, Any]: ...
        def refresh_random_ip_counter(self, *, adapter: Optional[Any] = None, async_mode: bool = True) -> None: ...
        def toggle_random_ip(self, enabled: bool, *, adapter: Optional[Any] = None) -> bool: ...
        def handle_random_ip_submission(self, *, stop_signal: Optional[threading.Event], adapter: Optional[Any] = None) -> None: ...
        def _start_with_initialization_gate(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> None: ...
        def _prepare_engine_state(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> tuple[ExecutionConfig, ExecutionState]: ...
        def _apply_pending_execution_config(self, config: ExecutionConfig, *, consume: bool) -> None: ...
        def _reset_initialization_state(self) -> None: ...
        def _build_initialization_logs(self) -> List[str]: ...

    def _create_adapter(self, stop_signal: threading.Event, *, random_ip_enabled: bool = False):
        adapter_cls = getattr(self, "_engine_adapter_cls", None)
        if adapter_cls is None:
            raise RuntimeError("Engine adapter class 未初始化")
        adapter = adapter_cls(
            self._dispatch_to_ui,
            stop_signal,
            quota_request_form_opener=self.quota_request_form_opener,
            on_ip_counter=self.on_ip_counter,
            on_random_ip_loading=self.on_random_ip_loading,
            message_handler=self.message_dialog_handler,
            confirm_handler=self.confirm_dialog_handler,
            async_dispatcher=self._dispatch_to_ui_async,
            cleanup_runner=self._cleanup_runner,
        )
        adapter.random_ip_enabled_var.set(bool(random_ip_enabled))
        self._sync_adapter_ui_bridge(adapter)
        adapter.refresh_random_ip_counter = lambda *, async_mode=True, _adapter=adapter: self.refresh_random_ip_counter(  # type: ignore[attr-defined]
            adapter=_adapter,
            async_mode=async_mode,
        )
        adapter.toggle_random_ip = lambda enabled=None, _adapter=adapter: self.toggle_random_ip(  # type: ignore[attr-defined]
            _adapter.is_random_ip_enabled() if enabled is None else enabled,
            adapter=_adapter,
        )
        adapter.handle_random_ip_submission = lambda stop_signal=None, _adapter=adapter: self.handle_random_ip_submission(  # type: ignore[attr-defined]
            stop_signal=stop_signal,
            adapter=_adapter,
        )
        return adapter
    def _dispatch_to_ui(self, callback: Callable[[], Any]):
        if QCoreApplication.instance() is None:
            try:
                callback()
            except Exception:
                logging.debug("无应用实例时同步 UI 回调执行失败", exc_info=True)
            return

        if threading.current_thread() is threading.main_thread():
            return callback()

        done = threading.Event()
        result_container: Dict[str, Any] = {}

        def _run():
            try:
                result_container["value"] = callback()
            finally:
                done.set()

        self._dispatch_to_ui_async(_run)
        if not done.wait(timeout=3):
            logging.warning("UI 调度超时，放弃等待以避免阻塞")
            return None
        return result_container.get("value")
    def start_run(self, config: RuntimeConfig):  # noqa: C901
        logging.debug("收到启动请求")

        if self.running or self._starting:
            logging.warning("任务已在运行中，忽略重复启动请求")
            return

        if not getattr(config, "question_entries", None):
            logging.error("未配置任何题目，无法启动")
            self.runFailed.emit('未配置任何题目，无法开始执行（请先在"题目配置"页添加/配置题目）')
            return

        logging.debug("验证题目配置...")
        questions_info = getattr(config, "questions_info", None)
        validation_error = validate_question_config(config.question_entries, questions_info)
        if validation_error:
            logging.error("题目配置验证失败：%s", validation_error)
            self.runFailed.emit(f"题目配置存在冲突，无法启动：\n\n{validation_error}")
            return

        logging.debug("开始配置任务：目标%s份，%s个线程", config.target, config.threads)

        self.config = config
        self.sync_runtime_ui_state_from_config(config)
        self.survey_provider = str(getattr(config, "survey_provider", "wjx") or "wjx")
        self.question_entries = list(getattr(config, "question_entries", []) or [])
        if not self.questions_info and getattr(config, "questions_info", None):
            self.questions_info = list(getattr(config, "questions_info") or [])
        self.stop_event = threading.Event()
        self.adapter = self._create_adapter(self.stop_event, random_ip_enabled=config.random_ip_enabled)
        self._paused_state = False
        self._completion_cleanup_done = False
        self._cleanup_scheduled = False
        self._stopped_by_stop_run = False
        self._starting = True
        self._initializing = False
        self._init_stage_text = ""
        self._init_steps = []
        self._init_completed_steps = set()
        self._init_current_step_key = ""
        self._init_gate_stop_event = None
        self._probe_hit_device_quota = False
        self._probe_failure_message = ""
        _ad = config.answer_duration or (0, 0)
        proxy_answer_duration: Tuple[int, int] = (0, 0) if config.timed_mode_enabled else (int(_ad[0]), int(_ad[1]))
        try:
            set_proxy_occupy_minute_by_answer_duration(proxy_answer_duration)
        except Exception:
            logging.debug("同步随机IP占用时长失败", exc_info=True)

        logging.debug("配置题目概率分布（共%s题）", len(config.question_entries))
        pending_config = ExecutionConfig()
        pending_config.survey_provider = str(getattr(config, "survey_provider", "wjx") or "wjx")
        try:
            configure_probabilities(
                config.question_entries,
                ctx=pending_config,
                reliability_mode_enabled=getattr(config, "reliability_mode_enabled", True),
            )
        except Exception as exc:
            logging.error("配置题目失败：%s", exc)
            self._starting = False
            self.runFailed.emit(str(exc))
            return

        pending_config.questions_metadata = {}
        if hasattr(self, "questions_info") and self.questions_info:
            for q_info in self.questions_info:
                q_num = q_info.get("num")
                if q_num:
                    pending_config.questions_metadata[q_num] = q_info
        self._pending_execution_config = pending_config

        self._start_with_initialization_gate(config, [])
    def _start_workers_with_proxy_pool(
        self,
        config: RuntimeConfig,
        proxy_pool: List[ProxyLease],
        *,
        emit_run_state: bool = True,
    ) -> None:
        execution_config, execution_state = self._prepare_engine_state(config, proxy_pool)
        execution_state.ensure_worker_threads(max(1, int(config.threads or 1)))
        self._apply_pending_execution_config(execution_config, consume=True)
        self._execution_state = execution_state
        self.adapter.execution_state = execution_state

        self.config.headless_mode = bool(getattr(config, "headless_mode", False))
        self.config.threads = max(1, int(config.threads or 1))
        self.running = True
        self._starting = False
        if emit_run_state:
            self.runStateChanged.emit(True)
        self._status_timer.start()

        _event_bus.emit(EVENT_TASK_STARTED, state=execution_state, config=execution_config)

        logging.debug("创建%s个工作线程", config.threads)
        threads: List[threading.Thread] = []
        for idx in range(config.threads):
            x = 50 + idx * 60
            y = 50 + idx * 60
            t = threading.Thread(
                target=run,
                args=(x, y, self.stop_event, self.adapter),
                kwargs={"config": execution_config, "state": execution_state},
                daemon=True,
                name=f"Worker-{idx+1}",
            )
            threads.append(t)
        self.worker_threads = threads

        logging.debug("启动所有工作线程")
        for idx, t in enumerate(threads):
            t.start()
            logging.debug("线程 %s/%s 已启动", idx + 1, len(threads))

        monitor = threading.Thread(
            target=self._wait_for_threads,
            args=(self.adapter,),
            daemon=True,
            name="Monitor",
        )
        monitor.start()
        logging.debug("任务启动完成，监控线程已启动")
    def _wait_for_threads(self, adapter_snapshot: Optional[Any] = None):
        for t in self.worker_threads:
            t.join()
        self._on_run_finished(adapter_snapshot)
    def _on_run_finished(self, adapter_snapshot: Optional[Any] = None):
        if threading.current_thread() is not threading.main_thread():
            self._dispatch_to_ui_async(lambda: self._on_run_finished(adapter_snapshot))
            return
        
        # 导出未完成的样本（如果是反填模式）
        self._export_incomplete_samples_if_needed()
        
        self._schedule_cleanup(adapter_snapshot)
        already_stopped = getattr(self, "_stopped_by_stop_run", False)
        self._stopped_by_stop_run = False
        self._status_timer.stop()
        _event_bus.emit(EVENT_TASK_STOPPED)
        if not already_stopped:
            self.running = False
            self.runStateChanged.emit(False)
        self._emit_status()
    def _submit_cleanup_task(
        self,
        adapter_snapshot: Optional[Any] = None,
        delay_seconds: float = 0.0,
    ) -> None:
        adapter = adapter_snapshot or self.adapter
        if not adapter:
            return

        def _cleanup():
            try:
                adapter.cleanup_browsers()
            except Exception:
                logging.warning("执行浏览器清理任务失败", exc_info=True)
            finally:
                self._dispatch_to_ui_async(self.cleanupFinished.emit)

        self._cleanup_runner.submit(_cleanup, delay_seconds=delay_seconds)
    def _schedule_cleanup(self, adapter_snapshot: Optional[Any] = None) -> None:
        if self._cleanup_scheduled:
            return
        self._cleanup_scheduled = True
    
    def _export_incomplete_samples_if_needed(self) -> None:
        """如果是反填模式且有未完成样本，导出到 Excel 文件。"""
        try:
            # 检查是否是反填模式
            execution_state = self._execution_state
            if not execution_state:
                return
            
            sample_dispatcher = getattr(execution_state, "sample_dispatcher", None)
            if not sample_dispatcher:
                return
            
            # 获取配置中的 Excel 路径
            config = self.config
            backfill_excel_path = getattr(config, "backfill_excel_path", "")
            if not backfill_excel_path:
                return
            
            # 导出未完成的样本
            output_path = sample_dispatcher.export_incomplete_samples(backfill_excel_path)
            
            if output_path:
                logging.info(f"已导出未完成样本到: {output_path}")
                # 可以在这里添加 UI 提示
                try:
                    from PySide6.QtWidgets import QMessageBox
                    from PySide6.QtCore import Qt
                    
                    def _show_message():
                        msg = QMessageBox()
                        msg.setIcon(QMessageBox.Icon.Information)
                        msg.setWindowTitle("未完成样本已导出")
                        msg.setText(f"有未完成的样本已导出到：\n\n{output_path}")
                        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                        msg.exec()
                    
                    self._dispatch_to_ui_async(_show_message)
                except Exception:
                    logging.info("显示导出提示失败", exc_info=True)
            else:
                logging.info("所有样本都已完成，无需导出")
                
        except Exception as exc:
            logging.error(f"导出未完成样本失败: {exc}", exc_info=True)
        self._submit_cleanup_task(
            adapter_snapshot,
            delay_seconds=STOP_FORCE_WAIT_SECONDS,
        )
    def stop_run(self):
        if self._starting and not self.running:
            self.stop_event.set()
            gate_stop = self._init_gate_stop_event
            if gate_stop is not None:
                gate_stop.set()
            self._starting = False
            return
        if not self.running:
            return
        self.stop_event.set()
        gate_stop = self._init_gate_stop_event
        if gate_stop is not None:
            gate_stop.set()
        if self._initializing:
            self._reset_initialization_state()
        try:
            self._status_timer.stop()
        except Exception:
            logging.debug("停止状态定时器失败", exc_info=True)
        try:
            if self.adapter:
                self.adapter.resume_run()
        except Exception:
            logging.debug("停止时恢复暂停状态失败", exc_info=True)
        self._schedule_cleanup()
        if self._paused_state:
            self._paused_state = False
            self.pauseStateChanged.emit(False, "")
        self.running = False
        self._stopped_by_stop_run = True
        self.runStateChanged.emit(False)
        self._emit_status()
    def resume_run(self):
        """Resume execution after a pause (does not restart threads)."""
        if not self.running:
            return
        try:
            self.adapter.resume_run()
        except Exception:
            logging.debug("恢复运行时清除暂停状态失败", exc_info=True)
        if self._paused_state:
            self._paused_state = False
            self.pauseStateChanged.emit(False, "")
    def _emit_status(self):
        if self._initializing:
            self.statusUpdated.emit("正在初始化", 0, 0)
            self.threadProgressUpdated.emit(
                {
                    "threads": [],
                    "target": 0,
                    "num_threads": 0,
                    "per_thread_target": 0,
                    "initializing": True,
                    "initializing_text": self._init_stage_text or "正在初始化",
                    "initialization_logs": self._build_initialization_logs(),
                }
            )
            if self._paused_state:
                self._paused_state = False
                self.pauseStateChanged.emit(False, "")
            return

        ctx = self._execution_state
        current = getattr(ctx, "cur_num", 0)
        target = getattr(ctx, "target_num", 0)
        fail = getattr(ctx, "cur_fail", 0)
        device_quota_fail_count = getattr(ctx, "device_quota_fail_count", 0)
        paused = False
        reason = ""
        try:
            paused = bool(self.adapter.is_paused())
            reason = str(self.adapter.get_pause_reason() or "")
        except Exception:
            paused = False
            reason = ""

        status_prefix = "已暂停" if paused else "已提交"
        status = f"{status_prefix} {current}/{target} 份 | 提交连续失败 {fail} 次"
        if int(device_quota_fail_count or 0) > 0:
            status = f"{status} | 设备限制拦截 {int(device_quota_fail_count or 0)} 次"
        if paused and reason:
            status = f"{status} | {reason}"
        self.statusUpdated.emit(status, int(current), int(target or 0))
        thread_rows = []
        num_threads = 0
        per_thread_target = 0
        if ctx is not None:
            try:
                thread_rows = ctx.snapshot_thread_progress()
            except Exception:
                logging.debug("获取线程进度快照失败", exc_info=True)
                thread_rows = []
            try:
                num_threads = max(1, int(getattr(ctx, "num_threads", 1) or 1))
            except Exception:
                num_threads = 1
            if int(target or 0) > 0:
                per_thread_target = int(math.ceil(float(target) / float(num_threads)))
        self.threadProgressUpdated.emit(
            {
                "threads": thread_rows,
                "target": int(target or 0),
                "num_threads": int(num_threads or 0),
                "per_thread_target": int(per_thread_target or 0),
                "device_quota_fail_count": int(device_quota_fail_count or 0),
                "initializing": False,
            }
        )

        if paused != self._paused_state:
            self._paused_state = paused
            self.pauseStateChanged.emit(bool(paused), str(reason or ""))

        should_force_cleanup = target > 0 and current >= target and not self._completion_cleanup_done
        if should_force_cleanup:
            self._completion_cleanup_done = True
            self._schedule_cleanup()
