"""运行控制器薄门面。"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal, Slot

from software.core.config.codec import build_runtime_config_snapshot
from software.core.config.schema import RuntimeConfig
from software.core.engine.async_engine import AsyncEngineClient
from software.core.engine.cleanup import CleanupRunner
from software.io.config.store import save_config
from software.system.power_management import SystemSleepBlocker
from software.ui.controller.run_command_service import RunCommandService
from software.ui.controller.run_state_store import RunStateStore
from software.ui.controller.survey_parse_service import SurveyParseService
from software.ui.controller.ui_dispatcher import UiCallbackDispatcher


class RunController(QObject):
    runtimeSnapshotChanged = Signal(dict)
    surveySnapshotChanged = Signal(dict)
    controllerEvent = Signal(dict)
    _uiCallbackQueued = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ui_dispatcher = UiCallbackDispatcher(self._uiCallbackQueued.emit)
        self._uiCallbackQueued.connect(self._drain_ui_callbacks)
        self._async_engine_client = AsyncEngineClient()
        self._cleanup_runner = CleanupRunner()
        self._sleep_blocker = SystemSleepBlocker()
        self._state_store = RunStateStore(
            on_runtime_snapshot_changed=self._emit_runtime_snapshot,
            on_survey_snapshot_changed=self._emit_survey_snapshot,
        )
        self._command_service = RunCommandService(
            state_store=self._state_store,
            async_engine_client=self._async_engine_client,
            cleanup_runner=self._cleanup_runner,
            sleep_blocker=self._sleep_blocker,
            dispatch_async=self._dispatch_to_ui_async,
            emit_event=self._emit_controller_event,
        )
        self._parse_service = SurveyParseService(
            async_engine_client=self._async_engine_client,
            state_store=self._state_store,
            emit_event=self._emit_controller_event,
            dispatch_async=self._dispatch_to_ui_async,
        )
        self.on_ip_counter: Optional[Callable[[float, float, bool], None]] = None
        self.config = RuntimeConfig()
        self._emit_runtime_snapshot(self._state_store.get_runtime_snapshot())
        self._emit_survey_snapshot(self._state_store.get_survey_snapshot())

    @Slot()
    def _drain_ui_callbacks(self) -> None:
        self._ui_dispatcher.drain()

    def _dispatch_to_ui_async(self, callback: Callable[[], Any]) -> None:
        self._ui_dispatcher.dispatch_async(callback)

    def _emit_runtime_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.runtimeSnapshotChanged.emit(dict(snapshot))
        random_ip = snapshot.get("random_ip") or {}
        if callable(self.on_ip_counter):
            try:
                self.on_ip_counter(
                    float(random_ip.get("used_quota") or 0.0),
                    float(random_ip.get("total_quota") or 0.0),
                    bool(random_ip.get("custom_api")),
                )
            except Exception:
                pass

    def _emit_survey_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.surveySnapshotChanged.emit(dict(snapshot))

    def _emit_controller_event(self, event: dict[str, Any]) -> None:
        self.controllerEvent.emit(dict(event))

    @property
    def running(self) -> bool:
        return bool(self._command_service.running)

    @running.setter
    def running(self, value: bool) -> None:
        self._command_service.running = bool(value)

    @property
    def adapter(self) -> Any:
        return self._command_service.runtime_port

    def is_initializing(self) -> bool:
        return self._command_service.is_initializing()

    def get_runtime_snapshot(self) -> dict[str, Any]:
        return self._state_store.get_runtime_snapshot()

    def get_survey_snapshot(self) -> dict[str, Any]:
        return self._state_store.get_survey_snapshot()

    def get_runtime_ui_state(self) -> dict[str, Any]:
        return dict(self.get_runtime_snapshot().get("settings") or {})

    def update_runtime_settings(self, *, emit: bool = True, **updates: Any) -> dict[str, Any]:
        state = self._state_store.update_runtime_settings(
            emit=emit,
            lock_threads=self._command_service.threads_update_locked(),
            **updates,
        )
        self._command_service.sync_runtime_settings(state)
        return state

    def set_runtime_ui_state(self, emit: bool = True, **updates: Any) -> dict[str, Any]:
        return self.update_runtime_settings(emit=emit, **updates)

    def hydrate_from_config(self, cfg: RuntimeConfig) -> RuntimeConfig:
        self.config = cfg
        self._state_store.hydrate_from_config(cfg)
        self._command_service.sync_runtime_settings(self.get_runtime_snapshot().get("settings", {}))
        return cfg

    def replace_question_entries(self, entries: Any, questions_info: Any = None) -> dict[str, Any]:
        return self._state_store.replace_question_entries(
            entries,
            questions_info=questions_info,
        )

    def write_runtime_settings_to_config(self, config: RuntimeConfig) -> RuntimeConfig:
        return self._state_store.write_runtime_settings_to_config(config)

    def write_to_config(self, config: RuntimeConfig) -> RuntimeConfig:
        return self.write_runtime_settings_to_config(config)

    def parse_survey(self, url: str) -> None:
        self._parse_service.parse_survey(url)

    def start_run(self, cfg: RuntimeConfig) -> None:
        self._command_service.start_run(cfg)

    def stop_run(self) -> None:
        self._command_service.stop_run()

    def resume_run(self) -> None:
        self._command_service.resume_run()

    def request_shutdown_for_close(self, timeout_seconds: float = 5.0) -> None:
        self._command_service.request_shutdown_for_close(timeout_seconds=timeout_seconds)

    def request_toggle_random_ip(
        self,
        enabled: bool,
        *,
        on_done: Optional[Callable[[bool], None]] = None,
    ) -> bool:
        return self._command_service.request_toggle_random_ip(
            bool(enabled),
            on_done=on_done,
        )

    def refresh_random_ip_counter(self) -> None:
        self._command_service.refresh_random_ip_counter()

    def sync_random_ip_counter_from_server(
        self,
        *,
        silent: bool = True,
        min_interval_seconds: float = 0.0,
    ) -> None:
        self._command_service.sync_random_ip_counter_from_server(
            silent=silent,
            min_interval_seconds=min_interval_seconds,
        )

    def load_saved_config(
        self,
        path: Optional[str] = None,
        *,
        strict: bool = False,
    ) -> RuntimeConfig:
        cfg = self._command_service.load_saved_config(path, strict=strict)
        self.hydrate_from_config(cfg)
        return cfg

    def save_config(self, cfg: RuntimeConfig, path: Optional[str] = None) -> str:
        self.config = cfg
        self.hydrate_from_config(cfg)
        return self._command_service.save_config(cfg, path)

    def save_current_config(
        self,
        path: Optional[str] = None,
        *,
        config: Optional[RuntimeConfig] = None,
    ) -> str:
        cfg = config or build_runtime_config_snapshot(
            RuntimeConfig(),
            question_entries=self.get_survey_snapshot().get("question_entries") or [],
            questions_info=self.get_survey_snapshot().get("questions_info") or [],
        )
        self.write_runtime_settings_to_config(cfg)
        snapshot = self.get_survey_snapshot()
        cfg.url = str(snapshot.get("url") or "")
        cfg.survey_title = str(snapshot.get("survey_title") or "")
        cfg.survey_provider = str(snapshot.get("survey_provider") or "wjx")
        cfg.questions_info = list(snapshot.get("questions_info") or [])
        cfg.question_entries = list(snapshot.get("question_entries") or [])
        self.config = cfg
        return save_config(cfg, path)


__all__ = ["RunController"]
