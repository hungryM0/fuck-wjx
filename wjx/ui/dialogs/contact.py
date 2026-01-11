"""联系开发者对话框"""
import re
import threading
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPlainTextEdit
from qfluentwidgets import (
    BodyLabel,
    LineEdit,
    ComboBox,
    PushButton,
    PrimaryPushButton,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
)

from wjx.ui.widgets import StatusPollingMixin
from wjx.utils.config import CONTACT_API_URL
from wjx.utils.version import __VERSION__


class ContactDialog(StatusPollingMixin, QDialog):
    """联系开发者（Qt 版本）。使用 StatusPollingMixin 处理状态轮询。"""

    _statusLoaded = Signal(str, str)  # text, color
    _sendFinished = Signal(bool, str)  # success, message

    def __init__(self, parent=None, default_type: str = "报错反馈", status_fetcher=None, status_formatter=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._sendFinished.connect(self._on_send_finished)
        self.setWindowTitle("联系开发者")
        self.resize(720, 520)
        
        # 初始化状态轮询 Mixin
        self._init_status_polling(status_fetcher, status_formatter)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form_layout = QVBoxLayout()
        form_layout.setSpacing(10)

        self.email_label = BodyLabel("您的邮箱（选填，如果希望收到回复的话）：", self)
        form_layout.addWidget(self.email_label)
        self.email_edit = LineEdit(self)
        self.email_edit.setPlaceholderText("name@example.com")
        form_layout.addWidget(self.email_edit)

        form_layout.addWidget(BodyLabel("消息类型（可选）：", self))
        self.type_combo = ComboBox(self)
        self.base_options = ["报错反馈", "卡密获取", "新功能建议", "纯聊天"]
        for item in self.base_options:
            self.type_combo.addItem(item, item)
        form_layout.addWidget(self.type_combo)

        # 金额输入行（仅卡密获取时显示）
        self.amount_row = QHBoxLayout()
        self.amount_label = BodyLabel("捐(施)助(舍)的金额：￥", self)
        self.amount_edit = LineEdit(self)
        self.amount_edit.setPlaceholderText("请输入金额")
        self.amount_edit.setMaximumWidth(200)
        validator = QDoubleValidator(0.0, 999999.99, 2, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.amount_edit.setValidator(validator)
        self.amount_edit.textChanged.connect(self._on_amount_changed)
        self.amount_row.addWidget(self.amount_label)
        self.amount_row.addWidget(self.amount_edit)
        self.amount_row.addStretch()
        form_layout.addLayout(self.amount_row)
        self.amount_label.hide()
        self.amount_edit.hide()

        self.message_label = BodyLabel("请输入您的消息：", self)
        form_layout.addWidget(self.message_label)
        self.message_edit = QPlainTextEdit(self)
        self.message_edit.setPlaceholderText("请描述问题、需求或留言…")
        self.message_edit.setMinimumHeight(180)
        form_layout.addWidget(self.message_edit, 1)

        layout.addLayout(form_layout)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_spinner = IndeterminateProgressRing(self)
        self.status_spinner.setFixedSize(16, 16)
        self.status_spinner.setStrokeWidth(2)
        self.online_label = BodyLabel("作者当前在线状态：查询中...", self)
        self.online_label.setStyleSheet("color:#BA8303;")
        status_row.addWidget(self.status_spinner)
        status_row.addWidget(self.online_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", self)
        self.send_btn = PrimaryPushButton("发送", self)
        self.send_spinner = IndeterminateProgressRing(self)
        self.send_spinner.setFixedSize(20, 20)
        self.send_spinner.setStrokeWidth(3)
        self.send_spinner.hide()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.send_btn)
        btn_row.addWidget(self.send_spinner)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(self.reject)
        self.send_btn.clicked.connect(self._on_send_clicked)

        # set default type
        idx = self.type_combo.findText(default_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        
        # 连接信号并初始化
        self.type_combo.currentIndexChanged.connect(lambda _: self._on_type_changed())
        QTimer.singleShot(0, self._on_type_changed)
        
        # 保存消息类型用于回调
        self._current_message_type: str = ""
        
        # 启动状态查询和定时刷新
        self._start_status_polling()

    def closeEvent(self, arg__1):
        """对话框关闭时安全停止线程"""
        self._stop_status_polling()
        super().closeEvent(arg__1)

    def reject(self):
        """取消时安全停止线程"""
        self._stop_status_polling()
        super().reject()

    def accept(self):
        """确认时安全停止线程"""
        self._stop_status_polling()
        super().accept()

    def _on_type_changed(self):
        current_type = self.type_combo.currentText()
        
        # 动态添加/移除"白嫖卡密"选项
        has_whitepiao = False
        whitepiao_idx = -1
        for i in range(self.type_combo.count()):
            if self.type_combo.itemText(i) == "白嫖卡密（？）":
                has_whitepiao = True
                whitepiao_idx = i
                break
        
        self.type_combo.blockSignals(True)
        try:
            if current_type == "卡密获取" and not has_whitepiao:
                self.type_combo.addItem("白嫖卡密（？）")
            elif current_type not in ("卡密获取", "白嫖卡密（？）") and has_whitepiao:
                if whitepiao_idx >= 0:
                    self.type_combo.removeItem(whitepiao_idx)
        finally:
            self.type_combo.blockSignals(False)

        # 控制金额行显示/隐藏
        if current_type == "卡密获取":
            self.amount_label.show()
            self.amount_edit.show()
            self.email_label.setText("您的邮箱（必填）：")
            self.message_label.setText("请输入您的消息：")
        elif current_type == "白嫖卡密（？）":
            self.amount_label.hide()
            self.amount_edit.hide()
            self.email_label.setText("您的邮箱（必填）：")
            self.message_label.setText("请输入白嫖话术：")
        else:
            self.amount_label.hide()
            self.amount_edit.hide()
            self.email_label.setText("您的邮箱（选填，如果希望收到回复的话）：")
            self.message_label.setText("请输入您的消息：")

    def _on_amount_changed(self, text: str):
        """金额输入框文本改变时同步到消息框"""
        current_type = self.type_combo.currentText()
        if current_type != "卡密获取":
            return
        
        # 获取当前消息框内容
        current_msg = self.message_edit.toPlainText()
        
        # 构建金额行
        amount_line = f"捐(施)助(舍)的金额：￥{text}" if text else ""
        
        # 检查消息框是否已有金额行
        lines = current_msg.split('\n')
        if lines and lines[0].startswith("捐(施)助(舍)的金额：￥"):
            # 替换第一行
            if amount_line:
                lines[0] = amount_line
            else:
                lines.pop(0)
            new_msg = '\n'.join(lines)
        else:
            # 在开头添加金额行
            if amount_line:
                new_msg = amount_line + ('\n' + current_msg if current_msg else '')
            else:
                new_msg = current_msg
        
        # 更新消息框
        self.message_edit.setPlainText(new_msg)

    def _on_status_loaded(self, text: str, color: str):
        """信号槽：在主线程更新状态标签"""
        try:
            self.status_spinner.hide()
            self.online_label.setText(text)
            self.online_label.setStyleSheet(f"color:{color};")
        except RuntimeError:
            pass

    def _validate_email(self, email: str) -> bool:
        if not email:
            return True
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(pattern, email) is not None

    def _on_send_clicked(self):
        email = (self.email_edit.text() or "").strip()
        
        # 延迟清除邮箱选中状态，确保在所有事件处理完成后执行
        QTimer.singleShot(10, lambda: self.email_edit.setSelection(0, 0))
        QTimer.singleShot(10, lambda: self.send_btn.setFocus())
        
        mtype = self.type_combo.currentText() or "报错反馈"
        
        # 直接读取消息框内容
        message = (self.message_edit.toPlainText() or "").strip()
        
        # 验证消息内容
        if mtype == "卡密获取":
            # 检查是否包含金额信息
            if not message or not message.startswith("捐(施)助(舍)的金额：￥"):
                InfoBar.warning("", "请输入捐助金额", parent=self, position=InfoBarPosition.TOP, duration=2000)
                return
        else:
            if not message:
                InfoBar.warning("", "请输入消息内容", parent=self, position=InfoBarPosition.TOP, duration=2000)
                return
        
        if mtype in ("卡密获取", "白嫖卡密（？）") and not email:
            InfoBar.warning("", f"{mtype}必须填写邮箱地址", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        if email and not self._validate_email(email):
            InfoBar.warning("", "邮箱格式不正确", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        try:
            from requests import post
        except Exception:
            InfoBar.error("", "requests 模块未安装，无法发送", parent=self, position=InfoBarPosition.TOP, duration=2500)
            return

        version_str = __VERSION__
        full_message = f"来源：fuck-wjx v{version_str}\n类型：{mtype}\n"
        if email:
            full_message += f"联系邮箱： {email}\n"
        full_message += f"消息：{message}"

        # 使用配置文件中的联系API地址
        api_url = CONTACT_API_URL
        if not api_url:
            InfoBar.error("", "联系API未配置", parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        payload = {"message": full_message, "timestamp": datetime.now().isoformat()}

        # 清除焦点，防止邮箱被选中
        self.send_btn.setFocus()
        
        self.send_btn.setEnabled(False)
        self.send_btn.setText("发送中...")
        self.send_spinner.show()

        # 保存消息类型用于回调
        self._current_message_type = mtype

        def _send():
            try:
                resp = post(api_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
                if resp.status_code == 200:
                    self._sendFinished.emit(True, "")
                else:
                    self._sendFinished.emit(False, f"发送失败：{resp.status_code}")
            except Exception as exc:
                self._sendFinished.emit(False, f"发送失败：{exc}")

        threading.Thread(target=_send, daemon=True).start()

    def _on_send_finished(self, success: bool, error_msg: str):
        """发送完成回调（在主线程执行）"""
        self.send_spinner.hide()
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        
        if success:
            msg = "发送成功！请留意邮件信息！" if getattr(self, '_current_message_type', '') == "卡密获取" else "消息已成功发送！"
            InfoBar.success("", msg, parent=self, position=InfoBarPosition.TOP, duration=2500)
            QTimer.singleShot(500, self.accept)
        else:
            InfoBar.error("", error_msg, parent=self, position=InfoBarPosition.TOP, duration=3000)
