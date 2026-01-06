"""联系开发者对话框"""
import os
import re
import threading
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
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

from wjx.ui.widgets import StatusFetchWorker
from wjx.utils.version import __VERSION__


class ContactDialog(QDialog):
    """联系开发者（Qt 版本）。使用 QThread + Worker 模式确保线程安全。"""

    _statusLoaded = Signal(str, str)  # text, color

    def __init__(self, parent=None, default_type: str = "报错反馈", status_fetcher=None, status_formatter=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._statusLoaded.connect(self._on_status_loaded)
        self.setWindowTitle("联系开发者")
        self.resize(720, 520)
        
        # QThread + Worker 相关
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[StatusFetchWorker] = None
        self._status_timer: Optional[QTimer] = None
        self._status_fetcher = status_fetcher
        self._status_formatter = status_formatter
        
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
        self.send_status_label = BodyLabel("", self)
        self.send_status_label.setStyleSheet("color:#2563EB;")
        status_row.addWidget(self.status_spinner)
        status_row.addWidget(self.online_label)
        status_row.addWidget(self.send_status_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", self)
        self.send_btn = PrimaryPushButton("发送", self)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.send_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(self.reject)
        self.send_btn.clicked.connect(self._on_send_clicked)

        # set default type
        idx = self.type_combo.findData(default_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        
        # 连接信号并初始化
        self.type_combo.currentIndexChanged.connect(lambda _: self._on_type_changed())
        QTimer.singleShot(0, self._on_type_changed)
        
        # 启动状态查询和定时刷新
        self._start_status_polling()

    def _start_status_polling(self):
        """启动状态轮询"""
        if not callable(self._status_fetcher):
            self.online_label.setText("作者当前在线状态：未知")
            self.status_spinner.hide()
            return
        
        # 立即执行一次查询
        self._fetch_status_once()
        
        # 设置定时器，每 5 秒刷新一次
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._fetch_status_once)
        self._status_timer.start()

    def _fetch_status_once(self):
        """执行一次状态查询（使用 QThread）"""
        # 如果上一次查询还在进行，跳过
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return
        
        # 创建新的 Worker 和 Thread
        self._worker_thread = QThread(self)
        self._worker = StatusFetchWorker(self._status_fetcher, self._status_formatter)
        self._worker.moveToThread(self._worker_thread)
        
        # 连接信号
        self._worker.finished.connect(self._on_status_loaded)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.started.connect(self._worker.fetch)
        
        # 启动线程
        self._worker_thread.start()

    def _stop_status_polling(self):
        """停止状态轮询并安全清理线程"""
        # 停止定时器
        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None
        
        # 停止 Worker
        if self._worker is not None:
            self._worker.stop()
        
        # 等待线程结束
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(1000)
            if self._worker_thread.isRunning():
                self._worker_thread.terminate()
        
        self._worker = None
        self._worker_thread = None

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
        # 检查是否已有白嫖卡密选项
        has_whitepiao = False
        whitepiao_idx = -1
        for i in range(self.type_combo.count()):
            if self.type_combo.itemText(i) == "白嫖卡密（？）":
                has_whitepiao = True
                whitepiao_idx = i
                break
        
        # 阻止信号避免递归
        self.type_combo.blockSignals(True)
        try:
            if current_type == "卡密获取" and not has_whitepiao:
                # 添加白嫖卡密选项
                self.type_combo.addItem("白嫖卡密（？）")
            elif current_type not in ("卡密获取", "白嫖卡密（？）") and has_whitepiao:
                # 移除白嫖卡密选项
                if whitepiao_idx >= 0:
                    self.type_combo.removeItem(whitepiao_idx)
        finally:
            self.type_combo.blockSignals(False)

        if current_type in ("卡密获取", "白嫖卡密（？）"):
            self.email_label.setText("您的邮箱（必填）：")
        else:
            self.email_label.setText("您的邮箱（选填，如果希望收到回复的话）：")

        # preset text for donation/whitepiao
        text = self.message_edit.toPlainText().strip()
        if current_type == "卡密获取":
            if not text.startswith("捐(施)助(舍)的金额：￥"):
                self.message_edit.setPlainText("捐(施)助(舍)的金额：￥")
        elif current_type == "白嫖卡密（？）":
            if text.startswith("捐(施)助(舍)的金额：￥"):
                self.message_edit.setPlainText("")
            self.message_label.setText("请输入白嫖话术：")
        else:
            self.message_label.setText("请输入您的消息：")
            if text.startswith("捐(施)助(舍)的金额：￥"):
                self.message_edit.setPlainText(text[13:])

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
        message = (self.message_edit.toPlainText() or "").strip()
        email = (self.email_edit.text() or "").strip()
        mtype = self.type_combo.currentData() or "报错反馈"
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

        # 从环境变量读取联系API地址（必须在.env中配置）
        api_url = os.getenv("CONTACT_API_URL")
        if not api_url:
            InfoBar.error("", "联系API未配置，请检查 .env 文件", parent=self, position=InfoBarPosition.TOP, duration=3000)
            self.send_btn.setEnabled(True)
            self.send_status_label.setText("")
            return
        payload = {"message": full_message, "timestamp": datetime.now().isoformat()}

        self.send_btn.setEnabled(False)
        self.send_status_label.setText("正在发送...")

        def _send():
            try:
                resp = post(api_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
                ok = resp.status_code == 200
                def _done():
                    self.send_btn.setEnabled(True)
                    self.send_status_label.setText("")
                    if ok:
                        msg = "发送成功！请留意邮件信息！" if mtype == "卡密获取" else "消息已成功发送！"
                        InfoBar.success("", msg, parent=self, position=InfoBarPosition.TOP, duration=2500)
                        self.accept()
                    else:
                        InfoBar.error("", f"发送失败：{resp.status_code}", parent=self, position=InfoBarPosition.TOP, duration=2500)
                QTimer.singleShot(0, _done)
            except Exception as exc:
                def _err():
                    self.send_btn.setEnabled(True)
                    self.send_status_label.setText("")
                    InfoBar.error("", f"发送失败：{exc}", parent=self, position=InfoBarPosition.TOP, duration=3000)
                QTimer.singleShot(0, _err)

        threading.Thread(target=_send, daemon=True).start()
