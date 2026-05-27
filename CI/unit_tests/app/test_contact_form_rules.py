from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import software.ui.widgets.contact_form.widget as contact_widget
from software.ui.widgets.contact_form.attachments import (
    build_bug_report_auto_files_payload,
    cleanup_pending_temp_files,
    fatal_crash_log_payload,
    read_file_bytes,
    remove_temp_file,
    renumber_files_payload,
)
from software.ui.widgets.contact_form.constants import (
    DONATION_AMOUNT_BLOCK_MESSAGE,
    MAX_REQUEST_QUOTA,
    REQUEST_MESSAGE_TYPE,
)
from software.ui.widgets.contact_form.send_workflow import (
    QuotaRequestValidationInputs,
    compute_send_timeout_fallback_ms,
    validate_email,
    validate_quota_request,
)


class _FakeLineEdit:
    def __init__(self, text: str = "") -> None:
        self._text = text
        self.block_calls: list[bool] = []
        self.selection = None
        self.focused = 0
        self.enabled = True

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = str(text)

    def clear(self) -> None:
        self._text = ""

    def blockSignals(self, value: bool) -> bool:
        self.block_calls.append(bool(value))
        return False

    def setSelection(self, start: int, length: int) -> None:
        self.selection = (start, length)

    def setFocus(self) -> None:
        self.focused += 1

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _FakeComboBox:
    def __init__(self, text: str = "", options: list[str] | None = None) -> None:
        self._text = text
        self.options = list(options or [])
        self.block_calls: list[bool] = []
        self._currentIndex = 0 if self.options else -1
        self.focused = 0
        self.enabled = True

    def currentText(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = str(text)

    def clear(self) -> None:
        self.options.clear()

    def addItem(self, text: str) -> None:
        self.options.append(str(text))

    def findText(self, text: str) -> int:
        try:
            return self.options.index(text)
        except ValueError:
            return -1

    def setCurrentIndex(self, index: int) -> None:
        self._currentIndex = int(index)
        if 0 <= index < len(self.options):
            self._text = self.options[index]

    def blockSignals(self, value: bool) -> bool:
        self.block_calls.append(bool(value))
        return False

    def setFocus(self) -> None:
        self.focused += 1

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _FakeCheckBox:
    def __init__(self, checked: bool = False) -> None:
        self.checked = checked
        self.block_calls: list[bool] = []

    def isChecked(self) -> bool:
        return self.checked

    def setChecked(self, checked: bool) -> None:
        self.checked = bool(checked)

    def blockSignals(self, value: bool) -> bool:
        self.block_calls.append(bool(value))
        return False


class _FakeTextEdit:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def toPlainText(self) -> str:
        return self._text

    def clear(self) -> None:
        self._text = ""


class _FakeAttachments:
    def __init__(self, payload: list[Any] | None = None) -> None:
        self._payload = list(payload or [])
        self.cleared = 0

    def files_payload(self) -> list[Any]:
        return list(self._payload)

    def clear(self) -> None:
        self.cleared += 1


class _FakeInfoBar:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def warning(self, *args, **kwargs) -> None:
        self.calls.append(("warning", args, kwargs))

    def error(self, *args, **kwargs) -> None:
        self.calls.append(("error", args, kwargs))

    def success(self, *args, **kwargs) -> None:
        self.calls.append(("success", args, kwargs))


class _FakeMessageBox:
    next_exec_result = True

    def __init__(self, title: str, message: str, _parent) -> None:
        self.title = title
        self.message = message
        self.yesButton = SimpleNamespace(setText=lambda _text: None)
        self.cancelButton = SimpleNamespace(setText=lambda _text: None, hide=lambda: None)

    def exec(self) -> bool:
        return bool(self.next_exec_result)

    def open(self) -> None:
        return


class _FakeTimer:
    scheduled: list[tuple[int, Any, Any]] = []

    @staticmethod
    def singleShot(delay: int, receiver, callback=None) -> None:
        if callback is None:
            callback = receiver
            receiver = None
        _FakeTimer.scheduled.append((int(delay), receiver, callback))
        callback()


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeContactForm:
    _parse_quantity_value = contact_widget.ContactForm._parse_quantity_value
    _normalize_quantity_text = contact_widget.ContactForm._normalize_quantity_text
    _normalize_quantity_if_needed = contact_widget.ContactForm._normalize_quantity_if_needed
    _parse_amount_value = contact_widget.ContactForm._parse_amount_value
    _get_donation_check_block_reason = contact_widget.ContactForm._get_donation_check_block_reason
    _sync_donation_check_state = contact_widget.ContactForm._sync_donation_check_state
    _normalize_amount_if_needed = contact_widget.ContactForm._normalize_amount_if_needed
    _on_quantity_changed = contact_widget.ContactForm._on_quantity_changed
    _get_minimum_allowed_amount = contact_widget.ContactForm._get_minimum_allowed_amount
    _get_allowed_amount_options = contact_widget.ContactForm._get_allowed_amount_options
    _is_amount_allowed = contact_widget.ContactForm._is_amount_allowed
    _refresh_amount_options = contact_widget.ContactForm._refresh_amount_options
    _sync_amount_rule_warning = contact_widget.ContactForm._sync_amount_rule_warning
    _cleanup_pending_temp_files = contact_widget.ContactForm._cleanup_pending_temp_files
    _read_file_bytes = staticmethod(contact_widget.ContactForm._read_file_bytes)
    _remove_temp_file = staticmethod(contact_widget.ContactForm._remove_temp_file)
    _export_bug_report_config_snapshot = contact_widget.ContactForm._export_bug_report_config_snapshot
    _export_bug_report_log_snapshot = contact_widget.ContactForm._export_bug_report_log_snapshot
    _fatal_crash_log_payload = staticmethod(contact_widget.ContactForm._fatal_crash_log_payload)
    _renumber_files_payload = staticmethod(contact_widget.ContactForm._renumber_files_payload)
    _build_bug_report_auto_files_payload = contact_widget.ContactForm._build_bug_report_auto_files_payload
    _validate_email = contact_widget.ContactForm._validate_email
    _compute_send_timeout_fallback_ms = contact_widget.ContactForm._compute_send_timeout_fallback_ms
    _clear_email_selection = contact_widget.ContactForm._clear_email_selection
    _focus_send_button = contact_widget.ContactForm._focus_send_button
    _on_send_finished = contact_widget.ContactForm._on_send_finished
    _find_controller_host = contact_widget.ContactForm._find_controller_host
    _on_send_clicked = contact_widget.ContactForm._on_send_clicked

    _SEND_CONNECT_TIMEOUT_SECONDS = 5
    _SEND_READ_TIMEOUT_SECONDS = 10
    _SEND_READ_TIMEOUT_WITH_FILES_SECONDS = 30
    _SEND_TIMEOUT_GRACE_MS = 1500

    def __init__(self) -> None:
        self.quantity_edit = _FakeLineEdit("")
        self.amount_edit = _FakeComboBox("", ["8.88", "11.45", "20.26", "50", "78.91", "114.51"])
        self.type_combo = _FakeComboBox("报错反馈")
        self.message_edit = _FakeTextEdit("")
        self.email_edit = _FakeLineEdit("")
        self.issue_title_edit = _FakeLineEdit("")
        self.urgency_combo = _FakeComboBox("中", ["低", "中", "高"])
        self.donated_cb = _FakeCheckBox(False)
        self.wechat_radio = _FakeCheckBox(False)
        self.alipay_radio = _FakeCheckBox(False)
        self.send_btn = _FakeLineEdit("")
        self.auto_attach_config_checkbox = _FakeCheckBox(False)
        self.auto_attach_log_checkbox = _FakeCheckBox(False)
        self.status_icon = SimpleNamespace(show=lambda: None, setIcon=lambda _icon: None)
        self.online_label = SimpleNamespace(setText=lambda _text: None, setStyleSheet=lambda _style: None)
        self.amount_rule_hint = SimpleNamespace(show=lambda: self.rule_actions.append("show"), hide=lambda: self.rule_actions.append("hide"))
        self._attachments = _FakeAttachments([])
        self._pending_temp_attachment_paths: list[str] = []
        self._random_ip_user_id = 0
        self._last_valid_quantity_text = ""
        self._send_in_progress = False
        self._send_state_lock = _FakeLock()
        self._send_generation = 0
        self._send_finished_generation = 0
        self._current_message_type = ""
        self._current_has_email = False
        self._auto_clear_on_success = True
        self._config_snapshot_provider: Any = None
        self.rule_actions: list[str] = []
        self.sendSucceeded = _FakeSignal()
        self.quotaRequestSucceeded = _FakeSignal()
        self._sendFinished = _FakeSignal()
        self.parent_widget: Any = None
        self.controller: Any = None

    def _selected_payment_method(self) -> str:
        if self.wechat_radio.isChecked():
            return "微信"
        if self.alipay_radio.isChecked():
            return "支付宝"
        return ""

    def _show_amount_rule_infobar(self) -> None:
        self.rule_actions.append("show")

    def _close_amount_rule_infobar(self) -> None:
        self.rule_actions.append("hide")

    def _update_send_button_state(self) -> None:
        self.rule_actions.append("update")

    def refresh_random_ip_user_id_hint(self) -> None:
        return

    def _clear_payment_method_selection(self) -> None:
        self.wechat_radio.setChecked(False)
        self.alipay_radio.setChecked(False)

    def _render_attachments_ui(self) -> None:
        return

    def _reset_bug_report_auto_attach_defaults(self) -> None:
        self.auto_attach_config_checkbox.setChecked(False)
        self.auto_attach_log_checkbox.setChecked(False)

    def _is_bug_report_type(self, message_type: str) -> bool:
        return message_type == "报错反馈"

    def _set_send_loading(self, loading: bool) -> None:
        self.rule_actions.append(f"send:{loading}")

    def window(self):
        return self.parent_widget

    def parentWidget(self):
        return self.parent_widget


class ContactFormRuleTests:
    def test_send_workflow_helpers(self) -> None:
        assert compute_send_timeout_fallback_ms(
            connect_timeout_seconds=5,
            read_timeout_seconds=10,
            grace_ms=1500,
        ) == 26500
        assert validate_email("") is True
        assert validate_email("user@example.com") is True
        assert validate_email("bad@@mail") is False

        result = validate_quota_request(
            QuotaRequestValidationInputs(
                email="user@example.com",
                amount_text="20.26",
                quantity_text="2000",
                payment_method="微信",
                donated=True,
            )
        )
        assert result.error_message is None
        assert result.normalized_quota_text == "2000"

        blocked = validate_quota_request(
            QuotaRequestValidationInputs(
                email="user@example.com",
                amount_text="8.88",
                quantity_text="2000",
                payment_method="微信",
                donated=True,
            )
        )
        assert blocked.error_message == DONATION_AMOUNT_BLOCK_MESSAGE
        assert blocked.amount_rule_blocked is True

    def test_attachment_helpers_module(self, tmp_path: Path) -> None:
        removed_errors: list[tuple[str, Exception]] = []
        file_path = tmp_path / "a.txt"
        file_path.write_bytes(b"abc")
        assert read_file_bytes(str(file_path)) == b"abc"
        remove_temp_file(
            str(file_path),
            on_error=lambda path, exc: removed_errors.append((path, exc)),
        )
        assert not file_path.exists()
        assert removed_errors == []

        temp_path = tmp_path / "temp.txt"
        temp_path.write_text("x", encoding="utf-8")
        remaining = cleanup_pending_temp_files(
            [str(temp_path)],
            on_error=lambda path, exc: removed_errors.append((path, exc)),
        )
        assert remaining == []
        assert not temp_path.exists()

        fatal = tmp_path / "fatal_crash.log"
        fatal.write_text("boom", encoding="utf-8")
        assert fatal_crash_log_payload(str(fatal)) == (
            "fatal_crash.log",
            ("fatal_crash.log", b"boom", "text/plain"),
        )
        assert renumber_files_payload(
            [
                ("配置快照", ("cfg.json", b"{}", "application/json")),
                ("日志快照", ("log.txt", b"log", "text/plain")),
            ]
        ) == [
            ("file1", ("cfg.json", b"{}", "application/json")),
            ("file2", ("log.txt", b"log", "text/plain")),
        ]

        payload, summary = build_bug_report_auto_files_payload(
            auto_attach_config=True,
            auto_attach_log=True,
            export_config_snapshot=lambda: ("配置快照", ("cfg.json", b"{}", "application/json")),
            export_log_snapshot=lambda: ("日志快照", ("log.txt", b"log", "text/plain")),
            get_fatal_payload=lambda: ("fatal_crash.log", ("fatal_crash.log", b"x", "text/plain")),
        )
        assert [item[0] for item in payload] == ["配置快照", "日志快照", "fatal_crash.log"]
        assert "fatal_crash.log：已附带" in summary

    def test_quantity_and_amount_parsing_rules(self) -> None:
        form = _FakeContactForm()

        assert form._parse_quantity_value("1.5") == Decimal("1.5")
        assert form._parse_quantity_value("1.2") is None
        assert form._parse_quantity_value("-1") is None
        assert form._normalize_quantity_text("1.50") == "1.5"

        form.quantity_edit.setText("2.50")
        form._normalize_quantity_if_needed()
        assert form.quantity_edit.text() == "2.5"

        form.quantity_edit.setText(str(MAX_REQUEST_QUOTA + 1))
        form._last_valid_quantity_text = "19999"
        form._normalize_quantity_if_needed()
        assert form.quantity_edit.text() == "19999"

        assert form._parse_amount_value("8.88") == Decimal("8.88")
        assert form._parse_amount_value("0") is None
        assert form._parse_amount_value("-1") is None

    def test_donation_block_reason_and_checkbox_sync(self) -> None:
        form = _FakeContactForm()
        form.type_combo.setText(REQUEST_MESSAGE_TYPE)
        assert "支付方式" in form._get_donation_check_block_reason()

        form.wechat_radio.setChecked(True)
        assert "支付金额" in form._get_donation_check_block_reason()

        form.amount_edit.setText("8.88")
        assert "暂时不能勾选" in form._get_donation_check_block_reason()

        form._random_ip_user_id = 7
        assert form._get_donation_check_block_reason() == ""

        form.donated_cb.setChecked(True)
        form._random_ip_user_id = 0
        form._sync_donation_check_state()
        assert form.donated_cb.isChecked() is False

    def test_quantity_change_and_amount_rule_logic(self) -> None:
        form = _FakeContactForm()
        form.quantity_edit.setText("1.0")
        form._on_quantity_changed("1.0")
        assert form._last_valid_quantity_text == "1"

        form.quantity_edit.setText(str(MAX_REQUEST_QUOTA + 1))
        form._last_valid_quantity_text = "10"
        form._on_quantity_changed(str(MAX_REQUEST_QUOTA + 1))
        assert form.quantity_edit.text() == "10"

        assert form._get_minimum_allowed_amount(Decimal("0")) == Decimal("8.88")
        assert form._get_minimum_allowed_amount(Decimal("1500")) == Decimal("11.45")
        assert form._get_allowed_amount_options(Decimal("3500")) == ["50", "78.91", "114.51"]
        assert form._is_amount_allowed("20.26", "2000") is True
        assert form._is_amount_allowed("8.88", "2000") is False

        form.type_combo.setText(REQUEST_MESSAGE_TYPE)
        form.amount_edit.setText("8.88")
        form.quantity_edit.setText("2000")
        form._sync_amount_rule_warning()
        assert form.rule_actions[-1] == "show"

        form.amount_edit.setText("20.26")
        form._sync_amount_rule_warning()
        assert form.rule_actions[-1] == "hide"

    def test_cleanup_temp_files_and_file_helpers(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        form = _FakeContactForm()
        target = tmp_path / "temp.txt"
        target.write_text("abc", encoding="utf-8")
        form._pending_temp_attachment_paths = [str(target)]
        form._cleanup_pending_temp_files()
        assert not target.exists()
        assert form._pending_temp_attachment_paths == []

        target.write_bytes(b"123")
        assert form._read_file_bytes(str(target)) == b"123"
        form._remove_temp_file(str(target))
        assert not target.exists()

    def test_bug_report_auto_files_payload_and_email_validation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        form = _FakeContactForm()
        form.auto_attach_config_checkbox.setChecked(True)
        form.auto_attach_log_checkbox.setChecked(True)
        monkeypatch.setattr(form, "_export_bug_report_config_snapshot", lambda: ("配置快照", ("cfg.json", b"{}", "application/json")))
        monkeypatch.setattr(form, "_export_bug_report_log_snapshot", lambda: ("日志快照", ("log.txt", b"log", "text/plain")))
        monkeypatch.setattr(
            _FakeContactForm,
            "_fatal_crash_log_payload",
            staticmethod(lambda: ("fatal_crash.log", ("fatal_crash.log", b"x", "text/plain"))),
        )

        payload, summary = form._build_bug_report_auto_files_payload()
        assert [item[0] for item in payload] == ["配置快照", "日志快照", "fatal_crash.log"]
        assert "fatal_crash.log：已附带" in summary

        assert form._renumber_files_payload(payload) == [
            ("file1", ("cfg.json", b"{}", "application/json")),
            ("file2", ("log.txt", b"log", "text/plain")),
            ("file3", ("fatal_crash.log", b"x", "text/plain")),
        ]
        assert form._validate_email("") is True
        assert form._validate_email("user@example.com") is True
        assert form._validate_email("bad@@mail") is False

    def test_export_snapshot_helpers(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        form = _FakeContactForm()
        form._config_snapshot_provider = lambda: SimpleNamespace(name="cfg")
        monkeypatch.setattr(contact_widget, "save_config", lambda cfg, path: Path(path).write_text("{}", encoding="utf-8"))
        monkeypatch.setattr(contact_widget.tempfile, "gettempdir", lambda: str(tmp_path))
        label, (file_name, data, mime) = form._export_bug_report_config_snapshot()
        assert label == "配置快照"
        assert file_name.endswith(".json")
        assert data == b"{}"
        assert mime == "application/json"

        monkeypatch.setattr(contact_widget, "export_full_log_to_file", lambda _root, path, fallback_records: Path(path).write_text("log", encoding="utf-8"))
        monkeypatch.setattr(contact_widget, "get_user_local_data_root", lambda: str(tmp_path))
        monkeypatch.setattr(contact_widget.LOG_BUFFER_HANDLER, "get_records", lambda: ["x"])
        label2, (file_name2, data2, mime2) = form._export_bug_report_log_snapshot()
        assert label2 == "日志快照"
        assert file_name2.endswith(".txt")
        assert data2 == b"log"
        assert mime2 == "text/plain"

        fatal = tmp_path / "fatal_crash.log"
        fatal.write_text("boom", encoding="utf-8")
        monkeypatch.setattr(contact_widget, "get_fatal_crash_log_path", lambda: str(fatal))
        assert form._fatal_crash_log_payload() == (
            "fatal_crash.log",
            ("fatal_crash.log", b"boom", "text/plain"),
        )

    def test_send_timeout_and_send_finished_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        form = _FakeContactForm()
        info_bar = _FakeInfoBar()
        monkeypatch.setattr(contact_widget, "InfoBar", info_bar)

        assert form._compute_send_timeout_fallback_ms(10) == 26500

        form.email_edit.setText("test@example.com")
        form._clear_email_selection()
        assert form.email_edit.selection == (0, 0)
        form._focus_send_button()
        assert form.send_btn.focused == 1

        form._current_message_type = REQUEST_MESSAGE_TYPE
        form._current_has_email = True
        form.amount_edit.setText("20.26")
        form.quantity_edit.setText("10")
        form.message_edit = _FakeTextEdit("msg")
        form.issue_title_edit.setText("bug")
        form.wechat_radio.setChecked(True)
        form.auto_attach_config_checkbox.setChecked(True)
        form.auto_attach_log_checkbox.setChecked(True)
        form._attachments = _FakeAttachments([("file1", ("a.png", b"1", "image/png"))])

        form._on_send_finished(True, "")
        assert form.quotaRequestSucceeded.calls == [()]
        assert form.sendSucceeded.calls == [()]
        assert info_bar.calls[-1][0] == "success"

        form._on_send_finished(False, "炸了")
        assert info_bar.calls[-1] == ("error", ("", "炸了"), {"parent": form, "position": contact_widget.InfoBarPosition.TOP, "duration": 3000})

    def test_find_controller_host_and_send_clicked_validations(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        form = _FakeContactForm()
        info_bar = _FakeInfoBar()
        monkeypatch.setattr(contact_widget, "InfoBar", info_bar)
        monkeypatch.setattr(contact_widget, "QTimer", _FakeTimer)
        monkeypatch.setattr(contact_widget, "MessageBox", _FakeMessageBox)
        monkeypatch.setattr(contact_widget, "CONTACT_API_URL", "https://api.test")
        monkeypatch.setattr(contact_widget, "build_contact_message", lambda **kwargs: "payload")
        monkeypatch.setattr(contact_widget, "build_contact_request_fields", lambda **kwargs: [("message", (None, "payload"))])
        monkeypatch.setattr(contact_widget, "http_post", lambda *args, **kwargs: SimpleNamespace(status_code=200))

        parent = SimpleNamespace(parentWidget=lambda: None, controller=True)
        form.parent_widget = parent
        assert form._find_controller_host() is form

        form.type_combo.setText(REQUEST_MESSAGE_TYPE)
        form._on_send_clicked()
        assert info_bar.calls[-1][1][1] == "请选择你刚刚使用的支付方式"

        form.wechat_radio.setChecked(True)
        form._on_send_clicked()
        assert info_bar.calls[-1][1][1] == "请输入支付金额"

        form.amount_edit.setText("8.88")
        form._on_send_clicked()
        assert info_bar.calls[-1][1][1] == "请先勾选“我已完成支付”后再发送申请"

        form.donated_cb.setChecked(True)
        form._on_send_clicked()
        assert info_bar.calls[-1][1][1] == "请输入申请额度"

        form.quantity_edit.setText("1.2")
        form._on_send_clicked()
        assert "只能填 0.5 的倍数" in info_bar.calls[-1][1][1]

        form.quantity_edit.setText(str(MAX_REQUEST_QUOTA + 1))
        form._on_send_clicked()
        assert info_bar.calls[-1][1][1] == "请输入申请额度"

        form.quantity_edit.setText("2000")
        form._on_send_clicked()
        assert info_bar.calls[-1][1][1] == DONATION_AMOUNT_BLOCK_MESSAGE
