"""RunController 启动提示与运行前状态辅助逻辑。"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.core.config.schema import RuntimeConfig
from .runtime_preparation import PreparedExecutionArtifacts


class RunControllerInitializationMixin:
    if TYPE_CHECKING:
        stop_event: Any
        worker_threads: List[Any]
        adapter: Any
        config: RuntimeConfig
        running: bool
        _status_timer: Any
        _execution_state: Optional[ExecutionState]
        _init_gate_thread: Optional[Any]
        survey_title: str
        runStateChanged: Any
        statusUpdated: Any
        threadProgressUpdated: Any

        @property
        def _starting(self) -> bool: ...
        @_starting.setter
        def _starting(self, value: bool) -> None: ...

        @property
        def _initializing(self) -> bool: ...
        @_initializing.setter
        def _initializing(self, value: bool) -> None: ...

        @property
        def _prepared_execution_artifacts(
            self,
        ) -> Optional[PreparedExecutionArtifacts]: ...
        @_prepared_execution_artifacts.setter
        def _prepared_execution_artifacts(
            self, value: Optional[PreparedExecutionArtifacts]
        ) -> None: ...

        @property
        def _init_stage_text(self) -> str: ...
        @_init_stage_text.setter
        def _init_stage_text(self, value: str) -> None: ...

        @property
        def _init_steps(self) -> List[Dict[str, str]]: ...
        @_init_steps.setter
        def _init_steps(self, value: List[Dict[str, str]]) -> None: ...

        @property
        def _init_completed_steps(self) -> set[str]: ...
        @_init_completed_steps.setter
        def _init_completed_steps(self, value: set[str]) -> None: ...

        @property
        def _init_current_step_key(self) -> str: ...
        @_init_current_step_key.setter
        def _init_current_step_key(self, value: str) -> None: ...

        @property
        def _init_gate_stop_event(self) -> Optional[Any]: ...
        @_init_gate_stop_event.setter
        def _init_gate_stop_event(self, value: Optional[Any]) -> None: ...

        def _start_workers_with_proxy_pool(
            self,
            config: RuntimeConfig,
            proxy_pool: List[ProxyLease],
            *,
            emit_run_state: bool = True,
        ) -> None: ...
        def _emit_status(self) -> None: ...

    def _prepare_engine_state(
        self, proxy_pool: List[ProxyLease]
    ) -> tuple[ExecutionConfig, ExecutionState]:
        """从已准备好的模板构建本次任务状态。"""
        prepared = getattr(self, "_prepared_execution_artifacts", None)
        if prepared is None:
            raise RuntimeError("运行准备产物缺失，无法启动任务")
        execution_config = copy.deepcopy(prepared.execution_config_template)
        execution_config.proxy_ip_pool = (
            list(proxy_pool) if execution_config.random_proxy_ip_enabled else []
        )
        execution_state = ExecutionState(config=execution_config, stop_event=self.stop_event)
        return execution_config, execution_state

    def _build_initialization_logs(self) -> List[str]:
        steps = list(getattr(self, "_init_steps", []) or [])
        if not steps:
            return [str(getattr(self, "_init_stage_text", "") or "正在初始化")]

        completed = set(getattr(self, "_init_completed_steps", set()) or set())
        current = str(getattr(self, "_init_current_step_key", "") or "")
        lines: List[str] = []
        stage_text = str(getattr(self, "_init_stage_text", "") or "").strip()
        if stage_text:
            lines.append(f"当前阶段：{stage_text}")
        for item in steps:
            key = str(item.get("key") or "").strip()
            label = str(item.get("label") or key).strip() or key
            if key in completed:
                lines.append(f"[√] {label}")
            elif key and key == current:
                lines.append(f"[>] {label}")
        return lines

    def _start_with_initialization_gate(
        self, config: RuntimeConfig, proxy_pool: List[ProxyLease]
    ) -> None:
        if self.stop_event.is_set():
            self._starting = False
            return
        self._start_workers_with_proxy_pool(config, list(proxy_pool))

    def _reset_initialization_state(self) -> None:
        self._initializing = False
        self._init_stage_text = ""
        self._init_steps = []
        self._init_completed_steps = set()
        self._init_current_step_key = ""
        self._init_gate_stop_event = None

    def _finish_initialization_idle_state(self, status_text: str) -> None:
        was_running = bool(self.running)
        self._reset_initialization_state()
        self._starting = False
        self._status_timer.stop()
        self.running = False
        self.worker_threads = []
        self._execution_state = None
        self._prepared_execution_artifacts = None
        if was_running:
            self.runStateChanged.emit(False)
        self.statusUpdated.emit(str(status_text or "已停止"), 0, 0)
        self.threadProgressUpdated.emit(
            {
                "threads": [],
                "target": 0,
                "num_threads": 0,
                "per_thread_target": 0,
                "initializing": False,
            }
        )

    def _cancel_initialization_startup(self) -> None:
        self._finish_initialization_idle_state("已取消启动")
