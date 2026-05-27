"""联系表单界面搭建。"""

from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    EditableComboBox,
    FluentIcon,
    IconWidget,
    IndeterminateProgressRing,
    PrimaryPushButton,
    PushButton,
    LineEdit,
    RadioButton,
)

from software.ui.helpers.fluent_tooltip import install_tooltip_filters

from .constants import (
    DONATION_AMOUNT_BLOCK_MESSAGE,
    DONATION_AMOUNT_OPTIONS,
    MAX_REQUEST_QUOTA,
    PAYMENT_METHOD_OPTIONS,
    REQUEST_MESSAGE_TYPE,
)
from .input_widgets import PasteOnlyLineEdit, PasteOnlyPlainTextEdit


def build_contact_form_ui(form: Any, *, default_type: str, show_cancel_button: bool) -> None:
    wrapper = QVBoxLayout(form)
    wrapper.setContentsMargins(0, 0, 0, 0)
    wrapper.setSpacing(16)

    form_layout = QVBoxLayout()
    form_layout.setSpacing(12)
    form_layout.setContentsMargins(0, 0, 0, 0)

    label_width = 75
    compact_field_width = 320

    type_row = QHBoxLayout()
    form.type_label_static = BodyLabel("消息类型：", form)
    form.type_label_static.setFixedWidth(label_width)
    form.type_combo = ComboBox(form)
    form.type_locked_label = BodyLabel("", form)
    form.type_locked_label.setFixedWidth(compact_field_width)
    form.base_options = [
        "报错反馈",
        REQUEST_MESSAGE_TYPE,
        "新功能建议",
        "纯聊天",
    ]
    for item in form.base_options:
        form.type_combo.addItem(item, item)
    form.type_combo.setFixedWidth(compact_field_width)
    type_row.addWidget(form.type_label_static)
    type_row.addWidget(form.type_combo)
    type_row.addWidget(form.type_locked_label)
    type_row.addStretch(1)
    form_layout.addLayout(type_row)

    email_row = QHBoxLayout()
    form.email_label = BodyLabel("联系邮箱：", form)
    form.email_label.setFixedWidth(label_width)
    form.email_edit = PasteOnlyLineEdit(form)
    form.email_edit.setPlaceholderText("name@example.com")
    form.email_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    email_row.addWidget(form.email_label)
    email_row.addWidget(form.email_edit, 1)

    form_layout.addLayout(email_row)

    title_row = QHBoxLayout()
    title_row.setSpacing(6)
    form.issue_title_label = BodyLabel("反馈标题：", form)
    form.issue_title_label.setFixedWidth(label_width)
    form.issue_title_edit = LineEdit(form)
    form.issue_title_edit.setPlaceholderText("可选")
    form.issue_title_edit.setClearButtonEnabled(True)
    form.issue_title_edit.setMaxLength(60)
    form.issue_title_edit.setFixedWidth(compact_field_width)
    title_row.addWidget(form.issue_title_label)
    title_row.addWidget(form.issue_title_edit)
    title_row.addStretch(1)
    form_layout.addLayout(title_row)

    form.issue_title_label.hide()
    form.issue_title_edit.hide()

    form.amount_row = QHBoxLayout()
    form.amount_label = BodyLabel("支付金额：￥", form)
    form.amount_edit = EditableComboBox(form)
    form.amount_edit.setPlaceholderText("必填")
    form.amount_edit.setMaximumWidth(100)
    amount_validator = QDoubleValidator(0.01, 9999.99, 2, form)
    amount_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    for amount in DONATION_AMOUNT_OPTIONS:
        form.amount_edit.addItem(amount)
    form.amount_edit.setText("11.45")
    form.amount_edit.setValidator(amount_validator)
    form.amount_edit.currentTextChanged.connect(form._on_amount_changed)
    form.amount_edit.editingFinished.connect(form._on_amount_editing_finished)
    form.amount_edit.installEventFilter(form)

    form.quantity_label = BodyLabel("需求额度：", form)
    form.quantity_edit = LineEdit(form)
    form.quantity_edit.setPlaceholderText("按需填写")
    form.quantity_edit.setMaximumWidth(90)
    form.quantity_edit.setMaxLength(len(str(MAX_REQUEST_QUOTA)) + 2)
    quantity_validator = QDoubleValidator(0.0, float(MAX_REQUEST_QUOTA), 1, form)
    quantity_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    form.quantity_edit.setValidator(quantity_validator)
    form.quantity_edit.textChanged.connect(form._on_quantity_changed)
    form.quantity_edit.editingFinished.connect(form._on_quantity_editing_finished)

    form.urgency_label = BodyLabel("问卷紧急程度：", form)
    form.urgency_combo = ComboBox(form)
    form.urgency_combo.setMaximumWidth(140)
    for urgency in [
        "低",
        "中（本月内）",
        "高（本周内）",
        "紧急（两天内）",
    ]:
        form.urgency_combo.addItem(urgency, urgency)
    urgency_default_index = form.urgency_combo.findText("中（本月内）")
    if urgency_default_index >= 0:
        form.urgency_combo.setCurrentIndex(urgency_default_index)
    form.urgency_combo.currentIndexChanged.connect(lambda _: form._on_urgency_changed())

    form.amount_row.addWidget(form.quantity_label)
    form.amount_row.addWidget(form.quantity_edit)
    form.amount_row.addSpacing(16)
    form.amount_row.addWidget(form.amount_label)
    form.amount_row.addWidget(form.amount_edit)
    form.amount_row.addSpacing(16)
    form.amount_row.addWidget(form.urgency_label)
    form.amount_row.addWidget(form.urgency_combo)
    form.amount_row.addStretch(1)
    form_layout.addLayout(form.amount_row)

    form.amount_rule_hint = QWidget(form)
    form.amount_rule_hint.setObjectName("amountRuleHint")
    form.amount_rule_hint.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Fixed,
    )
    form.amount_rule_hint.setStyleSheet(
        "#amountRuleHint {"
        "background-color: #FFF4CE;"
        "border: 1px solid #F2D58A;"
        "border-radius: 8px;"
        "}"
    )
    amount_rule_hint_layout = QHBoxLayout(form.amount_rule_hint)
    amount_rule_hint_layout.setContentsMargins(12, 8, 12, 8)
    amount_rule_hint_layout.setSpacing(8)
    form.amount_rule_hint_icon = IconWidget(FluentIcon.INFO, form.amount_rule_hint)
    form.amount_rule_hint_icon.setIcon(FluentIcon.INFO)
    form.amount_rule_hint_icon.setStyleSheet("color: #B57A00;")
    form.amount_rule_hint_text = BodyLabel(
        DONATION_AMOUNT_BLOCK_MESSAGE,
        form.amount_rule_hint,
    )
    form.amount_rule_hint_text.setStyleSheet("color: #7A5200;")
    amount_rule_hint_layout.addWidget(form.amount_rule_hint_icon)
    amount_rule_hint_layout.addWidget(form.amount_rule_hint_text, 1)
    form_layout.addWidget(form.amount_rule_hint)

    form.amount_label.hide()
    form.amount_edit.hide()
    form.quantity_label.hide()
    form.quantity_edit.hide()
    form.urgency_label.hide()
    form.urgency_combo.hide()
    form.amount_rule_hint.hide()

    msg_layout = QVBoxLayout()
    msg_layout.setSpacing(6)
    msg_label_row = QHBoxLayout()
    form.message_label = BodyLabel("消息内容：", form)
    msg_label_row.addWidget(form.message_label)
    msg_label_row.addStretch(1)

    form.message_edit = PasteOnlyPlainTextEdit(form, form._on_context_paste)
    form.message_edit.setPlaceholderText("请详细描述您的问题、需求或留言…")
    form.message_edit.setMinimumHeight(140)
    form.message_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    form.message_edit.installEventFilter(form)
    form.random_ip_user_id_label = BodyLabel("", form)
    form.random_ip_user_id_label.setWordWrap(True)
    form.random_ip_user_id_label.setStyleSheet("color: #666; font-size: 12px;")
    form.random_ip_user_id_label.hide()

    msg_layout.addLayout(msg_label_row)
    msg_layout.addWidget(form.message_edit, 1)
    msg_layout.addWidget(form.random_ip_user_id_label)

    form.attachments_section = QWidget(form)
    attachments_box = QVBoxLayout(form.attachments_section)
    attachments_box.setContentsMargins(0, 0, 0, 0)
    attachments_box.setSpacing(6)

    attach_toolbar = QGridLayout()
    attach_toolbar.setContentsMargins(0, 0, 0, 0)
    attach_toolbar.setHorizontalSpacing(10)
    attach_toolbar.setVerticalSpacing(6)
    form.attach_title = BodyLabel(
        "图片附件 (最多3张，支持Ctrl+V粘贴，单张≤10MB):",
        form.attachments_section,
    )
    form.attach_title.setWordWrap(True)
    form.attach_add_btn = PushButton(FluentIcon.ADD, "添加图片", form.attachments_section)
    form.attach_clear_btn = PushButton(
        FluentIcon.DELETE,
        "清空附件",
        form.attachments_section,
    )
    form.attach_add_btn.setMinimumWidth(112)
    form.attach_clear_btn.setMinimumWidth(112)
    attach_toolbar.addWidget(form.attach_title, 0, 0)
    attach_toolbar.addWidget(form.attach_add_btn, 0, 1)
    attach_toolbar.addWidget(form.attach_clear_btn, 0, 2)
    attach_toolbar.setColumnStretch(0, 1)
    attachments_box.addLayout(attach_toolbar)

    form.attach_list_layout = QHBoxLayout()
    form.attach_list_layout.setSpacing(12)
    form.attach_list_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

    form.attach_list_container = QWidget(form.attachments_section)
    form.attach_list_container.setLayout(form.attach_list_layout)

    form.attach_placeholder = BodyLabel("暂无附件", form.attachments_section)
    form.attach_placeholder.setStyleSheet("color: #888; padding: 6px;")

    attachments_box.addWidget(form.attach_list_container)
    attachments_box.addWidget(form.attach_placeholder)

    form.auto_attach_section = QWidget(form)
    auto_attach_layout = QHBoxLayout(form.auto_attach_section)
    auto_attach_layout.setContentsMargins(0, 0, 0, 0)
    auto_attach_layout.setSpacing(12)
    form.auto_attach_title = BodyLabel("附加排障文件：", form.auto_attach_section)
    form.auto_attach_config_checkbox = CheckBox("上传当前运行配置", form.auto_attach_section)
    form.auto_attach_log_checkbox = CheckBox("上传当前日志", form.auto_attach_section)
    form.auto_attach_config_checkbox.setChecked(form._auto_attach_config_default)
    form.auto_attach_log_checkbox.setChecked(form._auto_attach_log_default)
    auto_attach_layout.addWidget(form.auto_attach_title)
    auto_attach_layout.addWidget(form.auto_attach_config_checkbox)
    auto_attach_layout.addWidget(form.auto_attach_log_checkbox)
    form.auto_attach_section.hide()

    form.request_payment_section = QWidget(form)
    payment_layout = QVBoxLayout(form.request_payment_section)
    payment_layout.setContentsMargins(0, 0, 0, 0)
    payment_layout.setSpacing(6)

    payment_row = QHBoxLayout()
    payment_row.setSpacing(12)
    form.payment_method_label = BodyLabel("选择的支付方式：", form.request_payment_section)
    form.payment_method_group = QButtonGroup(form.request_payment_section)
    form.payment_method_group.setExclusive(True)
    form.payment_method_wechat_radio = RadioButton(
        PAYMENT_METHOD_OPTIONS[0],
        form.request_payment_section,
    )
    form.payment_method_alipay_radio = RadioButton(
        PAYMENT_METHOD_OPTIONS[1],
        form.request_payment_section,
    )
    form.payment_method_group.addButton(form.payment_method_wechat_radio, 1)
    form.payment_method_group.addButton(form.payment_method_alipay_radio, 2)
    payment_row.addWidget(form.payment_method_label)
    payment_row.addWidget(form.payment_method_wechat_radio)
    payment_row.addWidget(form.payment_method_alipay_radio)
    payment_row.addStretch(1)
    payment_layout.addLayout(payment_row)
    form.request_payment_section.hide()

    wrapper.addLayout(form_layout)
    wrapper.addLayout(msg_layout, 1)
    wrapper.addWidget(form.auto_attach_section)
    wrapper.addWidget(form.attachments_section)
    wrapper.addWidget(form.request_payment_section)

    form.request_payment_confirm_section = QWidget(form)
    donated_row = QHBoxLayout(form.request_payment_confirm_section)
    donated_row.setContentsMargins(0, 0, 0, 0)
    donated_row.setSpacing(8)
    form.donated_cb = CheckBox(
        "我已完成支付，且确认随机ip可用",
        form.request_payment_confirm_section,
    )
    form.open_donate_btn = PushButton(
        FluentIcon.HEART,
        "去支付",
        form.request_payment_confirm_section,
    )
    form.open_donate_btn.setToolTip("打开支付页面")
    donated_row.addStretch(1)
    donated_row.addWidget(form.open_donate_btn)
    donated_row.addWidget(form.donated_cb)
    form.request_payment_confirm_section.hide()
    wrapper.addWidget(form.request_payment_confirm_section)

    bottom_layout = QHBoxLayout()
    bottom_layout.setContentsMargins(0, 8, 0, 0)

    status_row = QHBoxLayout()
    status_row.setSpacing(8)
    form.status_spinner = IndeterminateProgressRing(form, start=False)
    form.status_spinner.setFixedSize(16, 16)
    form.status_spinner.setStrokeWidth(2)
    form.status_icon = IconWidget(FluentIcon.INFO, form)
    form.status_icon.setFixedSize(16, 16)
    form.status_icon.hide()
    form.online_label = BodyLabel("作者当前在线状态：查询中...", form)
    form.online_label.setStyleSheet("color:#BA8303;")
    form.online_label.setWordWrap(True)
    status_row.addWidget(form.status_spinner)
    status_row.addWidget(form.status_icon)
    status_row.addWidget(form.online_label, 1)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(10)
    form.cancel_btn = None
    if show_cancel_button:
        form.cancel_btn = PushButton("取消", form)
        btn_row.addWidget(form.cancel_btn)
    form.send_btn = PrimaryPushButton("发送", form)
    form.send_spinner = IndeterminateProgressRing(form, start=False)
    form.send_spinner.setFixedSize(20, 20)
    form.send_spinner.setStrokeWidth(3)
    form.send_spinner.hide()
    btn_row.addWidget(form.send_spinner)
    btn_row.addWidget(form.send_btn)

    bottom_layout.addLayout(status_row, 1)
    bottom_layout.addLayout(btn_row)
    wrapper.addLayout(bottom_layout)

    form.type_combo.currentIndexChanged.connect(lambda _: form._on_type_changed())
    form.donated_cb.installEventFilter(form)
    form.donated_cb.toggled.connect(lambda _: form._update_send_button_state())
    form.open_donate_btn.clicked.connect(form._open_donate_page)
    install_tooltip_filters((form.open_donate_btn, form.donated_cb, form.send_btn))
    form.send_btn.clicked.connect(form._on_send_clicked)
    form.attach_add_btn.clicked.connect(form._on_choose_files)
    form.attach_clear_btn.clicked.connect(form._on_clear_attachments)
    form.payment_method_group.buttonToggled.connect(lambda *_: form._update_send_button_state())
    if form.cancel_btn is not None:
        form.cancel_btn.clicked.connect(form.cancelRequested.emit)

    QTimer.singleShot(0, form._on_type_changed)
    if default_type:
        idx = form.type_combo.findText(default_type)
        if idx >= 0:
            form.type_combo.setCurrentIndex(idx)
    form._sync_message_type_lock_state()
    form.refresh_random_ip_user_id_hint()
