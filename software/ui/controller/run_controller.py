"""运行控制器 - 连接 UI 与引擎的业务逻辑桥接层。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from software.core.engine.cleanup import CleanupRunner
from software.core.engine.async_engine import AsyncEngineClient
from software.core.questions.config import QuestionEntry
from software.core.task import ExecutionState
from software.core.config.schema import RuntimeConfig
from software.io.config.store import load_config, save_config
from software.providers.contracts import SurveyQuestionMeta
from software.system.power_management import SystemSleepBlocker
from software.ui.controller.engine_adapter import (
    BoolVar as _BoolVar,
    EngineGuiAdapter,
)
from software.ui.controller.run_controller_parts.parsing import (
    RunControllerParsingMixin,
)
from software.ui.controller.run_controller_parts.runtime import (
    RunControllerRuntimeMixin,
)
from software.ui.controller.run_controller_parts.runtime_preparation import (
    PreparedExecutionArtifacts,
)
from software.ui.controller.runtime_settings_state import RuntimeSettingsState
from software.ui.controller.ui_dispatcher import UiCallbackDispatcher

BoolVar = _BoolVar


@dataclass
class RunControllerRuntimeState:
    """收口运行控制器里零散的生命周期状态。"""

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
    init_gate_stop_event: Optional[Any] = None
    prepared_execution_artifacts: Optional[Any] = None


class RunController(
    RunControllerParsingMixin,
    RunControllerRuntimeMixin,
    QObject,
):
    surveyParsed = Signal(list, str)
    surveyParseFailed = Signal(str)
    runStateChanged = Signal(bool)
    runFailed = Signal(str)
    statusUpdated = Signal(str, int, int)
    threadProgressUpdated = Signal(dict)
    pauseStateChanged = Signal(bool, str)
    cleanupFinished = Signal()
    quickBugReportSuggested = Signal()
    freeAiUnstableSuggested = Signal()
    submissionVerificationSuggested = Signal(str)
    runtimeUiStateChanged = Signal(dict)
    randomIpLoadingChanged = Signal(bool, str)
    _uiCallbackQueued = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = RuntimeConfig()
        self.questions_info: List[SurveyQuestionMeta] = []
        self.question_entries: List[QuestionEntry] = []
        self.survey_title = ""
        self.survey_provider = "wjx"
        self.stop_event = threading.Event()
        self.worker_threads: List[threading.Thread] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self._init_gate_thread: Optional[threading.Thread] = None
        self._execution_state: Optional[ExecutionState] = None
        self._async_engine_client: AsyncEngineClient = AsyncEngineClient()
        self._cleanup_runner = CleanupRunner()
        self.on_ip_counter: Optional[Callable[[float, float, bool], None]] = None
        self.on_random_ip_loading: Optional[Callable[[bool, str], None]] = None
        self.quota_request_form_opener: Optional[Callable[[], bool]] = None
        self.message_dialog_handler: Optional[Callable[[str, str, str], None]] = None
        self.confirm_dialog_handler: Optional[Callable[[str, str], bool]] = None
        self.custom_confirm_dialog_handler: Optional[Callable[[str, str, str, str], bool]] = None
        self._engine_adapter_cls = EngineGuiAdapter
        self._sleep_blocker = SystemSleepBlocker()
        self.running = False
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(600)
        self._status_timer.timeout.connect(self._emit_status)
        self._runtime_state = RunControllerRuntimeState()
        self._runtime_settings_state = RuntimeSettingsState()
        self._ui_dispatcher = UiCallbackDispatcher(self._uiCallbackQueued.emit)
        self._random_ip_toggle_lock = threading.Lock()
        self._random_ip_toggle_active = False
        self._random_ip_server_sync_lock = threading.Lock()
        self._random_ip_server_sync_active = False
        self._random_ip_last_server_sync_at = 0.0
        self._random_ip_background_threads: set[threading.Thread] = set()
        self._random_ip_background_threads_lock = threading.Lock()
        self._close_shutdown_lock = threading.Lock()
        self._close_shutdown_thread: Optional[threading.Thread] = None
        self._uiCallbackQueued.connect(self._drain_ui_callbacks)
        self.adapter = self._create_adapter(self.stop_event, random_ip_enabled=False)

    @property
    def _paused_state(self) -> bool:
        return self._runtime_state.paused

    @_paused_state.setter
    def _paused_state(self, value: bool) -> None:
        self._runtime_state.paused = bool(value)

    @property
    def _stopping(self) -> bool:
        return self._runtime_state.stopping

    @_stopping.setter
    def _stopping(self, value: bool) -> None:
        self._runtime_state.stopping = bool(value)

    @property
    def _completion_cleanup_done(self) -> bool:
        return self._runtime_state.completion_cleanup_done

    @_completion_cleanup_done.setter
    def _completion_cleanup_done(self, value: bool) -> None:
        self._runtime_state.completion_cleanup_done = bool(value)

    @property
    def _cleanup_scheduled(self) -> bool:
        return self._runtime_state.cleanup_scheduled

    @_cleanup_scheduled.setter
    def _cleanup_scheduled(self, value: bool) -> None:
        self._runtime_state.cleanup_scheduled = bool(value)

    @property
    def _stopped_by_stop_run(self) -> bool:
        return self._runtime_state.stopped_by_stop_run

    @_stopped_by_stop_run.setter
    def _stopped_by_stop_run(self, value: bool) -> None:
        self._runtime_state.stopped_by_stop_run = bool(value)

    @property
    def _quick_feedback_prompt_emitted(self) -> bool:
        return self._runtime_state.quick_feedback_prompt_emitted

    @_quick_feedback_prompt_emitted.setter
    def _quick_feedback_prompt_emitted(self, value: bool) -> None:
        self._runtime_state.quick_feedback_prompt_emitted = bool(value)

    @property
    def _starting(self) -> bool:
        return self._runtime_state.starting

    @_starting.setter
    def _starting(self, value: bool) -> None:
        self._runtime_state.starting = bool(value)

    @property
    def _initializing(self) -> bool:
        return self._runtime_state.initializing

    @_initializing.setter
    def _initializing(self, value: bool) -> None:
        self._runtime_state.initializing = bool(value)

    @property
    def _init_stage_text(self) -> str:
        return self._runtime_state.init_stage_text

    @_init_stage_text.setter
    def _init_stage_text(self, value: str) -> None:
        self._runtime_state.init_stage_text = str(value or "")

    @property
    def _init_steps(self) -> List[Dict[str, str]]:
        return self._runtime_state.init_steps

    @_init_steps.setter
    def _init_steps(self, value: List[Dict[str, str]]) -> None:
        self._runtime_state.init_steps = list(value or [])

    @property
    def _init_completed_steps(self) -> set[str]:
        return self._runtime_state.init_completed_steps

    @_init_completed_steps.setter
    def _init_completed_steps(self, value: set[str]) -> None:
        self._runtime_state.init_completed_steps = set(value or set())

    @property
    def _init_current_step_key(self) -> str:
        return self._runtime_state.init_current_step_key

    @_init_current_step_key.setter
    def _init_current_step_key(self, value: str) -> None:
        self._runtime_state.init_current_step_key = str(value or "")

    @property
    def _init_gate_stop_event(self) -> Optional[threading.Event]:
        return self._runtime_state.init_gate_stop_event

    @_init_gate_stop_event.setter
    def _init_gate_stop_event(self, value: Optional[threading.Event]) -> None:
        self._runtime_state.init_gate_stop_event = value

    @property
    def _prepared_execution_artifacts(
        self,
    ) -> Optional[PreparedExecutionArtifacts]:
        return self._runtime_state.prepared_execution_artifacts

    @_prepared_execution_artifacts.setter
    def _prepared_execution_artifacts(self, value: Optional[PreparedExecutionArtifacts]) -> None:
        self._runtime_state.prepared_execution_artifacts = value

    def is_initializing(self) -> bool:
        return bool(self._initializing)

    @Slot()
    def _drain_ui_callbacks(self) -> None:
        self._ui_dispatcher.drain()

    def _enqueue_ui_callback(self, callback: Callable[[], Any]) -> bool:
        return self._ui_dispatcher.enqueue(callback)

    def _dispatch_to_ui_async(self, callback: Callable[[], Any]) -> None:
        self._ui_dispatcher.dispatch_async(callback)

    def configure_ui_bridge(
        self,
        *,
        quota_request_form_opener: Optional[Callable[[], bool]] = None,
        on_ip_counter: Optional[Callable[[float, float, bool], None]] = None,
        on_random_ip_loading: Optional[Callable[[bool, str], None]] = None,
        message_handler: Optional[Callable[[str, str, str], None]] = None,
        confirm_handler: Optional[Callable[[str, str], bool]] = None,
        custom_confirm_handler: Optional[Callable[[str, str, str, str], bool]] = None,
    ) -> None:
        self.quota_request_form_opener = quota_request_form_opener
        self.on_ip_counter = on_ip_counter
        self.on_random_ip_loading = on_random_ip_loading
        self.message_dialog_handler = message_handler
        self.confirm_dialog_handler = confirm_handler
        self.custom_confirm_dialog_handler = custom_confirm_handler
        self._sync_adapter_ui_bridge()

    def get_runtime_ui_state(self) -> Dict[str, Any]:
        return self._runtime_settings_state.get()

    def _threads_update_locked(self) -> bool:
        return bool(self.running or self._starting or self._initializing)

    def set_runtime_ui_state(self, emit: bool = True, **updates: Any) -> Dict[str, Any]:
        state, changed = self._runtime_settings_state.update(
            lock_threads=self._threads_update_locked(),
            **updates,
        )
        if emit and changed:
            self.runtimeUiStateChanged.emit(dict(state))
        return dict(state)

    def sync_runtime_ui_state_from_config(
        self, config: RuntimeConfig, *, emit: bool = True
    ) -> Dict[str, Any]:
        state, changed = self._runtime_settings_state.sync_from_config(
            config,
            lock_threads=self._threads_update_locked(),
        )
        if emit and changed:
            self.runtimeUiStateChanged.emit(dict(state))
        return dict(state)

    def write_to_config(self, config: RuntimeConfig) -> RuntimeConfig:
        return self._runtime_settings_state.write_to_config(config)

    def write_runtime_ui_state_to_config(self, config: RuntimeConfig) -> RuntimeConfig:
        return self.write_to_config(config)

    def notify_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.randomIpLoadingChanged.emit(bool(loading), str(message or ""))

    def is_random_ip_toggle_active(self) -> bool:
        with self._random_ip_toggle_lock:
            return bool(self._random_ip_toggle_active)

    def request_toggle_random_ip(
        self,
        enabled: bool,
        *,
        adapter: Optional[EngineGuiAdapter] = None,
        on_done: Optional[Callable[[bool], None]] = None,
    ) -> bool:
        target_adapter = adapter or self.adapter
        with self._random_ip_toggle_lock:
            if self._random_ip_toggle_active:
                return False
            self._random_ip_toggle_active = True

        self.notify_random_ip_loading(True, "正在处理...")

        def _finish(final_enabled: bool) -> None:
            with self._random_ip_toggle_lock:
                self._random_ip_toggle_active = False
            self.notify_random_ip_loading(False, "")
            self.set_runtime_ui_state(random_ip_enabled=bool(final_enabled))
            if callable(on_done):
                try:
                    on_done(bool(final_enabled))
                except Exception:
                    import logging

                    logging.info("随机IP异步回调执行失败", exc_info=True)
            self.refresh_random_ip_counter(adapter=target_adapter)

        try:
            future = self.submit_toggle_random_ip(bool(enabled), adapter=target_adapter)
        except Exception:
            import logging

            logging.warning("随机IP异步切换提交失败", exc_info=True)
            with self._random_ip_toggle_lock:
                self._random_ip_toggle_active = False
            self.notify_random_ip_loading(False, "")
            return False

        def _on_done_callback(done_future) -> None:
            final_enabled = bool(enabled)
            try:
                final_enabled = bool(done_future.result())
            except Exception:
                import logging

                logging.warning("随机IP异步切换失败", exc_info=True)
                if target_adapter is not None:
                    try:
                        final_enabled = bool(target_adapter.is_random_ip_enabled())
                    except Exception:
                        final_enabled = False
            self._dispatch_to_ui_async(lambda value=bool(final_enabled): _finish(value))

        future.add_done_callback(_on_done_callback)
        return True

    def _sync_adapter_ui_bridge(self, adapter: Optional[EngineGuiAdapter] = None) -> None:
        target = adapter or self.adapter
        if target is None:
            return
        target.bind_ui_callbacks(
            quota_request_form_opener=self.quota_request_form_opener,
            on_ip_counter=self.on_ip_counter,
            on_random_ip_loading=self.on_random_ip_loading,
            message_handler=self.message_dialog_handler,
            confirm_handler=self.confirm_dialog_handler,
        )

    def load_saved_config(
        self, path: Optional[str] = None, *, strict: bool = False
    ) -> RuntimeConfig:
        cfg = load_config(path, strict=strict)
        self.config = cfg
        self.question_entries = cfg.question_entries
        self.questions_info = list(getattr(cfg, "questions_info", None) or [])
        self.survey_title = str(getattr(cfg, "survey_title", "") or "")
        self.survey_provider = str(getattr(cfg, "survey_provider", "wjx") or "wjx")
        return cfg

    def save_current_config(self, path: Optional[str] = None) -> str:
        entries = getattr(self.config, "question_entries", None)
        if entries is None:
            entries = self.question_entries
        self.question_entries = list(entries or [])
        self.config.question_entries = self.question_entries
        return save_config(self.config, path)
