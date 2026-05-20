from __future__ import annotations

import threading
from types import SimpleNamespace

from PySide6.QtGui import QColor
import software.ui.pages.workbench.dashboard.parts.random_ip as dashboard_random_ip
from software.ui.pages.workbench.dashboard.parts.random_ip import DashboardRandomIPMixin


class _FakeButton:
    def __init__(self) -> None:
        self.enabled = True
        self.text = ""
        self.tooltip = ""
        self.icon = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def setText(self, text: str) -> None:
        self.text = str(text)

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = str(tooltip)

    def setIcon(self, icon) -> None:
        self.icon = icon


class _FakeRing:
    def __init__(self) -> None:
        self.range = (0, 100)
        self.value = 0
        self.text_visible = False
        self.format_text = ""
        self.paused = False
        self.error = False
        self.colors = None

    def setRange(self, minimum: int, maximum: int) -> None:
        self.range = (minimum, maximum)

    def setValue(self, value: int) -> None:
        self.value = int(value)

    def setTextVisible(self, visible: bool) -> None:
        self.text_visible = bool(visible)

    def setFormat(self, text: str) -> None:
        self.format_text = str(text)

    def setPaused(self, paused: bool) -> None:
        self.paused = bool(paused)

    def setError(self, error: bool) -> None:
        self.error = bool(error)

    def setCustomBarColor(self, color1, color2) -> None:
        self.colors = (color1.name(), color2.name())


class _FakeToggle:
    def __init__(self) -> None:
        self.checked = False
        self.blocked = []

    def isChecked(self) -> bool:
        return self.checked

    def blockSignals(self, blocked: bool) -> None:
        self.blocked.append(bool(blocked))

    def setChecked(self, checked: bool) -> None:
        self.checked = bool(checked)


class _FakeDot:
    def __init__(self) -> None:
        self.style = ""
        self.tooltip = ""
        self.visible = True

    def setStyleSheet(self, style: str) -> None:
        self.style = str(style)

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = str(tooltip)

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False


class _FakeSpinner:
    def __init__(self) -> None:
        self.visible = False
        self.active = False

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False


class _FakeLabel:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""
        self.visible = True

    def setText(self, text: str) -> None:
        self.text = str(text)

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = str(tooltip)

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False


class _FakeInfoBar:
    def __init__(self) -> None:
        self.hidden = 0
        self.shown = 0
        self.title = ""
        self.content = ""
        self.titleLabel = _FakeLabel()
        self.contentLabel = _FakeLabel()
        self.adjust_calls = 0

    def hide(self) -> None:
        self.hidden += 1

    def show(self) -> None:
        self.shown += 1

    def _adjustText(self) -> None:
        self.adjust_calls += 1


class _FakeRow:
    def __init__(self) -> None:
        self.toggle_calls = []
        self.loading_calls = []

    def sync_toggle_presentation(self, enabled: bool) -> None:
        self.toggle_calls.append(bool(enabled))

    def set_loading(self, loading: bool, message: str) -> None:
        self.loading_calls.append((bool(loading), str(message)))


class _FakeSignal:
    def __init__(self) -> None:
        self.calls = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeTimer:
    def __init__(self, _parent=None) -> None:
        self.interval = 0
        self.started = 0
        self.callback = None
        self.timeout = SimpleNamespace(connect=lambda callback: setattr(self, "callback", callback))

    def setInterval(self, interval: int) -> None:
        self.interval = int(interval)

    def start(self) -> None:
        self.started += 1


class _FakeDashboard(DashboardRandomIPMixin):
    def __init__(self) -> None:
        self.card_btn = _FakeButton()
        self.random_ip_usage_ring = _FakeRing()
        self.random_ip_cb = _FakeToggle()
        self.random_ip_row = _FakeRow()
        self.random_ip_status_spinner = _FakeSpinner()
        self.random_ip_status_dot = _FakeDot()
        self.random_ip_status_label = _FakeLabel()
        self.random_ip_status_row = _FakeLabel()
        self._randomIpHeartbeatUpdated = _FakeSignal()
        self._random_ip_status_fetch_lock = threading.Lock()
        self._random_ip_status_fetching = False
        self._ip_low_infobar = _FakeInfoBar()
        self._ip_cost_infobar = _FakeInfoBar()
        self._ip_benefit_infobar = _FakeInfoBar()
        self._ip_cost_adjust_link = _FakeLabel()
        self._ip_low_infobar_dismissed = False
        self._ip_low_threshold = 0.0
        self.low_infobar_calls = []
        self.cost_infobar_calls = []
        self.sync_calls = []
        self.controller = SimpleNamespace(
            set_runtime_ui_state=lambda **kwargs: self.sync_calls.append(("ui_state", kwargs)),
            get_runtime_ui_state=lambda: {
                "proxy_source": "default",
                "timed_mode_enabled": False,
                "random_ip_enabled": True,
            },
            request_toggle_random_ip=lambda enabled, adapter=None: bool(enabled),
            adapter="adapter",
            refresh_random_ip_counter=lambda: self.sync_calls.append(("refresh_counter",)),
        )

    def _update_ip_low_infobar(self, count: float, limit: float, custom_api: bool) -> None:
        self.low_infobar_calls.append((count, limit, custom_api))

    def _update_ip_cost_infobar(self, custom_api: bool) -> None:
        self.cost_infobar_calls.append(bool(custom_api))

    def _sync_random_ip_toggle_presentation(self, enabled: bool) -> None:
        self.sync_calls.append(bool(enabled))

    def window(self):
        return getattr(self, "_window", self)


class DashboardRandomIPTests:
    def test_counter_card_shows_remaining_quota_and_inverse_warning_colors(self, monkeypatch) -> None:
        dashboard = _FakeDashboard()

        monkeypatch.setattr(
            dashboard_random_ip,
            "get_session_snapshot",
            lambda: {
                "authenticated": True,
                "user_id": 7,
                "remaining_quota": 2,
                "total_quota": 10,
            },
        )
        monkeypatch.setattr(dashboard_random_ip, "has_authenticated_session", lambda: True)
        monkeypatch.setattr(dashboard_random_ip, "has_unknown_local_quota", lambda _snapshot: False)
        monkeypatch.setattr(dashboard_random_ip, "is_quota_exhausted", lambda _snapshot: False)
        monkeypatch.setattr(dashboard_random_ip, "load_shop_icon", lambda: None)

        dashboard.update_random_ip_counter(8, 10, False)

        assert dashboard.card_btn.text == "额度兑换"
        assert dashboard.random_ip_usage_ring.format_text == "2/10"
        assert dashboard.random_ip_usage_ring.value == 20
        assert dashboard.random_ip_usage_ring.colors == ("#c77900", "#ffb347")
        assert dashboard.random_ip_usage_ring.paused is False
        assert dashboard.random_ip_usage_ring.error is False

    def test_status_heartbeat_fetch_and_apply(self, monkeypatch) -> None:
        dashboard = _FakeDashboard()
        monkeypatch.setattr(
            dashboard_random_ip,
            "set_indeterminate_progress_ring_active",
            lambda ring, active: setattr(ring, "active", bool(active)),
        )
        monkeypatch.setattr(
            dashboard_random_ip.http_client,
            "post",
            lambda *args, **kwargs: SimpleNamespace(status_code=204),
        )
        payload = dashboard._fetch_random_ip_heartbeat_status()
        assert payload["level"] == "success"

        dashboard._apply_random_ip_heartbeat_status(
            {"level": "error", "text": "挂了", "tooltip": "HTTP 500"}
        )
        assert dashboard.random_ip_status_spinner.visible is False
        assert "#C42B1C" in dashboard.random_ip_status_dot.style
        assert dashboard.random_ip_status_label.text == "挂了"
        assert dashboard.random_ip_status_row.tooltip == "HTTP 500"

        monkeypatch.setattr(
            dashboard_random_ip.http_client,
            "post",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        dashboard._run_random_ip_heartbeat_fetch()
        assert dashboard._randomIpHeartbeatUpdated.calls[-1][0]["text"] == "HTTP 0"

    def test_init_random_ip_status_refresh_and_async_guard(self, monkeypatch) -> None:
        dashboard = _FakeDashboard()
        monkeypatch.setattr(
            dashboard_random_ip,
            "set_indeterminate_progress_ring_active",
            lambda ring, active: setattr(ring, "active", bool(active)),
        )
        monkeypatch.setattr("PySide6.QtCore.QTimer", _FakeTimer)
        refresh_calls = []
        dashboard.refresh_random_ip_heartbeat_async = lambda: refresh_calls.append("refresh")
        dashboard._init_random_ip_status_refresh()
        assert dashboard.random_ip_status_spinner.visible is True
        assert dashboard.random_ip_status_spinner.active is True
        assert dashboard.random_ip_status_label.visible is False
        assert dashboard.random_ip_status_timer.interval == 60000
        assert dashboard.random_ip_status_timer.started == 1
        assert refresh_calls == ["refresh"]

        started = []

        class _Thread:
            def __init__(self, *, target=None, daemon=False, name="") -> None:
                self.target = target
                self.name = name
                started.append(self)

            def start(self) -> None:
                return

        monkeypatch.setattr(dashboard_random_ip.threading, "Thread", _Thread)
        dashboard.refresh_random_ip_heartbeat_async = DashboardRandomIPMixin.refresh_random_ip_heartbeat_async.__get__(dashboard, _FakeDashboard)
        dashboard.refresh_random_ip_heartbeat_async()
        dashboard._random_ip_status_fetching = True
        dashboard.refresh_random_ip_heartbeat_async()
        assert len(started) == 1

    def test_sync_loading_toggle_and_cost_infobars(self, monkeypatch) -> None:
        dashboard = _FakeDashboard()
        dashboard._sync_random_ip_usage_ring(mode="paused", percent=9, format_text="待校验")
        assert dashboard.random_ip_usage_ring.paused is True
        assert dashboard.random_ip_usage_ring.format_text == "待校验"

        monkeypatch.setattr(dashboard_random_ip, "themeColor", lambda: QColor("#123456"))
        dashboard._apply_random_ip_usage_ring_color(80)
        assert dashboard.random_ip_usage_ring.colors == ("#123456", "#123456")

        dashboard.set_random_ip_loading(True, "同步中")
        assert dashboard.random_ip_row.loading_calls == [(True, "同步中")]

        monkeypatch.setattr(
            dashboard_random_ip,
            "get_random_ip_counter_snapshot_local",
            lambda: (1, 2, True),
        )
        dashboard._refresh_ip_cost_infobar()
        assert dashboard.cost_infobar_calls[-1] is True

        dashboard._set_ip_cost_infobar_state(title="注意", content="很贵", show_adjust_link=True)
        assert dashboard._ip_cost_infobar.title == "注意"
        assert dashboard._ip_cost_infobar.content == "很贵"
        assert dashboard._ip_cost_adjust_link.visible is True
        assert dashboard._ip_cost_infobar.shown == 1

        dashboard.controller = SimpleNamespace(
            get_runtime_ui_state=lambda: {"proxy_source": "benefit", "timed_mode_enabled": False}
        )
        DashboardRandomIPMixin._update_ip_cost_infobar(dashboard, False)
        assert dashboard._ip_benefit_infobar.shown == 1

    def test_open_dialogs_toggle_and_low_quota_infobars(self, monkeypatch) -> None:
        dashboard = _FakeDashboard()
        dashboard.random_ip_cb.setChecked(True)
        monkeypatch.setattr(dashboard_random_ip, "has_authenticated_session", lambda: False)
        monkeypatch.setattr(
            dashboard_random_ip,
            "get_session_snapshot",
            lambda: {"authenticated": False, "remaining_quota": 0, "total_quota": 0},
        )
        monkeypatch.setattr(dashboard_random_ip, "has_unknown_local_quota", lambda _snapshot: False)
        monkeypatch.setattr(dashboard_random_ip, "is_quota_exhausted", lambda _snapshot: False)
        monkeypatch.setattr(dashboard_random_ip, "load_shop_icon", lambda: None)
        dashboard.update_random_ip_counter(0, 0, False)
        assert dashboard.random_ip_cb.isChecked() is False
        assert dashboard.sync_calls[-2:] == [False, ("ui_state", {"random_ip_enabled": False})]

        dashboard._on_random_ip_toggled(False)
        assert dashboard.random_ip_cb.isChecked() is True
        assert dashboard.sync_calls[-1] is True

        dashboard._window = SimpleNamespace(
            _open_contact_dialog=lambda default_type, lock_message_type: (
                default_type,
                lock_message_type,
            ),
            _open_quota_redeem_dialog=lambda: True,
        )
        assert dashboard._open_contact_dialog("报错反馈") == ("报错反馈", False)
        assert dashboard._open_contact_dialog("额度申请", lock_message_type=True) == (
            "额度申请",
            True,
        )
        assert dashboard._open_quota_redeem_dialog() is True
        dashboard._on_request_quota_clicked()
        assert ("refresh_counter",) not in dashboard.sync_calls

        monkeypatch.setattr(dashboard_random_ip, "has_authenticated_session", lambda: True)
        DashboardRandomIPMixin._update_ip_low_infobar(dashboard, 9, 10, False)
        assert dashboard._ip_low_infobar.shown == 1
        dashboard._on_ip_low_infobar_closed()
        assert dashboard._ip_low_infobar_dismissed is True
        DashboardRandomIPMixin._on_ip_balance_checked(dashboard, 99)
        assert dashboard._ip_low_infobar.hidden >= 1

    def test_open_dialog_methods_require_main_window_handlers(self) -> None:
        dashboard = _FakeDashboard()

        try:
            dashboard._open_contact_dialog()
        except RuntimeError as exc:
            assert "主窗口不支持联系开发者弹窗" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")

        try:
            dashboard._open_quota_redeem_dialog()
        except RuntimeError as exc:
            assert "主窗口不支持额度兑换弹窗" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
