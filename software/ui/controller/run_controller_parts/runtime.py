"""RunController 运行控制与状态管理逻辑。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from software.io.config import RuntimeConfig

from .runtime_execution import RunControllerExecutionMixin
from .runtime_init_gate import RunControllerInitializationMixin
from .runtime_random_ip import RunControllerRandomIPMixin

if TYPE_CHECKING:
    from PySide6.QtCore import QObject, QTimer

    from software.core.engine.cleanup import CleanupRunner

class RunControllerRuntimeMixin(
    RunControllerRandomIPMixin,
    RunControllerInitializationMixin,
    RunControllerExecutionMixin,
):
    if TYPE_CHECKING:
        runStateChanged: Any
        runFailed: Any
        statusUpdated: Any
        threadProgressUpdated: Any
        pauseStateChanged: Any
        cleanupFinished: Any
        _status_timer: QTimer
        _cleanup_runner: CleanupRunner
        quota_request_form_opener: Optional[Callable[[], bool]]
        on_ip_counter: Optional[Callable[[float, float, bool], None]]
        on_random_ip_loading: Optional[Callable[[bool, str], None]]
        message_dialog_handler: Optional[Callable[[str, str, str], None]]
        confirm_dialog_handler: Optional[Callable[[str, str], bool]]

        def _dispatch_to_ui_async(self, callback: Callable[[], Any]) -> None: ...
        def parent(self) -> QObject: ...
        def _sync_adapter_ui_bridge(self, adapter: Optional[Any] = None) -> None: ...
        def notify_random_ip_loading(self, loading: bool, message: str = "") -> None: ...
        def set_runtime_ui_state(self, emit: bool = True, **updates: Any) -> Dict[str, Any]: ...
        def sync_runtime_ui_state_from_config(self, config: RuntimeConfig, *, emit: bool = True) -> Dict[str, Any]: ...
