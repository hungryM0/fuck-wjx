"""RunController 运行控制与状态管理逻辑。"""
from __future__ import annotations

import copy
import logging
import math
import threading
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QCoreApplication

from software.core.engine.runner import run
from software.core.questions.config import configure_probabilities, validate_question_config
from software.core.task import TaskContext
from software.network.proxy.session import (
    activate_trial,
    RandomIPAuthError,
    format_random_ip_error,
    format_quota_value,
    get_fresh_quota_snapshot,
    get_quota_snapshot,
    get_session_snapshot,
    has_authenticated_session,
    has_unknown_local_quota,
    is_quota_exhausted,
    load_session_for_startup,
    sync_quota_snapshot_from_server,
)
from software.network.proxy import (
    get_effective_proxy_api_url,
    get_proxy_minute_by_answer_seconds,
    is_custom_proxy_api_active,
    set_proxy_occupy_minute_by_answer_duration,
)
from software.network.proxy.policy import get_random_ip_counter_snapshot_local
from software.app.config import STOP_FORCE_WAIT_SECONDS
from software.core.task import (
    bus as _event_bus,
    EVENT_TASK_STARTED,
    EVENT_TASK_STOPPED,
)
from software.io.config import RuntimeConfig
if TYPE_CHECKING:
    from PySide6.QtCore import QObject, QTimer

    from software.core.engine.cleanup import CleanupRunner

NON_HEADLESS_FALLBACK_MAX_THREADS = 8
DEVICE_QUOTA_LIMIT_MESSAGE = "当前设备已达到该问卷填写次数上限，无法继续"
PROXY_SOURCE_BENEFIT = "benefit"


class RunControllerRuntimeMixin:
    if TYPE_CHECKING:
        runStateChanged: Any
        runFailed: Any
        statusUpdated: Any
        threadProgressUpdated: Any
        pauseStateChanged: Any
        cleanupFinished: Any
        _status_timer: QTimer
        _cleanup_runner: CleanupRunner

        def _dispatch_to_ui_async(self, callback: Callable[[], None]) -> None: ...
        def parent(self) -> QObject: ...

    # -------------------- Run control --------------------
    @staticmethod
    def _normalize_proxy_source_value(source: Any) -> str:
        normalized = str(source or "default").strip().lower()
        return normalized if normalized in {"default", "benefit", "custom"} else "default"

    @staticmethod
    def _resolve_answer_duration_upper_bound(answer_duration: Any) -> int:
        if isinstance(answer_duration, (list, tuple)):
            if len(answer_duration) >= 2:
                return max(0, int(answer_duration[1] or 0))
            if len(answer_duration) >= 1:
                return max(0, int(answer_duration[0] or 0))
        return 0

    def _validate_benefit_proxy_compatibility(self, config: RuntimeConfig) -> None:
        if not bool(getattr(config, "random_ip_enabled", False)):
            return
        proxy_source = self._normalize_proxy_source_value(getattr(config, "proxy_source", "default"))
        if proxy_source != PROXY_SOURCE_BENEFIT:
            return
        answer_max = self._resolve_answer_duration_upper_bound(getattr(config, "answer_duration", (0, 0)))
        minute = int(get_proxy_minute_by_answer_seconds(answer_max))
        if minute > 1:
            raise RuntimeError(
                f"当前作答时长会要求 {minute} 分钟代理，但“限时福利”只支持 1 分钟。请切回“默认”代理源，或缩短作答时长后再试。"
            )

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

    @staticmethod
    def _resolve_counter_snapshot_values(snapshot: Dict[str, Any]) -> tuple[float, float]:
        return (
            max(0.0, float(snapshot.get("used_quota") or 0.0)),
            max(0.0, float(snapshot.get("total_quota") or 0.0)),
        )

    def _show_random_ip_message(self, adapter: Optional[Any], title: str, message: str, *, level: str = "info") -> None:
        if not adapter:
            return
        try:
            adapter.show_message_dialog(str(title or ""), str(message or ""), level=level)
        except Exception:
            logging.info("显示随机IP提示失败", exc_info=True)

    def _apply_random_ip_counter(self, adapter: Optional[Any], *, used: float, total: float, custom_api: bool) -> None:
        if not adapter:
            return
        try:
            adapter.update_random_ip_counter(float(used), float(total), bool(custom_api))
        except Exception:
            logging.info("更新随机IP额度显示失败", exc_info=True)

    def _set_random_ip_enabled(self, adapter: Optional[Any], enabled: bool) -> None:
        if not adapter:
            return
        try:
            adapter.set_random_ip_enabled(bool(enabled))
        except Exception:
            logging.info("更新随机IP开关失败", exc_info=True)

    def _set_random_ip_loading(self, adapter: Optional[Any], loading: bool, message: str = "") -> None:
        try:
            self.notify_random_ip_loading(bool(loading), str(message or ""))
        except Exception:
            logging.info("广播随机IP加载状态失败", exc_info=True)
        if not adapter:
            return
        try:
            adapter.set_random_ip_loading(bool(loading), str(message or ""))
        except Exception:
            logging.info("更新随机IP加载状态失败", exc_info=True)

    def _get_counter_snapshot(self) -> tuple[float, float, bool]:
        custom_api = bool(is_custom_proxy_api_active())
        if not custom_api and has_authenticated_session():
            try:
                return (*self._resolve_counter_snapshot_values(get_fresh_quota_snapshot()), False)
            except RandomIPAuthError as exc:
                if exc.detail.startswith("session_persist_failed"):
                    raise
                logging.warning("随机IP额度校验失败，回退本地快照：%s", exc.detail)
                return (*self._resolve_counter_snapshot_values(get_quota_snapshot()), False)
            except Exception as exc:
                logging.warning("读取随机IP额度失败，回退本地快照：%s", exc)
                return (*self._resolve_counter_snapshot_values(get_quota_snapshot()), False)
        count, limit, local_custom_api = get_random_ip_counter_snapshot_local()
        return max(0.0, float(count or 0.0)), max(0.0, float(limit or 0.0)), bool(custom_api or local_custom_api)

    def _refresh_random_ip_counter_now(self, adapter: Optional[Any]) -> None:
        if not adapter:
            return
        load_session_for_startup()
        try:
            used, total, custom_api = self._get_counter_snapshot()
        except RandomIPAuthError as exc:
            message = format_random_ip_error(exc)
            logging.error("随机IP账号状态校验失败：%s", message)
            self._set_random_ip_enabled(adapter, False)
            self._show_random_ip_message(adapter, "随机IP账号状态异常", message, level="error")
            used, total, custom_api = self._get_counter_snapshot()
        except Exception as exc:
            message = format_random_ip_error(exc)
            logging.warning("刷新随机IP计数失败：%s", message)
            used, total, custom_api = self._get_counter_snapshot()
        self._apply_random_ip_counter(adapter, used=used, total=total, custom_api=custom_api)

    def refresh_random_ip_counter(self, *, adapter: Optional[Any] = None, async_mode: bool = True) -> None:
        adapter = adapter or getattr(self, "adapter", None)
        if not adapter:
            return
        if async_mode and threading.current_thread() is threading.main_thread():
            threading.Thread(
                target=lambda: self._refresh_random_ip_counter_now(adapter),
                daemon=True,
                name="RandomIPCounterRefresh",
            ).start()
            return
        self._refresh_random_ip_counter_now(adapter)

    def _try_activate_random_ip_trial(self, adapter: Optional[Any]) -> tuple[bool, bool]:
        try:
            self._set_random_ip_loading(adapter, True, "正在领取试用...")
            session = activate_trial()
        except RandomIPAuthError as exc:
            message = format_random_ip_error(exc)
            if exc.detail in {"trial_already_claimed", "trial_already_used", "device_trial_already_claimed"}:
                self._show_random_ip_message(adapter, "试用已领取", message, level="warning")
                return False, True
            self._show_random_ip_message(adapter, "领取试用失败", message, level="error")
            return False, False
        except Exception as exc:
            self._show_random_ip_message(adapter, "领取试用失败", f"领取试用失败：{exc}", level="error")
            return False, False
        finally:
            self._set_random_ip_loading(adapter, False, "")

        total_quota = max(float(session.total_quota or 0.0), 0.0)
        used_quota = max(0.0, float(session.used_quota or 0.0))
        self._apply_random_ip_counter(adapter, used=used_quota, total=total_quota, custom_api=False)
        if total_quota > 0:
            self._show_random_ip_message(
                adapter,
                "试用已领取",
                f"已领取免费试用，当前随机IP已用/总额度：{format_quota_value(used_quota)}/{format_quota_value(total_quota)}。",
                level="info",
            )
        else:
            self._show_random_ip_message(adapter, "试用已领取", "已领取免费试用，随机IP账号已绑定到当前设备。", level="info")
        return True, False

    def _ensure_random_ip_ready(self, adapter: Optional[Any]) -> bool:
        if has_authenticated_session():
            return True
        activated, should_fallback_to_form = self._try_activate_random_ip_trial(adapter)
        if activated:
            return True
        if not should_fallback_to_form:
            return False
        if not adapter:
            return False
        try:
            return bool(adapter.open_quota_request_form())
        except Exception:
            logging.info("打开随机IP额度申请入口失败", exc_info=True)
            self._show_random_ip_message(adapter, "需要申请额度", "请在“联系开发者”中提交随机IP额度申请。", level="warning")
            return False

    def toggle_random_ip(self, enabled: bool, *, adapter: Optional[Any] = None) -> bool:
        adapter = adapter or getattr(self, "adapter", None)
        enabled = bool(enabled)
        if not adapter:
            return enabled
        if not enabled:
            self._set_random_ip_enabled(adapter, False)
            return False
        if is_custom_proxy_api_active():
            self._set_random_ip_enabled(adapter, True)
            self.refresh_random_ip_counter(adapter=adapter)
            return True
        if not self._ensure_random_ip_ready(adapter):
            self._set_random_ip_enabled(adapter, False)
            return False
        _count, _limit, _ = get_random_ip_counter_snapshot_local()
        self._apply_random_ip_counter(
            adapter,
            used=float(_count or 0.0),
            total=float(_limit or 0.0),
            custom_api=False,
        )
        try:
            self._set_random_ip_loading(adapter, True, "正在同步服务端额度...")
            snapshot = sync_quota_snapshot_from_server()
        except Exception as exc:
            message = format_random_ip_error(exc)
            self._show_random_ip_message(adapter, "随机IP暂不可用", message, level="warning")
            self._set_random_ip_enabled(adapter, False)
            self.refresh_random_ip_counter(adapter=adapter)
            return False
        finally:
            self._set_random_ip_loading(adapter, False, "")

        used_quota, total_quota = self._resolve_counter_snapshot_values(snapshot)
        self._apply_random_ip_counter(adapter, used=used_quota, total=total_quota, custom_api=False)
        if is_quota_exhausted({"authenticated": True, **snapshot}):
            self._show_random_ip_message(adapter, "提示", "随机IP已用额度已达到上限，请先补充额度后再启用。", level="warning")
            self._set_random_ip_enabled(adapter, False)
            return False
        self._set_random_ip_enabled(adapter, True)
        return True

    def handle_random_ip_submission(self, *, stop_signal: Optional[threading.Event], adapter: Optional[Any] = None) -> None:
        adapter = adapter or getattr(self, "adapter", None)
        if not adapter or is_custom_proxy_api_active():
            return
        try:
            snapshot = get_session_snapshot()
            if not bool(snapshot.get("authenticated")):
                if stop_signal:
                    stop_signal.set()
                self._set_random_ip_enabled(adapter, False)
                return
            self.refresh_random_ip_counter(adapter=adapter)
        except Exception as exc:
            message = format_random_ip_error(exc)
            logging.warning("刷新随机IP状态失败：%s", message)

    def _dispatch_to_ui(self, callback: Callable[[], None]):
        if QCoreApplication.instance() is None:
            try:
                callback()
            except Exception:
                logging.info("无应用实例时同步 UI 回调执行失败", exc_info=True)
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

    def _prepare_engine_state(self, config: RuntimeConfig, proxy_pool: List[str]) -> TaskContext:
        """构建本次任务的 TaskContext。"""
        fail_threshold = 5
        config_title = str(getattr(config, "survey_title", "") or "")
        fallback_title = str(getattr(self, "survey_title", "") or "")
        survey_title = config_title or fallback_title
        try:
            psycho_target_alpha = float(getattr(config, "psycho_target_alpha", 0.9) or 0.9)
        except Exception:
            psycho_target_alpha = 0.9
        psycho_target_alpha = max(0.70, min(0.95, psycho_target_alpha))

        ctx = TaskContext(
            url=config.url,
            survey_title=survey_title,
            survey_provider=str(getattr(config, "survey_provider", "wjx") or "wjx"),
            target_num=config.target,
            num_threads=max(1, int(config.threads or 1)),
            headless_mode=getattr(config, "headless_mode", False),
            browser_preference=list(getattr(config, "browser_preference", []) or []),
            fail_threshold=fail_threshold,
            cur_num=0,
            cur_fail=0,
            stop_event=self.stop_event,
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
        return ctx

    def _apply_pending_question_ctx(self, ctx: TaskContext, *, consume: bool) -> None:
        pending = self._pending_question_ctx
        if pending is None:
            return
        ctx.single_prob = copy.deepcopy(pending.single_prob)
        ctx.droplist_prob = copy.deepcopy(pending.droplist_prob)
        ctx.multiple_prob = copy.deepcopy(pending.multiple_prob)
        ctx.matrix_prob = copy.deepcopy(pending.matrix_prob)
        ctx.scale_prob = copy.deepcopy(pending.scale_prob)
        ctx.slider_targets = copy.deepcopy(pending.slider_targets)
        ctx.texts = copy.deepcopy(pending.texts)
        ctx.texts_prob = copy.deepcopy(pending.texts_prob)
        ctx.text_entry_types = copy.deepcopy(pending.text_entry_types)
        ctx.text_ai_flags = copy.deepcopy(pending.text_ai_flags)
        ctx.text_titles = copy.deepcopy(pending.text_titles)
        ctx.multi_text_blank_modes = copy.deepcopy(pending.multi_text_blank_modes)
        ctx.multi_text_blank_ai_flags = copy.deepcopy(pending.multi_text_blank_ai_flags)
        ctx.multi_text_blank_int_ranges = copy.deepcopy(getattr(pending, "multi_text_blank_int_ranges", []))
        ctx.single_option_fill_texts = copy.deepcopy(pending.single_option_fill_texts)
        ctx.single_attached_option_selects = copy.deepcopy(pending.single_attached_option_selects)
        ctx.droplist_option_fill_texts = copy.deepcopy(pending.droplist_option_fill_texts)
        ctx.multiple_option_fill_texts = copy.deepcopy(pending.multiple_option_fill_texts)
        ctx.question_config_index_map = copy.deepcopy(pending.question_config_index_map)
        ctx.question_dimension_map = copy.deepcopy(pending.question_dimension_map)
        ctx.question_strict_ratio_map = copy.deepcopy(getattr(pending, "question_strict_ratio_map", {}))
        ctx.question_psycho_bias_map = copy.deepcopy(pending.question_psycho_bias_map)
        ctx.questions_metadata = copy.deepcopy(pending.questions_metadata)
        ctx.survey_provider = str(getattr(pending, "survey_provider", getattr(ctx, "survey_provider", "wjx")) or "wjx")
        if consume:
            self._pending_question_ctx = None

    @staticmethod
    def _should_use_initialization_gate(config: RuntimeConfig) -> bool:
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

    @staticmethod
    def _clone_runtime_config_for_gate(config: RuntimeConfig) -> RuntimeConfig:
        """为初始化门禁创建轻量配置副本，避免深拷贝 UI 对象。"""
        try:
            return copy.copy(config)
        except Exception:
            cloned = RuntimeConfig()
            cloned.__dict__.update(dict(getattr(config, "__dict__", {})))
            return cloned

    def _consume_probe_failure_message(self) -> str:
        message = str(getattr(self, "_probe_failure_message", "") or "").strip()
        self._probe_failure_message = ""
        return message

    def _start_with_initialization_gate(self, config: RuntimeConfig, proxy_pool: List[str]) -> None:
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
        self._task_ctx = None
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
    ) -> List[str]:
        if not bool(getattr(config, "random_ip_enabled", False)):
            return []

        def _cancelled() -> bool:
            return bool(self.stop_event.is_set() or gate_stop_event.is_set())

        def _set_stage(text: str) -> None:
            self._dispatch_to_ui_async(
                lambda msg=str(text): (
                    self._set_initialization_stage("random_ip", msg),
                    self._emit_status(),
                )
            )

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

        proxy_source = str(getattr(config, "proxy_source", "default") or "default")
        custom_proxy_api = str(getattr(config, "custom_proxy_api", "") or "").strip()
        proxy_api_url = custom_proxy_api if (proxy_source == "custom" and custom_proxy_api) else get_effective_proxy_api_url()
        initial_proxy_count = min(
            max(1, int(getattr(config, "threads", 1) or 1)),
            max(1, int(getattr(config, "target", 1) or 1)),
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

    def _run_initialization_gate(
        self,
        config: RuntimeConfig,
        proxy_pool: List[str],
        gate_stop_event: threading.Event,
    ) -> None:
        self._probe_failure_message = ""
        self._probe_hit_device_quota = False

        def _cancelled() -> bool:
            return bool(self.stop_event.is_set() or gate_stop_event.is_set())

        effective_proxy_pool = list(proxy_pool)
        if bool(getattr(config, "random_ip_enabled", False)):
            try:
                effective_proxy_pool = self._prepare_random_ip_resources(config, gate_stop_event)
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
        self._dispatch_to_ui_async(lambda: self._start_after_init_fallback(fallback_config, effective_proxy_pool))

    def _run_single_probe_attempt(
        self,
        config: RuntimeConfig,
        proxy_pool: List[str],
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

        probe_ctx = self._prepare_engine_state(probe_config, list(proxy_pool))
        probe_ctx.stop_event = gate_stop_event
        probe_ctx.ensure_worker_threads(1)
        self._apply_pending_question_ctx(probe_ctx, consume=False)
        probe_adapter = self._create_adapter(gate_stop_event, random_ip_enabled=probe_config.random_ip_enabled)
        probe_adapter.task_ctx = probe_ctx

        try:
            run(50, 50, gate_stop_event, probe_adapter, ctx=probe_ctx)
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
        success = int(getattr(probe_ctx, "cur_num", 0) or 0) >= 1
        device_quota_fail_count = max(0, int(getattr(probe_ctx, "device_quota_fail_count", 0) or 0))
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

    def _start_after_init_success(self, config: RuntimeConfig, proxy_pool: List[str]) -> None:
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

    def _start_after_init_fallback(self, config: RuntimeConfig, proxy_pool: List[str]) -> None:
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
        self._task_ctx = None
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

    def start_run(self, config: RuntimeConfig):  # noqa: C901
        logging.info("收到启动请求")

        if self.running or self._starting:
            logging.warning("任务已在运行中，忽略重复启动请求")
            return

        if not getattr(config, "question_entries", None):
            logging.error("未配置任何题目，无法启动")
            self.runFailed.emit('未配置任何题目，无法开始执行（请先在"题目配置"页添加/配置题目）')
            return

        logging.info("验证题目配置...")
        questions_info = getattr(config, "questions_info", None)
        validation_error = validate_question_config(config.question_entries, questions_info)
        if validation_error:
            logging.error("题目配置验证失败：%s", validation_error)
            self.runFailed.emit(f"题目配置存在冲突，无法启动：\n\n{validation_error}")
            return

        logging.info("开始配置任务：目标%s份，%s个线程", config.target, config.threads)

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
            logging.info("同步随机IP占用时长失败", exc_info=True)

        logging.info("配置题目概率分布（共%s题）", len(config.question_entries))
        _tmp_ctx = TaskContext()
        _tmp_ctx.survey_provider = str(getattr(config, "survey_provider", "wjx") or "wjx")
        try:
            configure_probabilities(
                config.question_entries,
                ctx=_tmp_ctx,
                reliability_mode_enabled=getattr(config, "reliability_mode_enabled", True),
            )
        except Exception as exc:
            logging.error("配置题目失败：%s", exc)
            self._starting = False
            self.runFailed.emit(str(exc))
            return

        _tmp_ctx.questions_metadata = {}
        if hasattr(self, "questions_info") and self.questions_info:
            for q_info in self.questions_info:
                q_num = q_info.get("num")
                if q_num:
                    _tmp_ctx.questions_metadata[q_num] = q_info
        self._pending_question_ctx = _tmp_ctx

        self._start_with_initialization_gate(config, [])

    def _start_workers_with_proxy_pool(
        self,
        config: RuntimeConfig,
        proxy_pool: List[str],
        *,
        emit_run_state: bool = True,
    ) -> None:
        ctx = self._prepare_engine_state(config, proxy_pool)
        ctx.ensure_worker_threads(max(1, int(config.threads or 1)))
        self._apply_pending_question_ctx(ctx, consume=True)
        self._task_ctx = ctx
        self.adapter.task_ctx = ctx

        self.config.headless_mode = bool(getattr(config, "headless_mode", False))
        self.config.threads = max(1, int(config.threads or 1))
        self.running = True
        self._starting = False
        if emit_run_state:
            self.runStateChanged.emit(True)
        self._status_timer.start()

        _event_bus.emit(EVENT_TASK_STARTED, ctx=ctx)

        logging.info("创建%s个工作线程", config.threads)
        threads: List[threading.Thread] = []
        for idx in range(config.threads):
            x = 50 + idx * 60
            y = 50 + idx * 60
            t = threading.Thread(
                target=run,
                args=(x, y, self.stop_event, self.adapter),
                kwargs={"ctx": ctx},
                daemon=True,
                name=f"Worker-{idx+1}",
            )
            threads.append(t)
        self.worker_threads = threads

        logging.info("启动所有工作线程")
        for idx, t in enumerate(threads):
            t.start()
            logging.info("线程 %s/%s 已启动", idx + 1, len(threads))

        monitor = threading.Thread(
            target=self._wait_for_threads,
            args=(self.adapter,),
            daemon=True,
            name="Monitor",
        )
        monitor.start()
        logging.info("任务启动完成，监控线程已启动")

    def _wait_for_threads(self, adapter_snapshot: Optional[Any] = None):
        for t in self.worker_threads:
            t.join()
        self._on_run_finished(adapter_snapshot)

    def _on_run_finished(self, adapter_snapshot: Optional[Any] = None):
        if threading.current_thread() is not threading.main_thread():
            self._dispatch_to_ui_async(lambda: self._on_run_finished(adapter_snapshot))
            return
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
            logging.info("停止状态定时器失败", exc_info=True)
        try:
            if self.adapter:
                self.adapter.resume_run()
        except Exception:
            logging.info("停止时恢复暂停状态失败", exc_info=True)
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
            logging.info("恢复运行时清除暂停状态失败", exc_info=True)
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

        ctx = self._task_ctx
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
                logging.info("获取线程进度快照失败", exc_info=True)
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



