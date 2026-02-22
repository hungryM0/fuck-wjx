"""运行控制器 - 连接 UI 与引擎的业务逻辑桥接层"""
from __future__ import annotations

import math
import logging
import copy
from urllib.parse import urlparse
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, Signal, QTimer, QCoreApplication

from wjx.core.task_context import TaskContext
from wjx.utils.app.config import DEFAULT_FILL_TEXT, STOP_FORCE_WAIT_SECONDS
from wjx.utils.system.cleanup_runner import CleanupRunner
from wjx.core.questions.config import QuestionEntry, configure_probabilities, validate_question_config
from wjx.core.engine import (
    _normalize_question_type_code,
    run,
)
from wjx.utils.io.load_save import RuntimeConfig, load_config, save_config
from wjx.network.proxy import (
    get_effective_proxy_api_url,
    is_custom_proxy_api_active,
    set_proxy_occupy_minute_by_answer_duration,
)
from wjx.utils.system.registry_manager import RegistryManager
from wjx.utils.event_bus import (
    bus as _event_bus,
    EVENT_TASK_STARTED,
    EVENT_TASK_STOPPED,
)


def _is_wjx_domain(url_value: str) -> bool:
    """接受问卷星域名：wjx.top、wjx.cn、wjx.com 及其子域名。"""
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
    # 支持 wjx.top、wjx.cn、wjx.com 及其子域名
    allowed_domains = ["wjx.top", "wjx.cn", "wjx.com"]
    for domain in allowed_domains:
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


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
        on_ip_counter: Optional[Callable[[int, int, bool], None]] = None,
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
        self.task_ctx: Optional[TaskContext] = None  # 任务上下文，由 RunController 在 start_run 时设置
        self._pause_event = threading.Event()
        self._pause_reason = ""
        self._cleanup_runner = cleanup_runner  # 用于异步清理浏览器

    def _post_to_ui_thread(self, callback: Callable[[], None]) -> None:
        """提供 UI 线程派发钩子，供引擎辅助逻辑调用。"""
        try:
            self._dispatcher(callback)
        except Exception:
            logging.debug("UI 派发失败，尝试直接执行回调", exc_info=True)
            try:
                callback()
            except Exception:
                logging.debug("UI 派发失败且回调直接执行失败", exc_info=True)

    def _post_to_ui_thread_async(self, callback: Callable[[], None]) -> None:
        """Fire-and-forget UI dispatch to avoid blocking worker threads."""
        try:
            self._async_dispatcher(callback)
        except Exception:
            logging.debug("异步 UI 派发失败，尝试直接执行回调", exc_info=True)
            try:
                callback()
            except Exception:
                logging.debug("异步 UI 派发失败且回调直接执行失败", exc_info=True)

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
                logging.warning("获取卡密失败，返回空值", exc_info=True)
                return None
        return None

    def cleanup_browsers(self) -> None:
        """异步清理所有浏览器实例，立即返回不阻塞 GUI 线程

        这是兜底清理函数，会强制终止所有残留的浏览器进程。
        即使工作线程已经提交了清理任务，这里也会再次确保清理干净。

        优化策略：
        1. 立即刷新批量清理队列（不等待去抖延迟）
        2. 使用批量 taskkill 清理残留 PID
        3. 不再尝试调用 playwright.stop()（避免线程安全问题）
        """
        drivers = list(self.active_drivers or [])
        self.active_drivers.clear()
        pids_to_wait: Set[int] = set(self._launched_browser_pids or set())
        self._launched_browser_pids.clear()

        # 收集所有需要清理的 PID
        for driver in drivers:
            try:
                pid_single = getattr(driver, "browser_pid", None)
                if pid_single:
                    pids_to_wait.add(int(pid_single))
                pid_set = getattr(driver, "browser_pids", None)
                if pid_set:
                    pids_to_wait.update(int(p) for p in pid_set)
            except Exception:
                logging.debug("收集浏览器 PID 失败，跳过当前 driver", exc_info=True)

        # 【优化 1】异步提交残留 PID 到批量清理队列（立即返回）
        if pids_to_wait and self._cleanup_runner:
            try:
                self._cleanup_runner.submit_pid_cleanup(pids_to_wait)
                logging.debug(f"[兜底清理] 已提交 {len(pids_to_wait)} 个残留 PID 到批量清理队列")
            except Exception:
                logging.debug("提交残留 PID 失败", exc_info=True)

        # 【优化 2】立即触发批量清理（异步执行，不阻塞）
        if self._cleanup_runner:
            try:
                self._cleanup_runner.flush_pending_pids()
                logging.debug("[兜底清理] 已触发批量清理（异步）")
            except Exception:
                logging.debug("触发批量清理失败", exc_info=True)



class RunController(QObject):
    surveyParsed = Signal(list, str)
    surveyParseFailed = Signal(str)
    runStateChanged = Signal(bool)
    runFailed = Signal(str)
    statusUpdated = Signal(str, int, int)
    pauseStateChanged = Signal(bool, str)
    cleanupFinished = Signal()
    _uiCallbackQueued = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = RuntimeConfig()
        self.questions_info: List[Dict[str, Any]] = []
        self.question_entries: List[QuestionEntry] = []
        self.survey_title = ""
        self.stop_event = threading.Event()
        self.worker_threads: List[threading.Thread] = []
        # 当前任务上下文（每次 start_run 时重新构造）
        self._task_ctx: Optional[TaskContext] = None
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
        self.on_ip_counter: Optional[Callable[[int, int, bool], None]] = None
        self.card_code_provider: Optional[Callable[[], Optional[str]]] = None
        self._completion_cleanup_done = False
        self._cleanup_scheduled = False
        self._stopped_by_stop_run = False
        self._starting = False
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
                logging.debug("无 QCoreApplication 时执行回调失败", exc_info=True)
            return
        if threading.current_thread() is threading.main_thread():
            try:
                callback()
            except Exception:
                logging.debug("主线程直接执行回调失败", exc_info=True)
            return
        try:
            self._uiCallbackQueued.emit(callback)
        except Exception:
            logging.warning("UI 回调入队失败，尝试直接执行", exc_info=True)
            try:
                callback()
            except Exception:
                logging.debug("UI 回调入队失败且直接执行失败", exc_info=True)

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
                self.survey_title = title or ""
                self.surveyParsed.emit(info, title or "")
            except Exception as exc:
                friendly = str(exc) or "解析失败，请稍后重试"
                self.surveyParseFailed.emit(friendly)

        threading.Thread(target=_worker, daemon=True).start()

    def _parse_questions(self, url: str) -> Tuple[List[Dict[str, Any]], str]:
        from wjx.core.services.survey_service import parse_survey
        return parse_survey(url)

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
        """构建题目配置列表。优先按题号/题目文本精确复用旧配置，避免同题型串台。"""
        def _normalize_question_num(raw: Any) -> Optional[int]:
            try:
                if raw is None:
                    return None
                return int(raw)
            except Exception:
                return None

        def _normalize_title(raw: Any) -> str:
            try:
                text = str(raw or "").strip()
            except Exception:
                return ""
            if not text:
                return ""
            # 去掉所有空白，避免不同格式导致匹配失败
            return "".join(text.split())

        # 建立可复用配置映射（按题号、题目文本）
        existing_by_num: Dict[int, QuestionEntry] = {}
        existing_by_title: Dict[str, QuestionEntry] = {}
        if existing_entries:
            for entry in existing_entries:
                q_num = _normalize_question_num(getattr(entry, "question_num", None))
                if q_num is not None and q_num not in existing_by_num:
                    existing_by_num[q_num] = entry
                title_key = _normalize_title(getattr(entry, "question_title", None))
                if title_key and title_key not in existing_by_title:
                    existing_by_title[title_key] = entry
        
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
            
            parsed_title_key = _normalize_title(title_text)

            # 优先按题号匹配；题号可用时仍会校验题目标题，避免跨问卷误复用
            existing_config: Optional[QuestionEntry] = None
            parsed_question_num = _normalize_question_num(q.get("num"))
            if parsed_question_num is not None:
                candidate = existing_by_num.get(parsed_question_num)
                if candidate and candidate.question_type == q_type:
                    candidate_title_key = _normalize_title(getattr(candidate, "question_title", None))
                    if parsed_title_key and candidate_title_key and candidate_title_key != parsed_title_key:
                        candidate = None
                    if candidate is not None:
                        existing_config = candidate
            if existing_config is None:
                if parsed_title_key:
                    candidate = existing_by_title.get(parsed_title_key)
                    if candidate and candidate.question_type == q_type:
                        existing_config = candidate

            if existing_config:
                # 复用已配置的权重设置（深拷贝，避免多题共享同一对象）
                probabilities: Any = copy.deepcopy(existing_config.probabilities)
                distribution = existing_config.distribution_mode or "random"
                custom_weights = copy.deepcopy(existing_config.custom_weights)
                texts = copy.deepcopy(existing_config.texts)
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

        # 将回调派发到控制器所属线程（主线程）
        self._dispatch_to_ui_async(_run)
        if not done.wait(timeout=3):
            logging.warning("UI 调度超时，放弃等待以避免阻塞")
            return None
        return result_container.get("value")

    def _prepare_engine_state(self, config: RuntimeConfig, proxy_pool: List[str]) -> TaskContext:
        """构建本次任务的 TaskContext。"""
        fail_threshold = max(1, math.ceil(config.target / 4) + 1)
        config_title = str(getattr(config, "survey_title", "") or "")
        fallback_title = str(getattr(self, "survey_title", "") or "")
        survey_title = config_title or fallback_title

        # ── 构建 TaskContext 实例 ─────────────────────────────────────────
        ctx = TaskContext(
            url=config.url,
            survey_title=survey_title,
            target_num=config.target,
            num_threads=max(1, int(config.threads or 1)),
            browser_preference=list(getattr(config, "browser_preference", []) or []),
            fail_threshold=fail_threshold,
            cur_num=0,
            cur_fail=0,
            stop_event=self.stop_event,
            submit_interval_range_seconds=(int(config.submit_interval[0]), int(config.submit_interval[1])),
            answer_duration_range_seconds=(int(config.answer_duration[0]), int(config.answer_duration[1])),  # type: ignore[arg-type]
            timed_mode_enabled=config.timed_mode_enabled,
            timed_mode_refresh_interval=config.timed_mode_interval,
            random_proxy_ip_enabled=config.random_ip_enabled,
            proxy_ip_pool=list(proxy_pool) if config.random_ip_enabled else [],
            random_user_agent_enabled=config.random_ua_enabled,
            user_agent_pool_keys=list(config.random_ua_keys),
            user_agent_ratios=dict(getattr(config, "random_ua_ratios", {"wechat": 33, "mobile": 33, "pc": 34})),
            answer_rules=copy.deepcopy(getattr(config, "answer_rules", []) or []),
            stop_on_fail_enabled=config.fail_stop_enabled,
            pause_on_aliyun_captcha=bool(getattr(config, "pause_on_aliyun_captcha", True)),
        )

        return ctx

    def start_run(self, config: RuntimeConfig):  # noqa: C901
        import logging
        logging.info("收到启动请求")

        if self.running or self._starting:
            logging.warning("任务已在运行中，忽略重复启动请求")
            return

        if not getattr(config, "question_entries", None):
            logging.error("未配置任何题目，无法启动")
            self.runFailed.emit('未配置任何题目，无法开始执行（请先在"题目配置"页添加/配置题目）')
            return

        # 验证题目配置是否存在冲突
        logging.info("验证题目配置...")
        questions_info = getattr(config, "questions_info", None)
        validation_error = validate_question_config(config.question_entries, questions_info)
        if validation_error:
            logging.error(f"题目配置验证失败：{validation_error}")
            self.runFailed.emit(f"题目配置存在冲突，无法启动：\n\n{validation_error}")
            return

        logging.info(f"开始配置任务：目标{config.target}份，{config.threads}个线程")
        
        self.config = config
        self.question_entries = list(getattr(config, "question_entries", []) or [])
        if not self.questions_info and getattr(config, "questions_info", None):
            self.questions_info = list(getattr(config, "questions_info") or [])
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
        self._starting = True
        _ad = config.answer_duration or (0, 0)
        proxy_answer_duration: Tuple[int, int] = (0, 0) if config.timed_mode_enabled else (int(_ad[0]), int(_ad[1]))
        try:
            set_proxy_occupy_minute_by_answer_duration(proxy_answer_duration)
        except Exception:
            logging.debug("同步随机IP占用时长失败", exc_info=True)

        logging.info(f"配置题目概率分布（共{len(config.question_entries)}题）")
        # 构建本次任务的上下文（尚未有 proxy_pool，后面在 _start_workers_with_proxy_pool 中注入）
        # 这里先创建一个临时 ctx，供 configure_probabilities 写入题目配置
        _tmp_ctx = TaskContext()
        try:
            configure_probabilities(
                config.question_entries,
                ctx=_tmp_ctx,
                reliability_mode_enabled=getattr(config, "reliability_mode_enabled", True),
            )
        except Exception as exc:
            logging.error(f"配置题目失败：{exc}")
            self._starting = False
            self.runFailed.emit(str(exc))
            return

        # 保存题目元数据（用于统计展示时补充选项文本等信息）
        _tmp_ctx.questions_metadata = {}
        if hasattr(self, 'questions_info') and self.questions_info:
            for q_info in self.questions_info:
                q_num = q_info.get('num')
                if q_num:
                    _tmp_ctx.questions_metadata[q_num] = q_info
        # 把临时 ctx 的题目配置结果缓存到实例，等 _start_workers_with_proxy_pool 内合并到正式 ctx
        self._pending_question_ctx = _tmp_ctx

        if config.random_ip_enabled:
            # 检查是否已达随机IP上限
            if not is_custom_proxy_api_active():
                count = RegistryManager.read_submit_count()
                # 启动前做本地额度检查，避免在 GUI 线程同步请求默认额度 API
                limit = int(RegistryManager.read_quota_limit(0) or 0)
                if limit <= 0:
                    logging.warning("随机IP额度不可用，无法启动随机IP模式")
                    self._starting = False
                    self.runFailed.emit("随机IP额度不可用（本地未初始化且默认额度API不可用），请稍后重试或改用自定义代理接口")
                    return
                if count >= limit:
                    logging.warning(f"随机IP已达{limit}份上限，无法启动")
                    self._starting = False
                    self.runFailed.emit(f"随机IP已达{limit}份上限，请关闭随机IP开关或解锁大额IP后再试")
                    return
            threading.Thread(
                target=self._prefetch_proxies_and_start,
                args=(config,),
                daemon=True,
                name="ProxyPrefetch",
            ).start()
            return

        self._start_workers_with_proxy_pool(config, [])

    def _prefetch_proxies_and_start(self, config: RuntimeConfig) -> None:
        try:
            from wjx.core.services.proxy_service import prefetch_proxy_pool
            proxy_pool = prefetch_proxy_pool(
                expected_count=max(1, config.threads),
                proxy_api_url=config.random_proxy_api or get_effective_proxy_api_url(),
                stop_signal=self.stop_event,
            )
        except Exception as exc:
            err_text = str(exc)

            def _fail():
                self._starting = False
                self.runFailed.emit(err_text)

            self._dispatch_to_ui_async(_fail)
            return

        def _continue_start():
            # 若预取期间任务已被中断，则不再继续启动
            if self.stop_event.is_set():
                self._starting = False
                return
            self._start_workers_with_proxy_pool(config, proxy_pool)

        self._dispatch_to_ui_async(_continue_start)

    def _start_workers_with_proxy_pool(self, config: RuntimeConfig, proxy_pool: List[str]) -> None:
        # 构建并注入完整的 TaskContext
        ctx = self._prepare_engine_state(config, proxy_pool)
        # 将之前所配置的题目概率内容合并入正式 ctx
        pending = getattr(self, '_pending_question_ctx', None)
        if pending is not None:
            ctx.single_prob = pending.single_prob
            ctx.droplist_prob = pending.droplist_prob
            ctx.multiple_prob = pending.multiple_prob
            ctx.matrix_prob = pending.matrix_prob
            ctx.scale_prob = pending.scale_prob
            ctx.slider_targets = pending.slider_targets
            ctx.texts = pending.texts
            ctx.texts_prob = pending.texts_prob
            ctx.text_entry_types = pending.text_entry_types
            ctx.text_ai_flags = pending.text_ai_flags
            ctx.text_titles = pending.text_titles
            ctx.single_option_fill_texts = pending.single_option_fill_texts
            ctx.droplist_option_fill_texts = pending.droplist_option_fill_texts
            ctx.multiple_option_fill_texts = pending.multiple_option_fill_texts
            ctx.question_config_index_map = pending.question_config_index_map
            ctx.question_dimension_map = pending.question_dimension_map
            ctx.question_reverse_map = pending.question_reverse_map
            ctx.questions_metadata = pending.questions_metadata
            self._pending_question_ctx = None
        self._task_ctx = ctx
        # 将 TaskContext 传递给 adapter，供 runner.py 更新进度计数
        self.adapter.task_ctx = ctx

        self.running = True
        self._starting = False
        self.runStateChanged.emit(True)
        self._status_timer.start()

        _event_bus.emit(EVENT_TASK_STARTED, ctx=ctx)

        logging.info(f"创建{config.threads}个工作线程")
        threads: List[threading.Thread] = []
        for idx in range(config.threads):
            x = 50 + idx * 60
            y = 50 + idx * 60
            t = threading.Thread(
                target=run,
                args=(x, y, self.stop_event, self.adapter),
                kwargs={"ctx": ctx},
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
        """等待所有工作线程结束

        注意：这个方法在后台 Monitor 线程中运行，不会阻塞 GUI
        """
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
        _event_bus.emit(EVENT_TASK_STOPPED)
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
                logging.warning("执行浏览器清理任务失败", exc_info=True)
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
        if self._starting and not self.running:
            self.stop_event.set()
            self._starting = False
            return
        if not self.running:
            return
        self.stop_event.set()
        # 立即停止状态轮询定时器，减少关停期间的主线程开销
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
        # 做一次最终状态刷新
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
        ctx = self._task_ctx
        current = getattr(ctx, "cur_num", 0)
        target = getattr(ctx, "target_num", 0)
        fail = getattr(ctx, "cur_fail", 0)
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

    # -------------------- Persistence --------------------
    def load_saved_config(self, path: Optional[str] = None) -> RuntimeConfig:
        cfg = load_config(path)
        self.config = cfg
        self.question_entries = cfg.question_entries
        self.questions_info = list(getattr(cfg, "questions_info", None) or [])
        self.survey_title = str(getattr(cfg, "survey_title", "") or "")
        return cfg

    def save_current_config(self, path: Optional[str] = None) -> str:
        entries = getattr(self.config, "question_entries", None)
        if entries is None:
            entries = self.question_entries
        self.question_entries = list(entries or [])
        self.config.question_entries = self.question_entries
        return save_config(self.config, path)


