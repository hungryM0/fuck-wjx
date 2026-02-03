import logging
import random
import threading
import time
import traceback
from typing import Optional, Set

import wjx.core.state as state
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
    _is_fast_mode,
    _timed_mode_active,
    _trigger_target_reached_stop,
    _wait_if_paused,
)
from wjx.core.engine.submission import _is_device_quota_limit_page, _normalize_url_for_compare
from wjx.network.browser_driver import (
    BrowserDriver,
    ProxyConnectionError,
    TimeoutException,
    graceful_terminate_process_tree,
)
from wjx.network.random_ip import _mask_proxy_for_log, _proxy_is_responsive, handle_random_ip_submission
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


def run(window_x_pos, window_y_pos, stop_signal: threading.Event, gui_instance=None):

    fast_mode = _is_fast_mode()
    timed_mode_active = _timed_mode_active()
    try:
        timed_refresh_interval = float(state.timed_mode_refresh_interval or timed_mode.DEFAULT_REFRESH_INTERVAL)
    except Exception:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
    if timed_refresh_interval <= 0:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
    base_browser_preference = list(getattr(state, "browser_preference", []) or BROWSER_PREFERENCE)
    preferred_browsers = list(base_browser_preference)
    driver: Optional[BrowserDriver] = None
    proxy_address: Optional[str] = None  # 初始化代理地址变量，避免异常处理中未绑定错误

    # 获取浏览器实例信号量，限制同时运行的浏览器数量
    browser_sem = state._get_browser_semaphore(max(1, int(state.num_threads or 1)))
    sem_acquired = False

    logging.info(f"目标份数: {state.target_num}, 当前进度: {state.cur_num}/{state.target_num}")
    if timed_mode_active:
        logging.info("定时模式已启用")
    if state.random_proxy_ip_enabled:
        logging.info("随机IP已启用")
    if state.random_user_agent_enabled:
        logging.info("随机UA已启用")

    def _register_driver(instance: BrowserDriver) -> None:
        if gui_instance and hasattr(gui_instance, 'active_drivers'):
            gui_instance.active_drivers.append(instance)
            try:
                pids = set()
                pid_single = getattr(instance, "browser_pid", None)
                if pid_single:
                    pids.add(int(pid_single))
                pid_set = getattr(instance, "browser_pids", None)
                if pid_set:
                    pids.update(int(p) for p in pid_set)
                gui_instance._launched_browser_pids.update(pids)
            except Exception:
                pass

    def _unregister_driver(instance: BrowserDriver) -> None:
        if gui_instance and hasattr(gui_instance, 'active_drivers'):
            try:
                gui_instance.active_drivers.remove(instance)
            except ValueError:
                pass
            try:
                pids = set()
                pid_single = getattr(instance, "browser_pid", None)
                if pid_single:
                    pids.add(int(pid_single))
                pid_set = getattr(instance, "browser_pids", None)
                if pid_set:
                    pids.update(int(p) for p in pid_set)
                for pid in pids:
                    gui_instance._launched_browser_pids.discard(int(pid))
            except Exception:
                pass

    def _dispose_driver() -> None:
        nonlocal driver, sem_acquired
        if driver:
            # 收集浏览器进程 PID 用于强制清理
            pids_to_kill = set(getattr(driver, "browser_pids", set()))
            _unregister_driver(driver)
            try:
                driver.quit()
            except Exception:
                pass
            driver = None
            # 等待已知 PID 自行退出，避免 taskkill
            if pids_to_kill:
                try:
                    graceful_terminate_process_tree(pids_to_kill, wait_seconds=3.0)
                except Exception:
                    pass
        # 释放信号量
        if sem_acquired:
            try:
                browser_sem.release()
                sem_acquired = False
                logging.debug("已释放浏览器信号量")
            except Exception:
                pass

    while True:
        _wait_if_paused(gui_instance, stop_signal)
        if stop_signal.is_set():
            break
        with state.lock:
            if stop_signal.is_set() or (state.target_num > 0 and state.cur_num >= state.target_num):
                break

        if _full_simulation_active():
            if not _wait_for_next_full_simulation_slot(stop_signal):
                break
            logging.info("[Action Log] 时长控制时段管控中，等待编辑区释放...")
        if stop_signal.is_set():
            break
        _wait_if_paused(gui_instance, stop_signal)

        if driver is None:
            proxy_address = _select_proxy_for_session()
            if state.random_proxy_ip_enabled and not proxy_address:
                if _record_bad_proxy_and_maybe_pause(gui_instance):
                    continue
            if proxy_address:
                if not _proxy_is_responsive(proxy_address):
                    logging.warning(f"代理无响应：{_mask_proxy_for_log(proxy_address)}")
                    _discard_unresponsive_proxy(proxy_address)
                    if stop_signal.is_set():
                        break
                    # 避免代理源异常时进入高频死循环（频繁请求代理/健康检查会拖慢整机）
                    if state.random_proxy_ip_enabled:
                        if _record_bad_proxy_and_maybe_pause(gui_instance):
                            continue
                    stop_signal.wait(0.8)
                    continue
                else:
                    _reset_bad_proxy_streak()

            ua_value, _ = _select_user_agent_for_session()

            # 获取信号量，限制同时运行的浏览器实例数量
            if not sem_acquired:
                browser_sem.acquire()
                sem_acquired = True
                logging.debug("已获取浏览器信号量")

            try:
                driver, active_browser = create_playwright_driver(
                    headless=False,
                    prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                    proxy_address=proxy_address,
                    user_agent=ua_value,
                    window_position=(window_x_pos, window_y_pos),
                )
            except Exception as exc:
                # 创建浏览器失败时释放信号量
                if sem_acquired:
                    browser_sem.release()
                    sem_acquired = False
                    logging.debug("创建浏览器失败，已释放信号量")
                if stop_signal.is_set():
                    break
                logging.error(f"启动浏览器失败：{exc}")
                traceback.print_exc()
                if stop_signal.wait(1.0):
                    break
                continue

            preferred_browsers = [active_browser] + [b for b in base_browser_preference if b != active_browser]
            _register_driver(driver)
            driver.set_window_size(550, 650)

        driver_had_error = False
        try:
            if stop_signal.is_set():
                break
            if not state.url:
                logging.error("无法启动：问卷链接为空")
                driver_had_error = True
                break
            _wait_if_paused(gui_instance, stop_signal)
            if timed_mode_active:
                logging.info("[Action Log] 定时模式：开始刷新等待问卷开放")
                ready = timed_mode.wait_until_open(
                    driver,
                    state.url,
                    stop_signal,
                    refresh_interval=timed_refresh_interval,
                    logger=logging.info,
                )
                if not ready:
                    if not stop_signal.is_set():
                        stop_signal.set()
                    break
            else:
                driver.get(state.url)
                if stop_signal.is_set():
                    break
            if _is_device_quota_limit_page(driver):
                logging.warning("检测到“设备已达到最大填写次数”提示页，直接放弃当前浏览器实例并标记为成功。")
                should_handle_random_ip = False
                should_stop_after_quota = False
                trigger_target_stop = False
                force_stop = False
                with state.lock:
                    if state.target_num <= 0 or state.cur_num < state.target_num:
                        state.cur_num += 1
                        logging.info(
                            f"[OK/Quota] 已填写{state.cur_num}份 - 失败{state.cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                        )
                        should_handle_random_ip = state.random_proxy_ip_enabled
                        if state.target_num > 0 and state.cur_num >= state.target_num:
                            trigger_target_stop = True
                            force_stop = True
                            should_stop_after_quota = True
                    else:
                        force_stop = True
                        should_stop_after_quota = True
                if force_stop:
                    stop_signal.set()
                if trigger_target_stop:
                    _trigger_target_reached_stop(gui_instance, stop_signal)
                _dispose_driver()
                if should_handle_random_ip:
                    handle_random_ip_submission(gui_instance, stop_signal)
                if should_stop_after_quota:
                    break
                continue
            visited_urls: Set[str] = set()
            try:
                visited_urls.add(_normalize_url_for_compare(driver.current_url))
            except Exception:
                visited_urls.add(_normalize_url_for_compare(state.url))

            while True:
                if stop_signal.is_set():
                    break
                finished = brush(driver, stop_signal=stop_signal)
                if stop_signal.is_set() or not finished:
                    break

                # 简化判断逻辑：点击提交成功后，短暂等待让页面加载
                post_submit_wait = random.uniform(0.2, 0.6)
                if stop_signal.wait(post_submit_wait):
                    break

                # 检查是否触发阿里云验证
                aliyun_detected = False
                if not stop_signal.is_set():
                    try:
                        aliyun_detected = handle_aliyun_captcha(
                            driver,
                            timeout=2,
                            stop_signal=stop_signal,
                            raise_on_detect=False,
                        )
                    except Exception:
                        aliyun_detected = False

                if aliyun_detected:
                    driver_had_error = True
                    _handle_aliyun_captcha_detected(gui_instance, stop_signal)
                    break

                # 没有触发验证，直接标记为成功
                should_handle_random_ip = False
                trigger_target_stop = False
                should_break = False
                with state.lock:
                    if state.target_num <= 0 or state.cur_num < state.target_num:
                        state.cur_num += 1
                        logging.info(
                            f"[OK] 已填写{state.cur_num}份 - 失败{state.cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                        )
                        should_handle_random_ip = state.random_proxy_ip_enabled
                        if state.target_num > 0 and state.cur_num >= state.target_num:
                            trigger_target_stop = True
                    else:
                        should_break = True
                if should_break:
                    stop_signal.set()
                    break
                if trigger_target_stop:
                    stop_signal.set()
                    _trigger_target_reached_stop(gui_instance, stop_signal)
                grace_seconds = float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
                if grace_seconds > 0 and not stop_signal.is_set():
                    time.sleep(grace_seconds)
                _dispose_driver()
                if should_handle_random_ip:
                    handle_random_ip_submission(gui_instance, stop_signal)
                break
        except AliyunCaptchaBypassError:
            driver_had_error = True
            _handle_aliyun_captcha_detected(gui_instance, stop_signal)
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

            # 未检测到完成页时再等一会：
            # 1) 继续等待完成页跳转/文案出现
            # 2) 若仍未完成，检查是否出现阿里云智能验证；若出现则按既有流程触发全局停止
            completion_detected = False
            extra_wait_seconds = max(1.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 3.0)
            extra_poll = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
            extra_deadline = time.time() + extra_wait_seconds
            while time.time() < extra_deadline:
                if stop_signal.is_set():
                    break
                try:
                    current_url = driver.current_url
                except Exception:
                    current_url = ""
                if "complete" in str(current_url).lower():
                    completion_detected = True
                    break
                try:
                    if duration_control.is_survey_completion_page(driver):
                        completion_detected = True
                        break
                except Exception:
                    pass
                time.sleep(extra_poll)

            if not completion_detected and not stop_signal.is_set():
                aliyun_detected = False
                try:
                    aliyun_detected = handle_aliyun_captcha(
                        driver,
                        timeout=3,
                        stop_signal=stop_signal,
                        raise_on_detect=False,
                    )
                except Exception:
                    aliyun_detected = False
                if aliyun_detected:
                    driver_had_error = True
                    _handle_aliyun_captcha_detected(gui_instance, stop_signal)
                    break

            if not completion_detected and not stop_signal.is_set():
                try:
                    current_url = driver.current_url
                except Exception:
                    current_url = ""
                if "complete" in str(current_url).lower():
                    completion_detected = True
                else:
                    try:
                        completion_detected = bool(duration_control.is_survey_completion_page(driver))
                    except Exception:
                        completion_detected = False

            if completion_detected:
                driver_had_error = False
                should_handle_random_ip = False
                trigger_target_stop = False
                with state.lock:
                    if state.target_num <= 0 or state.cur_num < state.target_num:
                        state.cur_num += 1
                        logging.info(
                            f"[OK] 已填写{state.cur_num}份 - 失败{state.cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                        )
                        should_handle_random_ip = state.random_proxy_ip_enabled
                        if state.target_num > 0 and state.cur_num >= state.target_num:
                            trigger_target_stop = True
                    else:
                        stop_signal.set()
                if trigger_target_stop:
                    stop_signal.set()
                    _trigger_target_reached_stop(gui_instance, stop_signal)
                grace_seconds = float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
                if grace_seconds > 0 and not stop_signal.is_set():
                    time.sleep(grace_seconds)
                _dispose_driver()
                if should_handle_random_ip:
                    handle_random_ip_submission(gui_instance, stop_signal)
                continue

            driver_had_error = True
            if _handle_submission_failure(stop_signal):
                break
        except ProxyConnectionError as exc:
            driver_had_error = True
            if stop_signal.is_set():
                break
            logging.warning(f"代理隧道连接失败：{exc}")
            if proxy_address:
                _discard_unresponsive_proxy(proxy_address)
            if state.random_proxy_ip_enabled and proxy_address:
                if _record_bad_proxy_and_maybe_pause(gui_instance):
                    break
                stop_signal.wait(0.8)
                continue
            if _handle_submission_failure(stop_signal):
                break
        except EmptySurveySubmissionError:
            driver_had_error = True
            if stop_signal.is_set():
                break
            if _handle_submission_failure(stop_signal):
                break
        except Exception:
            driver_had_error = True
            if stop_signal.is_set():
                break
            traceback.print_exc()
            if _handle_submission_failure(stop_signal):
                break
        finally:
            if driver_had_error:
                _dispose_driver()

        if stop_signal.is_set():
            break
        if not _full_simulation_active():
            min_wait, max_wait = state.submit_interval_range_seconds
            if max_wait > 0:
                wait_seconds = min_wait if max_wait == min_wait else random.uniform(min_wait, max_wait)
                if stop_signal.wait(wait_seconds):
                    break

    _dispose_driver()
