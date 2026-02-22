"""引擎主循环 - 任务执行与线程调度"""
import random
import threading
import time
import traceback
from typing import Any, Optional, Set
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception

import wjx.modes.duration_control as duration_control
import wjx.modes.timed_mode as timed_mode
from wjx.core.ai.runtime import AIRuntimeError
from wjx.core.captcha.control import _handle_aliyun_captcha_detected
from wjx.core.captcha.handler import AliyunCaptchaBypassError, EmptySurveySubmissionError, handle_aliyun_captcha
from wjx.core.engine.answering import brush
from wjx.core.engine.driver_factory import create_playwright_driver
from wjx.core.engine.full_simulation import _full_simulation_active, _wait_for_next_full_simulation_slot
from wjx.core.engine.runtime_control import (
    _handle_submission_failure,
    _timed_mode_active,
    _trigger_target_reached_stop,
    _wait_if_paused,
)
from wjx.core.engine.submission import _is_device_quota_limit_page, _normalize_url_for_compare
from wjx.core.task_context import TaskContext
from wjx.network.browser import (
    BrowserDriver,
    ProxyConnectionError,
    TimeoutException,
)
from wjx.network.proxy import _mask_proxy_for_log, _proxy_is_responsive, handle_random_ip_submission
from wjx.network.session_policy import (
    _discard_unresponsive_proxy,
    _record_bad_proxy_and_maybe_pause,
    _reset_bad_proxy_streak,
    _select_proxy_for_session,
    _select_user_agent_for_session,
)
from wjx.utils.app.config import (
    BROWSER_PREFERENCE,
    POST_SUBMIT_CLOSE_GRACE_SECONDS,
    POST_SUBMIT_URL_MAX_WAIT,
    POST_SUBMIT_URL_POLL_INTERVAL,
)


def _submission_blocked_by_security_check(driver: BrowserDriver) -> bool:
    """检测提交后是否出现"需要安全校验/请重新提交"等拦截提示。"""

    script = r"""
        return (() => {
            const text = (document.body?.innerText || '').replace(/\s+/g, '');
            if (!text) return false;
            const markers = [
                '需要安全校验',
                '请重新提交',
                '安全校验',
                '安全验证',
                '智能验证',
                '人机验证',
                '滑动验证',
            ];
            return markers.some(marker => text.includes(marker));
        })();
    """
    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 浏览器生命周期管理（Phase 5 前临时封装）
# ---------------------------------------------------------------------------

class _BrowserSession:
    """封装单次浏览器会话的创建、注册、销毁逻辑。"""

    def __init__(self, ctx: TaskContext, gui_instance: Any):
        self.ctx = ctx
        self.gui_instance = gui_instance
        self.driver: Optional[BrowserDriver] = None
        self.proxy_address: Optional[str] = None
        self.sem_acquired = False
        self._browser_sem = ctx.get_browser_semaphore(max(1, int(ctx.num_threads or 1)))

    def _register_driver(self, instance: BrowserDriver) -> None:
        if self.gui_instance and hasattr(self.gui_instance, 'active_drivers'):
            self.gui_instance.active_drivers.append(instance)
            try:
                pids = set()
                pid_single = getattr(instance, "browser_pid", None)
                if pid_single:
                    pids.add(int(pid_single))
                pid_set = getattr(instance, "browser_pids", None)
                if pid_set:
                    pids.update(int(p) for p in pid_set)
                self.gui_instance._launched_browser_pids.update(pids)
            except Exception as exc:
                log_suppressed_exception("_BrowserSession._register_driver collect pids", exc, level=logging.WARNING)

    def _unregister_driver(self, instance: BrowserDriver) -> None:
        if self.gui_instance and hasattr(self.gui_instance, 'active_drivers'):
            try:
                self.gui_instance.active_drivers.remove(instance)
            except ValueError as exc:
                log_suppressed_exception("_BrowserSession._unregister_driver remove", exc, level=logging.WARNING)
            try:
                pids = set()
                pid_single = getattr(instance, "browser_pid", None)
                if pid_single:
                    pids.add(int(pid_single))
                pid_set = getattr(instance, "browser_pids", None)
                if pid_set:
                    pids.update(int(p) for p in pid_set)
                for pid in pids:
                    self.gui_instance._launched_browser_pids.discard(int(pid))
            except Exception as exc:
                log_suppressed_exception("_BrowserSession._unregister_driver cleanup pids", exc, level=logging.WARNING)

    def dispose(self) -> None:
        """释放浏览器资源，提交 PID 到批量清理队列。"""
        if not self.driver:
            if self.sem_acquired:
                try:
                    self._browser_sem.release()
                    self.sem_acquired = False
                    logging.debug("已释放浏览器信号量（无浏览器实例）")
                except Exception as exc:
                    log_suppressed_exception("_BrowserSession.dispose release semaphore (no driver)", exc, level=logging.WARNING)
            return

        if not self.driver.mark_cleanup_done():
            logging.debug("浏览器实例已被其他线程清理，跳过")
            self.driver = None
            if self.sem_acquired:
                self._browser_sem.release()
                self.sem_acquired = False
            return

        pids_to_kill = set(getattr(self.driver, "browser_pids", set()))
        playwright_instance = self.driver._playwright
        self._unregister_driver(self.driver)
        self.driver = None

        cleanup_runner = getattr(self.gui_instance, "_cleanup_runner", None) if self.gui_instance else None
        if cleanup_runner and pids_to_kill:
            try:
                cleanup_runner.submit_pid_cleanup(pids_to_kill)
                logging.debug(f"已提交 {len(pids_to_kill)} 个 PID 到批量清理队列")
            except Exception as exc:
                log_suppressed_exception("_BrowserSession.dispose submit_pid_cleanup", exc, level=logging.WARNING)

        try:
            playwright_instance.stop()
            logging.debug("已停止 playwright 实例")
        except Exception as exc:
            log_suppressed_exception("_BrowserSession.dispose playwright.stop", exc, level=logging.WARNING)

        if self.sem_acquired:
            try:
                self._browser_sem.release()
                self.sem_acquired = False
                logging.debug("已释放浏览器信号量")
            except Exception as exc:
                log_suppressed_exception("_BrowserSession.dispose release semaphore", exc, level=logging.WARNING)

    def create_browser(
        self,
        preferred_browsers: list,
        window_x_pos: int,
        window_y_pos: int,
    ) -> Optional[str]:
        """创建一个新的浏览器实例。返回实际使用的浏览器名称，失败返回 None。"""
        self.proxy_address = _select_proxy_for_session(self.ctx)

        if self.ctx.random_proxy_ip_enabled and not self.proxy_address:
            if _record_bad_proxy_and_maybe_pause(self.ctx, self.gui_instance):
                return None  # 触发暂停

        if self.proxy_address:
            if not _proxy_is_responsive(self.proxy_address):
                logging.warning(f"代理无响应：{_mask_proxy_for_log(self.proxy_address)}")
                _discard_unresponsive_proxy(self.ctx, self.proxy_address)
                if self.ctx.random_proxy_ip_enabled:
                    _record_bad_proxy_and_maybe_pause(self.ctx, self.gui_instance)
                return None
            else:
                _reset_bad_proxy_streak(self.ctx)

        ua_value, _ = _select_user_agent_for_session(self.ctx)

        if not self.sem_acquired:
            self._browser_sem.acquire()
            self.sem_acquired = True
            logging.debug("已获取浏览器信号量")

        try:
            self.driver, active_browser = create_playwright_driver(
                headless=False,
                prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                proxy_address=self.proxy_address,
                user_agent=ua_value,
                window_position=(window_x_pos, window_y_pos),
            )
        except Exception:
            if self.sem_acquired:
                self._browser_sem.release()
                self.sem_acquired = False
                logging.debug("创建浏览器失败，已释放信号量")
            raise

        self._register_driver(self.driver)
        self.driver.set_window_size(550, 650)
        return active_browser


# ---------------------------------------------------------------------------
# 提交后验证逻辑
# ---------------------------------------------------------------------------

def _wait_for_completion_page(
    driver: BrowserDriver,
    stop_signal: threading.Event,
    max_wait_seconds: float,
    poll_interval: float,
) -> bool:
    """轮询等待完成页出现，返回 True 表示检测到完成页。"""
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        if stop_signal.is_set():
            return False
        try:
            current_url = driver.current_url
        except Exception:
            current_url = ""
        if "complete" in str(current_url).lower():
            return True
        try:
            if duration_control.is_survey_completion_page(driver):
                return True
        except Exception as exc:
            log_suppressed_exception("runner._wait_for_completion_page", exc, level=logging.WARNING)
        time.sleep(poll_interval)
    return False


def _check_captcha_after_submit(
    driver: BrowserDriver,
    ctx: TaskContext,
    stop_signal: threading.Event,
    gui_instance: Any,
) -> bool:
    """提交后检测阿里云验证码。返回 True 表示命中验证码。"""
    try:
        handle_aliyun_captcha(
            driver,
            timeout=3,
            stop_signal=stop_signal,
            raise_on_detect=True,
        )
        return False
    except AliyunCaptchaBypassError:
        logging.warning("提交后检测到阿里云智能验证，触发全局暂停")
        _handle_submission_failure(ctx, stop_signal)
        _handle_aliyun_captcha_detected(ctx, gui_instance, stop_signal)
        return True
    except Exception as exc:
        logging.warning(f"验证码检测过程出现异常：{exc}")
        return False


def _record_successful_submission(
    ctx: TaskContext,
    stop_signal: threading.Event,
    gui_instance: Any,
) -> bool:
    """记录一次成功提交。返回 True 表示应该停止（已达目标）。"""
    should_handle_random_ip = False
    trigger_target_stop = False
    should_break = False

    with ctx.lock:
        if ctx.target_num <= 0 or ctx.cur_num < ctx.target_num:
            ctx.cur_num += 1
            logging.info(
                f"[OK] 已填写{ctx.cur_num}份 - 失败{ctx.cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
            )
            should_handle_random_ip = ctx.random_proxy_ip_enabled
            if ctx.target_num > 0 and ctx.cur_num >= ctx.target_num:
                trigger_target_stop = True
        else:
            should_break = True

    if should_break:
        stop_signal.set()
    if trigger_target_stop:
        stop_signal.set()
        _trigger_target_reached_stop(ctx, stop_signal, gui_instance)
    if should_handle_random_ip:
        handle_random_ip_submission(gui_instance, stop_signal)

    return should_break or trigger_target_stop


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------

def run(
    window_x_pos: int,
    window_y_pos: int,
    stop_signal: threading.Event,
    gui_instance: Any = None,
    ctx: Optional[TaskContext] = None,
):
    """引擎主循环 - 创建浏览器、填写问卷、处理结果。

    Args:
        window_x_pos: 浏览器窗口 X 位置
        window_y_pos: 浏览器窗口 Y 位置
        stop_signal: 停止信号
        gui_instance: EngineGuiAdapter 实例
        ctx: 任务上下文（传入后使用 ctx 配置，不再依赖全局 state）
    """
    # 如果没传 ctx，从 gui_instance 获取
    if ctx is None and gui_instance and hasattr(gui_instance, 'task_ctx'):
        ctx = gui_instance.task_ctx
    if ctx is None:
        raise ValueError("run() 必须传入 TaskContext，全局 state 兼容层已移除")

    timed_mode_on = _timed_mode_active(ctx)
    try:
        timed_refresh_interval = float(ctx.timed_mode_refresh_interval or timed_mode.DEFAULT_REFRESH_INTERVAL)
    except Exception:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
    if timed_refresh_interval <= 0:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL

    base_browser_preference = list(ctx.browser_preference or BROWSER_PREFERENCE)
    preferred_browsers = list(base_browser_preference)

    session = _BrowserSession(ctx, gui_instance)

    logging.debug(f"目标份数: {ctx.target_num}, 当前进度: {ctx.cur_num}/{ctx.target_num}")
    if timed_mode_on:
        logging.debug("定时模式已启用")
    if ctx.random_proxy_ip_enabled:
        logging.debug("随机IP已启用")
    if ctx.random_user_agent_enabled:
        logging.debug("随机UA已启用")

    while True:
        _wait_if_paused(gui_instance, stop_signal)
        if stop_signal.is_set():
            break
        with ctx.lock:
            if stop_signal.is_set() or (ctx.target_num > 0 and ctx.cur_num >= ctx.target_num):
                break

        if _full_simulation_active(ctx):
            if not _wait_for_next_full_simulation_slot(stop_signal):
                break
            logging.debug("[Action Log] 时长控制时段管控中，等待编辑区释放...")
        if stop_signal.is_set():
            break
        _wait_if_paused(gui_instance, stop_signal)

        # ── 1. 准备浏览器 ────────────────────────────────────────
        if session.driver is None:
            try:
                active_browser = session.create_browser(
                    preferred_browsers, window_x_pos, window_y_pos,
                )
            except Exception as exc:
                if stop_signal.is_set():
                    break
                logging.error(f"启动浏览器失败：{exc}")
                traceback.print_exc()
                if stop_signal.wait(1.0):
                    break
                continue

            if active_browser is None:
                # create_browser 返回 None 意味着代理不可用或触发暂停
                if stop_signal.is_set():
                    break
                stop_signal.wait(0.8)
                continue

            preferred_browsers = [active_browser] + [b for b in base_browser_preference if b != active_browser]

        driver_had_error = False
        try:
            if stop_signal.is_set():
                break
            if not ctx.url:
                logging.error("无法启动：问卷链接为空")
                driver_had_error = True
                break
            _wait_if_paused(gui_instance, stop_signal)

            # ── 2. 导航到问卷页面 ────────────────────────────────
            if timed_mode_on:
                logging.debug("[Action Log] 定时模式：开始刷新等待问卷开放")
                ready = timed_mode.wait_until_open(
                    session.driver,
                    ctx.url,
                    stop_signal,
                    refresh_interval=timed_refresh_interval,
                    logger=logging.info,
                )
                if not ready:
                    if not stop_signal.is_set():
                        stop_signal.set()
                    break
            else:
                session.driver.get(ctx.url)
                if stop_signal.is_set():
                    break

            # ── 3. 设备配额限制检查 ──────────────────────────────
            if _is_device_quota_limit_page(session.driver):
                logging.warning('检测到设备已达到最大填写次数提示页，直接放弃当前浏览器实例并标记为成功。')
                stopped = _record_successful_submission(ctx, stop_signal, gui_instance)
                session.dispose()
                if stopped:
                    break
                continue

            visited_urls: Set[str] = set()
            try:
                visited_urls.add(_normalize_url_for_compare(session.driver.current_url))
            except Exception:
                visited_urls.add(_normalize_url_for_compare(ctx.url))

            # ── 4. 答题 + 提交 ───────────────────────────────────
            while True:
                if stop_signal.is_set():
                    break
                finished = brush(session.driver, ctx=ctx, stop_signal=stop_signal)
                if stop_signal.is_set() or not finished:
                    break

                # 提交后短暂等待
                post_submit_wait = random.uniform(0.2, 0.6)
                if stop_signal.wait(post_submit_wait):
                    break

                # ── 5. 验证提交结果 ──────────────────────────────
                # 5a. 立即检测阿里云验证码
                if not stop_signal.is_set():
                    if _check_captcha_after_submit(session.driver, ctx, stop_signal, gui_instance):
                        driver_had_error = True
                        break

                # 5b. 安全校验文案检测
                if not stop_signal.is_set() and _submission_blocked_by_security_check(session.driver):
                    driver_had_error = True
                    logging.warning("提交后检测到安全校验拦截提示，触发全局暂停")
                    _handle_submission_failure(ctx, stop_signal)
                    _handle_aliyun_captcha_detected(ctx, gui_instance, stop_signal)
                    break

                # 5c. 等待完成页出现
                wait_seconds = max(3.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 6.0)
                poll_interval = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
                completion_detected = _wait_for_completion_page(
                    session.driver, stop_signal, wait_seconds, poll_interval,
                )

                # 等待期间检查安全校验
                if not completion_detected and not stop_signal.is_set():
                    if _submission_blocked_by_security_check(session.driver):
                        driver_had_error = True
                        logging.warning("提交后等待完成页期间命中安全校验提示，触发全局暂停")
                        _handle_submission_failure(ctx, stop_signal)
                        _handle_aliyun_captcha_detected(ctx, gui_instance, stop_signal)
                        break

                if driver_had_error or stop_signal.is_set():
                    break

                # 5d. 未检测到完成页时再次检测验证码
                if not completion_detected:
                    if _check_captcha_after_submit(session.driver, ctx, stop_signal, gui_instance):
                        driver_had_error = True
                        break

                if not completion_detected:
                    raise TimeoutException("提交后未检测到完成页")

                # ── 6. 记录成功 ──────────────────────────────────
                grace_seconds = float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
                if grace_seconds > 0 and not stop_signal.is_set():
                    time.sleep(grace_seconds)
                session.dispose()
                stopped = _record_successful_submission(ctx, stop_signal, gui_instance)
                if stopped:
                    pass  # 会在外层 while 检查 stop_signal 后 break
                break

        except AliyunCaptchaBypassError:
            driver_had_error = True
            _handle_submission_failure(ctx, stop_signal)
            _handle_aliyun_captcha_detected(ctx, gui_instance, stop_signal)
            break
        except AIRuntimeError as exc:
            driver_had_error = True
            logging.error("AI 填空失败，已停止任务：%s", exc, exc_info=True)
            if stop_signal and not stop_signal.is_set():
                stop_signal.set()
            break
        except TimeoutException as exc:
            if stop_signal.is_set():
                break
            logging.debug("提交未完成（未检测到完成页）：%s", exc)

            # 额外等待完成页
            extra_wait_seconds = max(1.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 3.0)
            extra_poll = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
            completion_detected = _wait_for_completion_page(
                session.driver, stop_signal, extra_wait_seconds, extra_poll,
            )

            if not completion_detected and not stop_signal.is_set():
                if _check_captcha_after_submit(session.driver, ctx, stop_signal, gui_instance):
                    driver_had_error = True
                    break

            if not completion_detected and not stop_signal.is_set():
                try:
                    current_url = session.driver.current_url
                except Exception:
                    current_url = ""
                if "complete" in str(current_url).lower():
                    completion_detected = True
                else:
                    try:
                        completion_detected = bool(duration_control.is_survey_completion_page(session.driver))
                    except Exception:
                        completion_detected = False

            if completion_detected:
                driver_had_error = False
                grace_seconds = float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
                if grace_seconds > 0 and not stop_signal.is_set():
                    time.sleep(grace_seconds)
                session.dispose()
                stopped = _record_successful_submission(ctx, stop_signal, gui_instance)
                if stopped:
                    continue  # 外层 while 会 break
                continue

            driver_had_error = True
            if _handle_submission_failure(ctx, stop_signal):
                break

        except ProxyConnectionError as exc:
            driver_had_error = True
            if stop_signal.is_set():
                break
            logging.warning(f"代理隧道连接失败：{exc}")
            if session.proxy_address:
                _discard_unresponsive_proxy(ctx, session.proxy_address)
            if ctx.random_proxy_ip_enabled and session.proxy_address:
                if _record_bad_proxy_and_maybe_pause(ctx, gui_instance):
                    break
                stop_signal.wait(0.8)
                continue
            if _handle_submission_failure(ctx, stop_signal):
                break
        except EmptySurveySubmissionError:
            driver_had_error = True
            if stop_signal.is_set():
                break
            if _handle_submission_failure(ctx, stop_signal):
                break
        except Exception:
            driver_had_error = True
            if stop_signal.is_set():
                break
            traceback.print_exc()
            if _handle_submission_failure(ctx, stop_signal):
                break
        finally:
            if driver_had_error:
                session.dispose()

        if stop_signal.is_set():
            break
        if not _full_simulation_active(ctx):
            min_wait, max_wait = ctx.submit_interval_range_seconds
            if max_wait > 0:
                wait_seconds = min_wait if max_wait == min_wait else random.uniform(min_wait, max_wait)
                if stop_signal.wait(wait_seconds):
                    break

    session.dispose()
