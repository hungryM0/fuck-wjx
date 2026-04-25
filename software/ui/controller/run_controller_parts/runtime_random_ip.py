"""RunController 随机 IP 与额度相关逻辑。"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

from software.network.proxy.session import (
    RandomIPAuthError,
    activate_trial,
    format_random_ip_error,
    format_quota_value,
    get_fresh_quota_snapshot,
    get_quota_snapshot,
    get_session_snapshot,
    has_authenticated_session,
    is_quota_exhausted,
    load_session_for_startup,
    sync_quota_snapshot_from_server,
)
from software.network.proxy import get_proxy_minute_by_answer_seconds, is_custom_proxy_api_active
from software.network.proxy.policy import get_random_ip_counter_snapshot_local
from software.logging.log_utils import log_deduped_message, reset_deduped_log_message

from .runtime_constants import PROXY_SOURCE_BENEFIT

_RANDOM_IP_SYNC_FAILURE_LOG_KEY = "random_ip_quota_sync_failure"

if TYPE_CHECKING:
    from software.io.config import RuntimeConfig


class RunControllerRandomIPMixin:
    if TYPE_CHECKING:
        adapter: Any

        def notify_random_ip_loading(self, loading: bool, message: str = "") -> None: ...

    def _normalize_proxy_source_value(self, source: Any) -> str:
        normalized = str(source or "default").strip().lower()
        return normalized if normalized in {"default", "benefit", "custom"} else "default"
    def _resolve_answer_duration_upper_bound(self, answer_duration: Any) -> int:
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
    def _resolve_counter_snapshot_values(self, snapshot: Dict[str, Any]) -> tuple[float, float]:
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
    def _begin_random_ip_server_sync(self, *, min_interval_seconds: float = 0.0) -> bool:
        if is_custom_proxy_api_active() or not has_authenticated_session():
            return False
        lock = getattr(self, "_random_ip_server_sync_lock", None)
        if lock is None:
            return True
        now = time.monotonic()
        with lock:
            if bool(getattr(self, "_random_ip_server_sync_active", False)):
                return False
            last_sync_at = float(getattr(self, "_random_ip_last_server_sync_at", 0.0) or 0.0)
            if min_interval_seconds > 0 and (now - last_sync_at) < float(min_interval_seconds):
                return False
            self._random_ip_server_sync_active = True
        return True
    def _finish_random_ip_server_sync(self, *, succeeded: bool) -> None:
        lock = getattr(self, "_random_ip_server_sync_lock", None)
        if lock is None:
            return
        with lock:
            if succeeded:
                self._random_ip_last_server_sync_at = time.monotonic()
            self._random_ip_server_sync_active = False
    def sync_random_ip_counter_from_server(
        self,
        *,
        adapter: Optional[Any] = None,
        async_mode: bool = True,
        silent: bool = True,
        min_interval_seconds: float = 0.0,
    ) -> None:
        adapter = adapter or getattr(self, "adapter", None)
        if not adapter:
            return
        if not self._begin_random_ip_server_sync(min_interval_seconds=min_interval_seconds):
            return

        def _worker() -> None:
            succeeded = False
            try:
                snapshot = sync_quota_snapshot_from_server(emit_logs=not silent)
                used, total = self._resolve_counter_snapshot_values(snapshot)
                self._apply_random_ip_counter(adapter, used=used, total=total, custom_api=False)
                reset_deduped_log_message(_RANDOM_IP_SYNC_FAILURE_LOG_KEY)
                succeeded = True
            except Exception as exc:
                message = format_random_ip_error(exc)
                log_level = logging.INFO if silent else logging.WARNING
                log_deduped_message(
                    _RANDOM_IP_SYNC_FAILURE_LOG_KEY,
                    f"同步随机IP额度失败：{message}",
                    level=log_level,
                )
                if not silent:
                    self._show_random_ip_message(adapter, "随机IP同步失败", message, level="warning")
                try:
                    self._refresh_random_ip_counter_now(adapter)
                except Exception:
                    logging.info("同步失败后回退随机IP本地额度显示失败", exc_info=True)
            finally:
                self._finish_random_ip_server_sync(succeeded=succeeded)

        if async_mode and threading.current_thread() is threading.main_thread():
            threading.Thread(
                target=_worker,
                daemon=True,
                name="RandomIPQuotaSync",
            ).start()
            return
        _worker()
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
