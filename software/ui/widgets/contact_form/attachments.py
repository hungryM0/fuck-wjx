"""联系表单附件相关方法。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, InfoBar, InfoBarPosition, PushButton

from .constants import REQUEST_MESSAGE_TYPE


class ContactFormAttachmentsMixin:
    if TYPE_CHECKING:
        message_edit: Any
        type_combo: Any
        attach_list_layout: Any
        attach_list_container: QWidget
        attach_placeholder: QWidget
        attach_clear_btn: PushButton
        _attachments: Any

        def _handle_clipboard_image(self) -> bool: ...

    def _on_context_paste(self, target: QWidget) -> bool:
        """右键菜单触发粘贴时的特殊处理，返回 True 表示已处理。"""
        if target is self.message_edit:
            # 优先尝试粘贴图片到附件
            if self._handle_clipboard_image():
                return True
        return False
    def _attachments_enabled(self) -> bool:
        return (self.type_combo.currentText() or "") != REQUEST_MESSAGE_TYPE
    def _render_attachments_ui(self):
        """重新渲染附件列表。"""
        parent_widget = cast(QWidget, self)
        while self.attach_list_layout.count():
            item = self.attach_list_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self._attachments.attachments:
            self.attach_list_container.setVisible(False)
            self.attach_placeholder.setVisible(True)
            self.attach_clear_btn.setEnabled(False)
            return

        self.attach_list_container.setVisible(True)
        self.attach_placeholder.setVisible(False)
        self.attach_clear_btn.setEnabled(True)

        for idx, att in enumerate(self._attachments.attachments):
            card_widget = QWidget(parent_widget)
            card_layout = QVBoxLayout(card_widget)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(6)

            thumb_label = QLabel(parent_widget)
            thumb_label.setFixedSize(96, 96)
            thumb_label.setScaledContents(True)
            thumb_label.setStyleSheet("border: 1px solid #E0E0E0; border-radius: 4px;")
            if att.pixmap and not att.pixmap.isNull():
                thumb_label.setPixmap(att.pixmap)
            card_layout.addWidget(thumb_label)

            size_label = BodyLabel(f"{round(len(att.data) / 1024, 1)} KB", parent_widget)
            size_label.setStyleSheet("color: #666; font-size: 11px;")
            size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(size_label)

            remove_btn = PushButton("移除", parent_widget)
            remove_btn.setFixedWidth(96)
            remove_btn.clicked.connect(lambda _=False, i=idx: self._remove_attachment(i))
            card_layout.addWidget(remove_btn)

            self.attach_list_layout.addWidget(card_widget)
        self.attach_list_layout.addStretch(1)
    def _remove_attachment(self, index: int):
        self._attachments.remove_at(index)
        self._render_attachments_ui()
    def _on_clear_attachments(self):
        self._attachments.clear()
        self._render_attachments_ui()
    def _handle_clipboard_image(self) -> bool:
        """处理 Ctrl+V 粘贴图片，返回是否消费了事件。"""
        if not self._attachments_enabled():
            return False
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is None or not mime.hasImage():
            return False

        image = clipboard.image()
        ok, msg = self._attachments.add_qimage(image, "clipboard.png")
        if ok:
            self._render_attachments_ui()
        else:
            InfoBar.error("", msg, parent=self, position=InfoBarPosition.TOP, duration=2500)
        return True
    def _on_choose_files(self):
        if not self._attachments_enabled():
            return
        parent_widget = cast(QWidget, self)
        paths, _ = QFileDialog.getOpenFileNames(
            parent_widget,
            "选择图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;所有文件 (*.*)",
        )
        if not paths:
            return
        for path in paths:
            ok, msg = self._attachments.add_file_path(path)
            if not ok:
                InfoBar.error("", msg, parent=self, position=InfoBarPosition.TOP, duration=2500)
                break
        self._render_attachments_ui()
