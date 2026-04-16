"""RunController 初始化闸门与预探测逻辑。"""
from __future__ import annotations

import copy
import logging
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from software.core.engine.runner import run
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.io.config import RuntimeConfig
from software.network.proxy import get_effective_proxy_api_url, is_custom_proxy_api_active
from software.network.proxy.session import (
    RandomIPAuthError,
    format_random_ip_error,
    get_fresh_quota_snapshot,
    get_session_snapshot,
    has_authenticated_session,
    has_unknown_local_quota,
    is_quota_exhausted,
)

from .runtime_constants import DEVICE_QUOTA_LIMIT_MESSAGE, NON_HEADLESS_FALLBACK_MAX_THREADS


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
        _pending_execution_config: Optional[ExecutionConfig]
        _probe_hit_device_quota: bool
        _probe_failure_message: str
        _init_stage_text: str
        _init_steps: List[Dict[str, str]]
        _init_completed_steps: set[str]
        _init_current_step_key: str
        _init_gate_stop_event: Optional[threading.Event]
        survey_title: str
        runStateChanged: Any
        statusUpdated: Any
        threadProgressUpdated: Any
        runFailed: Any

        def _start_workers_with_proxy_pool(
            self,
            config: RuntimeConfig,
            proxy_pool: List[ProxyLease],
            *,
            emit_run_state: bool = True,
        ) -> None: ...
        def _emit_status(self) -> None: ...
        def _dispatch_to_ui_async(self, callback: Any) -> None: ...
        def _validate_benefit_proxy_compatibility(self, config: RuntimeConfig) -> None: ...
        def refresh_random_ip_counter(self, *, adapter: Optional[Any] = None, async_mode: bool = True) -> None: ...
        def _create_adapter(self, stop_signal: threading.Event, *, random_ip_enabled: bool = False) -> Any: ...
        def set_runtime_ui_state(self, emit: bool = True, **updates: Any) -> Dict[str, Any]: ...

    def _prepare_engine_state(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> tuple[ExecutionConfig, ExecutionState]:
        """构建本次任务的 ExecutionConfig 与 ExecutionState。"""
        fail_threshold = 5
        config_title = str(getattr(config, "survey_title", "") or "")
        fallback_title = str(getattr(self, "survey_title", "") or "")
        survey_title = config_title or fallback_title
        try:
            psycho_target_alpha = float(getattr(config, "psycho_target_alpha", 0.9) or 0.9)
        except Exception:
            psycho_target_alpha = 0.9
        psycho_target_alpha = max(0.70, min(0.95, psycho_target_alpha))

        execution_config = ExecutionConfig(
            url=config.url,
            survey_title=survey_title,
            survey_provider=str(getattr(config, "survey_provider", "wjx") or "wjx"),
            target_num=config.target,
            num_threads=max(1, int(config.threads or 1)),
            headless_mode=getattr(config, "headless_mode", False),
            browser_preference=list(getattr(config, "browser_preference", []) or []),
            fail_threshold=fail_threshold,
            submit_interval_range_seconds=(int(config.submit_interval[0]), int(config.submit_interval[1])),
            answer_duration_range_seconds=(int(config.answer_duration[0]), int(config.answer_duration[1])),
            timed_mode_enabled=config.timed_mode_enabled,
            timed_mode_refresh_interval=config.timed_mode_interval,
            random_proxy_ip_enabled=config.random_ip_enabled,
            proxy_ip_pool=list(proxy_pool) if config.random_ip_enabled else [],
            random_user_agent_enabled=config.random_ua_enabled,
            user_agent_ratios=dict(getattr(config, "random_ua_ratios", {"wechat": 33, "mobile": 33, "pc": 34})),
            answer_rules=copy.deepcopy(getattr(config, "answer_rules", []) or []),
            psycho_target_alpha=psycho_target_alpha,
            stop_on_fail_enabled=config.fail_stop_enabled,
            pause_on_aliyun_captcha=bool(getattr(config, "pause_on_aliyun_captcha", True)),
        )
        execution_state = ExecutionState(config=execution_config, stop_event=self.stop_event)
        return execution_config, execution_state
    def _apply_pending_execution_config(self, config: ExecutionConfig, *, consume: bool) -> None:
        pending = self._pending_execution_config
        if pending is None:
            return
        config.single_prob = copy.deepcopy(pending.single_prob)
        config.droplist_prob = copy.deepcopy(pending.droplist_prob)
        config.multiple_prob = copy.deepcopy(pending.multiple_prob)
        config.matrix_prob = copy.deepcopy(pending.matrix_prob)
        config.scale_prob = copy.deepcopy(pending.scale_prob)
        config.slider_targets = copy.deepcopy(pending.slider_targets)
        config.texts = copy.deepcopy(pending.texts)
        config.texts_prob = copy.deepcopy(pending.texts_prob)
        config.text_entry_types = copy.deepcopy(pending.text_entry_types)
        config.text_ai_flags = copy.deepcopy(pending.text_ai_flags)
        config.text_titles = copy.deepcopy(pending.text_titles)
        config.multi_text_blank_modes = copy.deepcopy(pending.multi_text_blank_modes)
        config.multi_text_blank_ai_flags = copy.deepcopy(pending.multi_text_blank_ai_flags)
        config.multi_text_blank_int_ranges = copy.deepcopy(getattr(pending, "multi_text_blank_int_ranges", []))
        config.single_option_fill_texts = copy.deepcopy(pending.single_option_fill_texts)
        config.single_attached_option_selects = copy.deepcopy(pending.single_attached_option_selects)
        config.droplist_option_fill_texts = copy.deepcopy(pending.droplist_option_fill_texts)
        config.multiple_option_fill_texts = copy.deepcopy(pending.multiple_option_fill_texts)
        config.question_config_index_map = copy.deepcopy(pending.question_config_index_map)
        config.question_dimension_map = copy.deepcopy(pending.question_dimension_map)
        config.question_strict_ratio_map = copy.deepcopy(getattr(pending, "question_strict_ratio_map", {}))
        config.question_psycho_bias_map = copy.deepcopy(pending.question_psycho_bias_map)
        config.questions_metadata = copy.deepcopy(pending.questions_metadata)
        config.survey_provider = str(getattr(pending, "survey_provider", getattr(config, "survey_provider", "wjx")) or "wjx")
        if consume:
            self._pending_execution_config = None
    def _should_use_initialization_gate(self, config: RuntimeConfig) -> bool:
        headless_mode = bool(getattr(config, "headless_mode", False))
        thread_count = max(1, int(getattr(config, "threads", 1) or 1))
        return headless_mode and thread_count > 1
    def _build_initialization_plan(self, config: RuntimeConfig) -> List[Dict[str, str]]:
        steps: List[Dict[str, str]] = [
            {"key": "question_detection", "label": "初始化题目检测模块"},
            {"key": "answering", "label": "初始化答题模块"},
        ]
        if bool(getattr(config, "random_ip_enabled", False)):
            steps.append({"key": "random_ip", "label": "初始化随机IP模块"})
        if self._should_use_initialization_gate(config):
            steps.append({"key": "playwright", "label": "初始化Playwright浏览器环境"})
        steps.append({"key": "submission", "label": "初始化提交行为模块"})
        return steps
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
        self._init_completed_steps = {"question_detection", "answering"}
        self._init_current_step_key = ""
        if bool(getattr(config, "random_ip_enabled", False)):
            self._set_initialization_stage("random_ip", "初始化随机IP模块")
        elif self._should_use_initialization_gate(config):
            self._set_initialization_stage("playwright", "初始化Playwright浏览器环境")
        else:
            self._set_initialization_stage("submission", "初始化提交行为模块")
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
            else:
                lines.append(f"[ ] {label}")
        return lines
    def _clone_runtime_config_for_gate(self, config: RuntimeConfig) -> RuntimeConfig:
        """为初始化门禁创建轻量配置副本，避免深拷贝 UI 对象。"""
        try:
            return copy.copy(config)
        except Exception:
            cloned = RuntimeConfig()
            cloned.__dict__.update(dict(getattr(config, "__dict__", {})))
            return cloned
    def _resolve_random_ip_proxy_target_count(self, config: RuntimeConfig) -> int:
        threads = max(1, int(getattr(config, "threads", 1) or 1))
        target = max(1, int(getattr(config, "target", 1) or 1))
        return min(threads, target)
    def _resolve_random_ip_init_prefetch_count(self, config: RuntimeConfig) -> int:
        if self._should_use_initialization_gate(config):
            return 1
        return self._resolve_random_ip_proxy_target_count(config)
    def _resolve_proxy_api_url_for_config(self, config: RuntimeConfig) -> str:
        proxy_source = str(getattr(config, "proxy_source", "default") or "default")
        custom_proxy_api = str(getattr(config, "custom_proxy_api", "") or "").strip()
        return custom_proxy_api if (proxy_source == "custom" and custom_proxy_api) else get_effective_proxy_api_url()
    def _consume_probe_failure_message(self) -> str:
        message = str(getattr(self, "_probe_failure_message", "") or "").strip()
        self._probe_failure_message = ""
        return message
    def _start_with_initialization_gate(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> None:
        if self.stop_event.is_set():
            self._starting = False
            return
        should_use_gate = self._should_use_initialization_gate(config)
        requires_network_init = bool(getattr(config, "random_ip_enabled", False))
        if not should_use_gate and not requires_network_init:
            self._start_workers_with_proxy_pool(config, proxy_pool)
            return

        self.running = True
        self._starting = False
        self._initializing = True
        self._setup_initialization_progress(config)
        if should_use_gate and not requires_network_init:
            self._set_initialization_stage("playwright", "初始化Playwright浏览器环境")
        self._execution_state = None
        self.runStateChanged.emit(True)
        self._status_timer.start()
        self._emit_status()

        gate_stop_event = threading.Event()
        self._init_gate_stop_event = gate_stop_event
        threading.Thread(
            target=self._run_initialization_gate,
            args=(config, list(proxy_pool), gate_stop_event),
            daemon=True,
            name="InitGate",
        ).start()
    def _prepare_random_ip_resources(
        self,
        config: RuntimeConfig,
        gate_stop_event: threading.Event,
        *,
        expected_count: Optional[int] = None,
    ) -> List[ProxyLease]:
        if not bool(getattr(config, "random_ip_enabled", False)):
            return []

        def _cancelled() -> bool:
            return bool(self.stop_event.is_set() or gate_stop_event.is_set())

        def _set_stage(text: str) -> None:
            def _update_stage(msg: str = str(text)) -> None:
                self._set_initialization_stage("random_ip", msg)
                self._emit_status()

            self._dispatch_to_ui_async(_update_stage)

        if _cancelled():
            return []

        self._validate_benefit_proxy_compatibility(config)

        if not is_custom_proxy_api_active():
            if not has_authenticated_session():
                raise RuntimeError("默认随机IP需要先领取免费试用或提交额度申请，请先完成后再试，或改用自定义代理接口")
            _set_stage("初始化随机IP模块（检查本地额度缓存）")
            try:
                snapshot = get_fresh_quota_snapshot()
            except RandomIPAuthError as exc:
                raise RuntimeError(format_random_ip_error(exc)) from exc
            except Exception as exc:
                raise RuntimeError(f"读取随机IP本地额度缓存失败：{exc}") from exc
            session_snapshot = get_session_snapshot()
            if is_quota_exhausted({**snapshot, "authenticated": True}) and not has_unknown_local_quota(session_snapshot):
                raise RuntimeError("随机IP已用额度已达到上限，请补充额度后再试，或改用自定义代理接口")
            if has_unknown_local_quota(session_snapshot):
                logging.warning("检测到随机IP本地额度状态未知：账号已存在，但当前额度仍待校验；继续预取代理以触发真实额度回填")
            if _cancelled():
                return []

        _set_stage("初始化随机IP模块（预取代理）")
        from software.network.proxy.pool import prefetch_proxy_pool

        proxy_api_url = self._resolve_proxy_api_url_for_config(config)
        initial_proxy_count = max(
            1,
            int(
                self._resolve_random_ip_init_prefetch_count(config)
                if expected_count is None
                else expected_count
            ),
        )
        proxy_pool = prefetch_proxy_pool(
            expected_count=initial_proxy_count,
            proxy_api_url=proxy_api_url,
            stop_signal=self.stop_event,
        )
        if _cancelled():
            return []
        try:
            self._dispatch_to_ui_async(lambda: self.refresh_random_ip_counter(adapter=self.adapter))
        except Exception:
            logging.info("预取代理后刷新随机IP额度失败", exc_info=True)
        return proxy_pool
    def _top_up_random_ip_resources_for_run(
        self,
        config: RuntimeConfig,
        proxy_pool: List[ProxyLease],
        gate_stop_event: threading.Event,
    ) -> List[ProxyLease]:
        if not bool(getattr(config, "random_ip_enabled", False)):
            return list(proxy_pool)

        desired_count = self._resolve_random_ip_proxy_target_count(config)
        existing_pool = list(proxy_pool)
        missing_count = max(0, int(desired_count) - len(existing_pool))
        if missing_count <= 0:
            return existing_pool

        if self.stop_event.is_set() or gate_stop_event.is_set():
            return existing_pool

        def _update_stage_for_top_up() -> None:
            self._set_initialization_stage("random_ip", "初始化随机IP模块（补齐正式运行代理）")
            self._emit_status()

        self._dispatch_to_ui_async(_update_stage_for_top_up)

        from software.network.proxy.pool import prefetch_proxy_pool

        fetched = prefetch_proxy_pool(
            expected_count=missing_count,
            proxy_api_url=self._resolve_proxy_api_url_for_config(config),
            stop_signal=self.stop_event,
        )
        if self.stop_event.is_set() or gate_stop_event.is_set():
            return existing_pool
        combined_pool = existing_pool + list(fetched or [])
        try:
            self._dispatch_to_ui_async(lambda: self.refresh_random_ip_counter(adapter=self.adapter))
        except Exception:
            logging.info("补齐正式运行代理后刷新随机IP额度失败", exc_info=True)
        return combined_pool
    def _run_initialization_gate(
        self,
        config: RuntimeConfig,
        proxy_pool: List[ProxyLease],
        gate_stop_event: threading.Event,
    ) -> None:
        self._probe_failure_message = ""
        self._probe_hit_device_quota = False

        def _cancelled() -> bool:
            return bool(self.stop_event.is_set() or gate_stop_event.is_set())

        effective_proxy_pool = list(proxy_pool)
        if bool(getattr(config, "random_ip_enabled", False)):
            try:
                effective_proxy_pool = self._prepare_random_ip_resources(
                    config,
                    gate_stop_event,
                    expected_count=self._resolve_random_ip_init_prefetch_count(config),
                )
            except Exception as exc:
                self._dispatch_to_ui_async(lambda msg=str(exc): self._finish_initialization_failure(msg))
                return
            if _cancelled():
                return

        if not self._should_use_initialization_gate(config):
            self._dispatch_to_ui_async(lambda: self._start_after_init_success(config, effective_proxy_pool))
            return

        first_headless = self._run_single_probe_attempt(
            config,
            effective_proxy_pool,
            headless=True,
            gate_stop_event=gate_stop_event,
        )
        if first_headless is None:
            return
        if first_headless:
            if bool(getattr(config, "random_ip_enabled", False)):
                try:
                    effective_proxy_pool = self._top_up_random_ip_resources_for_run(
                        config,
                        effective_proxy_pool,
                        gate_stop_event,
                    )
                except Exception as exc:
                    self._dispatch_to_ui_async(lambda msg=str(exc): self._finish_initialization_failure(msg))
                    return
                if _cancelled():
                    return
            self._dispatch_to_ui_async(lambda: self._start_after_init_success(config, effective_proxy_pool))
            return

        second_headful = self._run_single_probe_attempt(
            config,
            effective_proxy_pool,
            headless=False,
            gate_stop_event=gate_stop_event,
        )
        if second_headful is None:
            return
        if not second_headful:
            failure_message = self._consume_probe_failure_message()
            self._dispatch_to_ui_async(
                lambda msg=(
                    failure_message
                    or "初始化失败：无头测试失败后，有头单线程测试也失败，请检查配置后重试"
                ): self._finish_initialization_failure(msg)
            )
            return

        third_headless = self._run_single_probe_attempt(
            config,
            effective_proxy_pool,
            headless=True,
            gate_stop_event=gate_stop_event,
        )
        if third_headless is None:
            return
        if third_headless:
            if bool(getattr(config, "random_ip_enabled", False)):
                try:
                    effective_proxy_pool = self._top_up_random_ip_resources_for_run(
                        config,
                        effective_proxy_pool,
                        gate_stop_event,
                    )
                except Exception as exc:
                    self._dispatch_to_ui_async(lambda msg=str(exc): self._finish_initialization_failure(msg))
                    return
                if _cancelled():
                    return
            self._dispatch_to_ui_async(lambda: self._start_after_init_success(config, effective_proxy_pool))
            return

        if _cancelled():
            return
        fallback_config = self._clone_runtime_config_for_gate(config)
        fallback_config.headless_mode = False
        fallback_threads = min(
            max(1, int(getattr(config, "threads", 1) or 1)),
            NON_HEADLESS_FALLBACK_MAX_THREADS,
        )
        fallback_config.threads = fallback_threads
        if bool(getattr(config, "random_ip_enabled", False)):
            try:
                effective_proxy_pool = self._top_up_random_ip_resources_for_run(
                    fallback_config,
                    effective_proxy_pool,
                    gate_stop_event,
                )
            except Exception as exc:
                self._dispatch_to_ui_async(lambda msg=str(exc): self._finish_initialization_failure(msg))
                return
            if _cancelled():
                return
        self._dispatch_to_ui_async(lambda: self._start_after_init_fallback(fallback_config, effective_proxy_pool))
    def _run_single_probe_attempt(
        self,
        config: RuntimeConfig,
        proxy_pool: List[ProxyLease],
        *,
        headless: bool,
        gate_stop_event: threading.Event,
    ) -> Optional[bool]:
        if self.stop_event.is_set() or gate_stop_event.is_set():
            return None

        mode_text = "无头" if headless else "有头"
        logging.info("初始化门禁：开始%s单线程测试", mode_text)
        def _init_stage() -> None:
            self._set_initialization_stage("playwright", f"初始化Playwright浏览器环境（{mode_text}预检）")
            self._emit_status()
        self._dispatch_to_ui_async(_init_stage)
        probe_config = self._clone_runtime_config_for_gate(config)
        probe_config.headless_mode = bool(headless)
        probe_config.threads = 1
        probe_config.target = 1
        # 门禁探测只用于验证流程可用性，不应消耗作答时长等待。
        probe_config.answer_duration = (0, 0)

        probe_execution_config, probe_state = self._prepare_engine_state(probe_config, list(proxy_pool))
        probe_state.stop_event = gate_stop_event
        probe_state.ensure_worker_threads(1)
        self._apply_pending_execution_config(probe_execution_config, consume=False)
        probe_adapter = self._create_adapter(gate_stop_event, random_ip_enabled=probe_config.random_ip_enabled)
        probe_adapter.execution_state = probe_state

        try:
            run(50, 50, gate_stop_event, probe_adapter, config=probe_execution_config, state=probe_state)
        except Exception:
            logging.error("初始化门禁：%s单线程测试发生异常", mode_text, exc_info=True)
        finally:
            try:
                probe_adapter.cleanup_browsers()
            except Exception:
                logging.info("初始化门禁清理浏览器失败", exc_info=True)

        # run() 在目标达成时会主动 set(stop_signal)，这里的 gate_stop_event 同时承担“外部取消”与“探测内部停止”两种语义。
        # 仅当全局 stop_event 被置位时才视为用户取消；否则按探测结果继续流程。
        if self.stop_event.is_set():
            logging.info("初始化门禁：%s单线程测试已取消", mode_text)
            return None
        success = int(getattr(probe_state, "cur_num", 0) or 0) >= 1
        device_quota_fail_count = max(0, int(getattr(probe_state, "device_quota_fail_count", 0) or 0))
        if device_quota_fail_count > 0:
            self._probe_hit_device_quota = True
            self._probe_failure_message = DEVICE_QUOTA_LIMIT_MESSAGE
        if gate_stop_event.is_set():
            gate_stop_event.clear()
        logging.info("初始化门禁：%s单线程测试%s", mode_text, "成功" if success else "失败")
        return success
    def _reset_initialization_state(self) -> None:
        self._initializing = False
        self._init_stage_text = ""
        self._init_steps = []
        self._init_completed_steps = set()
        self._init_current_step_key = ""
        self._init_gate_stop_event = None
        self._probe_hit_device_quota = False
        self._probe_failure_message = ""
    def _start_after_init_success(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> None:
        if self.stop_event.is_set():
            self._reset_initialization_state()
            return
        self._set_initialization_stage("submission", "初始化提交行为模块")
        self._emit_status()
        self._reset_initialization_state()
        self._start_workers_with_proxy_pool(config, proxy_pool, emit_run_state=False)
    def _apply_headless_fallback_to_ui(self, effective_threads: int) -> None:
        try:
            self.set_runtime_ui_state(
                headless_mode=False,
                threads=int(effective_threads),
            )
        except Exception:
            logging.info("降级到有头模式后同步共享运行状态失败", exc_info=True)
    def _start_after_init_fallback(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> None:
        if self.stop_event.is_set():
            self._reset_initialization_state()
            return

        effective_threads = max(1, int(getattr(config, "threads", 1) or 1))
        self._apply_headless_fallback_to_ui(effective_threads)
        self.config.headless_mode = False
        self.config.threads = effective_threads
        self._set_initialization_stage("submission", "初始化提交行为模块")
        self._emit_status()
        self._reset_initialization_state()
        self._start_workers_with_proxy_pool(config, proxy_pool, emit_run_state=False)
    def _finish_initialization_failure(self, message: str) -> None:
        if self.stop_event.is_set() and not self.running:
            self._reset_initialization_state()
            return
        self._reset_initialization_state()
        self._starting = False
        self._status_timer.stop()
        was_running = bool(self.running)
        self.running = False
        self.worker_threads = []
        self._execution_state = None
        if was_running:
            self.runStateChanged.emit(False)
        self.statusUpdated.emit("初始化失败", 0, 0)
        self.threadProgressUpdated.emit(
            {
                "threads": [],
                "target": 0,
                "num_threads": 0,
                "per_thread_target": 0,
                "initializing": False,
            }
        )
        self.runFailed.emit(str(message or "初始化失败"))
