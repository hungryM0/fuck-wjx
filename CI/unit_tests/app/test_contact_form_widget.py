from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QColor, QGuiApplication, QImage

import software.ui.widgets.contact_form.ui_behavior as behavior_module
import software.ui.widgets.contact_form.widget as widget_module
from software.core.config.schema import RuntimeConfig
from software.ui.widgets.contact_form.constants import REQUEST_MESSAGE_TYPE
from software.ui.widgets.contact_form.widget import ContactForm


class _InfoBarRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def warning(self, _title: str, message: str, **_kwargs):
        self.calls.append(("warning", message))
        return None

    def error(self, _title: str, message: str, **_kwargs):
        self.calls.append(("error", message))
        return None

    def success(self, _title: str, message: str, **_kwargs):
        self.calls.append(("success", message))
        return None


def _patch_contact_form_dependencies(monkeypatch, *, user_id: int = 0) -> _InfoBarRecorder:
    recorder = _InfoBarRecorder()
    monkeypatch.setattr(widget_module, "get_session_snapshot", lambda: {"user_id": user_id})
    monkeypatch.setattr(widget_module, "InfoBar", recorder)
    monkeypatch.setattr(behavior_module, "InfoBar", recorder)
    monkeypatch.setattr(widget_module, "set_indeterminate_progress_ring_active", lambda *_args: None)
    monkeypatch.setattr(widget_module, "save_config", lambda _cfg, path: Path(path).write_text("{}", encoding="utf-8"))
    monkeypatch.setattr(widget_module, "export_full_log_to_file", lambda _root, path, **_kwargs: Path(path).write_text("log", encoding="utf-8"))
    monkeypatch.setattr(widget_module, "get_user_local_data_root", lambda: "root")
    return recorder


def _select_message_type(form: ContactForm, text: str) -> None:
    idx = form.type_combo.findText(text)
    assert idx >= 0
    form.type_combo.setCurrentIndex(idx)
    form._on_type_changed()


def test_contact_form_builds_and_switches_between_feedback_and_quota(monkeypatch, qtbot) -> None:
    _patch_contact_form_dependencies(monkeypatch, user_id=0)
    form = ContactForm(default_type="报错反馈", manage_polling=False)
    qtbot.addWidget(form)
    form._on_type_changed()

    assert not form.issue_title_edit.isHidden()
    assert not form.auto_attach_section.isHidden()
    assert not form.attachments_section.isHidden()
    assert form.send_btn.isEnabled()

    _select_message_type(form, REQUEST_MESSAGE_TYPE)

    assert form.attachments_section.isHidden()
    assert not form.request_payment_section.isHidden()
    assert not form.verify_code_edit.isHidden()
    assert not form.send_btn.isEnabled()
    assert "支付方式" in form.send_btn.toolTip()

    monkeypatch.setattr(widget_module, "get_session_snapshot", lambda: {"user_id": 42})
    form.refresh_random_ip_user_id_hint()
    form.payment_method_wechat_radio.setChecked(True)
    form.amount_edit.setText("11.45")
    form.quantity_edit.setText("1500")
    form.donated_cb.setChecked(True)
    form._update_send_button_state()

    assert form.send_btn.isEnabled()
    assert not form.random_ip_user_id_label.isHidden()
    assert "42" in form.random_ip_user_id_label.text()


def test_contact_form_amount_quantity_boundaries_and_status(monkeypatch, qtbot) -> None:
    _patch_contact_form_dependencies(monkeypatch, user_id=7)
    form = ContactForm(default_type=REQUEST_MESSAGE_TYPE, manage_polling=False)
    qtbot.addWidget(form)
    form._on_type_changed()

    form.quantity_edit.setText("25000")
    form._on_quantity_changed("25000")
    assert form.quantity_edit.text() == ""

    form.quantity_edit.setText("2000")
    form._on_quantity_changed("2000")
    form.amount_edit.setText("8.88")
    form._sync_amount_rule_warning()
    assert not form.amount_rule_hint.isHidden()

    form.amount_edit.setText("20.26")
    form._sync_amount_rule_warning()
    assert form.amount_rule_hint.isHidden()

    form._on_status_loaded("在线", "#228b22")
    assert form.online_label.text() == "在线"
    form._on_status_loaded("离线", "#cc0000")
    assert form.online_label.text() == "离线"
    form._on_status_loaded("未知", "#666666")
    assert form.online_label.text() == "未知"


def test_contact_form_attachment_render_choose_clipboard_and_cleanup(monkeypatch, qtbot, tmp_path) -> None:
    recorder = _patch_contact_form_dependencies(monkeypatch, user_id=0)
    form = ContactForm(default_type="报错反馈", manage_polling=False)
    qtbot.addWidget(form)
    form._on_type_changed()

    image_path = tmp_path / "shot.png"
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(image_path))

    monkeypatch.setattr(
        behavior_module.QFileDialog,
        "getOpenFileNames",
        lambda *_args, **_kwargs: ([str(image_path)], ""),
    )
    form._on_choose_files()
    assert len(form._attachments.attachments) == 1
    assert form.attach_clear_btn.isEnabled()

    form._remove_attachment(0)
    assert len(form._attachments.attachments) == 0
    assert not form.attach_placeholder.isHidden()

    QGuiApplication.clipboard().setImage(image)
    assert form._handle_clipboard_image() is True
    assert len(form._attachments.attachments) == 1

    form._attachments.max_count = 1
    assert form._handle_clipboard_image() is True
    assert recorder.calls[-1][0] == "error"

    form._on_clear_attachments()
    assert len(form._attachments.attachments) == 0


def test_contact_form_send_validation_and_completion_paths(monkeypatch, qtbot) -> None:
    recorder = _patch_contact_form_dependencies(monkeypatch, user_id=0)
    form = ContactForm(default_type="纯聊天", manage_polling=False, auto_clear_on_success=True)
    qtbot.addWidget(form)
    _select_message_type(form, "纯聊天")

    form._on_send_clicked()
    assert recorder.calls[-1] == ("warning", "请输入消息内容")

    form.message_edit.setPlainText("hello")
    form.email_edit.setText("bad-email")
    form._on_send_clicked()
    assert recorder.calls[-1] == ("warning", "邮箱格式不正确")

    form._send_in_progress = True
    assert form.has_pending_async_work() is True
    form._on_send_finished(False, "boom")
    assert recorder.calls[-1] == ("error", "boom")
    assert form.has_pending_async_work() is False

    form._attachments.add_qimage(QImage(8, 8, QImage.Format.Format_RGB32), "empty.png")
    form._current_message_type = "报错反馈"
    form._current_has_email = True
    form.message_edit.setPlainText("sent")
    form.issue_title_edit.setText("title")
    form._on_send_finished(True, "")
    assert recorder.calls[-1][0] == "success"
    assert form.message_edit.toPlainText() == ""
    assert form.issue_title_edit.text() == ""
    assert len(form._attachments.attachments) == 0


def test_contact_form_bug_report_auto_payload_and_verify_code(monkeypatch, qtbot) -> None:
    recorder = _patch_contact_form_dependencies(monkeypatch, user_id=0)
    form = ContactForm(
        default_type="报错反馈",
        manage_polling=False,
        config_snapshot_provider=lambda: RuntimeConfig(target=3, threads=1),
    )
    qtbot.addWidget(form)

    files, errors = form._build_bug_report_auto_files_payload()
    assert errors == ["当前运行配置快照：已附带", "当前日志快照：已附带", "fatal_crash.log：未发现"]
    assert {label for label, _payload in files} == {"配置快照", "日志快照"}

    form._verify_code_sending = True
    form._on_send_verify_clicked()
    assert recorder.calls == []

    form._verify_code_sending = False
    form.email_edit.setText("")
    form._on_send_verify_clicked()
    assert recorder.calls[-1] == ("warning", "请先填写邮箱地址")

    form._on_verify_code_finished(True, "", "a@example.com")
    assert form._verify_code_requested is True
    assert form._verify_code_requested_email == "a@example.com"
    form._stop_cooldown()

    form._on_verify_code_finished(False, "invalid request", "a@example.com")
    assert recorder.calls[-1] == ("error", "邮箱参数无效，请检查邮箱后重试")

    host = SimpleNamespace(controller=object())
    monkeypatch.setattr(form, "parentWidget", lambda: host)
    assert form._find_controller_host() is host
