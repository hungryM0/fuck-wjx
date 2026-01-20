from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from PySide6.QtCore import QObject, Signal, QTimer, QCoreApplication

from wjx import engine
from wjx.core import engine_state as state
from wjx.utils.config import DEFAULT_HTTP_HEADERS, DEFAULT_FILL_TEXT, STOP_FORCE_WAIT_SECONDS
from wjx.utils.cleanup_runner import CleanupRunner
from wjx.core.question_config import QuestionEntry, configure_probabilities
from wjx.engine import (
    create_playwright_driver,
    parse_survey_questions_from_html,
    _normalize_question_type_code,
    _extract_survey_title_from_html,
    _normalize_html_text,
)
from wjx.network.browser_driver import kill_processes_by_pid
from wjx.utils.load_save import RuntimeConfig, load_config, save_config
from wjx.utils.log_utils import log_popup_confirm, log_popup_error, log_popup_info, log_popup_warning
from wjx.network.random_ip import (
    _fetch_new_proxy_batch,
    get_effective_proxy_api_url,
    get_random_ip_limit,
    is_custom_proxy_api_active,
)
from wjx.utils.registry_manager import RegistryManager


class BoolVar:
    """Tiny stand-in for tkinter.BooleanVar."""

    def __init__(self, value: bool = False):
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool):
        self._value = bool(value)


class EngineGuiAdapter:
    """Adapter passed into engine.run to bridge callbacks back to the Qt UI."""

    def __init__(
        self,
        dispatcher: Callable[[Callable[[], None]], None],
        stop_signal: threading.Event,
        card_code_provider: Optional[Callable[[], Optional[str]]] = None,
        on_ip_counter: Optional[Callable[[int, int, bool, bool], None]] = None,
    ):
        self.random_ip_enabled_var = BoolVar(False)
        self.active_drivers: List[Any] = []
        self._launched_browser_pids: Set[int] = set()
        self._dispatcher = dispatcher
        self._stop_signal = stop_signal
        self._card_code_provider = card_code_provider
        self.update_random_ip_counter = on_ip_counter
        self._pause_event = threading.Event()
        self._pause_reason = ""

    def _post_to_ui_thread(self, callback: Callable[[], None]) -> None:
        """Expose a Tk-style dispatcher hook expected by engine helpers."""
        try:
            self._dispatcher(callback)
        except Exception:
            try:
                callback()
            except Exception:
                pass

    def pause_run(self, reason: str = "") -> None:
        """Pause all worker loops until resumed by UI."""
        self._pause_reason = str(reason or "已暂停")
        self._pause_event.set()

    def resume_run(self) -> None:
        self._pause_reason = ""
        self._pause_event.clear()

    def is_paused(self) -> bool:
        return bool(self._pause_event.is_set())

    def get_pause_reason(self) -> str:
        return self._pause_reason or ""

    def wait_if_paused(self, stop_signal: Optional[threading.Event] = None) -> None:
        """Block worker thread while paused; returns immediately if stop is set."""
        signal = stop_signal or self._stop_signal
        while self.is_paused() and signal and not signal.is_set():
            signal.wait(0.25)

    def force_stop_immediately(self, reason: Optional[str] = None):
        self._stop_signal.set()

    def stop_run(self):
        self._stop_signal.set()

    def request_card_code(self) -> Optional[str]:
        if callable(self._card_code_provider):
            try:
                return self._card_code_provider()
            except Exception:
                return None
        return None

    def cleanup_browsers(self) -> None:
        drivers = list(self.active_drivers or [])
        self.active_drivers.clear()
        pids_to_kill: Set[int] = set(self._launched_browser_pids or set())
        self._launched_browser_pids.clear()

        for driver in drivers:
            try:
                pid_single = getattr(driver, "browser_pid", None)
                if pid_single:
                    pids_to_kill.add(int(pid_single))
                pid_set = getattr(driver, "browser_pids", None)
                if pid_set:
                    pids_to_kill.update(int(p) for p in pid_set)
            except Exception:
                pass
            try:
                driver.quit()
            except Exception:
                pass

        if pids_to_kill:
            try:
                kill_processes_by_pid(pids_to_kill)
            except Exception:
                pass


class RunController(QObject):
    surveyParsed = Signal(list, str)
    surveyParseFailed = Signal(str)
    runStateChanged = Signal(bool)
    runFailed = Signal(str)
    statusUpdated = Signal(str, int, int)
    pauseStateChanged = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = RuntimeConfig()
        self.questions_info: List[Dict[str, Any]] = []
        self.question_entries: List[QuestionEntry] = []
        self.stop_event = threading.Event()
        self.worker_threads: List[threading.Thread] = []
        self.adapter = EngineGuiAdapter(self._dispatch_to_ui, self.stop_event)
        self.running = False
        self._paused_state = False
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(600)
        self._status_timer.timeout.connect(self._emit_status)
        self.on_ip_counter: Optional[Callable[[int, int, bool, bool], None]] = None
        self.card_code_provider: Optional[Callable[[], Optional[str]]] = None
        self._cleanup_runner = CleanupRunner()

    # -------------------- Parsing --------------------
    def parse_survey(self, url: str):
        """Parse survey structure in a worker thread."""
        if not url:
            self.surveyParseFailed.emit("请填写问卷链接")
            return

        def _worker():
            try:
                info, title = self._parse_questions(url)
                self.questions_info = info
                self.question_entries = self._build_default_entries(info)
                self.config.url = url
                self.surveyParsed.emit(info, title or "")
            except Exception as exc:
                self.surveyParseFailed.emit(str(exc) or "解析失败，请稍后重试")

        threading.Thread(target=_worker, daemon=True).start()

    def _parse_questions(self, url: str) -> Tuple[List[Dict[str, Any]], str]:
        info: Optional[List[Dict[str, Any]]] = None
        title = ""
        if requests:
            try:
                resp = requests.get(url, timeout=12, headers=DEFAULT_HTTP_HEADERS, proxies={})
                resp.raise_for_status()
                html = resp.text
                info = parse_survey_questions_from_html(html)
                title = _extract_survey_title_from_html(html) or title
            except Exception:
                info = None
        if info is None:
            driver = None
            try:
                driver, _ = create_playwright_driver(headless=True, user_agent=None)
                driver.get(url)
                time.sleep(2.5)
                page_source = driver.page_source
                info = parse_survey_questions_from_html(page_source)
                title = _extract_survey_title_from_html(page_source) or title
            finally:
                try:
                    if driver:
                        driver.quit()
                except Exception:
                    pass
        if not info:
            raise RuntimeError("无法解析问卷，请确认链接是否正确或问卷已开放")
        normalized_title = _normalize_html_text(title) if title else ""
        return info, normalized_title

    @staticmethod
    def _as_float(val, default):
        """将值转换为浮点数，失败时返回默认值"""
        try:
            return float(val)
        except Exception:
            return default

    def _build_default_entries(self, questions_info: List[Dict[str, Any]]) -> List[QuestionEntry]:
        entries: List[QuestionEntry] = []
        for q in questions_info:
            type_code = _normalize_question_type_code(q.get("type_code"))
            option_count = int(q.get("options") or 0)
            rows = int(q.get("rows") or 1)
            is_location = bool(q.get("is_location"))
            is_multi_text = bool(q.get("is_multi_text"))
            is_text_like = bool(q.get("is_text_like"))
            text_inputs = int(q.get("text_inputs") or 0)
            slider_min = q.get("slider_min")
            slider_max = q.get("slider_max")
            title_text = str(q.get("title") or "").strip()

            if is_multi_text or (is_text_like and text_inputs > 1):
                q_type = "multi_text"
            elif is_text_like or type_code in ("1", "2"):
                q_type = "text"
            elif type_code == "3":
                q_type = "single"
            elif type_code == "4":
                q_type = "multiple"
            elif type_code == "5":
                q_type = "scale"
            elif type_code == "6":
                q_type = "matrix"
            elif type_code == "7":
                q_type = "dropdown"
            elif type_code == "8":
                q_type = "slider"
            else:
                q_type = "single"

            option_count = max(option_count, text_inputs, 1)
            if q_type in ("single", "dropdown", "scale"):
                probabilities: Any = -1
                distribution = "random"
                custom_weights = None
                texts = None
            elif q_type == "multiple":
                probabilities = [1.0] * option_count
                distribution = "random"
                custom_weights = None
                texts = None
            elif q_type == "matrix":
                probabilities = -1
                distribution = "random"
                custom_weights = None
                texts = None
            elif q_type == "slider":
                min_val = self._as_float(slider_min, 0.0)
                max_val = self._as_float(slider_max, 100.0 if slider_max is None else slider_max)
                if max_val <= min_val:
                    max_val = min_val + 100.0
                midpoint = min_val + (max_val - min_val) / 2.0
                probabilities = [midpoint]
                distribution = "custom"
                custom_weights = [midpoint]
                texts = None
                option_count = 1
            else:
                probabilities = [1.0]
                distribution = "random"
                custom_weights = None
                texts = [DEFAULT_FILL_TEXT]

            entry = QuestionEntry(
                question_type=q_type,
                probabilities=probabilities,
                texts=texts,
                rows=rows,
                option_count=option_count,
                distribution_mode=distribution,
                custom_weights=custom_weights,
                question_num=q.get("num"),
                question_title=title_text or None,
                ai_enabled=False,
                option_fill_texts=None,
                fillable_option_indices=q.get("fillable_options"),
                is_location=is_location,
            )
            entries.append(entry)
        return entries

    # -------------------- Run control --------------------
    def _dispatch_to_ui(self, callback: Callable[[], None]):
        if QCoreApplication.instance() is None:
            try:
                callback()
            except Exception:
                pass
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

        # 将回调派发到控制器所属线程（主线程）
        QTimer.singleShot(0, _run)
        done.wait()
        return result_container.get("value")

    def _prepare_engine_state(self, config: RuntimeConfig, proxy_pool: List[str]) -> None:
        fail_threshold = max(1, math.ceil(config.target / 4) + 1)
        # sync controller copies
        state.url = config.url
        state.target_num = config.target
        state.num_threads = min(config.threads, state.MAX_THREADS)
        state.fail_threshold = fail_threshold
        state.cur_num = getattr(state, "cur_num", 0)
        state.cur_fail = getattr(state, "cur_fail", 0)
        state.stop_event = self.stop_event
        state.submit_interval_range_seconds = tuple(config.submit_interval)
        state.answer_duration_range_seconds = tuple(config.answer_duration)
        state.timed_mode_enabled = config.timed_mode_enabled
        state.timed_mode_refresh_interval = config.timed_mode_interval
        state.random_proxy_ip_enabled = config.random_ip_enabled
        state.proxy_ip_pool = proxy_pool if config.random_ip_enabled else []
        state.random_user_agent_enabled = config.random_ua_enabled
        state.user_agent_pool_keys = config.random_ua_keys
        state.stop_on_fail_enabled = config.fail_stop_enabled
        state.pause_on_aliyun_captcha = bool(getattr(config, "pause_on_aliyun_captcha", True))
        # sync module-level aliases used elsewhere in this file
        state._aliyun_captcha_stop_triggered = False
        state._aliyun_captcha_popup_shown = False
        state._target_reached_stop_triggered = False

    def start_run(self, config: RuntimeConfig):
        import logging
        logging.info("收到启动请求")
        
        if self.running:
            logging.warning("任务已在运行中，忽略重复启动请求")
            return
        if not getattr(config, "question_entries", None):
            logging.error("未配置任何题目，无法启动")
            self.runFailed.emit('未配置任何题目，无法开始执行（请先在"题目配置"页添加/配置题目）')
            return
        
        logging.info(f"开始配置任务：目标{config.target}份，{config.threads}个线程")
        
        self.config = config
        self.question_entries = list(getattr(config, "question_entries", []) or [])
        self.stop_event = threading.Event()
        self.adapter = EngineGuiAdapter(
            self._dispatch_to_ui,
            self.stop_event,
            card_code_provider=getattr(self, "card_code_provider", None),
            on_ip_counter=getattr(self, "on_ip_counter", None),
        )
        self.adapter.random_ip_enabled_var.set(config.random_ip_enabled)
        self._paused_state = False
        
        logging.info(f"配置题目概率分布（共{len(config.question_entries)}题）")
        try:
            configure_probabilities(config.question_entries)
        except Exception as exc:
            logging.error(f"配置题目失败：{exc}")
            self.runFailed.emit(str(exc))
            return

        proxy_pool: List[str] = []
        if config.random_ip_enabled:
            # 检查是否已达随机IP上限
            if not RegistryManager.is_quota_unlimited() and not is_custom_proxy_api_active():
                count = RegistryManager.read_submit_count()
                limit = max(1, get_random_ip_limit())
                if count >= limit:
                    logging.warning(f"随机IP已达{limit}份上限，无法启动")
                    self.runFailed.emit(f"随机IP已达{limit}份上限，请关闭随机IP开关或解锁大额IP后再试")
                    return
            
            try:
                proxy_pool = _fetch_new_proxy_batch(
                    expected_count=max(1, config.threads),
                    proxy_url=config.random_proxy_api or get_effective_proxy_api_url(),
                )
            except Exception as exc:
                self.runFailed.emit(str(exc))
                return

        self._prepare_engine_state(config, proxy_pool)
        self.running = True
        self.runStateChanged.emit(True)
        self._status_timer.start()

        logging.info(f"创建{config.threads}个工作线程")
        threads: List[threading.Thread] = []
        for idx in range(config.threads):
            x = 50 + idx * 60
            y = 50 + idx * 60
            t = threading.Thread(
                target=engine.run,
                args=(x, y, self.stop_event, self.adapter),
                daemon=True,
                name=f"Worker-{idx+1}"
            )
            threads.append(t)
        self.worker_threads = threads
        
        logging.info("启动所有工作线程")
        for idx, t in enumerate(threads):
            t.start()
            logging.info(f"线程 {idx+1}/{len(threads)} 已启动")

        monitor = threading.Thread(
            target=self._wait_for_threads,
            args=(self.adapter,),
            daemon=True,
            name="Monitor",
        )
        monitor.start()
        logging.info("任务启动完成，监控线程已启动")

    def _wait_for_threads(self, adapter_snapshot: Optional[EngineGuiAdapter] = None):
        for t in self.worker_threads:
            t.join()
        self._on_run_finished(adapter_snapshot)

    def _on_run_finished(self, adapter_snapshot: Optional[EngineGuiAdapter] = None):
        if threading.current_thread() is not threading.main_thread():
            QTimer.singleShot(0, lambda: self._on_run_finished(adapter_snapshot))
            return
        self._schedule_cleanup(adapter_snapshot)
        self.running = False
        self.runStateChanged.emit(False)
        self._status_timer.stop()
        self._emit_status()

    def _schedule_cleanup(self, adapter_snapshot: Optional[EngineGuiAdapter] = None) -> None:
        adapter = adapter_snapshot or self.adapter

        def _cleanup():
            if adapter:
                adapter.cleanup_browsers()

        self._cleanup_runner.submit(_cleanup, delay_seconds=STOP_FORCE_WAIT_SECONDS)

    def stop_run(self):
        if not self.running:
            return
        self.stop_event.set()
        try:
            if self.adapter:
                self.adapter.resume_run()
        except Exception:
            pass
        self._schedule_cleanup()
        if self._paused_state:
            self._paused_state = False
            self.pauseStateChanged.emit(False, "")
        self.running = False
        self.runStateChanged.emit(False)

    def resume_run(self):
        """Resume execution after a pause (does not restart threads)."""
        if not self.running:
            return
        try:
            self.adapter.resume_run()
        except Exception:
            pass
        if self._paused_state:
            self._paused_state = False
            self.pauseStateChanged.emit(False, "")

    def _emit_status(self):
        current = getattr(state, "cur_num", 0)
        target = getattr(state, "target_num", 0)
        fail = getattr(state, "cur_fail", 0)
        paused = False
        reason = ""
        try:
            paused = bool(self.adapter.is_paused())
            reason = str(self.adapter.get_pause_reason() or "")
        except Exception:
            paused = False
            reason = ""

        status_prefix = "已暂停" if paused else "已提交"
        status = f"{status_prefix} {current}/{target} 份 | 失败 {fail} 次"
        if paused and reason:
            status = f"{status} | {reason}"
        self.statusUpdated.emit(status, int(current), int(target or 0))

        if paused != self._paused_state:
            self._paused_state = paused
            self.pauseStateChanged.emit(bool(paused), str(reason or ""))

    def _cleanup_browsers(self) -> None:
        try:
            if self.adapter:
                self.adapter.cleanup_browsers()
        except Exception:
            pass

    # -------------------- Persistence --------------------
    def load_saved_config(self, path: Optional[str] = None) -> RuntimeConfig:
        cfg = load_config(path)
        self.config = cfg
        self.question_entries = cfg.question_entries
        return cfg

    def save_current_config(self, path: Optional[str] = None) -> str:
        entries = getattr(self.config, "question_entries", None)
        if entries is None:
            entries = self.question_entries
        self.question_entries = list(entries or [])
        self.config.question_entries = self.question_entries
        return save_config(self.config, path)
