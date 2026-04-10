"""联系开发者表单组件，可嵌入页面或对话框。"""
import logging
from typing import Callable, Optional, cast

from software.logging.log_utils import log_suppressed_exception

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    EditableComboBox,
    FluentIcon,
    IconWidget,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    RadioButton,
)

from software.ui.helpers.contact_api import get_session_snapshot
from software.ui.helpers.fluent_tooltip import install_tooltip_filters
from software.ui.helpers.image_attachments import ImageAttachmentManager
from software.ui.widgets.status_polling_mixin import StatusPollingMixin

from .attachments import ContactFormAttachmentsMixin
from .constants import (
    DONATION_AMOUNT_BLOCK_MESSAGE,
    DONATION_AMOUNT_OPTIONS,
    MAX_REQUEST_QUOTA,
    PAYMENT_METHOD_OPTIONS,
    REQUEST_MESSAGE_TYPE,
)
from .donation import ContactFormDonationMixin
from .inputs import ContactFormInputMixin, PasteOnlyLineEdit, PasteOnlyPlainTextEdit
from .submission import ContactFormSubmissionMixin
from .verification import ContactFormVerificationMixin


class ContactForm(
    ContactFormAttachmentsMixin,
    ContactFormVerificationMixin,
    ContactFormDonationMixin,
    ContactFormSubmissionMixin,
    ContactFormInputMixin,
    StatusPollingMixin,
    QWidget,
):
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
        self.attachments_section = QWidget(self)
        attachments_box = QVBoxLayout(self.attachments_section)
        attachments_box.setContentsMargins(0, 0, 0, 0)
        attachments_box.setSpacing(6)

        attach_toolbar = QHBoxLayout()
        self.attach_title = BodyLabel("图片附件 (最多3张，支持Ctrl+V粘贴，单张≤10MB):", self.attachments_section)

        self.attach_add_btn = PushButton(FluentIcon.ADD, "添加图片", self.attachments_section)
        self.attach_clear_btn = PushButton(FluentIcon.DELETE, "清空附件", self.attachments_section)

        attach_toolbar.addWidget(self.attach_title)
        attach_toolbar.addStretch(1)
        attach_toolbar.addWidget(self.attach_add_btn)
        attach_toolbar.addWidget(self.attach_clear_btn)

        attachments_box.addLayout(attach_toolbar)

        self.attach_list_layout = QHBoxLayout()
        self.attach_list_layout.setSpacing(12)
        self.attach_list_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.attach_list_container = QWidget(self.attachments_section)
        self.attach_list_container.setLayout(self.attach_list_layout)

        self.attach_placeholder = BodyLabel("暂无附件", self.attachments_section)
        self.attach_placeholder.setStyleSheet("color: #888; padding: 6px;")

        attachments_box.addWidget(self.attach_list_container)
        attachments_box.addWidget(self.attach_placeholder)

        self.request_payment_section = QWidget(self)
        payment_layout = QVBoxLayout(self.request_payment_section)
        payment_layout.setContentsMargins(0, 0, 0, 0)
        payment_layout.setSpacing(6)

        payment_row = QHBoxLayout()
        payment_row.setSpacing(12)
        self.payment_method_label = BodyLabel("选择的支付方式：", self.request_payment_section)
        self.payment_method_group = QButtonGroup(self.request_payment_section)
        self.payment_method_group.setExclusive(True)
        self.payment_method_wechat_radio = RadioButton(PAYMENT_METHOD_OPTIONS[0], self.request_payment_section)
        self.payment_method_alipay_radio = RadioButton(PAYMENT_METHOD_OPTIONS[1], self.request_payment_section)
        self.payment_method_group.addButton(self.payment_method_wechat_radio, 1)
        self.payment_method_group.addButton(self.payment_method_alipay_radio, 2)
        payment_row.addWidget(self.payment_method_label)
        payment_row.addWidget(self.payment_method_wechat_radio)
        payment_row.addWidget(self.payment_method_alipay_radio)
        payment_row.addStretch(1)
        payment_layout.addLayout(payment_row)

        self.request_payment_section.hide()

        # 组装表单、消息、附件
        wrapper.addLayout(form_layout)
        wrapper.addLayout(msg_layout, 1) # 给消息框最大的 stretch
        wrapper.addWidget(self.attachments_section)
        wrapper.addWidget(self.request_payment_section)

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
        self.payment_method_group.buttonToggled.connect(lambda *_: self._update_send_button_state())
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

    def _selected_payment_method(self) -> str:
        checked_button = self.payment_method_group.checkedButton()
        return checked_button.text() if checked_button is not None else ""

    def _clear_payment_method_selection(self) -> None:
        was_exclusive = self.payment_method_group.exclusive()
        self.payment_method_group.setExclusive(False)
        try:
            for button in self.payment_method_group.buttons():
                button.setChecked(False)
        finally:
            self.payment_method_group.setExclusive(was_exclusive)

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

    def _on_type_changed(self):
        current_type = self.type_combo.currentText()
        self._sync_message_type_lock_state()

        # 控制额度申请参数显示/隐藏
        if current_type == REQUEST_MESSAGE_TYPE:
            self.attachments_section.hide()
            self.request_payment_section.show()
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
            self.attachments_section.show()
            self.request_payment_section.hide()
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
