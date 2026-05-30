from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from PySide6.QtCore import QEvent

import software.ui.dialogs.quota_redeem as quota_redeem
from software.ui.dialogs.quota_redeem import QuotaRedeemDialog
from software.ui.helpers.proxy_access import RandomIPAuthError


class _FakeInfoBar:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def warning(self, *args, **kwargs) -> None:
        self.calls.append(("warning", args, kwargs))

    def success(self, *args, **kwargs) -> None:
        self.calls.append(("success", args, kwargs))

    def error(self, *args, **kwargs) -> None:
        self.calls.append(("error", args, kwargs))


class _FakeLineEdit:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def clear(self) -> None:
        self._text = ""


class _FakeLabel:
    def __init__(self) -> None:
        self.value = ""
        self.style = ""

    def setText(self, text: str) -> None:
        self.value = str(text)

    def text(self) -> str:
        return self.value

    def setStyleSheet(self, style: str) -> None:
        self.style = str(style)


class _FakeMessageBox:
    next_exec_result = False

    def __init__(self, title: str, content: str, parent) -> None:
        self.title = title
        self.content = content
        self.parent = parent
        self.yesButton = SimpleNamespace(setText=lambda _text: None)
        self.cancelButton = SimpleNamespace(setText=lambda _text: None)

    def exec(self) -> bool:
        return bool(self.next_exec_result)


class _FakeDialog:
    validate = quota_redeem.QuotaRedeemDialog.validate
    eventFilter = quota_redeem.QuotaRedeemDialog.eventFilter
    _refresh_account_hint = quota_redeem.QuotaRedeemDialog._refresh_account_hint
    _apply_account_hint_style = quota_redeem.QuotaRedeemDialog._apply_account_hint_style
    _on_redeem_finished = quota_redeem.QuotaRedeemDialog._on_redeem_finished

    def __init__(self, *, card_code: str = "") -> None:
        self._redeeming = False
        self.cardCodeEdit = _FakeLineEdit(card_code)
        self.accountHintLabel = _FakeLabel()
        self.pending_warning_calls = 0
        self.layout_calls = 0
        self.set_redeeming_calls: list[bool] = []
        self.accept_calls = 0
        self.yesButton = object()

    def _show_pending_warning(self) -> None:
        self.pending_warning_calls += 1

    def _set_redeeming(self, redeeming: bool) -> None:
        self._redeeming = bool(redeeming)
        self.set_redeeming_calls.append(bool(redeeming))

    def _layout_yes_button_spinner(self) -> None:
        self.layout_calls += 1

    def accept(self) -> None:
        self.accept_calls += 1


class QuotaRedeemDialogTests:
    def test_validate_without_authenticated_session_shows_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dialog = _FakeDialog()
        info_bar = _FakeInfoBar()
        monkeypatch.setattr(quota_redeem, "InfoBar", info_bar)
        monkeypatch.setattr(quota_redeem, "has_authenticated_session", lambda: False)
        monkeypatch.setattr(quota_redeem, "get_session_snapshot", lambda: {})

        assert dialog.validate() is False
        assert info_bar.calls[0][0] == "warning"
        assert "测试随机ip是否真的可用" in info_bar.calls[0][1][1]

    def test_validate_with_empty_card_code_shows_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dialog = _FakeDialog(card_code="   ")
        info_bar = _FakeInfoBar()
        monkeypatch.setattr(quota_redeem, "InfoBar", info_bar)
        monkeypatch.setattr(quota_redeem, "has_authenticated_session", lambda: True)
        monkeypatch.setattr(quota_redeem, "get_session_snapshot", lambda: {"user_id": 7})

        assert dialog.validate() is False
        assert info_bar.calls[0][0] == "warning"
        assert info_bar.calls[0][1][1] == "请输入卡密"

    def test_validate_stops_when_user_cancels_confirmation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dialog = _FakeDialog(card_code="CARD-001")
        monkeypatch.setattr(quota_redeem, "MessageBox", _FakeMessageBox)
        monkeypatch.setattr(quota_redeem, "has_authenticated_session", lambda: True)
        monkeypatch.setattr(quota_redeem, "get_session_snapshot", lambda: {"user_id": 7})
        _FakeMessageBox.next_exec_result = False

        assert dialog.validate() is False
        assert dialog._redeeming is False
        assert dialog.set_redeeming_calls == []

    def test_refresh_account_hint_updates_by_session_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dialog = _FakeDialog()
        monkeypatch.setattr(quota_redeem, "get_session_snapshot", lambda: {})
        monkeypatch.setattr(quota_redeem, "has_authenticated_session", lambda: False)

        dialog._refresh_account_hint()
        assert "请先启用一次随机 IP" in dialog.accountHintLabel.text()

        monkeypatch.setattr(quota_redeem, "get_session_snapshot", lambda: {"user_id": 42})
        monkeypatch.setattr(quota_redeem, "has_authenticated_session", lambda: True)
        dialog._refresh_account_hint()
        assert dialog.accountHintLabel.text() == "用户 ID：42"

    def test_redeem_success_shows_success_and_clears_input(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dialog = _FakeDialog(card_code="CARD-001")
        info_bar = _FakeInfoBar()
        monkeypatch.setattr(quota_redeem, "InfoBar", info_bar)
        monkeypatch.setattr(quota_redeem, "has_authenticated_session", lambda: True)
        monkeypatch.setattr(quota_redeem, "get_session_snapshot", lambda: {"user_id": 7})
        monkeypatch.setattr(quota_redeem.QTimer, "singleShot", lambda _ms, callback: callback())

        dialog._on_redeem_finished(
            True,
            {"card_quota": 5, "remaining_quota": 8, "total_quota": 10},
        )

        assert dialog.set_redeeming_calls == [False]
        assert info_bar.calls[0][0] == "success"
        assert info_bar.calls[0][1][1] == "兑换成功，已到账 5！"
        assert dialog.cardCodeEdit.text() == ""
        assert dialog.accept_calls == 1

    def test_redeem_auth_error_maps_to_readable_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dialog = _FakeDialog()
        info_bar = _FakeInfoBar()
        monkeypatch.setattr(quota_redeem, "InfoBar", info_bar)
        monkeypatch.setattr(quota_redeem, "has_authenticated_session", lambda: True)
        monkeypatch.setattr(quota_redeem, "get_session_snapshot", lambda: {"user_id": 7})
        monkeypatch.setattr(quota_redeem, "format_random_ip_error", lambda exc: f"raw:{exc}")

        dialog._on_redeem_finished(
            False,
            RandomIPAuthError("redeem_card_not_found"),
        )

        assert dialog.set_redeeming_calls == [False]
        assert info_bar.calls[0][0] == "error"
        assert info_bar.calls[0][1][1] == "该卡密不存在，请检查是否输错"

    def test_event_filter_ignores_events_before_yes_button_ready(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dialog = cast(Any, QuotaRedeemDialog.__new__(QuotaRedeemDialog))
        dialog.layout_calls = 0
        dialog._layout_yes_button_spinner = lambda: setattr(dialog, "layout_calls", dialog.layout_calls + 1)
        monkeypatch.setattr(
            quota_redeem.MessageBoxBase,
            "eventFilter",
            lambda self, _obj, _e: False,
        )

        result = quota_redeem.QuotaRedeemDialog.eventFilter(dialog, object(), QEvent(QEvent.Type.Show))

        assert result is False
        assert dialog.layout_calls == 0

    def test_event_filter_relayouts_spinner_for_yes_button_resize(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dialog = cast(Any, QuotaRedeemDialog.__new__(QuotaRedeemDialog))
        dialog.layout_calls = 0
        dialog.yesButton = object()
        dialog._layout_yes_button_spinner = lambda: setattr(dialog, "layout_calls", dialog.layout_calls + 1)
        monkeypatch.setattr(
            quota_redeem.MessageBoxBase,
            "eventFilter",
            lambda self, _obj, _e: False,
        )

        result = quota_redeem.QuotaRedeemDialog.eventFilter(
            dialog,
            dialog.yesButton,
            QEvent(QEvent.Type.Resize),
        )

        assert result is False
        assert dialog.layout_calls == 1
