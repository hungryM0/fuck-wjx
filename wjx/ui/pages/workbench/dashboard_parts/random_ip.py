"""DashboardPage 随机 IP 与额度申请相关方法。"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Optional, cast
from qfluentwidgets import FluentIcon

from wjx.network.proxy.auth import (
    get_session_snapshot,
    has_authenticated_session,
    has_incomplete_session,
    has_unknown_local_quota,
    is_quota_exhausted,
)
from wjx.network.proxy import (
    PROXY_SOURCE_BENEFIT,
    format_quota_value,
    get_proxy_source,
    _format_status_payload,
    get_proxy_minute_by_answer_seconds,
    get_quota_cost_by_minute,
    get_random_ip_counter_snapshot_local,
    get_status,
    on_random_ip_toggle,
    refresh_ip_counter_display,
)
from wjx.ui.dialogs.contact import ContactDialog
from wjx.utils.logging.log_utils import log_suppressed_exception

if TYPE_CHECKING:
    from qfluentwidgets import BodyLabel, CheckBox, PushButton
    from wjx.ui.controller import RunController
    from wjx.ui.pages.workbench.runtime import RuntimePage
    from wjx.ui.widgets.full_width_infobar import FullWidthInfoBar


class DashboardRandomIPMixin:
    """随机 IP、额度提示与额度申请逻辑。"""

    if TYPE_CHECKING:
        # 以下属性由 DashboardPage 主类提供，此处仅用于 Pylance 类型检查
        card_btn: PushButton
        random_ip_hint: BodyLabel
        random_ip_cb: CheckBox
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
        _ipBalanceChecked: Any   # 同上

        def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False) -> Any: ...
        def window(self) -> Any: ...  # 继承自 QWidget，此处仅供类型检查

    def _set_runtime_ip_switch(self, enabled: bool) -> None:
        """设置运行时页面的随机IP开关，并同步展开区域的启用状态（绕过信号阻塞）。"""
        try:
            self.runtime_page.random_ip_card.switchButton.blockSignals(True)
            self.runtime_page.random_ip_card.switchButton.setChecked(enabled)
            self.runtime_page.random_ip_card.switchButton.blockSignals(False)
            self.runtime_page.random_ip_card._sync_ip_enabled(enabled)
        except Exception as exc:
            log_suppressed_exception("_set_runtime_ip_switch", exc, level=logging.WARNING)

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        active = bool(loading)
        text = str(message or "正在处理...") if active else ""
        try:
            self.random_ip_loading_ring.setVisible(active)
            self.random_ip_loading_label.setVisible(active)
            self.random_ip_loading_label.setText(text)
            self.random_ip_cb.setEnabled(not active)
        except Exception as exc:
            log_suppressed_exception("set_random_ip_loading dashboard", exc, level=logging.WARNING)
        try:
            if hasattr(self.runtime_page, "random_ip_card"):
                self.runtime_page.random_ip_card.setLoading(active, text)
        except Exception as exc:
            log_suppressed_exception("set_random_ip_loading runtime", exc, level=logging.WARNING)

    def update_random_ip_counter(self, count: float, limit: float, custom_api: bool):
        snapshot = get_session_snapshot()
        authenticated = bool(snapshot.get("authenticated")) and has_authenticated_session()
        session_incomplete = bool(snapshot.get("session_incomplete")) and has_incomplete_session()
        unknown_local_quota = has_unknown_local_quota(snapshot)
        used = max(0.0, float(count or 0.0))
        total = max(0.0, float(limit or 0.0))
        quota_exhausted = is_quota_exhausted(
            {"authenticated": authenticated, "user_id": int(snapshot.get("user_id") or 0), "used_quota": used, "total_quota": total}
        )
        self.card_btn.setEnabled(True)
        self.card_btn.setText("申请额度")
        self.card_btn.setIcon(FluentIcon.FINGERPRINT)
        if authenticated:
            self.card_btn.setToolTip("提交额度申请后，开发者会人工补充随机IP额度")
        elif session_incomplete:
            self.card_btn.setToolTip("检测到可恢复的随机IP旧会话，系统会自动尝试恢复；若长时间未恢复，再改用报错反馈")
        else:
            self.card_btn.setToolTip("勾选随机IP会自动尝试领取试用；试用不可用时可在这里提交额度申请")

        if custom_api:
            self.random_ip_hint.setText("自定义接口")
            self.random_ip_hint.setStyleSheet("color:#ff8c00;")
            self._update_ip_low_infobar(count, limit, custom_api)
            self._update_ip_cost_infobar(custom_api)
            return
        if not authenticated and not session_incomplete:
            self.random_ip_hint.setText("--/--")
            self.random_ip_hint.setStyleSheet("color:#6b6b6b;")
            self._update_ip_low_infobar(count, limit, custom_api)
            self._update_ip_cost_infobar(custom_api)
            if self.random_ip_cb.isChecked():
                self.random_ip_cb.blockSignals(True)
                self.random_ip_cb.setChecked(False)
                self.random_ip_cb.blockSignals(False)
            return
        if session_incomplete and not authenticated:
            self.random_ip_hint.setText("恢复中")
            self.random_ip_hint.setStyleSheet("color:#D46B08;")
            self._update_ip_low_infobar(count, limit, custom_api)
            self._update_ip_cost_infobar(custom_api)
            return
        if unknown_local_quota:
            self.random_ip_hint.setText("待校验")
            self.random_ip_hint.setStyleSheet("color:#D46B08;")
            self.card_btn.setToolTip("本机还记得随机IP账号，但当前额度状态暂时无法确认。后续真实提取代理时会自动尝试回填。")
            self._update_ip_low_infobar(count, limit, custom_api)
            self._update_ip_cost_infobar(custom_api)
            return
        self.random_ip_hint.setText(f"{format_quota_value(used)}/{format_quota_value(total)}")
        if quota_exhausted:
            self.random_ip_hint.setStyleSheet("color:red;")
        else:
            self.random_ip_hint.setStyleSheet("color:#6b6b6b;")
        self._update_ip_low_infobar(count, limit, custom_api)
        self._update_ip_cost_infobar(custom_api)
        if quota_exhausted and self.random_ip_cb.isChecked():
            self.random_ip_cb.blockSignals(True)
            self.random_ip_cb.setChecked(False)
            self.random_ip_cb.blockSignals(False)
            self._set_runtime_ip_switch(False)

    @staticmethod
    def _format_duration_text(seconds: int) -> str:
        total = max(0, int(seconds))
        mins = total // 60
        secs = total % 60
        return f"{mins}分{secs}秒"

    def _refresh_ip_cost_infobar(self) -> None:
        """根据当前配置刷新随机IP成本提示条。"""
        try:
            _, _, custom_api = get_random_ip_counter_snapshot_local()
        except Exception:
            custom_api = False
        self._update_ip_cost_infobar(bool(custom_api))

    def _set_ip_cost_infobar_state(self, *, title: str, content: str = "", show_adjust_link: bool = False) -> None:
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

        current_source = str(get_proxy_source() or "").strip().lower()
        if current_source == PROXY_SOURCE_BENEFIT:
            self._ip_cost_infobar.hide()
            if self._ip_benefit_infobar:
                self._ip_benefit_infobar.show()
            return

        try:
            timed_enabled = bool(self.runtime_page.timed_card.switchButton.isChecked())
        except Exception:
            timed_enabled = False
        if timed_enabled:
            self._ip_cost_infobar.hide()
            return

        try:
            answer_seconds = int(self.runtime_page.answer_card.getValue())
        except Exception:
            answer_seconds = 0

        minute = int(get_proxy_minute_by_answer_seconds(answer_seconds))
        if minute <= 1:
            self._ip_cost_infobar.hide()
            return

        quota_cost = int(get_quota_cost_by_minute(minute))
        content = (
            f"当前作答时长约 {self._format_duration_text(answer_seconds)}，成本较高，"
            f"将按 {quota_cost} 倍消耗速率扣减随机IP额度。"
        )
        try:
            self._set_ip_cost_infobar_state(
                title=content,
                show_adjust_link=True,
            )
        except Exception as exc:
            log_suppressed_exception("_update_ip_cost_infobar", exc, level=logging.WARNING)

    def _on_random_ip_toggled(self, state: int):
        enabled = state != 0
        try:
            self.controller.adapter.random_ip_enabled_var.set(bool(enabled))
            on_random_ip_toggle(self.controller.adapter)
            enabled = bool(self.controller.adapter.random_ip_enabled_var.get())
        except Exception:
            enabled = bool(enabled)
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(enabled)
        self.random_ip_cb.blockSignals(False)
        self._set_runtime_ip_switch(enabled)
        refresh_ip_counter_display(self.controller.adapter)

    def _open_contact_dialog(self, default_type: str = "报错反馈", lock_message_type: bool = False):
        """打开联系对话框"""
        win = self.window()
        if hasattr(win, "_open_contact_dialog"):
            try:
                return win._open_contact_dialog(default_type, lock_message_type)  # type: ignore[union-attr]
            except Exception as exc:
                log_suppressed_exception("_open_contact_dialog passthrough", exc, level=logging.WARNING)
        dlg = ContactDialog(
            self,
            default_type=default_type,
            lock_message_type=lock_message_type,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
        )
        dlg.exec()

    def _on_request_quota_clicked(self):
        """用户主动打开额度申请表单。"""
        if self._open_contact_dialog(default_type="额度申请", lock_message_type=True):
            refresh_ip_counter_display(self.controller.adapter)

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
        threshold = max(5.0, min(50.0, float(getattr(self, "_ip_low_threshold", 20.0) or 20.0)))
        if remaining_ip < threshold:
            if not self._ip_low_infobar_dismissed:
                self._ip_low_infobar.show()
        else:
            self._ip_low_infobar.hide()
            self._ip_low_infobar_dismissed = False
