"""RunController 轻量初始化门禁与启动提示逻辑。"""
from __future__ import annotations

import copy
import logging
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from software.app.browser_probe import BrowserProbeResult, run_browser_probe_subprocess
from software.app.config import DEFAULT_HTTP_HEADERS
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.integrations.ai.client import AI_MODE_FREE, get_ai_settings
from software.io.config import RuntimeConfig
import software.network.http as http_client
from .runtime_preparation import PreparedExecutionArtifacts

from .runtime_constants import (
    BROWSER_PROBE_TIMEOUT_SECONDS,
    STARTUP_HINT_DURATION_MS,
    STARTUP_STATUS_TIMEOUT_SECONDS,
    STATUS_MONITOR_FREE_AI,
    STATUS_MONITOR_RANDOM_IP,
    STATUS_PAGE_BASE_URL,
    STATUS_PAGE_SLUG,
)


def _parse_status_page_monitor_names(payload: Dict[str, Any]) -> Dict[int, str]:
    names: Dict[int, str] = {}
    for group in list(payload.get("publicGroupList") or []):
        monitor_list = group.get("monitorList") or []
        if not isinstance(monitor_list, list):
            continue
        for monitor in monitor_list:
            try:
                monitor_id = int(monitor.get("id"))
            except Exception:
                continue
            monitor_name = str(monitor.get("name") or "").strip()
            if monitor_name:
                names[monitor_id] = monitor_name
    return names


def _extract_startup_service_warnings(
    heartbeat_payload: Dict[str, Any],
    monitor_targets: Dict[int, str],
    monitor_names: Optional[Dict[int, str]] = None,
) -> List[str]:
    warnings: List[str] = []
    heartbeat_map = heartbeat_payload.get("heartbeatList") or {}
    names = dict(monitor_names or {})

    for monitor_id, fallback_name in monitor_targets.items():
        heartbeat_list = heartbeat_map.get(str(monitor_id)) or heartbeat_map.get(monitor_id) or []
        latest = heartbeat_list[-1] if isinstance(heartbeat_list, list) and heartbeat_list else {}
        try:
            raw_status = latest.get("status")
            status = int(0 if raw_status is None else raw_status)
        except Exception:
            status = 0
        if status == 1:
            continue
        service_name = str(names.get(int(monitor_id)) or fallback_name or f"服务 {monitor_id}").strip()
        detail = str(latest.get("msg") or "").strip()
        time_text = str(latest.get("time") or "").strip()
        suffix_parts: List[str] = []
        if detail:
            suffix_parts.append(detail)
        if time_text:
            suffix_parts.append(f"最近时间：{time_text}")
        suffix = f"（{'；'.join(suffix_parts)}）" if suffix_parts else ""
        warnings.append(f"{service_name} 当前状态异常{suffix}")
    return warnings


class RunControllerInitializationMixin:
    if TYPE_CHECKING:
        stop_event: threading.Event
        worker_threads: List[threading.Thread]
        adapter: Any
        config: RuntimeConfig
        running: bool
        _starting: bool
        _initializing: bool
        _status_timer: Any
        _execution_state: Optional[ExecutionState]
        _prepared_execution_artifacts: Optional[PreparedExecutionArtifacts]
        _init_stage_text: str
        _init_steps: List[Dict[str, str]]
        _init_completed_steps: set[str]
        _init_current_step_key: str
        _init_gate_stop_event: Optional[threading.Event]
        _init_gate_thread: Optional[threading.Thread]
        _startup_status_check_lock: threading.Lock
        _startup_status_check_active: bool
        _startup_service_warnings: List[str]
        survey_title: str
        custom_confirm_dialog_handler: Optional[Any]
        confirm_dialog_handler: Optional[Any]
        runStateChanged: Any
        statusUpdated: Any
        threadProgressUpdated: Any
        runFailed: Any
        startupHintEmitted: Any

        def _start_workers_with_proxy_pool(
            self,
            config: RuntimeConfig,
            proxy_pool: List[ProxyLease],
            *,
            emit_run_state: bool = True,
        ) -> None: ...
        def _emit_status(self) -> None: ...
        def _dispatch_to_ui_async(self, callback: Any) -> None: ...

    def _prepare_engine_state(self, proxy_pool: List[ProxyLease]) -> tuple[ExecutionConfig, ExecutionState]:
        """从已准备好的模板构建本次任务的 ExecutionConfig 与 ExecutionState。"""
        prepared = getattr(self, "_prepared_execution_artifacts", None)
        if prepared is None:
            raise RuntimeError("运行准备产物缺失，无法启动任务")
        execution_config = copy.deepcopy(prepared.execution_config_template)
        execution_config.proxy_ip_pool = list(proxy_pool) if execution_config.random_proxy_ip_enabled else []
        execution_state = ExecutionState(config=execution_config, stop_event=self.stop_event)
        return execution_config, execution_state

    def _should_use_initialization_gate(self, config: RuntimeConfig) -> bool:
        headless_mode = bool(getattr(config, "headless_mode", False))
        thread_count = max(1, int(getattr(config, "threads", 1) or 1))
        return headless_mode and thread_count > 1

    def _build_initialization_plan(self, config: RuntimeConfig) -> List[Dict[str, str]]:
        if not self._should_use_initialization_gate(config):
            return []
        return [{"key": "playwright", "label": "初始化浏览器环境（快速检查）"}]

    def _find_init_step_label(self, step_key: str) -> str:
        key = str(step_key or "").strip()
        if not key:
            return ""
        for item in list(getattr(self, "_init_steps", []) or []):
            if str(item.get("key") or "") == key:
                return str(item.get("label") or "")
        return ""

    def _setup_initialization_progress(self, config: RuntimeConfig) -> None:
        self._init_steps = self._build_initialization_plan(config)
        self._init_completed_steps = set()
        self._init_current_step_key = ""
        self._set_initialization_stage("playwright", "初始化浏览器环境（快速检查）")

    def _set_initialization_stage(self, step_key: str, stage_text: str = "") -> None:
        key = str(step_key or "").strip()
        prev = str(getattr(self, "_init_current_step_key", "") or "")
        completed = set(getattr(self, "_init_completed_steps", set()) or set())
        if prev and prev != key:
            completed.add(prev)
        if key and key in completed:
            completed.discard(key)
        self._init_completed_steps = completed
        self._init_current_step_key = key
        label = self._find_init_step_label(key)
        self._init_stage_text = str(stage_text or label or "正在初始化")

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

    def _start_startup_status_check(self, config: RuntimeConfig) -> None:
        monitor_targets = self._resolve_startup_status_targets(config)
        with self._startup_status_check_lock:
            self._startup_service_warnings = []
            if not monitor_targets:
                self._startup_status_check_active = False
                return
            if self._startup_status_check_active:
                return
            self._startup_status_check_active = True

        threading.Thread(
            target=self._run_startup_status_check,
            args=(monitor_targets,),
            daemon=True,
            name="StartupStatusHint",
        ).start()

    def _resolve_startup_status_targets(self, config: RuntimeConfig) -> Dict[int, str]:
        targets: Dict[int, str] = {}
        if bool(getattr(config, "random_ip_enabled", False)):
            targets[STATUS_MONITOR_RANDOM_IP] = "随机IP提取"
        try:
            ai_mode = str(get_ai_settings().get("ai_mode") or "").strip().lower()
        except Exception:
            ai_mode = ""
        if ai_mode == AI_MODE_FREE:
            targets[STATUS_MONITOR_FREE_AI] = "免费AI填空"
        return targets

    def _run_startup_status_check(self, monitor_targets: Dict[int, str]) -> None:
        warnings: List[str] = []
        try:
            warnings = self._fetch_startup_service_warnings(monitor_targets)
        except Exception:
            logging.info("启动服务提示检查失败，已忽略", exc_info=True)
        finally:
            with self._startup_status_check_lock:
                self._startup_service_warnings = list(warnings)
                self._startup_status_check_active = False

        for warning in warnings:
            self.startupHintEmitted.emit(str(warning), "warning", int(STARTUP_HINT_DURATION_MS))

    def _fetch_startup_service_warnings(self, monitor_targets: Dict[int, str]) -> List[str]:
        page_url = f"{STATUS_PAGE_BASE_URL}/api/status-page/{STATUS_PAGE_SLUG}"
        heartbeat_url = f"{STATUS_PAGE_BASE_URL}/api/status-page/heartbeat/{STATUS_PAGE_SLUG}"
        monitor_names: Dict[int, str] = {}
        try:
            response = http_client.get(
                page_url,
                timeout=STARTUP_STATUS_TIMEOUT_SECONDS,
                headers=DEFAULT_HTTP_HEADERS,
                proxies={},
            )
            monitor_names = _parse_status_page_monitor_names(response.json())
        except Exception:
            logging.info("读取状态页配置失败，启动时忽略服务提示", exc_info=True)

        try:
            response = http_client.get(
                heartbeat_url,
                timeout=STARTUP_STATUS_TIMEOUT_SECONDS,
                headers=DEFAULT_HTTP_HEADERS,
                proxies={},
            )
            return _extract_startup_service_warnings(response.json(), monitor_targets, monitor_names)
        except Exception:
            logging.info("读取状态页心跳失败，启动时忽略服务提示", exc_info=True)
            return []

    def _snapshot_startup_service_warnings(self) -> List[str]:
        with self._startup_status_check_lock:
            return list(self._startup_service_warnings or [])

    def _start_with_initialization_gate(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> None:
        if self.stop_event.is_set():
            self._starting = False
            return

        if not self._should_use_initialization_gate(config):
            self._start_workers_with_proxy_pool(config, list(proxy_pool))
            return

        self.running = True
        self._starting = False
        self._initializing = True
        self._setup_initialization_progress(config)
        self._execution_state = None
        self.runStateChanged.emit(True)
        self._status_timer.start()
        self._emit_status()

        gate_stop_event = threading.Event()
        self._init_gate_stop_event = gate_stop_event
        gate_thread = threading.Thread(
            target=self._run_initialization_gate,
            args=(config, list(proxy_pool), gate_stop_event),
            daemon=True,
            name="InitGate",
        )
        self._init_gate_thread = gate_thread
        gate_thread.start()

    def _run_initialization_gate(
        self,
        config: RuntimeConfig,
        proxy_pool: List[ProxyLease],
        gate_stop_event: threading.Event,
    ) -> None:
        if self.stop_event.is_set() or gate_stop_event.is_set():
            return

        try:
            probe_result = run_browser_probe_subprocess(
                headless=bool(getattr(config, "headless_mode", False)),
                browser_preference=list(getattr(config, "browser_preference", []) or []),
                timeout_seconds=BROWSER_PROBE_TIMEOUT_SECONDS,
                cancel_event=gate_stop_event,
            )
        except Exception as exc:
            logging.error("浏览器快速检查执行失败", exc_info=True)
            probe_result = BrowserProbeResult(
                ok=False,
                error_kind="probe_failed",
                message=f"浏览器环境快速检查失败：{exc}",
            )

        if self.stop_event.is_set() or gate_stop_event.is_set() or probe_result.error_kind == "cancelled":
            return

        if probe_result.ok:
            self._dispatch_to_ui_async(lambda: self._start_after_init_success(config, list(proxy_pool)))
            return

        self._dispatch_to_ui_async(
            lambda result=probe_result, run_config=config, pool=list(proxy_pool): self._handle_browser_probe_failure(
                run_config,
                pool,
                result,
            )
        )

    def _build_browser_probe_failure_message(self, result: BrowserProbeResult) -> str:
        lines = [
            "浏览器环境快速检查没有通过。",
            "",
            f"失败原因：{str(result.message or '未知错误')}",
        ]
        if int(result.elapsed_ms or 0) > 0:
            lines.append(f"检查耗时：{int(result.elapsed_ms)} ms")
        if str(result.browser or "").strip():
            lines.append(f"已尝试浏览器：{str(result.browser).strip()}")
        warnings = self._snapshot_startup_service_warnings()
        if warnings:
            lines.append("")
            lines.append("另外，当前相关服务也有异常提示：")
            for item in warnings:
                lines.append(f"- {item}")
        lines.append("")
        lines.append("你可以停止启动，避免直接硬跑；如果你想继续试，也可以仍按原配置继续。")
        return "\n".join(lines)

    def _handle_browser_probe_failure(
        self,
        config: RuntimeConfig,
        proxy_pool: List[ProxyLease],
        result: BrowserProbeResult,
    ) -> None:
        if self.stop_event.is_set():
            self._cancel_initialization_startup()
            return

        message = self._build_browser_probe_failure_message(result)
        continue_run = False
        fallback_handler = None
        handler = getattr(self, "custom_confirm_dialog_handler", None)
        if callable(handler):
            try:
                continue_run = bool(
                    handler(
                        "浏览器环境快速检查失败",
                        message,
                        "仍按原配置继续",
                        "停止启动",
                    )
                )
            except Exception:
                logging.warning("显示浏览器快检失败确认框失败", exc_info=True)
        else:
            fallback_handler = getattr(self, "confirm_dialog_handler", None)
            if not callable(fallback_handler):
                fallback_handler = None
        if not continue_run and fallback_handler is not None:
            try:
                continue_run = bool(fallback_handler("浏览器环境快速检查失败", message))
            except Exception:
                logging.warning("显示默认确认框失败", exc_info=True)

        if continue_run:
            self._start_after_init_success(config, proxy_pool)
            return
        self._cancel_initialization_startup()

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

    def _start_after_init_success(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> None:
        if self.stop_event.is_set():
            self._reset_initialization_state()
            return
        self._reset_initialization_state()
        self._start_workers_with_proxy_pool(config, proxy_pool, emit_run_state=False)

    def _cancel_initialization_startup(self) -> None:
        self._finish_initialization_idle_state("已取消启动")

    def _finish_initialization_failure(self, message: str) -> None:
        if self.stop_event.is_set() and not self.running:
            self._finish_initialization_idle_state("已取消启动")
            return
        self._finish_initialization_idle_state("初始化失败")
        self.runFailed.emit(str(message or "初始化失败"))
