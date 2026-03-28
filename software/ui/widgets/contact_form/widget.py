"""联系开发者表单组件，可嵌入页面或对话框。"""
import logging
import re
import threading
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Callable, cast, Any

from software.logging.log_utils import log_suppressed_exception


from PySide6.QtCore import Qt, QTimer, Signal, QEvent
from PySide6.QtGui import QDoubleValidator, QIntValidator, QKeySequence, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
    QLabel,
    QSizePolicy,
)
from qfluentwidgets import (
    BodyLabel,
    LineEdit,
    ComboBox,
    EditableComboBox,
    CheckBox,
    PushButton,
    PrimaryPushButton,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    Action,
    FluentIcon,
    IconWidget,
    RoundMenu,
    PlainTextEdit,
)

from software.ui.helpers.contact_api import format_quota_value, get_session_snapshot, post as http_post
from software.ui.helpers.fluent_tooltip import install_tooltip_filters
from software.ui.widgets.status_polling_mixin import StatusPollingMixin
from software.ui.helpers.image_attachments import ImageAttachmentManager
from software.app.config import CONTACT_API_URL, EMAIL_VERIFY_ENDPOINT
from software.app.version import __VERSION__

REQUEST_MESSAGE_TYPE = "额度申请"
DONATION_AMOUNT_OPTIONS = ["8.88", "11.45", "20.26", "50", "78.91", "114.51"]
DONATION_AMOUNT_BLOCK_MESSAGE = "该金额下开发者已亏本💔"
MAX_REQUEST_QUOTA = 19999
REQUEST_QUOTA_STEP = Decimal("0.5")
DONATION_AMOUNT_RULES = [
    (Decimal("13000"), Decimal("114.51")),
    (Decimal("8000"), Decimal("78.91")),
    (Decimal("3500"), Decimal("50")),
    (Decimal("2000"), Decimal("20.26")),
    (Decimal("1500"), Decimal("11.45")),
]


class PasteOnlyLineEdit(LineEdit):
    """只显示 Fluent 风格“复制 / 粘贴 / 全选”菜单的 LineEdit。"""



    def __init__(self, parent=None, on_paste: Optional[Callable[[QWidget], bool]] = None):
        super().__init__(parent)
        self._on_paste = on_paste

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        copy_action = Action(FluentIcon.COPY, "复制", parent=menu)
        copy_action.setEnabled(self.hasSelectedText())
        copy_action.triggered.connect(self.copy)
        paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)

        def _do_paste():
            if self._on_paste and self._on_paste(self):
                return
            self.paste()

        menu.addAction(copy_action)
        paste_action.triggered.connect(_do_paste)
        menu.addAction(paste_action)
        menu.exec(e.globalPos())
        e.accept()


class PasteOnlyPlainTextEdit(PlainTextEdit):
    """只显示 Fluent 风格“复制 / 粘贴 / 全选”菜单的 PlainTextEdit，兼容外部粘贴处理。"""

    def __init__(self, parent=None, on_paste: Optional[Callable[[QWidget], bool]] = None):
        super().__init__(parent)
        self._on_paste = on_paste

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        copy_action = Action(FluentIcon.COPY, "复制", parent=menu)
        copy_action.setEnabled(self.textCursor().hasSelection())
        copy_action.triggered.connect(self.copy)
        paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)

        def _do_paste():
            if self._on_paste and self._on_paste(self):
                return
            self.paste()

        menu.addAction(copy_action)
        paste_action.triggered.connect(_do_paste)
        menu.addAction(paste_action)
        menu.exec(e.globalPos())
        e.accept()


class ContactForm(StatusPollingMixin, QWidget):
    """联系开发者表单，负责消息发送、状态轮询和附件处理。"""

    _statusLoaded = Signal(str, str)  # text, color
    _sendFinished = Signal(bool, str)  # success, message
    _verifyCodeFinished = Signal(bool, str, str)  # success, message, email

    sendSucceeded = Signal()
    quotaRequestSucceeded = Signal()
    cancelRequested = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        default_type: str = "报错反馈",
        lock_message_type: bool = False,
        status_endpoint: str = "",
        status_formatter: Optional[Callable] = None,
        show_cancel_button: bool = False,
        auto_clear_on_success: bool = True,
        manage_polling: bool = True,
    ):
        super().__init__(parent)
        self._sendFinished.connect(self._on_send_finished)
        self._verifyCodeFinished.connect(self._on_verify_code_finished)
        self._init_status_polling(status_endpoint, status_formatter)
        self._attachments = ImageAttachmentManager(max_count=3, max_size_bytes=10 * 1024 * 1024)
        self._current_message_type: str = ""
        self._current_has_email: bool = False
        self._verify_code_requested: bool = False
        self._verify_code_requested_email: str = ""
        self._verify_code_sending: bool = False
        self._cooldown_timer: Optional[QTimer] = None
        self._cooldown_remaining: int = 0
        self._polling_started = False
        self._auto_clear_on_success = auto_clear_on_success
        self._manage_polling = manage_polling
        self._lock_message_type = lock_message_type
        self._random_ip_user_id: int = 0
        self._last_valid_quantity_text: str = ""

        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(16)

        # 顶部表单区
        form_layout = QVBoxLayout()
        form_layout.setSpacing(12)
        form_layout.setContentsMargins(0, 0, 0, 0)

        LABEL_WIDTH = 75

        # 1. 消息类型
        type_row = QHBoxLayout()
        self.type_label_static = BodyLabel("消息类型：", self)
        self.type_label_static.setFixedWidth(LABEL_WIDTH)
        self.type_combo = ComboBox(self)
        self.type_locked_label = BodyLabel("", self)
        self.type_locked_label.setMinimumWidth(160)
        self.base_options = ["报错反馈", REQUEST_MESSAGE_TYPE, "新功能建议", "纯聊天"]
        for item in self.base_options:
            self.type_combo.addItem(item, item)
        self.type_combo.setMinimumWidth(160)
        type_row.addWidget(self.type_label_static)
        type_row.addWidget(self.type_combo)
        type_row.addWidget(self.type_locked_label)
        type_row.addStretch(1)
        form_layout.addLayout(type_row)

        # 2. 邮箱 + 验证码（同一行）
        email_row = QHBoxLayout()
        self.email_label = BodyLabel("联系邮箱：", self)
        self.email_label.setFixedWidth(LABEL_WIDTH)
        self.email_edit = PasteOnlyLineEdit(self)
        self.email_edit.setPlaceholderText("name@example.com")
        email_row.addWidget(self.email_label)
        email_row.addWidget(self.email_edit)

        self.verify_code_edit = LineEdit(self)
        self.verify_code_edit.setPlaceholderText("6位验证码")
        self.verify_code_edit.setMaxLength(6)
        self.verify_code_edit.setValidator(QIntValidator(0, 999999, self))
        self.verify_code_edit.setMaximumWidth(120)

        self.send_verify_btn = PushButton("发送验证码", self)
        self.verify_send_spinner = IndeterminateProgressRing(self)
        self.verify_send_spinner.setFixedSize(16, 16)
        self.verify_send_spinner.setStrokeWidth(2)
        self.verify_send_spinner.hide()

        email_row.addSpacing(4)
        email_row.addWidget(self.send_verify_btn)
        email_row.addWidget(self.verify_send_spinner)
        email_row.addWidget(self.verify_code_edit)
        form_layout.addLayout(email_row)

        self.verify_code_edit.hide()
        self.send_verify_btn.hide()
        self.verify_send_spinner.hide()

        # 4. 额度申请参数
        self.amount_row = QHBoxLayout()
        self.amount_label = BodyLabel("支付金额：￥", self)
        self.amount_edit = EditableComboBox(self)
        self.amount_edit.setPlaceholderText("必填")
        self.amount_edit.setMaximumWidth(100)
        validator = QDoubleValidator(0.01, 9999.99, 2, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        for amount in DONATION_AMOUNT_OPTIONS:
            self.amount_edit.addItem(amount)
        self.amount_edit.setText("11.45")
        self.amount_edit.setValidator(validator)
        self.amount_edit.currentTextChanged.connect(self._on_amount_changed)
        self.amount_edit.editingFinished.connect(self._on_amount_editing_finished)
        self.amount_edit.installEventFilter(self)

        self.quantity_label = BodyLabel("需求额度：", self)
        self.quantity_edit = LineEdit(self)
        self.quantity_edit.setPlaceholderText("按需填写")
        self.quantity_edit.setMaximumWidth(90)
        self.quantity_edit.setMaxLength(len(str(MAX_REQUEST_QUOTA)) + 2)
        quantity_validator = QDoubleValidator(0.0, float(MAX_REQUEST_QUOTA), 1, self)
        quantity_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.quantity_edit.setValidator(quantity_validator)
        self.quantity_edit.textChanged.connect(self._on_quantity_changed)
        self.quantity_edit.editingFinished.connect(self._on_quantity_editing_finished)

        self.urgency_label = BodyLabel("问卷紧急程度：", self)
        self.urgency_combo = ComboBox(self)
        self.urgency_combo.setMaximumWidth(140)
        for urgency in ["低", "中（本月内）", "高（本周内）", "紧急（两天内）"]:
            self.urgency_combo.addItem(urgency, urgency)
        urgency_default_index = self.urgency_combo.findText("中（本月内）")
        if urgency_default_index >= 0:
            self.urgency_combo.setCurrentIndex(urgency_default_index)
        self.urgency_combo.currentIndexChanged.connect(lambda _: self._on_urgency_changed())

        self.amount_row.addWidget(self.quantity_label)
        self.amount_row.addWidget(self.quantity_edit)
        self.amount_row.addSpacing(16)
        self.amount_row.addWidget(self.amount_label)
        self.amount_row.addWidget(self.amount_edit)
        self.amount_row.addSpacing(16)
        self.amount_row.addWidget(self.urgency_label)
        self.amount_row.addWidget(self.urgency_combo)
        self.amount_row.addStretch(1)
        form_layout.addLayout(self.amount_row)

        self.amount_rule_hint = QWidget(self)
        self.amount_rule_hint.setObjectName("amountRuleHint")
        self.amount_rule_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.amount_rule_hint.setStyleSheet(
            "#amountRuleHint {"
            "background-color: #FFF4CE;"
            "border: 1px solid #F2D58A;"
            "border-radius: 8px;"
            "}"
        )
        amount_rule_hint_layout = QHBoxLayout(self.amount_rule_hint)
        amount_rule_hint_layout.setContentsMargins(12, 8, 12, 8)
        amount_rule_hint_layout.setSpacing(8)
        self.amount_rule_hint_icon = IconWidget(FluentIcon.INFO, self.amount_rule_hint)
        self.amount_rule_hint_icon.setIcon(FluentIcon.INFO)
        self.amount_rule_hint_icon.setStyleSheet("color: #B57A00;")
        self.amount_rule_hint_text = BodyLabel(DONATION_AMOUNT_BLOCK_MESSAGE, self.amount_rule_hint)
        self.amount_rule_hint_text.setStyleSheet("color: #7A5200;")
        amount_rule_hint_layout.addWidget(self.amount_rule_hint_icon)
        amount_rule_hint_layout.addWidget(self.amount_rule_hint_text, 1)
        form_layout.addWidget(self.amount_rule_hint)

        self.amount_label.hide()
        self.amount_edit.hide()
        self.quantity_label.hide()
        self.quantity_edit.hide()
        self.urgency_label.hide()
        self.urgency_combo.hide()
        self.amount_rule_hint.hide()

        # 第二部分：消息内容
        msg_layout = QVBoxLayout()
        msg_layout.setSpacing(6)
        msg_label_row = QHBoxLayout()
        self.message_label = BodyLabel("消息内容：", self)
        msg_label_row.addWidget(self.message_label)
        msg_label_row.addStretch(1)

        self.message_edit = PasteOnlyPlainTextEdit(self, self._on_context_paste)
        self.message_edit.setPlaceholderText("请详细描述您的问题、需求或留言…")
        self.message_edit.setMinimumHeight(140)
        self.message_edit.installEventFilter(self)
        self.random_ip_user_id_label = BodyLabel("", self)
        self.random_ip_user_id_label.setWordWrap(True)
        self.random_ip_user_id_label.setStyleSheet("color: #666; font-size: 12px;")
        self.random_ip_user_id_label.hide()

        msg_layout.addLayout(msg_label_row)
        msg_layout.addWidget(self.message_edit, 1)
        msg_layout.addWidget(self.random_ip_user_id_label)

        # 第三部分：图片附件
        attachments_box = QVBoxLayout()
        attachments_box.setSpacing(6)

        attach_toolbar = QHBoxLayout()
        attach_title = BodyLabel("图片附件 (最多3张，支持Ctrl+V粘贴，单张≤10MB):", self)

        self.attach_add_btn = PushButton(FluentIcon.ADD, "添加图片", self)
        self.attach_clear_btn = PushButton(FluentIcon.DELETE, "清空附件", self)

        attach_toolbar.addWidget(attach_title)
        attach_toolbar.addStretch(1)
        attach_toolbar.addWidget(self.attach_add_btn)
        attach_toolbar.addWidget(self.attach_clear_btn)

        attachments_box.addLayout(attach_toolbar)

        self.attach_list_layout = QHBoxLayout()
        self.attach_list_layout.setSpacing(12)
        self.attach_list_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.attach_list_container = QWidget(self)
        self.attach_list_container.setLayout(self.attach_list_layout)

        self.attach_placeholder = BodyLabel("暂无附件", self)
        self.attach_placeholder.setStyleSheet("color: #888; padding: 6px;")

        attachments_box.addWidget(self.attach_list_container)
        attachments_box.addWidget(self.attach_placeholder)

        # 组装表单、消息、附件
        wrapper.addLayout(form_layout)
        wrapper.addLayout(msg_layout, 1) # 给消息框最大的 stretch
        wrapper.addLayout(attachments_box)

        # 支付确认行
        donated_row = QHBoxLayout()
        donated_row.setSpacing(8)
        self.donated_cb = CheckBox("我已完成支付，且确认随机ip可用", self)
        self.open_donate_btn = PushButton(FluentIcon.HEART, "去支付", self)
        self.open_donate_btn.setToolTip("打开支付页面")
        donated_row.addStretch(1)
        donated_row.addWidget(self.open_donate_btn)
        donated_row.addWidget(self.donated_cb)
        wrapper.addLayout(donated_row)

        # 第四部分：底部状态与按钮
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 8, 0, 0)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_spinner = IndeterminateProgressRing(self)
        self.status_spinner.setFixedSize(16, 16)
        self.status_spinner.setStrokeWidth(2)
        self.status_icon = IconWidget(FluentIcon.INFO, self)
        self.status_icon.setFixedSize(16, 16)
        self.status_icon.hide()
        self.online_label = BodyLabel("作者当前在线状态：查询中...", self)
        self.online_label.setStyleSheet("color:#BA8303;")
        status_row.addWidget(self.status_spinner)
        status_row.addWidget(self.status_icon)
        status_row.addWidget(self.online_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.cancel_btn: Optional[PushButton] = None
        if show_cancel_button:
            self.cancel_btn = PushButton("取消", self)
            btn_row.addWidget(self.cancel_btn)
        self.send_btn = PrimaryPushButton("发送", self)
        self.send_spinner = IndeterminateProgressRing(self)
        self.send_spinner.setFixedSize(20, 20)
        self.send_spinner.setStrokeWidth(3)
        self.send_spinner.hide()
        btn_row.addWidget(self.send_spinner)
        btn_row.addWidget(self.send_btn)

        bottom_layout.addLayout(status_row)
        bottom_layout.addStretch(1)
        bottom_layout.addLayout(btn_row)
        wrapper.addLayout(bottom_layout)

        self.type_combo.currentIndexChanged.connect(lambda _: self._on_type_changed())
        self.donated_cb.installEventFilter(self)
        self.donated_cb.toggled.connect(lambda _: self._update_send_button_state())
        self.open_donate_btn.clicked.connect(self._open_donate_page)
        install_tooltip_filters((self.open_donate_btn, self.donated_cb, self.send_btn))
        QTimer.singleShot(0, self._on_type_changed)
        if default_type:
            idx = self.type_combo.findText(default_type)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
        self._sync_message_type_lock_state()

        self.send_btn.clicked.connect(self._on_send_clicked)
        self.send_verify_btn.clicked.connect(self._on_send_verify_clicked)
        self.attach_add_btn.clicked.connect(self._on_choose_files)
        self.attach_clear_btn.clicked.connect(self._on_clear_attachments)
        if self.cancel_btn is not None:
            self.cancel_btn.clicked.connect(self.cancelRequested.emit)
        self.refresh_random_ip_user_id_hint()

    def eventFilter(self, watched, event):
        message_edit = getattr(self, "message_edit", None)
        donated_cb = getattr(self, "donated_cb", None)
        if message_edit is not None and watched is message_edit and event.type() == QEvent.Type.KeyPress:
            key_event = cast(QKeyEvent, event)
            if key_event.matches(QKeySequence.StandardKey.Paste):
                if self._handle_clipboard_image():
                    return True
        if donated_cb is not None and watched is donated_cb:
            block_reason = self._get_donation_check_block_reason()
            if block_reason and not donated_cb.isChecked():
                if event.type() == QEvent.Type.MouseButtonPress:
                    InfoBar.warning("", block_reason, parent=self, position=InfoBarPosition.TOP, duration=2600)
                    return True
                if event.type() == QEvent.Type.KeyPress:
                    key_event = cast(QKeyEvent, event)
                    if key_event.key() in (
                        Qt.Key.Key_Space,
                        Qt.Key.Key_Return,
                        Qt.Key.Key_Enter,
                        Qt.Key.Key_Select,
                    ):
                        InfoBar.warning("", block_reason, parent=self, position=InfoBarPosition.TOP, duration=2600)
                        return True
        if watched is self.amount_edit and event.type() == QEvent.Type.FocusOut:
            self._normalize_amount_if_needed()
        return super().eventFilter(watched, event)

    def _on_context_paste(self, target: QWidget) -> bool:
        """右键菜单触发粘贴时的特殊处理，返回 True 表示已处理。"""
        if target is self.message_edit:
            # 优先尝试粘贴图片到附件
            if self._handle_clipboard_image():
                return True
        return False

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_random_ip_user_id_hint()
        if self._manage_polling:
            self.start_status_polling()

    def hideEvent(self, event):
        if self._manage_polling:
            self.stop_status_polling()
        super().hideEvent(event)

    def closeEvent(self, event):
        """关闭事件：停止轮询、关闭所有 InfoBar 并断开信号"""
        self.stop_status_polling()
        self._stop_cooldown()

        # 关闭所有可能存在的 InfoBar，避免其内部线程导致崩溃
        self._close_all_infobars()

        # 断开所有信号连接以避免回调析构警告
        try:
            self._sendFinished.disconnect()
            self._verifyCodeFinished.disconnect()
            self._statusLoaded.disconnect()
        except Exception as exc:
            log_suppressed_exception("closeEvent: disconnect signals", exc, level=logging.WARNING)
        super().closeEvent(event)

    def __del__(self):
        """析构函数：确保轮询请求被清理"""
        try:
            self.stop_status_polling()
        except Exception:
            pass

    def _close_all_infobars(self):
        """关闭所有子 InfoBar 组件，避免线程泄漏"""
        try:
            from qfluentwidgets import InfoBar
            # 遍历所有子组件，找到 InfoBar 并关闭
            for child in self.findChildren(InfoBar):
                try:
                    child.close()
                    child.deleteLater()
                except Exception:
                    pass
        except Exception as exc:
            log_suppressed_exception("_close_all_infobars", exc, level=logging.WARNING)
        finally:
            self.amount_rule_hint.hide()

    def refresh_random_ip_user_id_hint(self) -> None:
        """刷新消息框下方的随机IP账号提示。"""
        try:
            snapshot = get_session_snapshot()
        except Exception as exc:
            log_suppressed_exception("refresh_random_ip_user_id_hint", exc, level=logging.WARNING)
            snapshot = {}
        user_id = int(snapshot.get("user_id") or 0)
        self._random_ip_user_id = user_id
        if user_id > 0:
            self.random_ip_user_id_label.setText(f"随机IP用户ID：{user_id}")
            self.random_ip_user_id_label.show()
        else:
            self.random_ip_user_id_label.hide()
        self._sync_donation_check_state()
        self._update_send_button_state()

    def _get_donation_check_block_reason(self) -> str:
        current_type = self.type_combo.currentText() or ""
        if current_type != REQUEST_MESSAGE_TYPE:
            return ""
        amount_text = (self.amount_edit.currentText() or "").strip()
        if not amount_text:
            return "请先填写支付金额后，再勾选“我已完成支付，且确认随机ip可用”。"
        if self._random_ip_user_id > 0:
            return ""
        return "你还没有成功使用过随机IP，暂时不能勾选。请先启用并实际跑通一次随机IP，确认能正常用，再来申请。"

    def _sync_donation_check_state(self) -> None:
        """当勾选条件失效时，自动撤销“已支付”勾选。"""
        if not hasattr(self, "donated_cb"):
            return
        if self._get_donation_check_block_reason() and self.donated_cb.isChecked():
            previous_block_state = self.donated_cb.blockSignals(True)
            try:
                self.donated_cb.setChecked(False)
            finally:
                self.donated_cb.blockSignals(previous_block_state)

    def _open_donate_page(self) -> None:
        widget: Optional[QWidget] = self
        while widget is not None:
            if hasattr(widget, "_get_donate_page") and hasattr(widget, "_switch_to_more_page"):
                try:
                    host = cast(Any, widget)
                    donate_page = host._get_donate_page()
                    host._switch_to_more_page(donate_page)
                    top_level = self.window()
                    if top_level is not None and top_level is not widget:
                        top_level.close()
                    return
                except Exception as exc:
                    log_suppressed_exception("_open_donate_page", exc, level=logging.WARNING)
                    break
            widget = widget.parentWidget()
        InfoBar.warning(
            "",
                    "暂时打不开支付页，请从“更多 -> 捐助”进入",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2500,
        )

    def start_status_polling(self):
        if self._polling_started:
            return
        self._polling_started = True
        self.status_spinner.show()
        self.status_icon.hide()
        self.online_label.setText("作者当前在线状态：查询中...")
        self.online_label.setStyleSheet("color:#BA8303;")
        self._start_status_polling()

    def stop_status_polling(self):
        if not self._polling_started:
            return
        self._polling_started = False
        self._stop_status_polling()

    def _render_attachments_ui(self):
        """重新渲染附件列表。"""
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
            card_widget = QWidget(self)
            card_layout = QVBoxLayout(card_widget)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(6)

            thumb_label = QLabel(self)
            thumb_label.setFixedSize(96, 96)
            thumb_label.setScaledContents(True)
            thumb_label.setStyleSheet("border: 1px solid #E0E0E0; border-radius: 4px;")
            if att.pixmap and not att.pixmap.isNull():
                thumb_label.setPixmap(att.pixmap)
            card_layout.addWidget(thumb_label)
            
            size_label = BodyLabel(f"{round(len(att.data) / 1024, 1)} KB", self)
            size_label.setStyleSheet("color: #666; font-size: 11px;")
            size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(size_label)

            remove_btn = PushButton("移除", self)
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
        paths, _ = QFileDialog.getOpenFileNames(
            self,
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

    def _on_type_changed(self):
        current_type = self.type_combo.currentText()
        self._sync_message_type_lock_state()

        # 控制额度申请参数显示/隐藏
        if current_type == REQUEST_MESSAGE_TYPE:
            self.amount_label.show()
            self.amount_edit.show()
            self.quantity_label.show()
            self.quantity_edit.show()
            self.urgency_label.show()
            self.urgency_combo.show()
            self.verify_code_edit.show()
            self.send_verify_btn.show()
            self.email_edit.setPlaceholderText("name@example.com")
            self.message_label.setText("补充说明（选填）：")
            self.message_edit.setPlaceholderText("请简单说明你的问卷紧急情况或使用场景...\n以及...是大学生吗（？")
        else:
            self.amount_label.hide()
            self.amount_edit.hide()
            self.quantity_label.hide()
            self.quantity_edit.hide()
            self.urgency_label.hide()
            self.urgency_combo.hide()
            self.verify_code_edit.hide()
            self.send_verify_btn.hide()
            self.verify_send_spinner.hide()
            self.verify_code_edit.clear()
            self._verify_code_requested = False
            self._verify_code_requested_email = ""
            self._verify_code_sending = False
            self._stop_cooldown()
            self.email_edit.setPlaceholderText("name@example.com")
            self.message_label.setText("消息内容：")
            self.message_edit.setPlaceholderText("请详细描述您的问题、需求或留言…")
            self._close_amount_rule_infobar()
        self._refresh_amount_options()
        self._sync_amount_rule_warning()
        self._sync_donation_check_state()
        self._update_send_button_state()

    def _sync_message_type_lock_state(self) -> None:
        current_type = self.type_combo.currentText() or ""
        self.type_locked_label.setText(current_type)
        self.type_combo.setVisible(not self._lock_message_type)
        self.type_combo.setEnabled(not self._lock_message_type)
        self.type_locked_label.setVisible(self._lock_message_type)

    def _update_send_button_state(self) -> None:
        if not hasattr(self, "send_btn"):
            return
        if self.send_spinner.isVisible():
            self.send_btn.setEnabled(False)
            self.send_btn.setToolTip("")
            return

        current_type = self.type_combo.currentText() or ""
        require_donation_check = current_type == REQUEST_MESSAGE_TYPE
        block_reason = self._get_donation_check_block_reason()
        can_send = (not require_donation_check) or (self.donated_cb.isChecked() and not block_reason)
        self.send_btn.setEnabled(can_send)
        if require_donation_check and block_reason:
            self.donated_cb.setToolTip(block_reason)
        else:
            self.donated_cb.setToolTip("")
        if require_donation_check and not can_send:
            if block_reason:
                self.send_btn.setToolTip(block_reason)
            else:
                self.send_btn.setToolTip("请先勾选“我已完成支付，且确认随机ip可用”后再发送申请")
        else:
            self.send_btn.setToolTip("")

    def _set_verify_code_sending(self, sending: bool):
        self._verify_code_sending = sending
        self.send_verify_btn.setEnabled(not sending)
        self.send_verify_btn.setText("发送中..." if sending else "发送验证码")
        self.verify_send_spinner.setVisible(sending)

    def _start_cooldown(self):
        """发送成功后启动30秒冷却，期间按钮不可点击并显示倒计时。"""
        self._cooldown_remaining = 30
        self.send_verify_btn.setEnabled(False)
        self.send_verify_btn.setText(f"重新发送({self._cooldown_remaining}s)")
        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.setInterval(1000)
        self._cooldown_timer.timeout.connect(self._on_cooldown_tick)
        self._cooldown_timer.start()

    def _on_cooldown_tick(self):
        self._cooldown_remaining -= 1
        if self._cooldown_remaining <= 0:
            if self._cooldown_timer is not None:
                self._cooldown_timer.stop()
            self._cooldown_timer = None
            self.send_verify_btn.setEnabled(True)
            self.send_verify_btn.setText("发送验证码")
        else:
            self.send_verify_btn.setText(f"重新发送({self._cooldown_remaining}s)")

    def _stop_cooldown(self):
        """停止冷却计时器并重置按钮状态。"""
        if self._cooldown_timer is not None:
            self._cooldown_timer.stop()
            self._cooldown_timer = None
        self._cooldown_remaining = 0
        self.send_verify_btn.setEnabled(True)
        self.send_verify_btn.setText("发送验证码")

    def _on_send_verify_clicked(self):
        if self._verify_code_sending:
            return

        email = (self.email_edit.text() or "").strip()
        if not email:
            InfoBar.warning("", "请先填写邮箱地址", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        if not self._validate_email(email):
            InfoBar.warning("", "邮箱格式不正确，请先检查", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        if not EMAIL_VERIFY_ENDPOINT:
            InfoBar.error("", "验证码接口未配置", parent=self, position=InfoBarPosition.TOP, duration=2500)
            return

        self._verify_code_requested = False
        self._verify_code_requested_email = ""
        self._set_verify_code_sending(True)

        def _send_verify():
            try:
                resp = http_post(
                    EMAIL_VERIFY_ENDPOINT,
                    headers={"Content-Type": "application/json"},
                    json={"email": email},
                    timeout=10,
                )
                data = None
                try:
                    data = resp.json()
                except Exception:
                    data = None

                if resp.status_code == 200 and isinstance(data, dict) and bool(data.get("ok")):
                    self._verifyCodeFinished.emit(True, "", email)
                    return

                if isinstance(data, dict):
                    error_msg = str(data.get("error") or f"发送失败：{resp.status_code}")
                else:
                    error_msg = f"发送失败：{resp.status_code}"
                self._verifyCodeFinished.emit(False, error_msg, email)
            except Exception as exc:
                self._verifyCodeFinished.emit(False, f"发送失败：{exc}", email)

        threading.Thread(target=_send_verify, daemon=True).start()

    def _on_verify_code_finished(self, success: bool, error_msg: str, email: str):
        self._set_verify_code_sending(False)

        if success:
            self._verify_code_requested = True
            self._verify_code_requested_email = email
            InfoBar.success("", "验证码已发送，请查收并输入验证码", parent=self, position=InfoBarPosition.TOP, duration=2200)
            self._start_cooldown()
            return

        self._verify_code_requested = False
        self._verify_code_requested_email = ""
        normalized = (error_msg or "").strip().lower()
        if normalized == "invalid request":
            ui_msg = "邮箱参数无效，请检查邮箱后重试"
        elif normalized == "send mail failed":
            ui_msg = "邮件发送失败，请稍后重试"
        else:
            ui_msg = error_msg or "验证码发送失败，请稍后重试"
        InfoBar.error("", ui_msg, parent=self, position=InfoBarPosition.TOP, duration=2500)

    def _on_amount_changed(self, text: str):
        """金额输入变化时同步金额规则提示。"""
        _ = text
        self._sync_amount_rule_warning()
        self._sync_donation_check_state()
        self._update_send_button_state()

    def _normalize_amount_if_needed(self) -> None:
        """将 0 自动纠正为 0.01，避免提交无效金额。"""
        text = (self.amount_edit.currentText() or "").strip()
        if not text:
            return
        try:
            value = float(text)
        except ValueError:
            return
        if value == 0.0 and text != "0.01":
            self.amount_edit.setText("0.01")

    def _on_amount_editing_finished(self):
        self._normalize_amount_if_needed()
        self._sync_amount_rule_warning()

    def _on_quantity_changed(self, text: str):
        """申请额度变化时刷新支付金额选项。"""
        normalized_text = (text or "").strip()
        if not normalized_text:
            self._last_valid_quantity_text = ""
        else:
            quantity = self._parse_quantity_value(normalized_text)
            if quantity is not None and quantity <= Decimal(str(MAX_REQUEST_QUOTA)):
                self._last_valid_quantity_text = self._normalize_quantity_text(normalized_text)
            elif quantity is not None and quantity > Decimal(str(MAX_REQUEST_QUOTA)):
                self.quantity_edit.blockSignals(True)
                try:
                    self.quantity_edit.setText(self._last_valid_quantity_text)
                finally:
                    self.quantity_edit.blockSignals(False)
                return
        self._refresh_amount_options()
        self._sync_amount_rule_warning()

    def _on_quantity_editing_finished(self):
        self._normalize_quantity_if_needed()
        self._refresh_amount_options()
        self._sync_amount_rule_warning()

    def _on_urgency_changed(self):
        """紧急程度改变时预留钩子。"""
        return

    def _on_status_loaded(self, text: str, color: str):
        """信号槽：在主线程更新状态标签"""
        try:
            self.status_spinner.hide()
            self.status_icon.show()
            if color.lower() == "#228b22":
                self.status_icon.setIcon(FluentIcon.ACCEPT)
            elif color.lower() == "#cc0000":
                self.status_icon.setIcon(FluentIcon.REMOVE_FROM)
            else:
                self.status_icon.setIcon(FluentIcon.INFO)
            self.online_label.setText(text)
            self.online_label.setStyleSheet(f"color:{color};")
        except RuntimeError as exc:
            log_suppressed_exception("_on_status_loaded: self.status_spinner.hide()", exc, level=logging.WARNING)

    def _validate_email(self, email: str) -> bool:
        if not email:
            return True
        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        return re.match(pattern, email) is not None

    def _on_send_clicked(self):
        email = (self.email_edit.text() or "").strip()
        self._current_has_email = bool(email)

        QTimer.singleShot(10, lambda: self._clear_email_selection())
        QTimer.singleShot(10, lambda: self._focus_send_button())

        mtype = self.type_combo.currentText() or "报错反馈"

        request_amount_text = ""
        request_quota_text = ""
        request_urgency_text = ""
        if mtype == REQUEST_MESSAGE_TYPE:
            self._normalize_amount_if_needed()
            self._normalize_quantity_if_needed()
            amount_text = (self.amount_edit.currentText() or "").strip()
            quantity_text = (self.quantity_edit.text() or "").strip()
            verify_code = (self.verify_code_edit.text() or "").strip()
            request_amount_text = amount_text
            request_quota_text = self._normalize_quantity_text(quantity_text)
            request_urgency_text = (self.urgency_combo.currentText() or "").strip()
            if not amount_text:
                InfoBar.warning("", "请输入支付金额", parent=self, position=InfoBarPosition.TOP, duration=2000)
                return
            if not self.donated_cb.isChecked():
                InfoBar.warning("", "请先勾选“我已完成支付”后再发送申请", parent=self, position=InfoBarPosition.TOP, duration=2000)
                self._update_send_button_state()
                return
            if not quantity_text:
                InfoBar.warning("", "请输入申请额度", parent=self, position=InfoBarPosition.TOP, duration=2000)
                return
            quantity_value = self._parse_quantity_value(quantity_text)
            if quantity_value is None:
                InfoBar.warning("", "申请额度必须 >= 0，且只能填 0.5 的倍数", parent=self, position=InfoBarPosition.TOP, duration=2200)
                return
            if quantity_value > Decimal(str(MAX_REQUEST_QUOTA)):
                InfoBar.warning(
                    "",
                    f"申请额度不能超过 {format_quota_value(MAX_REQUEST_QUOTA)}",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                return
            if amount_text and not self._is_amount_allowed(amount_text, quantity_text):
                self._show_amount_rule_infobar()
                InfoBar.warning("", DONATION_AMOUNT_BLOCK_MESSAGE, parent=self, position=InfoBarPosition.TOP, duration=2200)
                return
            if not self._verify_code_requested:
                InfoBar.warning("", "请先点击发送验证码", parent=self, position=InfoBarPosition.TOP, duration=2000)
                return
            if email != self._verify_code_requested_email:
                InfoBar.warning("", "邮箱已变更，请重新发送验证码", parent=self, position=InfoBarPosition.TOP, duration=2200)
                return
            if verify_code != "114514":
                InfoBar.warning("", "验证码错误，请重试", parent=self, position=InfoBarPosition.TOP, duration=2200)
                return

        message = (self.message_edit.toPlainText() or "").strip()
        if not message and mtype != REQUEST_MESSAGE_TYPE:
            warn_text = "请输入消息内容"
            InfoBar.warning("", warn_text, parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        if mtype == REQUEST_MESSAGE_TYPE and not email:
            InfoBar.warning("", "额度申请必须填写邮箱地址", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        if email and not self._validate_email(email):
            InfoBar.warning("", "邮箱格式不正确", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        self.refresh_random_ip_user_id_hint()
        if mtype == REQUEST_MESSAGE_TYPE and self._random_ip_user_id <= 0:
            InfoBar.warning(
                "",
                "暂时还不能申请额度。请先小测试一两份，确认能正常提交成功后，再来申请额度。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3500,
            )
            return

        if mtype == REQUEST_MESSAGE_TYPE:
            confirm_email_box = MessageBox(
                "确认邮箱地址",
                f"当前输入的邮箱地址是：{email}\n\n请确认邮箱地址正确无误。开发者会在2小时内发放额度并通过邮件通知",
                self.window() or self,
            )
            confirm_email_box.yesButton.setText("确认发送")
            confirm_email_box.cancelButton.setText("返回检查")
            if not confirm_email_box.exec():
                return

        if mtype != REQUEST_MESSAGE_TYPE and not email:
            confirm_box = MessageBox(
                "未填写邮箱",
                "当前未输入邮箱地址，开发者可能无法联系你回复处理进度。是否继续发送？",
                self.window() or self,
            )
            confirm_box.yesButton.setText("继续发送")
            confirm_box.cancelButton.setText("返回填写")
            if not confirm_box.exec():
                return

        version_str = __VERSION__
        full_message = f"来源：SurveyController v{version_str}\n类型：{mtype}\n"
        if email:
            full_message += f"联系邮箱： {email}\n"
        full_message += f"已支付：{'是' if self.donated_cb.isChecked() else '否'}\n"
        if self._random_ip_user_id > 0:
            full_message += f"随机IP用户ID：{self._random_ip_user_id}\n"
        if mtype == REQUEST_MESSAGE_TYPE:
            full_message += f"支付金额：￥{request_amount_text}\n"
            full_message += f"申请额度：{request_quota_text}\n"
            full_message += f"紧急程度：{request_urgency_text or '中'}\n"
            full_message += f"补充说明：{message or '未填写'}"
        else:
            full_message += f"消息：{message}"

        api_url = CONTACT_API_URL
        if not api_url:
            InfoBar.error("", "联系API未配置", parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        payload = {"message": full_message, "timestamp": datetime.now().isoformat()}
        files_payload = self._attachments.files_payload()

        self.send_btn.setFocus()

        self.send_btn.setEnabled(False)
        self.send_btn.setText("发送中...")
        self.send_spinner.show()
        self._update_send_button_state()

        self._current_message_type = mtype

        def _send():
            try:
                multipart_fields: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
                    ("message", (None, payload["message"])),
                    ("timestamp", (None, payload["timestamp"])),
                ]
                if files_payload:
                    multipart_fields.extend(files_payload)
                timeout = 20 if files_payload else 10
                resp = http_post(api_url, files=multipart_fields, timeout=timeout)
                if resp.status_code == 200:
                    self._sendFinished.emit(True, "")
                else:
                    self._sendFinished.emit(False, f"发送失败：{resp.status_code}")
            except Exception as exc:
                self._sendFinished.emit(False, f"发送失败：{exc}")

        threading.Thread(target=_send, daemon=True).start()

    def _clear_email_selection(self):
        """清除邮箱选择（由QTimer调用）"""
        try:
            self.email_edit.setSelection(0, 0)
        except (RuntimeError, AttributeError) as exc:
            log_suppressed_exception("_clear_email_selection: self.email_edit.setSelection(0, 0)", exc, level=logging.WARNING)

    def _focus_send_button(self):
        """聚焦发送按钮（由QTimer调用）"""
        try:
            self.send_btn.setFocus()
        except (RuntimeError, AttributeError) as exc:
            log_suppressed_exception("_focus_send_button: self.send_btn.setFocus()", exc, level=logging.WARNING)

    def _on_send_finished(self, success: bool, error_msg: str):
        """发送完成回调（在主线程执行）"""
        self.send_spinner.hide()
        self.send_btn.setText("发送")
        self._update_send_button_state()

        if success:
            current_type = getattr(self, "_current_message_type", "")
            if current_type == REQUEST_MESSAGE_TYPE:
                msg = "申请已提交，请等待人工处理"
            else:
                msg = "消息已发送"
            if getattr(self, "_current_has_email", False):
                msg += "，开发者会优先通过邮箱联系你"
            InfoBar.success("", msg, parent=self, position=InfoBarPosition.TOP, duration=2500)
            if current_type == REQUEST_MESSAGE_TYPE:
                self.quotaRequestSucceeded.emit()
            if self._auto_clear_on_success:
                self._close_amount_rule_infobar()
                self.amount_edit.setText("")
                self.quantity_edit.clear()
                self.verify_code_edit.clear()
                self._verify_code_requested = False
                self._verify_code_requested_email = ""
                urgency_default_index = self.urgency_combo.findText("中")
                if urgency_default_index >= 0:
                    self.urgency_combo.setCurrentIndex(urgency_default_index)
                self.message_edit.clear()
                self._attachments.clear()
                self._render_attachments_ui()
            self.sendSucceeded.emit()
        else:
            InfoBar.error("", error_msg, parent=self, position=InfoBarPosition.TOP, duration=3000)

    def _find_controller_host(self) -> Optional[QWidget]:
        widget: Optional[QWidget] = self
        while widget is not None:
            if hasattr(widget, "controller"):
                return widget
            widget = widget.parentWidget()
        win = self.window()
        if isinstance(win, QWidget) and hasattr(win, "controller"):
            return win
        return None

    def _parse_quantity_value(self, text: Optional[str] = None) -> Optional[Decimal]:
        raw_text = (self.quantity_edit.text() if text is None else text) or ""
        raw_text = raw_text.strip()
        if not raw_text:
            return None
        try:
            value = Decimal(raw_text)
        except (InvalidOperation, ValueError):
            return None
        if value < 0:
            return None
        scaled = value / REQUEST_QUOTA_STEP
        if scaled != scaled.to_integral_value():
            return None
        return value

    def _normalize_quantity_text(self, text: str) -> str:
        quantity = self._parse_quantity_value(text)
        if quantity is None:
            return (text or "").strip()
        return format_quota_value(quantity)

    def _normalize_quantity_if_needed(self) -> None:
        raw_text = (self.quantity_edit.text() or "").strip()
        if not raw_text:
            return
        quantity = self._parse_quantity_value(raw_text)
        if quantity is None:
            return
        normalized_text = self._normalize_quantity_text(raw_text)
        if quantity > Decimal(str(MAX_REQUEST_QUOTA)):
            normalized_text = self._last_valid_quantity_text
        if normalized_text == raw_text:
            return
        self.quantity_edit.blockSignals(True)
        try:
            self.quantity_edit.setText(normalized_text)
        finally:
            self.quantity_edit.blockSignals(False)

    def _normalize_amount_text(self, text: str) -> str:
        raw_text = (text or "").strip()
        if not raw_text:
            return ""
        try:
            normalized = Decimal(raw_text)
        except (InvalidOperation, ValueError):
            return raw_text
        return format(normalized.normalize(), "f").rstrip("0").rstrip(".") or "0"

    def _parse_amount_value(self, text: Optional[str] = None) -> Optional[Decimal]:
        raw_text = (self.amount_edit.currentText() if text is None else text) or ""
        raw_text = raw_text.strip()
        if not raw_text:
            return None
        try:
            value = Decimal(raw_text)
        except (InvalidOperation, ValueError):
            return None
        if value <= 0:
            return None
        return value

    def _get_minimum_allowed_amount(self, quantity: Decimal) -> Optional[Decimal]:
        for min_quantity, min_amount in DONATION_AMOUNT_RULES:
            if quantity >= min_quantity:
                return min_amount
        return self._parse_amount_value(DONATION_AMOUNT_OPTIONS[0])

    def _get_allowed_amount_options(self, quantity: Decimal) -> list[str]:
        minimum_allowed_amount = self._get_minimum_allowed_amount(quantity)
        if minimum_allowed_amount is None:
            return DONATION_AMOUNT_OPTIONS[:]
        return [
            amount
            for amount in DONATION_AMOUNT_OPTIONS
            if (self._parse_amount_value(amount) or Decimal("0")) >= minimum_allowed_amount
        ]

    def _is_amount_allowed(self, amount_text: str, quantity_text: Optional[str] = None) -> bool:
        amount_value = self._parse_amount_value(amount_text)
        if amount_value is None:
            return True

        quantity = self._parse_quantity_value(quantity_text) or Decimal("0")
        minimum_allowed_amount = self._get_minimum_allowed_amount(quantity)
        if minimum_allowed_amount is None:
            return True
        return amount_value >= minimum_allowed_amount

    def _refresh_amount_options(self) -> None:
        current_text = (self.amount_edit.currentText() or "").strip()
        allowed_amounts = self._get_allowed_amount_options(self._parse_quantity_value() or Decimal("0"))

        previous_block_state = self.amount_edit.blockSignals(True)
        try:
            self.amount_edit.clear()
            for amount in allowed_amounts:
                self.amount_edit.addItem(amount)
            if not current_text:
                self.amount_edit._currentIndex = -1
                self.amount_edit.setText("")
            else:
                current_index = self.amount_edit.findText(current_text)
                if current_index >= 0:
                    self.amount_edit.setCurrentIndex(current_index)
                else:
                    self.amount_edit._currentIndex = -1
                    self.amount_edit.setText(current_text)
        finally:
            self.amount_edit.blockSignals(previous_block_state)

    def _show_amount_rule_infobar(self) -> None:
        self.amount_rule_hint.show()

    def _close_amount_rule_infobar(self) -> None:
        self.amount_rule_hint.hide()

    def _sync_amount_rule_warning(self) -> None:
        current_type = self.type_combo.currentText() or ""
        amount_text = (self.amount_edit.currentText() or "").strip()
        if current_type != REQUEST_MESSAGE_TYPE or not amount_text:
            self._close_amount_rule_infobar()
            return
        if self._is_amount_allowed(amount_text):
            self._close_amount_rule_infobar()
            return
        self._show_amount_rule_infobar()



