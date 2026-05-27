"""联系表单界面行为。"""

from typing import Any, cast

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from qfluentwidgets import BodyLabel, ImageLabel, InfoBar, InfoBarPosition, PushButton

from .constants import REQUEST_MESSAGE_TYPE


def sync_message_type_lock_state(form: Any) -> None:
    current_type = form.type_combo.currentText() or ""
    form.type_locked_label.setText(current_type)
    form.type_combo.setVisible(not form._lock_message_type)
    form.type_combo.setEnabled(not form._lock_message_type)
    form.type_locked_label.setVisible(form._lock_message_type)


def on_type_changed(form: Any) -> None:
    current_type = form.type_combo.currentText()
    sync_message_type_lock_state(form)
    is_bug_report = form._is_bug_report_type(current_type)

    if current_type == REQUEST_MESSAGE_TYPE:
        form.attachments_section.hide()
        form.auto_attach_section.hide()
        form.issue_title_label.hide()
        form.issue_title_edit.hide()
        form.issue_title_edit.clear()
        form.request_payment_section.show()
        form.request_payment_confirm_section.show()
        form.amount_label.show()
        form.amount_edit.show()
        form.quantity_label.show()
        form.quantity_edit.show()
        form.urgency_label.show()
        form.urgency_combo.show()
        form.email_edit.setPlaceholderText("name@example.com")
        form.message_label.setText("补充说明（选填）：")
        form.message_edit.setPlaceholderText(
            "请简单说明你的问卷紧急情况或使用场景...\n以及...是大学生吗（？"
        )
    else:
        form.attachments_section.show()
        form.auto_attach_section.setVisible(is_bug_report)
        form.issue_title_label.setVisible(is_bug_report)
        form.issue_title_edit.setVisible(is_bug_report)
        if not is_bug_report:
            form.issue_title_edit.clear()
        form.request_payment_section.hide()
        form.request_payment_confirm_section.hide()
        form.amount_label.hide()
        form.amount_edit.hide()
        form.quantity_label.hide()
        form.quantity_edit.hide()
        form.urgency_label.hide()
        form.urgency_combo.hide()
        form.email_edit.setPlaceholderText("name@example.com")
        form.message_label.setText("消息内容：")
        form.message_edit.setPlaceholderText("请详细描述您的问题、需求或留言…")
        form._close_amount_rule_infobar()
    form._refresh_amount_options()
    form._sync_amount_rule_warning()
    form._sync_donation_check_state()
    form._update_send_button_state()


def update_send_button_state(form: Any) -> None:
    if not hasattr(form, "send_btn"):
        return
    if form.send_spinner.isVisible():
        form.send_btn.setEnabled(False)
        form.send_btn.setToolTip("")
        return

    current_type = form.type_combo.currentText() or ""
    require_donation_check = current_type == REQUEST_MESSAGE_TYPE
    block_reason = form._get_donation_check_block_reason()
    can_send = (not require_donation_check) or (
        form.donated_cb.isChecked() and not block_reason
    )
    form.send_btn.setEnabled(can_send)
    if require_donation_check and block_reason:
        form.donated_cb.setToolTip(block_reason)
    else:
        form.donated_cb.setToolTip("")
    if require_donation_check and not can_send:
        if block_reason:
            form.send_btn.setToolTip(block_reason)
        else:
            form.send_btn.setToolTip("请先勾选“我已完成支付，且确认随机ip可用”后再发送申请")
    else:
        form.send_btn.setToolTip("")


def on_context_paste(form: Any, target: QWidget) -> bool:
    if target is form.message_edit and form._handle_clipboard_image():
        return True
    return False


def attachments_enabled(form: Any) -> bool:
    return (form.type_combo.currentText() or "") != REQUEST_MESSAGE_TYPE


def render_attachments_ui(form: Any) -> None:
    parent_widget = cast(QWidget, form)
    while form.attach_list_layout.count():
        item = form.attach_list_layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget:
            widget.deleteLater()

    if not form._attachments.attachments:
        form.attach_list_container.setVisible(False)
        form.attach_placeholder.setVisible(True)
        form.attach_clear_btn.setEnabled(False)
        return

    form.attach_list_container.setVisible(True)
    form.attach_placeholder.setVisible(False)
    form.attach_clear_btn.setEnabled(True)

    for idx, att in enumerate(form._attachments.attachments):
        card_widget = QWidget(parent_widget)
        card_layout = QVBoxLayout(card_widget)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(6)

        thumb_label = ImageLabel(parent_widget)
        thumb_label.setFixedSize(96, 96)
        thumb_label.setStyleSheet("border: 1px solid #E0E0E0; border-radius: 4px;")
        if att.pixmap and not att.pixmap.isNull():
            thumb_label.setPixmap(
                att.pixmap.scaled(
                    thumb_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        card_layout.addWidget(thumb_label)

        size_label = BodyLabel(f"{round(len(att.data) / 1024, 1)} KB", parent_widget)
        size_label.setStyleSheet("color: #666; font-size: 11px;")
        size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(size_label)

        remove_btn = PushButton("移除", parent_widget)
        remove_btn.setFixedWidth(96)
        remove_btn.clicked.connect(lambda _=False, i=idx: form._remove_attachment(i))
        card_layout.addWidget(remove_btn)

        form.attach_list_layout.addWidget(card_widget)
    form.attach_list_layout.addStretch(1)


def remove_attachment(form: Any, index: int) -> None:
    form._attachments.remove_at(index)
    form._render_attachments_ui()


def clear_attachments(form: Any) -> None:
    form._attachments.clear()
    form._render_attachments_ui()


def handle_clipboard_image(form: Any) -> bool:
    if not attachments_enabled(form):
        return False
    clipboard = QGuiApplication.clipboard()
    mime = clipboard.mimeData()
    if mime is None or not mime.hasImage():
        return False

    image = clipboard.image()
    ok, msg = form._attachments.add_qimage(image, "clipboard.png")
    if ok:
        form._render_attachments_ui()
    else:
        InfoBar.error(
            "",
            msg,
            parent=form,
            position=InfoBarPosition.TOP,
            duration=2500,
        )
    return True


def choose_files(form: Any) -> None:
    if not attachments_enabled(form):
        return
    parent_widget = cast(QWidget, form)
    paths, _ = QFileDialog.getOpenFileNames(
        parent_widget,
        "选择图片",
        "",
        "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;所有文件 (*.*)",
    )
    if not paths:
        return
    for path in paths:
        ok, msg = form._attachments.add_file_path(path)
        if not ok:
            InfoBar.error(
                "",
                msg,
                parent=form,
                position=InfoBarPosition.TOP,
                duration=2500,
            )
            break
    form._render_attachments_ui()
