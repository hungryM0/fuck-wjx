"""DashboardPage 随机 IP 与额度申请相关方法。"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Optional, cast
from PySide6.QtGui import QColor
from qfluentwidgets import themeColor

import software.network.http as http_client

from software.ui.dialogs.quota_redeem import load_shop_icon
from software.app.config import DEFAULT_HTTP_HEADERS, IP_EXTRACT_ENDPOINT
from software.logging.log_utils import log_suppressed_exception
from software.ui.helpers.qfluent_compat import set_indeterminate_progress_ring_active
from software.ui.helpers.proxy_access import (
    PROXY_SOURCE_BENEFIT,
    format_quota_value,
    get_random_ip_counter_snapshot_local,
    get_session_snapshot,
    has_authenticated_session,
    has_unknown_local_quota,
    is_quota_exhausted,
)

_RANDOM_IP_HEALTH_TIMEOUT_SECONDS = 5

if TYPE_CHECKING:
    from qfluentwidgets import (
        BodyLabel,
        ProgressRing,
        PushButton,
        TogglePushButton,
    )
    from software.ui.controller.run_controller import RunController
    from software.ui.pages.workbench.runtime_panel.main import RuntimePage
    from software.ui.pages.workbench.shared.random_ip_toggle_row import (
        RandomIpToggleRow,
    )
    from software.ui.widgets.full_width_infobar import FullWidthInfoBar


class DashboardRandomIPMixin:
    """随机 IP、额度提示与额度申请逻辑。"""

    if TYPE_CHECKING:
        # 以下属性由 DashboardPage 主类提供，此处仅用于 Pylance 类型检查
        card_btn: PushButton
        random_ip_row: RandomIpToggleRow
        random_ip_usage_ring: ProgressRing
        random_ip_cb: TogglePushButton
        random_ip_loading_ring: Any
        random_ip_loading_label: BodyLabel
        controller: RunController
        runtime_page: RuntimePage
        _ip_low_infobar: Optional[FullWidthInfoBar]
        _ip_cost_infobar: Optional[FullWidthInfoBar]
        _ip_benefit_infobar: Optional[FullWidthInfoBar]
        _ip_low_infobar_dismissed: bool
        _ip_low_threshold: float
        _ip_cost_adjust_link: Any
        _api_balance_cache: Optional[float]
        _ip_balance_fetch_lock: threading.Lock
        _ip_balance_fetching: bool
        _last_ip_balance_fetch_ts: float
        _ip_balance_fetch_interval_sec: float
        _random_ip_status_fetch_lock: threading.Lock
        _random_ip_status_fetching: bool
        _ipBalanceChecked: Any  # 同上
        _randomIpHeartbeatUpdated: Any
        random_ip_status_dot: Any
        random_ip_status_spinner: Any
        random_ip_status_label: BodyLabel
        random_ip_status_row: Any
        random_ip_status_timer: Any

        def _toast(
            self,
            text: str,
            level: str = "info",
            duration: int = 2000,
            show_progress: bool = False,
        ) -> Any: ...
        def window(self) -> Any: ...  # 继承自 QWidget，此处仅供类型检查

    def _init_random_ip_status_refresh(self) -> None:
        """初始化主页随机IP服务状态点。"""
        try:
            from PySide6.QtCore import QTimer
        except Exception as exc:
            log_suppressed_exception(
                "_init_random_ip_status_refresh: import QTimer",
                exc,
                level=logging.WARNING,
            )
            return

        self._apply_random_ip_heartbeat_loading()
        self.random_ip_status_timer = QTimer(cast(Any, self))
        self.random_ip_status_timer.setInterval(60_000)
        self.random_ip_status_timer.timeout.connect(self.refresh_random_ip_heartbeat_async)
        self.random_ip_status_timer.start()
        self.refresh_random_ip_heartbeat_async()

    def refresh_random_ip_heartbeat_async(self) -> None:
        """后台刷新随机IP服务状态，避免阻塞主页。"""
        lock = getattr(self, "_random_ip_status_fetch_lock", None)
        if lock is None:
            return
        with lock:
            if bool(getattr(self, "_random_ip_status_fetching", False)):
                return
            self._random_ip_status_fetching = True
        self._apply_random_ip_heartbeat_loading()

        threading.Thread(
            target=self._run_random_ip_heartbeat_fetch,
            daemon=True,
            name="DashboardRandomIpHeartbeat",
        ).start()

    def _run_random_ip_heartbeat_fetch(self) -> None:
        payload = None
        try:
            payload = self._fetch_random_ip_heartbeat_status()
        except Exception as exc:
            logging.warning("随机IP服务状态检查失败，已按未知状态处理：%s", exc)
            payload = {
                "level": "warning",
                "text": "HTTP 0",
                "tooltip": f"随机IP提取接口请求失败：{exc}",
            }
        finally:
            with self._random_ip_status_fetch_lock:
                self._random_ip_status_fetching = False

        try:
            if bool(getattr(self, "_is_closing", False)):
                return
            window = self.window()
            if window is not None and bool(getattr(window, "_is_closing", False)):
                return
        except Exception:
            return

        try:
            self._randomIpHeartbeatUpdated.emit(payload or {})
        except Exception as exc:
            log_suppressed_exception(
                "_run_random_ip_heartbeat_fetch emit",
                exc,
                level=logging.WARNING,
            )

    def _fetch_random_ip_heartbeat_status(self) -> dict[str, str]:
        headers = {
            **DEFAULT_HTTP_HEADERS,
            "X-Health-Token": "status-rzib9lqpuk3httr4",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        response = http_client.post(
            IP_EXTRACT_ENDPOINT,
            json={},
            timeout=_RANDOM_IP_HEALTH_TIMEOUT_SECONDS,
            headers=headers,
        )
        elapsed_ms = max(1, int(round((time.perf_counter() - started) * 1000)))
        status_code = int(getattr(response, "status_code", 0) or 0)
        if 200 <= status_code < 300:
            return {
                "level": "success",
                "text": f"服务正常 {elapsed_ms} ms",
                "tooltip": f"随机IP提取接口返回 HTTP {status_code}，耗时 {elapsed_ms} ms。",
            }
        return {
            "level": "error",
            "text": f"异常 {status_code or 0}",
            "tooltip": f"随机IP提取接口返回 HTTP {status_code or 0}，耗时 {elapsed_ms} ms。",
        }

    def _apply_random_ip_heartbeat_status(self, payload: Any) -> None:
        data = payload if isinstance(payload, dict) else {}
        level = str(data.get("level") or "warning").strip().lower()
        text = str(data.get("text") or "--").strip()
        tooltip = str(data.get("tooltip") or text).strip()
        color_map = {
            "success": "#0F9D58",
            "warning": "#C77900",
            "error": "#C42B1C",
        }
        color = color_map.get(level, "#C77900")
        dot_style = f"background-color: {color}; border-radius: 5px;"
        try:
            set_indeterminate_progress_ring_active(self.random_ip_status_spinner, False)
            self.random_ip_status_spinner.hide()
            self.random_ip_status_dot.setStyleSheet(dot_style)
            self.random_ip_status_dot.show()
            self.random_ip_status_label.setText(text)
            self.random_ip_status_label.show()
            self.random_ip_status_dot.setToolTip(tooltip)
            self.random_ip_status_label.setToolTip(tooltip)
            self.random_ip_status_row.setToolTip(tooltip)
        except Exception as exc:
            log_suppressed_exception(
                "_apply_random_ip_heartbeat_status", exc, level=logging.WARNING
            )

    def _apply_random_ip_heartbeat_loading(self) -> None:
        try:
            self.random_ip_status_dot.hide()
            self.random_ip_status_label.hide()
            self.random_ip_status_label.setToolTip("")
            self.random_ip_status_row.setToolTip("")
            self.random_ip_status_spinner.show()
            set_indeterminate_progress_ring_active(self.random_ip_status_spinner, True)
        except Exception as exc:
            log_suppressed_exception(
                "_apply_random_ip_heartbeat_loading", exc, level=logging.WARNING
            )

    def _sync_random_ip_toggle_presentation(self, enabled: bool) -> None:
        """同步概览页随机 IP 按钮的文案和图标。"""
        try:
            self.random_ip_row.sync_toggle_presentation(enabled)
        except Exception as exc:
            log_suppressed_exception(
                "_sync_random_ip_toggle_presentation",
                exc,
                level=logging.WARNING,
            )

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        try:
            self.random_ip_row.set_loading(loading, message)
        except Exception as exc:
            log_suppressed_exception("set_random_ip_loading dashboard", exc, level=logging.WARNING)

    def update_random_ip_counter(self, count: float, limit: float, custom_api: bool):
        snapshot = get_session_snapshot()
        authenticated = bool(snapshot.get("authenticated")) and has_authenticated_session()
        unknown_local_quota = has_unknown_local_quota(snapshot)
        used = max(0.0, float(count or 0.0))
        total = max(0.0, float(limit or 0.0))
        remaining_snapshot = max(0.0, float(snapshot.get("remaining_quota") or 0.0))
        remaining = min(total, remaining_snapshot) if total > 0 else remaining_snapshot
        if total > 0 and remaining_snapshot <= 0:
            remaining = max(0.0, total - used)
        quota_exhausted = is_quota_exhausted(
            {
                "authenticated": authenticated,
                "user_id": int(snapshot.get("user_id") or 0),
                "used_quota": used,
                "total_quota": total,
            }
        )
        self.card_btn.setEnabled(True)
        self.card_btn.setText("额度兑换")
        shop_icon = load_shop_icon()
        if shop_icon is not None:
            self.card_btn.setIcon(shop_icon)
        if authenticated:
            self.card_btn.setToolTip("通常情况下，1额度即提交1份问卷")
        else:
            self.card_btn.setToolTip(
                "先勾选随机IP领取试用账号，之后才能在这里兑换额度卡密"
            )

        if custom_api:
            self._sync_random_ip_usage_ring(mode="paused", percent=0, format_text="自定义")
            self._update_ip_low_infobar(count, limit, custom_api)
            self._update_ip_cost_infobar(custom_api)
            return
        if not authenticated:
            self._sync_random_ip_usage_ring(mode="paused", percent=0, format_text="--/--")
            self._update_ip_low_infobar(count, limit, custom_api)
            self._update_ip_cost_infobar(custom_api)
            if self.random_ip_cb.isChecked():
                self.random_ip_cb.blockSignals(True)
                self.random_ip_cb.setChecked(False)
                self.random_ip_cb.blockSignals(False)
                self._sync_random_ip_toggle_presentation(False)
                self.controller.set_runtime_ui_state(random_ip_enabled=False)
            return
        if unknown_local_quota:
            self._sync_random_ip_usage_ring(mode="paused", percent=0, format_text="待校验")
            self.card_btn.setToolTip(
                "本机还记得随机IP账号，但当前额度状态暂时无法确认。后续真实提取代理时会自动尝试回填。"
            )
            self._update_ip_low_infobar(count, limit, custom_api)
            self._update_ip_cost_infobar(custom_api)
            return
        quota_text = f"{format_quota_value(remaining)}/{format_quota_value(total)}"
        percent = 0 if total <= 0 else max(0, min(int(round((remaining / total) * 100)), 100))
        self._sync_random_ip_usage_ring(
            mode="error" if quota_exhausted else "normal",
            percent=percent,
            format_text=quota_text,
        )
        self._update_ip_low_infobar(count, limit, custom_api)
        self._update_ip_cost_infobar(custom_api)
        if quota_exhausted and self.random_ip_cb.isChecked():
            self.random_ip_cb.blockSignals(True)
            self.random_ip_cb.setChecked(False)
            self.random_ip_cb.blockSignals(False)
            self._sync_random_ip_toggle_presentation(False)
            self.controller.set_runtime_ui_state(random_ip_enabled=False)

    def _sync_random_ip_usage_ring(self, *, mode: str, percent: int, format_text: str) -> None:
        try:
            value = max(0, min(int(percent), 100))
            self.random_ip_usage_ring.setRange(0, 100)
            self.random_ip_usage_ring.setValue(value)
            self.random_ip_usage_ring.setTextVisible(True)
            self.random_ip_usage_ring.setFormat(str(format_text or "--"))
            normalized_mode = str(mode or "").lower()
            is_paused = normalized_mode == "paused"
            is_error = normalized_mode == "error"
            if not is_paused and not is_error:
                self._apply_random_ip_usage_ring_color(value)
            self.random_ip_usage_ring.setPaused(is_paused)
            self.random_ip_usage_ring.setError(is_error)
        except Exception as exc:
            log_suppressed_exception("_sync_random_ip_usage_ring", exc, level=logging.WARNING)

    def _apply_random_ip_usage_ring_color(self, percent: int) -> None:
        try:
            value = max(0, min(int(percent), 100))
            if value <= 5:
                self.random_ip_usage_ring.setCustomBarColor(QColor("#C42B1C"), QColor("#FF99A4"))
                return
            if value <= 20:
                self.random_ip_usage_ring.setCustomBarColor(QColor("#C77900"), QColor("#FFB347"))
                return
            accent = themeColor()
            self.random_ip_usage_ring.setCustomBarColor(accent, accent)
        except Exception as exc:
            log_suppressed_exception(
                "_apply_random_ip_usage_ring_color", exc, level=logging.WARNING
            )

    def _refresh_ip_cost_infobar(self) -> None:
        """根据当前配置刷新随机IP成本提示条。"""
        try:
            _, _, custom_api = get_random_ip_counter_snapshot_local()
        except Exception:
            custom_api = False
        self._update_ip_cost_infobar(bool(custom_api))

    def _set_ip_cost_infobar_state(
        self, *, title: str, content: str = "", show_adjust_link: bool = False
    ) -> None:
        """统一更新高消耗额度提示条的文案与附加操作。"""
        if not self._ip_cost_infobar:
            return

        self._ip_cost_infobar.title = title
        self._ip_cost_infobar.content = content

        if hasattr(self._ip_cost_infobar, "titleLabel"):
            self._ip_cost_infobar.titleLabel.setVisible(bool(title))
        if hasattr(self._ip_cost_infobar, "contentLabel"):
            self._ip_cost_infobar.contentLabel.setVisible(bool(content))

        if hasattr(self, "_ip_cost_adjust_link"):
            cast(Any, self)._ip_cost_adjust_link.setVisible(bool(show_adjust_link))

        if hasattr(self._ip_cost_infobar, "_adjustText"):
            self._ip_cost_infobar._adjustText()
        self._ip_cost_infobar.show()

    def _update_ip_cost_infobar(self, custom_api: bool) -> None:
        if not self._ip_cost_infobar:
            return
        if self._ip_benefit_infobar:
            self._ip_benefit_infobar.hide()
        if custom_api:
            self._ip_cost_infobar.hide()
            return

        try:
            state = self.controller.get_runtime_ui_state()
            current_source = str(state.get("proxy_source") or "").strip().lower()
        except Exception as exc:
            context = "_update_ip_cost_infobar: self.controller.get_runtime_ui_state()"
            log_suppressed_exception(
                context,
                exc,
                level=logging.WARNING,
            )
            return
        if current_source == PROXY_SOURCE_BENEFIT:
            self._ip_cost_infobar.hide()
            if self._ip_benefit_infobar:
                self._ip_benefit_infobar.show()
            return
        self._ip_cost_infobar.hide()

    def _on_random_ip_toggled(self, enabled: bool):
        self._sync_random_ip_toggle_presentation(bool(enabled))
        if self.controller.request_toggle_random_ip(bool(enabled), adapter=self.controller.adapter):
            return

        fallback_enabled = bool(
            self.controller.get_runtime_ui_state().get("random_ip_enabled", False)
        )
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(fallback_enabled)
        self.random_ip_cb.blockSignals(False)
        self._sync_random_ip_toggle_presentation(fallback_enabled)

    def _open_contact_dialog(self, default_type: str = "报错反馈", lock_message_type: bool = False):
        """转交主窗口打开联系对话框。"""
        win = self.window()
        if hasattr(win, "_open_contact_dialog"):
            try:
                return cast(Any, win)._open_contact_dialog(default_type, lock_message_type)
            except Exception as exc:
                log_suppressed_exception(
                    "_open_contact_dialog passthrough",
                    exc,
                    level=logging.WARNING,
                )
        raise RuntimeError("主窗口不支持联系开发者弹窗")

    def _open_quota_redeem_dialog(self) -> bool:
        """转交主窗口打开额度兑换对话框。"""
        win = self.window()
        if hasattr(win, "_open_quota_redeem_dialog"):
            try:
                return cast(Any, win)._open_quota_redeem_dialog()
            except Exception as exc:
                log_suppressed_exception(
                    "_open_quota_redeem_dialog passthrough",
                    exc,
                    level=logging.WARNING,
                )
        raise RuntimeError("主窗口不支持额度兑换弹窗")

    def _on_request_quota_clicked(self):
        """用户主动打开额度兑换弹窗。"""
        self._open_quota_redeem_dialog()

    def _on_ip_low_infobar_closed(self):
        self._ip_low_infobar_dismissed = True
        if self._ip_low_infobar:
            self._ip_low_infobar.hide()

    def _update_ip_low_infobar(self, count: float, limit: float, custom_api: bool):
        """更新随机IP余额不足提示条。"""
        if not self._ip_low_infobar:
            return
        if custom_api:
            self._ip_low_infobar.hide()
            self._ip_low_infobar_dismissed = False
            return
        if not has_authenticated_session():
            self._ip_low_infobar.hide()
            self._ip_low_infobar_dismissed = False
            return
        remaining = max(0.0, float(limit or 0.0) - float(count or 0.0))
        limit_value = max(0.0, float(limit or 0.0))
        threshold = max(5.0, min(50.0, limit_value / 5 if limit_value > 0 else 5.0))
        self._ip_low_threshold = threshold
        self._on_ip_balance_checked(remaining if remaining <= threshold else threshold + 1)

    def _on_ip_balance_checked(self, remaining_ip: float):
        """处理IP余额检查结果（在主线程中执行）"""
        if not self._ip_low_infobar:
            return
        threshold = max(
            5.0,
            min(50.0, float(getattr(self, "_ip_low_threshold", 20.0) or 20.0)),
        )
        if remaining_ip < threshold:
            if not self._ip_low_infobar_dismissed:
                self._ip_low_infobar.show()
        else:
            self._ip_low_infobar.hide()
            self._ip_low_infobar_dismissed = False
