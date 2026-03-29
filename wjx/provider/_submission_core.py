"""提交流程处理 - 问卷提交与结果验证"""
import logging
import threading
import time
from typing import Optional
from urllib.parse import quote, urljoin, urlparse

import httpx

from software.core.engine.runtime_control import _is_headless_mode, _sleep_with_stop
from software.core.questions.utils import extract_text_from_element as _extract_text_from_element
from software.core.task import TaskContext
from software.network.browser import By, BrowserDriver, NoSuchElementException, TimeoutException
import software.network.http as http_client
from software.network.proxy import (
    PROXY_SOURCE_CUSTOM,
    get_proxy_required_ttl_seconds,
    get_proxy_source,
    proxy_lease_has_sufficient_ttl,
)
from software.network.proxy.pool import coerce_proxy_lease, mask_proxy_for_log, normalize_proxy_address
from software.network.proxy.api import fetch_proxy_batch
from software.app.config import (
    HEADLESS_SUBMIT_CLICK_SETTLE_DELAY,
    HEADLESS_SUBMIT_INITIAL_DELAY,
    SUBMIT_CLICK_SETTLE_DELAY,
    SUBMIT_INITIAL_DELAY,
)
from software.app.config import get_proxy_auth
from software.logging.log_utils import log_suppressed_exception

_HEADLESS_SUBMIT_PROXY_RETRY_LIMIT = 1
_HEADLESS_SUBMIT_RETRYABLE_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
)


class EmptySurveySubmissionError(RuntimeError):
    """检测到问卷未添加题目导致无法提交时抛出，用于关闭当前实例并继续下一份。"""


def _click_submit_button(driver: BrowserDriver, max_wait: float = 10.0) -> bool:
    """点击“提交”按钮（简单版）。"""

    submit_keywords = ("提交", "完成", "交卷", "确认提交", "确认")

    locator_candidates = [
        (By.CSS_SELECTOR, "#ctlNext"),
        (By.CSS_SELECTOR, "#submit_button"),
        (By.CSS_SELECTOR, "#SubmitBtnGroup .submitbtn"),
        (By.CSS_SELECTOR, ".submitbtn.mainBgColor"),
        (By.CSS_SELECTOR, "#SM_BTN_1"),
        (By.CSS_SELECTOR, "#divSubmit"),
        (By.CSS_SELECTOR, ".btn-submit"),
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.XPATH, "//a[normalize-space(.)='提交' or normalize-space(.)='完成' or normalize-space(.)='交卷' or normalize-space(.)='确认提交' or normalize-space(.)='确认']"),
        (By.XPATH, "//button[normalize-space(.)='提交' or normalize-space(.)='完成' or normalize-space(.)='交卷' or normalize-space(.)='确认提交' or normalize-space(.)='确认']"),
    ]

    def _text_looks_like_submit(element) -> bool:
        text = (_extract_text_from_element(element) or "").strip()
        if not text:
            text = (element.get_attribute("value") or "").strip()
        if not text:
            return False
        return any(k in text for k in submit_keywords)

    deadline = time.time() + max(0.0, float(max_wait or 0.0))
    while True:
        for by, value in locator_candidates:
            try:
                elements = driver.find_elements(by, value)
            except Exception:
                continue
            for element in elements:
                try:
                    if not element.is_displayed():
                        continue
                except Exception:
                    continue

                if by == By.CSS_SELECTOR and value in ("button[type='submit']",):
                    if not _text_looks_like_submit(element):
                        continue

                try:
                    element.click()
                    logging.info("成功点击提交按钮：%s=%s", by, value)
                    return True
                except Exception:
                    pass
                try:
                    driver.execute_script("arguments[0].click();", element)
                    logging.info("成功通过JS点击提交按钮：%s=%s", by, value)
                    return True
                except Exception:
                    continue

        if time.time() >= deadline:
            break
        time.sleep(0.2)

    # 问卷星常见兜底：直接触发页面注册的提交入口
    try:
        force_triggered = bool(
            driver.execute_script(
                r"""
                return (() => {
                    const clickVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = el.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) return false;
                        el.click();
                        return true;
                    };

                    const ctlNext = document.querySelector('#ctlNext');
                    if (clickVisible(ctlNext)) return true;

                    const submitBtn = document.querySelector('#submit_button');
                    if (clickVisible(submitBtn)) return true;

                    const submitLike = Array.from(document.querySelectorAll('div,a,button,input,span')).find((el) => {
                        const text = (el.innerText || el.textContent || el.value || '').replace(/\s+/g, '');
                        return text === '提交' || text === '完成' || text === '交卷' || text === '确认提交';
                    });
                    if (clickVisible(submitLike)) return true;

                    if (typeof submit_button_click === 'function') {
                        submit_button_click();
                        return true;
                    }

                    return false;
                })();
                """
            )
        )
        if force_triggered:
            logging.info("提交按钮常规选择器未命中，已触发问卷星提交兜底入口")
            return True
    except Exception as exc:
        log_suppressed_exception("submission._click_submit_button force trigger", exc, level=logging.WARNING)

    return False


def _click_submit_confirm_button(driver: BrowserDriver, settle_delay: float = 0.0) -> None:
    """点击可能出现的提交确认按钮（有则点，无则忽略）。"""
    try:
        confirm_candidates = [
            (By.XPATH, '//*[@id="layui-layer1"]/div[3]/a'),
            (By.CSS_SELECTOR, "#layui-layer1 .layui-layer-btn a"),
            (By.CSS_SELECTOR, ".layui-layer .layui-layer-btn a.layui-layer-btn0"),
        ]
        for by, value in confirm_candidates:
            try:
                el = driver.find_element(by, value)
            except Exception:
                el = None
            if not el:
                continue
            try:
                if not el.is_displayed():
                    continue
            except Exception:
                continue
            try:
                el.click()
                if settle_delay > 0:
                    time.sleep(settle_delay)
                break
            except Exception:
                continue
    except Exception as exc:
        log_suppressed_exception("submission._click_submit_confirm_button", exc)


def _parse_submit_response(raw_text: str) -> tuple[str, str]:
    """解析问卷星提交通用响应格式：`业务码〒内容`。"""
    text = str(raw_text or "").strip()
    if "〒" not in text:
        return text, ""
    code, payload = text.split("〒", 1)
    return code.strip(), payload.strip()


def _resolve_completion_url(submit_url: str, payload: str) -> str:
    """把提交响应中的完成页路径转为可访问 URL。"""
    value = str(payload or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return urljoin(submit_url, value)
    return urljoin(submit_url, f"/{value}")


def _sanitize_request_headers(headers: dict) -> dict:
    """过滤不适合原样透传给 httpx 的头字段。"""
    if not isinstance(headers, dict):
        return {}
    blocked = {"host", "content-length", "connection", "accept-encoding"}
    cleaned = {}
    for key, value in headers.items():
        lower_key = str(key or "").strip().lower()
        if not lower_key or lower_key in blocked:
            continue
        cleaned[lower_key] = value
    return cleaned


def _collect_page_cookies(driver: BrowserDriver, submit_url: str) -> dict:
    """把当前浏览器上下文里的 cookie 迁移给 httpx。"""
    page = getattr(driver, "page", None)
    if page is None:
        return {}
    try:
        cookies = page.context.cookies([submit_url])
    except Exception as exc:
        log_suppressed_exception("submission._collect_page_cookies cookies()", exc, level=logging.WARNING)
        return {}

    cookie_map = {}
    for item in cookies or []:
        name = (item or {}).get("name")
        value = (item or {}).get("value")
        if name:
            cookie_map[str(name)] = str(value or "")
    return cookie_map


def _build_submit_proxy_url(proxy_address: Optional[str]) -> Optional[str]:
    """构造给 httpx 使用的代理 URL，必要时补全认证信息。"""
    normalized = normalize_proxy_address(proxy_address)
    if not normalized:
        return None

    try:
        parsed = urlparse(normalized)
    except Exception:
        return normalized

    scheme = str(parsed.scheme or "http").lower()
    host = str(parsed.hostname or "").strip()
    if not host:
        return normalized
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    host_port = f"{host}:{parsed.port}" if parsed.port else host

    username = parsed.username
    password = parsed.password
    if (
        not username
        and get_proxy_source() == PROXY_SOURCE_CUSTOM
    ):
        try:
            auth = get_proxy_auth()
            username, password = auth.split(":", 1)
        except Exception:
            username = None
            password = None

    if username:
        user = quote(str(username), safe="")
        pwd = quote("" if password is None else str(password), safe="")
        netloc = f"{user}:{pwd}@{host_port}"
    else:
        netloc = host_port

    return f"{scheme}://{netloc}"


def _is_retryable_submit_proxy_error(exc: BaseException) -> bool:
    return isinstance(exc, _HEADLESS_SUBMIT_RETRYABLE_ERRORS)


def _required_submit_proxy_ttl_seconds(ctx: Optional[TaskContext]) -> int:
    if ctx is None:
        return 20
    return int(get_proxy_required_ttl_seconds(getattr(ctx, "answer_duration_range_seconds", (0, 0))))


def _remove_proxy_from_ctx_pool(ctx: TaskContext, proxy_address: Optional[str]) -> bool:
    normalized = normalize_proxy_address(proxy_address)
    if not normalized:
        return False

    removed = False
    with ctx.lock:
        retained = []
        for item in list(ctx.proxy_ip_pool or []):
            lease = coerce_proxy_lease(item)
            if lease is None:
                continue
            if lease.address == normalized:
                removed = True
                continue
            retained.append(lease)
        ctx.proxy_ip_pool = retained
    return removed


def _pop_replacement_proxy_from_pool_locked(ctx: TaskContext, current_proxy: Optional[str]) -> Optional[str]:
    required_ttl = _required_submit_proxy_ttl_seconds(ctx)
    current = normalize_proxy_address(current_proxy)
    retained = []
    selected = None
    for item in list(ctx.proxy_ip_pool or []):
        lease = coerce_proxy_lease(item)
        if lease is None:
            continue
        if lease.address == current:
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
            logging.info("已丢弃即将过期的提交代理：%s", mask_proxy_for_log(lease.address))
            continue
        if selected is None:
            selected = lease.address
            continue
        retained.append(lease)
    ctx.proxy_ip_pool = retained
    return selected


def _acquire_replacement_submit_proxy(
    driver: BrowserDriver,
    ctx: Optional[TaskContext],
    *,
    stop_signal: Optional[threading.Event],
) -> Optional[str]:
    if ctx is None or not bool(getattr(ctx, "random_proxy_ip_enabled", False)):
        return None
    if stop_signal and stop_signal.is_set():
        return None

    current_proxy = normalize_proxy_address(getattr(driver, "_submit_proxy_address", None))
    removed_from_pool = _remove_proxy_from_ctx_pool(ctx, current_proxy)
    if current_proxy:
        logging.warning("无头提交代理疑似失效，已废弃：%s", mask_proxy_for_log(current_proxy))
    elif removed_from_pool:
        logging.info("已从代理池移除重复的失效提交代理")

    with ctx.lock:
        candidate = _pop_replacement_proxy_from_pool_locked(ctx, current_proxy)
    if candidate:
        setattr(driver, "_submit_proxy_address", candidate)
        logging.info("无头提交改用代理池中的新代理：%s", mask_proxy_for_log(candidate))
        return candidate

    with ctx._proxy_fetch_lock:
        with ctx.lock:
            candidate = _pop_replacement_proxy_from_pool_locked(ctx, current_proxy)
        if candidate:
            setattr(driver, "_submit_proxy_address", candidate)
            logging.info("无头提交改用代理池中的新代理：%s", mask_proxy_for_log(candidate))
            return candidate

        if stop_signal and stop_signal.is_set():
            return None

        try:
            fetched = fetch_proxy_batch(expected_count=1, stop_signal=stop_signal)
        except Exception as exc:
            logging.warning("无头提交切换新代理失败：%s", exc)
            return None
        for item in fetched or []:
            lease = coerce_proxy_lease(item)
            candidate = lease.address if lease is not None else ""
            if not candidate or candidate == current_proxy:
                continue
            if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=_required_submit_proxy_ttl_seconds(ctx)):
                logging.info("已跳过即将过期的新提交代理：%s", mask_proxy_for_log(candidate))
                continue
            setattr(driver, "_submit_proxy_address", candidate)
            logging.info("无头提交已切换为新提取代理：%s", mask_proxy_for_log(candidate))
            return candidate
    return None


def _capture_submit_request_via_route(
    driver: BrowserDriver,
    *,
    stop_signal: Optional[threading.Event],
    settle_delay: float,
    max_wait: float = 12.0,
) -> dict:
    """通过 Playwright 路由拦截 processjq 请求，拿到完整 URL + payload。"""
    page = getattr(driver, "page", None)
    if page is None:
        raise RuntimeError("当前驱动不支持 page.route，无法走无头 httpx 提交")

    route_pattern = "**/joinnew/processjq.ashx*"
    captured: dict = {}
    captured_event = threading.Event()

    def _route_handler(route, request):
        if captured_event.is_set():
            try:
                route.abort()
            except Exception as exc:
                log_suppressed_exception("submission._capture_submit_request_via_route abort duplicated", exc, level=logging.WARNING)
            return
        try:
            captured["method"] = request.method
            captured["url"] = request.url
            captured["headers"] = dict(request.headers or {})
            captured["post_data"] = request.post_data or ""
        except Exception as exc:
            log_suppressed_exception("submission._capture_submit_request_via_route collect request", exc, level=logging.WARNING)
        finally:
            captured_event.set()
            try:
                route.abort()
            except Exception as exc:
                log_suppressed_exception("submission._capture_submit_request_via_route abort", exc, level=logging.WARNING)

    page.route(route_pattern, _route_handler)
    try:
        clicked = _click_submit_button(driver, max_wait=10.0)
        if not clicked:
            raise NoSuchElementException("Submit button not found")
        if settle_delay > 0:
            time.sleep(settle_delay)
        _click_submit_confirm_button(driver, settle_delay=settle_delay)

        deadline = time.time() + max(0.0, float(max_wait or 0.0))
        while not captured_event.is_set() and time.time() < deadline:
            if stop_signal and stop_signal.is_set():
                break
            time.sleep(0.05)

        if not captured_event.is_set() and not (stop_signal and stop_signal.is_set()):
            # 首次点击命中容器节点时，可能不会真正触发提交；这里强制再触发一次问卷星提交入口。
            try:
                force_triggered = bool(
                    driver.execute_script(
                        r"""
                        return (() => {
                            const clickVisible = (el) => {
                                if (!el) return false;
                                const style = window.getComputedStyle(el);
                                if (!style) return false;
                                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                                const rect = el.getBoundingClientRect();
                                if (rect.width <= 0 || rect.height <= 0) return false;
                                el.click();
                                return true;
                            };

                            if (clickVisible(document.querySelector('#ctlNext'))) return true;
                            if (clickVisible(document.querySelector('#submit_button'))) return true;
                            if (typeof submit_button_click === 'function') {
                                submit_button_click();
                                return true;
                            }
                            return false;
                        })();
                        """
                    )
                )
                if force_triggered:
                    logging.info("无头抓包未命中，已强制触发问卷星提交入口重试")
                    _click_submit_confirm_button(driver, settle_delay=settle_delay)
            except Exception as exc:
                log_suppressed_exception("submission._capture_submit_request_via_route force trigger", exc, level=logging.WARNING)

            retry_deadline = time.time() + min(4.0, max(0.0, deadline - time.time()))
            while not captured_event.is_set() and time.time() < retry_deadline:
                if stop_signal and stop_signal.is_set():
                    break
                time.sleep(0.05)
    finally:
        try:
            page.unroute(route_pattern, _route_handler)
        except Exception as exc:
            log_suppressed_exception("submission._capture_submit_request_via_route unroute", exc, level=logging.WARNING)

    if not captured:
        validation_hint = ""
        try:
            validation_hint = str(
                driver.execute_script(
                    r"""
                    return (() => {
                        const visible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            if (!style) return false;
                            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                            const rect = el.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0;
                        };

                        const selectors = [
                            '.errorMessage',
                            '.div_question_error',
                            '.field.error .div_title_question_all',
                            '.field.error .error',
                            '.layui-layer-content',
                            '.wjxerrortips',
                        ];
                        const messages = [];
                        for (const sel of selectors) {
                            const nodes = document.querySelectorAll(sel);
                            for (const node of nodes) {
                                if (!visible(node)) continue;
                                const text = (node.innerText || node.textContent || '').trim();
                                if (text) messages.push(text);
                            }
                        }

                        const uniq = Array.from(new Set(messages.map(m => m.replace(/\s+/g, ' ').trim()))).slice(0, 3);
                        if (uniq.length) return uniq.join(' | ');

                        const bodyText = (document.body?.innerText || '').replace(/\s+/g, ' ');
                        if (bodyText.includes('请选择选项')) return '页面校验未通过：请选择选项';
                        if (bodyText.includes('请完成本页')) return '页面校验未通过：请完成本页必答项';
                        return '';
                    })();
                    """
                )
                or ""
            ).strip()
        except Exception as exc:
            log_suppressed_exception("submission._capture_submit_request_via_route validation hint", exc, level=logging.WARNING)

        if validation_hint:
            raise TimeoutException(f"无头提交流程未捕获到 processjq 请求，可能被页面校验拦截：{validation_hint}")
        raise TimeoutException("无头提交流程未捕获到 processjq 请求")
    return captured


def _submit_via_headless_httpx(
    driver: BrowserDriver,
    *,
    ctx: Optional[TaskContext],
    stop_signal: Optional[threading.Event],
    settle_delay: float,
) -> None:
    """无头模式：先由页面生成提交请求，再用 httpx 真正发出。"""
    setattr(driver, "_headless_httpx_submit_success", False)
    logging.info("无头模式启用：走 Playwright 抓包 + httpx 提交路线")
    captured = _capture_submit_request_via_route(
        driver,
        stop_signal=stop_signal,
        settle_delay=settle_delay,
    )
    submit_url = str(captured.get("url") or "").strip()
    method = str(captured.get("method") or "POST").upper()
    payload = str(captured.get("post_data") or "")
    if not submit_url:
        raise RuntimeError("无头提交流程捕获失败：提交 URL 为空")

    request_headers = _sanitize_request_headers(captured.get("headers") or {})
    cookies = _collect_page_cookies(driver, submit_url)
    timeout = httpx.Timeout(20.0, connect=10.0)
    response = None
    used_proxy_retry = False

    for attempt in range(_HEADLESS_SUBMIT_PROXY_RETRY_LIMIT + 1):
        submit_proxy_address = getattr(driver, "_submit_proxy_address", None)
        submit_proxy = _build_submit_proxy_url(submit_proxy_address)
        masked_proxy = mask_proxy_for_log(submit_proxy_address)
        logging.info(
            "无头+httpx 提交代理状态: %s, attempt=%s, proxy=%s",
            "enabled" if submit_proxy else "disabled",
            attempt + 1,
            masked_proxy or "<none>",
        )
        try:
            response = http_client.request(
                method=method,
                url=submit_url,
                headers=request_headers,
                content=payload,
                cookies=cookies,
                timeout=timeout,
                proxies=submit_proxy,
                allow_redirects=False,
            )
            break
        except Exception as exc:
            should_retry = (
                attempt < _HEADLESS_SUBMIT_PROXY_RETRY_LIMIT
                and submit_proxy is not None
                and _is_retryable_submit_proxy_error(exc)
            )
            if should_retry:
                replacement = _acquire_replacement_submit_proxy(
                    driver,
                    ctx,
                    stop_signal=stop_signal,
                )
                if replacement:
                    used_proxy_retry = True
                    logging.warning(
                        "无头+httpx 提交命中可重试代理错误，将切换新代理后重试：%s",
                        exc,
                    )
                    continue
            raise RuntimeError(f"无头+httpx 提交请求失败: {exc}") from exc

    if response is None:
        raise RuntimeError("无头+httpx 提交失败：未获得有效响应")
    if used_proxy_retry:
        logging.info("无头+httpx 提交在切换新代理后重试成功")

    response_text = response.text or ""
    business_code, business_payload = _parse_submit_response(response_text)

    if response.status_code != 200:
        raise RuntimeError(f"无头+httpx 提交 HTTP 状态异常: {response.status_code}, 响应: {response_text[:200]}")

    if business_code != "10":
        if business_code == "22":
            raise RuntimeError("无头+httpx 提交被验证码拦截（业务码22：请输入验证码）")
        raise RuntimeError(f"无头+httpx 提交失败，业务码={business_code}，响应={business_payload or response_text[:200]}")

    completion_url = _resolve_completion_url(submit_url, business_payload)
    if completion_url:
        try:
            driver.get(completion_url, timeout=15000)
        except Exception as exc:
            log_suppressed_exception("submission._submit_via_headless_httpx open completion url", exc, level=logging.WARNING)
    setattr(driver, "_headless_httpx_submit_success", True)
    logging.info("无头+httpx 提交成功，业务码=10")


def consume_headless_httpx_submit_success(driver: BrowserDriver) -> bool:
    """读取并清空无头+httpx提交成功标记。"""
    value = bool(getattr(driver, "_headless_httpx_submit_success", False))
    setattr(driver, "_headless_httpx_submit_success", False)
    return value


def submit(
    driver: BrowserDriver,
    ctx: Optional[TaskContext] = None,
    stop_signal: Optional[threading.Event] = None,
):
    """点击提交按钮并结束。

    仅保留最基础的行为：可选等待 -> 点击提交 -> 可选稳定等待。
    不再做弹窗确认/验证码检测/JS 强行触发等兜底逻辑。
    """
    headless_mode = _is_headless_mode(ctx)
    settle_delay = float(HEADLESS_SUBMIT_CLICK_SETTLE_DELAY if headless_mode else SUBMIT_CLICK_SETTLE_DELAY)
    pre_submit_delay = float(HEADLESS_SUBMIT_INITIAL_DELAY if headless_mode else SUBMIT_INITIAL_DELAY)

    if pre_submit_delay > 0 and _sleep_with_stop(stop_signal, pre_submit_delay):
        return
    if stop_signal and stop_signal.is_set():
        return

    if (
        ctx is not None
        and bool(getattr(ctx, "headless_mode", False))
        and str(getattr(ctx, "survey_provider", "wjx") or "wjx").strip().lower() == "wjx"
    ):
        _submit_via_headless_httpx(
            driver,
            ctx=ctx,
            stop_signal=stop_signal,
            settle_delay=settle_delay,
        )
        return

    clicked = _click_submit_button(driver, max_wait=10.0)
    if not clicked:
        raise NoSuchElementException("Submit button not found")

    if settle_delay > 0:
        time.sleep(settle_delay)
    _click_submit_confirm_button(driver, settle_delay=settle_delay)


def _normalize_url_for_compare(value: str) -> str:
    """用于比较的 URL 归一化：去掉 fragment，去掉首尾空白。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return text
    try:
        if parsed.fragment:
            parsed = parsed._replace(fragment="")
        return parsed.geturl()
    except Exception:
        return text


def _is_wjx_domain(url_value: str) -> bool:
    try:
        parsed = urlparse(str(url_value))
    except Exception:
        return False
    host = (parsed.netloc or "").split(":", 1)[0].lower()
    return bool(host == "wjx.cn" or host.endswith(".wjx.cn"))


def _looks_like_wjx_survey_url(url_value: str) -> bool:
    """粗略判断是否像问卷星问卷链接（用于“提交后分流到下一问卷”的识别）。"""
    if not url_value:
        return False
    text = str(url_value).strip()
    if not text:
        return False
    if not _is_wjx_domain(text):
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    path = (parsed.path or "").lower()
    if "complete" in path:
        return False
    if not path.endswith(".aspx"):
        return False
    # 常见路径：/vm/xxxxx.aspx、/jq/xxxxx.aspx、/vj/xxxxx.aspx
    if any(segment in path for segment in ("/vm/", "/jq/", "/vj/")):
        return True
    return True


def _page_looks_like_wjx_questionnaire(driver: BrowserDriver) -> bool:
    """用 DOM 特征判断当前页是否为可作答的问卷页。"""
    script = r"""
        return (() => {
            const bodyText = (document.body?.innerText || '').replace(/\s+/g, '');
            const completeMarkers = ['答卷已经提交', '感谢您的参与', '感谢参与'];
            if (completeMarkers.some(m => bodyText.includes(m))) return false;

            // 开屏“开始作答”页（还未展示题目）
            if (bodyText.includes('开始作答') || bodyText.includes('开始答题') || bodyText.includes('开始填写')) {
                const startLike = Array.from(document.querySelectorAll('div, a, button, span')).some(el => {
                    const t = (el.innerText || el.textContent || '').replace(/\s+/g, '');
                    return t === '开始作答' || t === '开始答题' || t === '开始填写';
                });
                if (startLike) return true;
            }

            const questionLike = document.querySelector(
                '#div1, #divQuestion, [id^="divquestion"], .div_question, .question, .wjx_question, [topic]'
            );

            const actionLike = document.querySelector(
                '#submit_button, #divSubmit, #ctlNext, #divNext, #btnNext, #next, ' +
                '.next, .next-btn, .next-button, .btn-next, button[type="submit"], a.button.mainBgColor'
            );

            return !!(questionLike && actionLike);
        })();
    """
    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


def _is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    """检测"设备已达到最大填写次数"提示页。"""
    script = r"""
        return (() => {
            const text = (document.body?.innerText || '').replace(/\s+/g, '');
            if (!text) return false;

            const limitMarkers = [
                '设备已达到最大填写次数',
                '已达到最大填写次数',
                '达到最大填写次数',
                '填写次数已达上限',
                '超过最大填写次数',
            ];
            const hasLimit = limitMarkers.some(marker => text.includes(marker));
            if (!hasLimit) return false;

            const hasThanks = text.includes('感谢参与') || text.includes('感谢参与!');
            const hasApology = text.includes('很抱歉') || text.includes('提示');
            if (!(hasThanks || hasApology)) return false;

            const questionLike = document.querySelector(
                '#divQuestion, [id^="divquestion"], .div_question, .question, .wjx_question, [topic]'
            );
            if (questionLike) return false;

            const startHints = ['开始作答', '开始答题', '开始填写', '继续作答', '继续填写'];
            if (startHints.some(hint => text.includes(hint))) return false;

            const submitSelectors = [
                '#submit_button',
                '#divSubmit',
                '#ctlNext',
                '#SM_BTN_1',
                '.submitDiv a',
                '.btn-submit',
                'button[type="submit"]',
                'a.mainBgColor',
            ];
            if (submitSelectors.some(sel => document.querySelector(sel))) return false;

            return true;
        })();
    """
    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False




