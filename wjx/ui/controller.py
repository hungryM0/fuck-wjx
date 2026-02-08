from __future__ import annotations

import math
import logging
from urllib.parse import urlparse
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from PySide6.QtCore import QObject, Signal, QTimer, QCoreApplication

from wjx import engine
import wjx.core.state as state
from wjx.utils.app.config import DEFAULT_HTTP_HEADERS, DEFAULT_FILL_TEXT, STOP_FORCE_WAIT_SECONDS
from wjx.utils.system.cleanup_runner import CleanupRunner
from wjx.core.questions.config import QuestionEntry, configure_probabilities
from wjx.engine import (
    create_playwright_driver,
    parse_survey_questions_from_html,
    _normalize_question_type_code,
    _extract_survey_title_from_html,
    _normalize_html_text,
)
from wjx.utils.io.load_save import RuntimeConfig, load_config, save_config
from wjx.utils.logging.log_utils import log_popup_confirm, log_popup_error, log_popup_info, log_popup_warning
from wjx.network.browser_driver import graceful_terminate_process_tree
from wjx.network.random_ip import (
    _fetch_new_proxy_batch,
    get_effective_proxy_api_url,
    get_random_ip_limit,
    is_custom_proxy_api_active,
)
from wjx.utils.system.registry_manager import RegistryManager
from wjx.core.stats.collector import stats_collector
from wjx.core.stats.persistence import save_stats


def _is_wjx_domain(url_value: str) -> bool:
    """仅接受 wjx.cn 及子域名。"""
    if not url_value:
        return False
    text = str(url_value).strip()
    if not text:
        return False
    # 若缺少协议，urlparse 取 netloc 为空，尝试补全协议再解析
    candidate = text if "://" in text else f"http://{text}"
    try:
        parsed = urlparse(candidate)
    except Exception:
        return False
    host = (parsed.netloc or "").split(":", 1)[0].lower()
    return bool(host == "wjx.cn" or host.endswith(".wjx.cn"))


class BoolVar:
    """简单的布尔状态封装，用于 UI 适配。"""

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
        async_dispatcher: Optional[Callable[[Callable[[], None]], None]] = None,
        cleanup_runner: Optional[CleanupRunner] = None,
    ):
        self.random_ip_enabled_var = BoolVar(False)
        self.active_drivers: List[Any] = []
        self._launched_browser_pids: Set[int] = set()
        self._dispatcher = dispatcher
        self._async_dispatcher = async_dispatcher or dispatcher
        self._stop_signal = stop_signal
        self._card_code_provider = card_code_provider
        self.update_random_ip_counter = on_ip_counter
        self._pause_event = threading.Event()
        self._pause_reason = ""
        self._cleanup_runner = cleanup_runner  # 用于异步清理浏览器

    def _post_to_ui_thread(self, callback: Callable[[], None]) -> None:
        """提供 UI 线程派发钩子，供引擎辅助逻辑调用。"""
        try:
            self._dispatcher(callback)
        except Exception:
            try:
                callback()
            except Exception:
                pass

    def _post_to_ui_thread_async(self, callback: Callable[[], None]) -> None:
        """Fire-and-forget UI dispatch to avoid blocking worker threads."""
        try:
            self._async_dispatcher(callback)
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
        pids_to_wait: Set[int] = set(self._launched_browser_pids or set())
        self._launched_browser_pids.clear()

        for driver in drivers:
            try:
                pid_single = getattr(driver, "browser_pid", None)
                if pid_single:
                    pids_to_wait.add(int(pid_single))
                pid_set = getattr(driver, "browser_pids", None)
                if pid_set:
                    pids_to_wait.update(int(p) for p in pid_set)
            except Exception:
                pass
            try:
                driver.quit()
            except Exception:
                pass

        if pids_to_wait:
            try:
                # 降低等待时间，加快浏览器重启速度（从1.5秒→0.8秒）
                graceful_terminate_process_tree(pids_to_wait, wait_seconds=0.8)
            except Exception:
                pass


class RunController(QObject):
    surveyParsed = Signal(list, str)
    surveyParseFailed = Signal(str)
    runStateChanged = Signal(bool)
    runFailed = Signal(str)
    statusUpdated = Signal(str, int, int)
    pauseStateChanged = Signal(bool, str)
    cleanupFinished = Signal()
    askSaveStats = Signal()  # 新增：询问用户是否保存统计数据
    _uiCallbackQueued = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = RuntimeConfig()
        self.questions_info: List[Dict[str, Any]] = []
        self.question_entries: List[QuestionEntry] = []
        self.stop_event = threading.Event()
        self.worker_threads: List[threading.Thread] = []
        # 先创建清理器，后续 adapter 需要引用
        self._cleanup_runner = CleanupRunner()
        self.adapter = EngineGuiAdapter(
            self._dispatch_to_ui,
            self.stop_event,
            async_dispatcher=self._dispatch_to_ui_async,
            cleanup_runner=self._cleanup_runner,
        )
        self.running = False
        self._paused_state = False
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(600)
        self._status_timer.timeout.connect(self._emit_status)
        self.on_ip_counter: Optional[Callable[[int, int, bool, bool], None]] = None
        self.card_code_provider: Optional[Callable[[], Optional[str]]] = None
        self._completion_cleanup_done = False
        self._cleanup_scheduled = False
        self._stopped_by_stop_run = False
        self._stats_saved = False  # 新增：防止重复保存统计
        self._uiCallbackQueued.connect(self._execute_ui_callback)

    def _execute_ui_callback(self, callback: object) -> None:
        if not callable(callback):
            return
        try:
            callback()
        except Exception:
            logging.debug("执行 UI 回调失败", exc_info=True)

    def _dispatch_to_ui_async(self, callback: Callable[[], None]) -> None:
        if not callable(callback):
            return
        if QCoreApplication.instance() is None:
            try:
                callback()
            except Exception:
                pass
            return
        if threading.current_thread() is threading.main_thread():
            try:
                callback()
            except Exception:
                pass
            return
        try:
            self._uiCallbackQueued.emit(callback)
        except Exception:
            try:
                callback()
            except Exception:
                pass

    # -------------------- Parsing --------------------
    def parse_survey(self, url: str):
        """Parse survey structure in a worker thread."""
        if not url:
            self.surveyParseFailed.emit("请填写问卷链接")
            return
        normalized_url = str(url or "").strip()
        if not _is_wjx_domain(normalized_url):
            logging.warning("收到非问卷星域名链接：%r", normalized_url)
            self.surveyParseFailed.emit("仅支持问卷星链接")
            return

        def _worker():
            try:
                info, title = self._parse_questions(normalized_url)
                # 过滤掉说明页/阅读材料，只保留真正的题目
                info = [q for q in info if not q.get("is_description")]
                self.questions_info = info
                # 传入现有配置，以便复用已配置的题型权重
                self.question_entries = self._build_default_entries(info, self.question_entries)
                self.config.url = normalized_url
                self.surveyParsed.emit(info, title or "")
            except Exception as exc:
                friendly = str(exc) or "解析失败，请稍后重试"
                self.surveyParseFailed.emit(friendly)

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
            except Exception as exc:
                logging.exception("使用 requests 获取问卷失败，url=%r", url)
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
            except Exception as exc:
                logging.exception("使用 Playwright 获取问卷失败，url=%r", url)
                info = None
            finally:
                try:
                    if driver:
                        driver.quit()
                except Exception:
                    pass
        if not info:
            raise RuntimeError("无法打开问卷链接，请确认链接有效且网络正常")
        normalized_title = _normalize_html_text(title) if title else ""
        return info, normalized_title

    @staticmethod
    def _as_float(val, default):
        """将值转换为浮点数，失败时返回默认值"""
        try:
            return float(val)
        except Exception:
            return default

    @staticmethod
    def _build_mid_bias_weights(option_count: int) -> List[float]:
        """生成等权重（评价题默认）。"""
        count = max(1, int(option_count or 1))
        return [1.0] * count

    def _build_default_entries(
        self, 
        questions_info: List[Dict[str, Any]], 
        existing_entries: Optional[List[QuestionEntry]] = None
    ) -> List[QuestionEntry]:
        """构建题目配置列表。如果 existing_entries 中有相同题型的配置，则优先复用其权重设置。"""
        # 建立题型到已配置权重的映射
        type_config_map: Dict[str, QuestionEntry] = {}
        if existing_entries:
            for entry in existing_entries:
                q_type = entry.question_type
                # 只保存每个题型的第一个配置作为参考
                if q_type not in type_config_map:
                    type_config_map[q_type] = entry
        
        entries: List[QuestionEntry] = []
        for q in questions_info:
            type_code = _normalize_question_type_code(q.get("type_code"))
            # 跳过说明页/阅读材料，不为其创建配置条目
            if bool(q.get("is_description")):
                continue
            option_count = int(q.get("options") or 0)
            rows = int(q.get("rows") or 1)
            is_location = bool(q.get("is_location"))
            is_multi_text = bool(q.get("is_multi_text"))
            is_text_like = bool(q.get("is_text_like"))
            text_inputs = int(q.get("text_inputs") or 0)
            slider_min = q.get("slider_min")
            slider_max = q.get("slider_max")
            is_rating = bool(q.get("is_rating"))
            rating_max = int(q.get("rating_max") or 0)
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
                q_type = "score" if is_rating else "scale"
            elif type_code == "6":
                q_type = "matrix"
            elif type_code == "7":
                q_type = "dropdown"
            elif type_code == "8":
                q_type = "slider"
            elif type_code == "11":
                q_type = "order"
            else:
                q_type = "single"

            base_option_count = max(option_count, rating_max, 1)
            if q_type in ("text", "multi_text"):
                option_count = max(base_option_count, text_inputs, 1)
            else:
                option_count = base_option_count
            
            # 检查是否有已配置的相同题型，如果有则复用其权重配置
            existing_config = type_config_map.get(q_type)
            if existing_config:
                # 复用已配置的权重设置
                probabilities: Any = existing_config.probabilities
                distribution = existing_config.distribution_mode or "random"
                custom_weights = existing_config.custom_weights
                texts = existing_config.texts
                # 对于文本题，复用AI设置
                ai_enabled_from_existing = getattr(existing_config, "ai_enabled", False) if q_type in ("text", "multi_text") else False
            else:
                # 没有已配置的相同题型，使用默认配置
                ai_enabled_from_existing = False
                if q_type in ("single", "dropdown", "scale"):
                    probabilities = -1
                    distribution = "random"
                    custom_weights = None
                    texts = None
                elif q_type == "score":
                    option_count = max(option_count, 2)
                    weights = self._build_mid_bias_weights(option_count)
                    probabilities = list(weights)
                    distribution = "custom"
                    custom_weights = list(weights)
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
                elif q_type == "order":
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
                ai_enabled=ai_enabled_from_existing if q_type in ("text", "multi_text") else False,
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
        self._dispatch_to_ui_async(_run)
        if not done.wait(timeout=3):
            try:
                import logging
                logging.warning("UI 调度超时，放弃等待以避免阻塞")
            except Exception:
                pass
            return None
        return result_container.get("value")

    def _prepare_engine_state(self, config: RuntimeConfig, proxy_pool: List[str]) -> None:
        fail_threshold = max(1, math.ceil(config.target / 4) + 1)
        # sync controller copies
        state.url = config.url
        state.target_num = config.target
        state.num_threads = max(1, int(config.threads or 1))
        state.browser_preference = list(getattr(config, "browser_preference", []) or [])
        state.fail_threshold = fail_threshold
        # 新一轮任务必须从 0 开始计数，否则进度会沿用上次完成值
        state.cur_num = 0
        state.cur_fail = 0
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

        # 仅在确认要启动新一轮任务时再重置全局进度状态
        # 避免“正在运行时误点开始”把当前任务状态清零。
        state.cur_num = 0
        state.cur_fail = 0
        state.target_num = max(1, int(getattr(config, "target", 1) or 1))
        state._target_reached_stop_triggered = False
        state._aliyun_captcha_stop_triggered = False
        state._aliyun_captcha_popup_shown = False
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
            async_dispatcher=self._dispatch_to_ui_async,
            cleanup_runner=self._cleanup_runner,  # 传递异步清理器
        )
        self.adapter.random_ip_enabled_var.set(config.random_ip_enabled)
        self._paused_state = False
        self._completion_cleanup_done = False
        self._cleanup_scheduled = False
        self._stopped_by_stop_run = False
        self._stats_saved = False  # 重置统计保存标志
        
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
                    notify_on_area_error=False,
                    stop_signal=self.stop_event,
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
            self._dispatch_to_ui_async(lambda: self._on_run_finished(adapter_snapshot))
            return
        self._schedule_cleanup(adapter_snapshot)
        # 如果已经由 stop_run() 处理过状态变更，不再重复发信号（避免双重触发 UI 更新）
        already_stopped = getattr(self, '_stopped_by_stop_run', False)
        self._stopped_by_stop_run = False
        self._status_timer.stop()
        if not already_stopped:
            self.running = False
            self.runStateChanged.emit(False)
        self._emit_status()

    def _submit_cleanup_task(
        self,
        adapter_snapshot: Optional[EngineGuiAdapter] = None,
        delay_seconds: float = 0.0,
    ) -> None:
        adapter = adapter_snapshot or self.adapter
        if not adapter:
            return

        def _cleanup():
            try:
                adapter.cleanup_browsers()
            except Exception:
                pass
            finally:
                self._dispatch_to_ui_async(self.cleanupFinished.emit)

        self._cleanup_runner.submit(_cleanup, delay_seconds=delay_seconds)

    def _schedule_cleanup(self, adapter_snapshot: Optional[EngineGuiAdapter] = None) -> None:
        if self._cleanup_scheduled:
            return
        self._cleanup_scheduled = True
        self._submit_cleanup_task(
            adapter_snapshot,
            delay_seconds=STOP_FORCE_WAIT_SECONDS,
        )

    def stop_run(self):
        if not self.running:
            return
        self.stop_event.set()
        # 立即停止状态轮询定时器，减少关停期间的主线程开销
        try:
            self._status_timer.stop()
        except Exception:
            pass
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
        self._stopped_by_stop_run = True
        self.runStateChanged.emit(False)
        # 做一次最终状态刷新
        self._emit_status()
        
        # 如果是用户手动停止（未达到目标份数），询问是否保存统计
        current = getattr(state, "cur_num", 0)
        target = getattr(state, "target_num", 0)
        if target > 0 and current < target and current > 0 and not self._stats_saved:
            # 延迟发送信号，确保UI状态已更新
            QTimer.singleShot(100, self.askSaveStats.emit)

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

        should_force_cleanup = target > 0 and current >= target and not self._completion_cleanup_done
        if should_force_cleanup:
            self._completion_cleanup_done = True
            self._schedule_cleanup()
            # 达到目标份数，自动保存统计
            if not self._stats_saved:
                self._stats_saved = True
                self._save_stats_if_available()

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

    def _save_stats_if_available(self) -> Optional[str]:
        """内部方法：保存统计数据（如果有）"""
        try:
            current_stats = stats_collector.get_current_stats()
            if current_stats and current_stats.total_submissions > 0:
                path = save_stats(current_stats)
                logging.info(f"统计数据已保存到：{path}")
                return path
        except Exception as exc:
            logging.error(f"保存统计数据失败：{exc}", exc_info=True)
        return None

    def save_stats_with_prompt(self) -> Optional[str]:
        """UI调用：保存统计数据（通常在用户确认后调用）"""
        return self._save_stats_if_available()
