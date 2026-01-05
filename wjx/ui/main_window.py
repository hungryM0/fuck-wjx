from __future__ import annotations

import os
import re
import threading
import weakref
import webbrowser
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QObject, QThread, QTimer, Signal, QEvent, QMetaObject
from PySide6.QtGui import QIcon, QGuiApplication, QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSlider,
    QSizePolicy,
    QMenuBar,
    QToolButton,
)


class NoWheelSlider(QSlider):
    """禁用鼠标滚轮的滑块"""
    def wheelEvent(self, event):  # type: ignore[override]
        event.ignore()

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    CommandBar,
    Action,
    FluentIcon,
    FluentWindow,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    NavigationItemPosition,
    PasswordLineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TableWidget,
    Theme,
    setTheme,
    setThemeColor,
    RoundMenu,
    qconfig,
    TransparentToolButton,
    TeachingTip,
    TeachingTipTailPosition,
)

from wjx.utils.config import APP_ICON_RELATIVE_PATH, DEFAULT_FILL_TEXT, USER_AGENT_PRESETS
from wjx.engine import QuestionEntry, _get_entry_type_label, configure_probabilities, decode_qrcode, _get_resource_path as get_resource_path
from wjx.utils.load_save import RuntimeConfig, get_runtime_directory
from wjx.utils.log_utils import LOG_BUFFER_HANDLER, register_popup_handler, save_log_records_to_file
from wjx.network.random_ip import (
    on_random_ip_toggle,
    refresh_ip_counter_display,
    show_card_validation_dialog,
    get_status,
    _format_status_payload,
    _validate_card,
    RegistryManager,
)
from wjx.ui.controller import RunController
from wjx.utils.version import __VERSION__, ISSUE_FEEDBACK_URL, GITHUB_OWNER, GITHUB_REPO


class NoWheelSpinBox(SpinBox):
    """禁用鼠标滚轮的数字输入框"""
    def wheelEvent(self, event):  # type: ignore[override]
        event.ignore()


TYPE_CHOICES = [
    ("single", "单选题"),
    ("multiple", "多选题"),
    ("dropdown", "下拉题"),
    ("scale", "量表题"),
    ("matrix", "矩阵题"),
    ("text", "填空题"),
    ("multi_text", "多项填空"),
]

STRATEGY_CHOICES = [
    ("random", "完全随机"),
    ("custom", "自定义配比"),
]


def _question_summary(entry: QuestionEntry) -> str:
    try:
        return entry.summary()
    except Exception:
        return f"{entry.question_type} / {entry.option_count} 个选项"


class StatusFetchWorker(QObject):
    """状态查询 Worker，运行在独立 QThread 中，确保线程安全。"""
    finished = Signal(str, str)  # text, color
    
    def __init__(self, fetcher, formatter):
        super().__init__()
        self.fetcher = fetcher
        self.formatter = formatter
        self._stopped = False
    
    def stop(self):
        """标记停止，防止后续操作"""
        self._stopped = True
    
    def fetch(self):
        """执行状态查询，完成后发送 finished 信号"""
        if self._stopped:
            return
        text = "作者当前在线状态：未知"
        color = "#666666"
        try:
            if self._stopped:
                return
            result = self.fetcher()
            if self._stopped:
                return
            if callable(self.formatter):
                fmt_result = self.formatter(result)
                if isinstance(fmt_result, tuple) and len(fmt_result) >= 2:
                    text, color = str(fmt_result[0]), str(fmt_result[1])
            else:
                online = bool(result.get("online")) if isinstance(result, dict) else True
                text = f"作者当前在线状态：{'在线' if online else '离线'}"
                color = "#228B22" if online else "#cc0000"
        except Exception:
            text = "作者当前在线状态：未知"
            color = "#666666"
        
        if not self._stopped:
            self.finished.emit(text, color)


class CardUnlockDialog(QDialog):
    """解锁大额随机 IP 的说明/输入弹窗。使用 QThread + Worker 模式确保线程安全。"""

    _statusLoaded = Signal(str, str)  # text, color

    def __init__(self, parent=None, status_fetcher=None, status_formatter=None, contact_handler=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._statusLoaded.connect(self._on_status_loaded)
        self.setWindowTitle("随机IP额度限制")
        self.resize(820, 600)
        
        # QThread + Worker 相关
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[StatusFetchWorker] = None
        self._status_timer: Optional[QTimer] = None
        self._status_fetcher = status_fetcher
        self._status_formatter = status_formatter
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = SubtitleLabel("解锁大额随机IP提交额度", self)
        layout.addWidget(title)

        desc = BodyLabel(
            "作者只是一个大一小登，但是由于ip池及开发成本较高，用户量大，问卷份数要求多，"
            "加上学业压力，导致长期如此无偿经营困难……",
            self,
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 步骤说明卡片
        steps_card = CardWidget(self)
        steps_layout = QVBoxLayout(steps_card)
        steps_layout.setContentsMargins(12, 10, 12, 10)
        steps_layout.setSpacing(4)
        
        step1 = BodyLabel("1. 捐助任意金额（多少都行?）", steps_card)
        step2 = BodyLabel("2. 在「联系」中找到开发者，并留下联系邮箱", steps_card)
        step3 = BodyLabel("3. 输入卡密后即可解锁大额随机IP提交额度，不够用可继续免费申请", steps_card)
        step4 = BodyLabel("4. 你也可以通过自己的口才白嫖卡密（误）", steps_card)
        step4.setStyleSheet("color: #888; text-decoration: line-through;")
        
        steps_layout.addWidget(step1)
        steps_layout.addWidget(step2)
        steps_layout.addWidget(step3)
        steps_layout.addWidget(step4)
        layout.addWidget(steps_card)

        thanks = BodyLabel("感谢您的支持与理解！🙏", self)
        layout.addWidget(thanks)

        # 在线状态行（带加载动画）
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_spinner = IndeterminateProgressRing(self)
        self.status_spinner.setFixedSize(16, 16)
        self.status_spinner.setStrokeWidth(2)
        self.status_label = BodyLabel("作者当前在线状态：获取中...", self)
        self.status_label.setStyleSheet("color:#BA8303;")
        status_row.addWidget(self.status_spinner)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.contact_btn = PushButton("联系", self)
        self.donate_btn = PushButton("捐助", self)
        btn_row.addWidget(self.contact_btn)
        btn_row.addWidget(self.donate_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addWidget(BodyLabel("请输入卡密：", self))
        self.card_edit = PasswordLineEdit(self)
        self.card_edit.setPlaceholderText("输入卡密后点击「验证」")
        # 修改眼睛按钮为点击切换模式（而非按住模式）
        self._setup_toggle_password_button()
        # 为卡密输入框添加右键菜单
        self.card_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.card_edit.customContextMenuRequested.connect(self._show_card_edit_menu)
        layout.addWidget(self.card_edit)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        cancel_btn = PushButton("取消", self)
        ok_btn = PrimaryPushButton("验证", self)
        action_row.addWidget(cancel_btn)
        action_row.addWidget(ok_btn)
        layout.addLayout(action_row)

        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        self.contact_btn.clicked.connect(contact_handler if callable(contact_handler) else self._open_contact)
        self.donate_btn.clicked.connect(self._open_donate)

        # 启动状态查询和定时刷新
        self._start_status_polling()

        try:
            self.card_edit.setFocus()
        except Exception:
            pass

    def _start_status_polling(self):
        """启动状态轮询"""
        if not callable(self._status_fetcher):
            self.status_label.setText("作者当前在线状态：未知")
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
            self._worker_thread.wait(1000)  # 最多等待 1 秒
            if self._worker_thread.isRunning():
                self._worker_thread.terminate()
        
        self._worker = None
        self._worker_thread = None

    def closeEvent(self, event):
        """对话框关闭时安全停止线程"""
        self._stop_status_polling()
        super().closeEvent(event)

    def reject(self):
        """取消时安全停止线程"""
        self._stop_status_polling()
        super().reject()

    def accept(self):
        """确认时安全停止线程"""
        self._stop_status_polling()
        super().accept()

    def _on_status_loaded(self, text: str, color: str):
        """信号槽：在主线程更新状态标签"""
        try:
            self.status_spinner.hide()
            self.status_label.setText(text)
            self.status_label.setStyleSheet(f"color:{color};")
        except RuntimeError:
            pass

    def _open_contact(self):
        try:
            dlg = ContactDialog(
                self.window() or self,
                default_type="卡密获取",
                status_fetcher=self._status_fetcher or get_status,
                status_formatter=self._status_formatter or _format_status_payload,
            )
            dlg.exec()
        except Exception:
            webbrowser.open(ISSUE_FEEDBACK_URL)

    def _open_donate(self):
        try:
            payment_path = os.path.join(get_runtime_directory(), "assets", "payment.png")
            if os.path.exists(payment_path):
                webbrowser.open(payment_path)
                return
        except Exception:
            pass
        webbrowser.open("https://github.com/hungryM0/fuck-wjx")

    def _show_card_edit_menu(self, pos):
        """显示卡密输入框的右键菜单"""
        menu = RoundMenu(parent=self)
        
        # 剪切
        cut_action = Action(FluentIcon.CUT, "剪切")
        cut_action.triggered.connect(self.card_edit.cut)
        menu.addAction(cut_action)
        
        # 复制
        copy_action = Action(FluentIcon.COPY, "复制")
        copy_action.triggered.connect(self.card_edit.copy)
        menu.addAction(copy_action)
        
        # 粘贴
        paste_action = Action(FluentIcon.PASTE, "粘贴")
        paste_action.triggered.connect(self.card_edit.paste)
        menu.addAction(paste_action)
        
        menu.addSeparator()
        
        # 全选
        select_all_action = Action(FluentIcon.CHECKBOX, "全选")
        select_all_action.triggered.connect(self.card_edit.selectAll)
        menu.addAction(select_all_action)
        
        # 在鼠标位置显示菜单
        menu.exec(self.card_edit.mapToGlobal(pos))

    def _setup_toggle_password_button(self):
        """将密码眼睛按钮从按住模式改为点击切换模式"""
        try:
            # 尝试获取内部的密码按钮并修改行为
            # qfluentwidgets 的 PasswordLineEdit 内部有一个 button 属性
            btn = getattr(self.card_edit, 'button', None)
            if btn is None:
                # 尝试其他可能的属性名
                for attr in ['passwordButton', '_button', 'viewButton']:
                    btn = getattr(self.card_edit, attr, None)
                    if btn is not None:
                        break
            
            if btn is not None:
                # 断开原有的按住显示信号
                try:
                    btn.pressed.disconnect()
                except Exception:
                    pass
                try:
                    btn.released.disconnect()
                except Exception:
                    pass
                
                # 使用点击切换模式
                self._password_visible = False
                def toggle_password():
                    self._password_visible = not self._password_visible
                    if self._password_visible:
                        self.card_edit.setEchoMode(QLineEdit.EchoMode.Normal)
                    else:
                        self.card_edit.setEchoMode(QLineEdit.EchoMode.Password)
                
                btn.clicked.connect(toggle_password)
        except Exception:
            pass

    def get_card_code(self) -> Optional[str]:
        return self.card_edit.text().strip() or None


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

    def closeEvent(self, event):
        """对话框关闭时安全停止线程"""
        self._stop_status_polling()
        super().closeEvent(event)

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
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
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



class SettingsPage(ScrollArea):
    """独立的运行参数/开关页，方便在侧边栏查看。"""

    def __init__(self, controller: RunController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.view.setObjectName("settings_view")
        self.ua_checkboxes: Dict[str, CheckBox] = {}
        self._build_ui()
        self._bind_events()
        self._sync_random_ua(self.random_ua_switch.isChecked())

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        run_group = CardWidget(self.view)
        run_layout = QVBoxLayout(run_group)
        run_layout.setContentsMargins(16, 16, 16, 16)
        run_layout.setSpacing(12)
        run_layout.addWidget(SubtitleLabel("运行参数", self.view))

        self.target_spin = NoWheelSpinBox(self.view)
        self.target_spin.setRange(1, 99999)
        self.target_spin.setValue(10)
        self.target_spin.setMinimumWidth(110)
        self.target_spin.setFixedHeight(36)
        self.target_spin.setStyleSheet("QSpinBox { padding: 4px 8px; font-size: 11pt; }")
        self.thread_spin = NoWheelSpinBox(self.view)
        self.thread_spin.setRange(1, 12)
        self.thread_spin.setValue(2)
        self.thread_spin.setMinimumWidth(110)
        self.thread_spin.setFixedHeight(36)
        self.thread_spin.setStyleSheet("QSpinBox { padding: 4px 8px; font-size: 11pt; }")
        self.fail_stop_switch = SwitchButton("失败过多自动停止", self.view)
        self.fail_stop_switch.setChecked(True)
        self._pin_switch_label(self.fail_stop_switch, "失败过多自动停止")

        target_row = QHBoxLayout()
        target_row.addWidget(BodyLabel("目标份数"))
        target_row.addWidget(self.target_spin)
        target_row.addStretch(1)
        run_layout.addLayout(target_row)

        thread_row = QHBoxLayout()
        thread_row.addWidget(BodyLabel("并发浏览器"))
        thread_row.addWidget(self.thread_spin)
        thread_row.addStretch(1)
        run_layout.addLayout(thread_row)

        run_layout.addWidget(self.fail_stop_switch)
        layout.addWidget(run_group)

        time_group = CardWidget(self.view)
        time_layout = QVBoxLayout(time_group)
        time_layout.setContentsMargins(16, 16, 16, 16)
        time_layout.setSpacing(12)
        time_layout.addWidget(SubtitleLabel("时间控制", self.view))

        # 提交间隔 - 使用按钮显示时间
        self.interval_min_seconds = 0
        self.interval_max_seconds = 0
        self.answer_min_seconds = 0
        self.answer_max_seconds = 0
        
        interval_row = QHBoxLayout()
        interval_row.addWidget(BodyLabel("提交间隔"))
        self.interval_min_btn = PushButton("0分0秒", self.view)
        self.interval_min_btn.setMinimumWidth(100)
        interval_row.addWidget(self.interval_min_btn)
        interval_row.addWidget(BodyLabel("~"))
        self.interval_max_btn = PushButton("0分0秒", self.view)
        self.interval_max_btn.setMinimumWidth(100)
        interval_row.addWidget(self.interval_max_btn)
        interval_row.addStretch(1)
        time_layout.addLayout(interval_row)

        answer_row = QHBoxLayout()
        answer_row.addWidget(BodyLabel("作答时长"))
        self.answer_min_btn = PushButton("0分0秒", self.view)
        self.answer_min_btn.setMinimumWidth(100)
        answer_row.addWidget(self.answer_min_btn)
        answer_row.addWidget(BodyLabel("~"))
        self.answer_max_btn = PushButton("0分0秒", self.view)
        self.answer_max_btn.setMinimumWidth(100)
        answer_row.addWidget(self.answer_max_btn)
        answer_row.addStretch(1)
        time_layout.addLayout(answer_row)
        
        timed_row = QHBoxLayout()
        timed_row.setSpacing(8)
        self.timed_switch = SwitchButton("定时模式", self.view)
        self._pin_switch_label(self.timed_switch, "定时模式")
        timed_row.addWidget(self.timed_switch)
        
        # 添加帮助按钮 - 使用 Qt 原生 QToolButton
        help_btn = QToolButton(self.view)
        help_btn.setIcon(FluentIcon.INFO.icon())
        help_btn.setFixedSize(32, 32)
        help_btn.setAutoRaise(True)
        help_btn.setToolTip("")  # 显式设置空 tooltip
        help_btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 6px;
            }
            QToolButton:hover {
                background: rgba(0, 0, 0, 0.05);
            }
            QToolButton:pressed {
                background: rgba(0, 0, 0, 0.08);
            }
        """)
        help_btn.clicked.connect(self._show_timed_mode_help)
        timed_row.addWidget(help_btn)
        timed_row.addStretch(1)
        
        time_layout.addLayout(timed_row)
        layout.addWidget(time_group)

        feature_group = CardWidget(self.view)
        feature_layout = QVBoxLayout(feature_group)
        feature_layout.setContentsMargins(16, 16, 16, 16)
        feature_layout.setSpacing(12)
        feature_layout.addWidget(SubtitleLabel("特性开关", self.view))

        feature_row = QHBoxLayout()
        self.random_ip_switch = SwitchButton("随机IP", self.view)
        self.random_ua_switch = SwitchButton("随机 UA", self.view)
        self._pin_switch_label(self.random_ip_switch, "随机IP")
        self._pin_switch_label(self.random_ua_switch, "随机 UA")
        feature_row.addWidget(self.random_ip_switch)
        feature_row.addWidget(self.random_ua_switch)
        feature_row.addStretch(1)
        feature_layout.addLayout(feature_row)

        # 代理源选择
        proxy_source_row = QHBoxLayout()
        proxy_source_row.setSpacing(8)
        proxy_source_row.addWidget(BodyLabel("代理源：", self.view))
        self.proxy_source_combo = ComboBox(self.view)
        self.proxy_source_combo.addItem("默认", "default")
        self.proxy_source_combo.addItem("皮卡丘代理站 (中国大陆)", "pikachu")
        self.proxy_source_combo.setMinimumWidth(200)
        proxy_source_row.addWidget(self.proxy_source_combo)
        proxy_source_row.addStretch(1)
        feature_layout.addLayout(proxy_source_row)

        ua_group = CardWidget(self.view)
        ua_layout = QVBoxLayout(ua_group)
        ua_layout.setContentsMargins(12, 12, 12, 12)
        ua_layout.setSpacing(8)
        ua_layout.addWidget(SubtitleLabel("随机 UA 类型", self.view))
        ua_grid = QGridLayout()
        ua_grid.setSpacing(8)
        col = 0
        row = 0
        for key, preset in USER_AGENT_PRESETS.items():
            label = preset.get("label") or key
            cb = CheckBox(label, self.view)
            cb.setChecked(key == "pc_web")
            self.ua_checkboxes[key] = cb
            ua_grid.addWidget(cb, row, col)
            col += 1
            if col >= 3:
                col = 0
                row += 1
        ua_layout.addLayout(ua_grid)
        feature_layout.addWidget(ua_group)
        layout.addWidget(feature_group)

        layout.addStretch(1)

    def _bind_events(self):
        self.random_ip_switch.checkedChanged.connect(self._on_random_ip_toggled)
        self.random_ua_switch.checkedChanged.connect(self._sync_random_ua)
        self.timed_switch.checkedChanged.connect(self._sync_timed_mode)
        self.interval_min_btn.clicked.connect(lambda: self._show_time_picker("interval_min"))
        self.interval_max_btn.clicked.connect(lambda: self._show_time_picker("interval_max"))
        self.answer_min_btn.clicked.connect(lambda: self._show_time_picker("answer_min"))
        self.answer_max_btn.clicked.connect(lambda: self._show_time_picker("answer_max"))
        self.proxy_source_combo.currentIndexChanged.connect(self._on_proxy_source_changed)

    def _on_random_ip_toggled(self, enabled: bool):
        """参数页随机IP开关切换时，同步到主页并显示弹窗"""
        main_win = self.window()
        # 调用主页的处理逻辑（包含弹窗和同步）
        if hasattr(main_win, "dashboard"):
            # 阻止信号避免循环
            self.random_ip_switch.blockSignals(True)
            try:
                main_win.dashboard._on_random_ip_toggled(2 if enabled else 0)  # type: ignore[union-attr]
            finally:
                self.random_ip_switch.blockSignals(False)

    def _on_proxy_source_changed(self, index: int):
        """代理源选择变化时更新设置"""
        try:
            from wjx.network.random_ip import set_proxy_source
            source = self.proxy_source_combo.currentData() or "default"
            set_proxy_source(source)
        except Exception:
            pass

    def request_card_code(self) -> Optional[str]:
        """为解锁弹窗提供卡密输入。"""
        main_win = self.window()
        if hasattr(main_win, "_ask_card_code"):
            try:
                return main_win._ask_card_code()  # type: ignore[union-attr]
            except Exception:
                return None
        return None

    def _sync_random_ua(self, enabled: bool):
        try:
            for cb in self.ua_checkboxes.values():
                cb.setEnabled(bool(enabled))
        except Exception:
            pass
    
    def _sync_timed_mode(self, enabled: bool):
        """定时模式切换时禁用/启用时间控制按钮"""
        try:
            disabled = bool(enabled)
            self.interval_min_btn.setEnabled(not disabled)
            self.interval_max_btn.setEnabled(not disabled)
            self.answer_min_btn.setEnabled(not disabled)
            self.answer_max_btn.setEnabled(not disabled)
        except Exception:
            pass
    
    def _show_time_picker(self, field: str):
        """显示时间选择对话框（全新设计）"""
        # 获取当前值
        if field == "interval_min":
            current_seconds = self.interval_min_seconds
            title = "设置提交间隔最小值"
        elif field == "interval_max":
            current_seconds = self.interval_max_seconds
            title = "设置提交间隔最大值"
        elif field == "answer_min":
            current_seconds = self.answer_min_seconds
            title = "设置作答时长最小值"
        else:  # answer_max
            current_seconds = self.answer_max_seconds
            title = "设置作答时长最大值"
        
        # 创建对话框
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle(title)
        dialog.setFixedSize(480, 360)
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)
        
        # 标题区域
        title_label = SubtitleLabel(title, dialog)
        main_layout.addWidget(title_label)
        
        # 卡片容器
        card = CardWidget(dialog)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(20)
        
        # 实时预览区域
        preview_container = QWidget(card)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)
        preview_hint = BodyLabel("当前设置", card)
        preview_hint.setStyleSheet("color: #888; font-size: 11pt;")
        preview_value = StrongBodyLabel("0分0秒", card)
        preview_value.setStyleSheet("font-size: 18pt; color: #2563EB;")
        preview_layout.addWidget(preview_hint, alignment=Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(preview_value, alignment=Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(preview_container)
        
        # 分钟控制区域
        minutes_container = QWidget(card)
        minutes_layout = QHBoxLayout(minutes_container)
        minutes_layout.setContentsMargins(0, 0, 0, 0)
        minutes_layout.setSpacing(12)
        
        minutes_label = BodyLabel("分钟", card)
        minutes_label.setFixedWidth(50)
        minutes_slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
        minutes_slider.setRange(0, 10)
        minutes_slider.setValue(current_seconds // 60)
        minutes_spin = NoWheelSpinBox(card)
        minutes_spin.setRange(0, 10)
        minutes_spin.setValue(current_seconds // 60)
        minutes_spin.setFixedWidth(70)
        
        minutes_layout.addWidget(minutes_label)
        minutes_layout.addWidget(minutes_slider, 1)
        minutes_layout.addWidget(minutes_spin)
        card_layout.addWidget(minutes_container)
        
        # 秒控制区域
        seconds_container = QWidget(card)
        seconds_layout = QHBoxLayout(seconds_container)
        seconds_layout.setContentsMargins(0, 0, 0, 0)
        seconds_layout.setSpacing(12)
        
        seconds_label = BodyLabel("秒", card)
        seconds_label.setFixedWidth(50)
        seconds_slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
        seconds_slider.setRange(0, 59)
        seconds_slider.setValue(current_seconds % 60)
        seconds_spin = NoWheelSpinBox(card)
        seconds_spin.setRange(0, 59)
        seconds_spin.setValue(current_seconds % 60)
        seconds_spin.setFixedWidth(70)
        
        seconds_layout.addWidget(seconds_label)
        seconds_layout.addWidget(seconds_slider, 1)
        seconds_layout.addWidget(seconds_spin)
        card_layout.addWidget(seconds_container)
        
        main_layout.addWidget(card)
        main_layout.addStretch(1)
        
        # 更新预览函数
        def update_preview():
            m = minutes_spin.value()
            s = seconds_spin.value()
            preview_value.setText(f"{m}分{s}秒")
        
        # 联动逻辑
        minutes_slider.valueChanged.connect(minutes_spin.setValue)
        minutes_spin.valueChanged.connect(minutes_slider.setValue)
        minutes_spin.valueChanged.connect(lambda: update_preview())
        
        seconds_slider.valueChanged.connect(seconds_spin.setValue)
        seconds_spin.valueChanged.connect(seconds_slider.setValue)
        seconds_spin.valueChanged.connect(lambda: update_preview())
        
        # 初始化预览
        update_preview()
        
        # 按钮区域
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", dialog)
        cancel_btn.setMinimumWidth(90)
        ok_btn = PrimaryPushButton("确定", dialog)
        ok_btn.setMinimumWidth(90)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        main_layout.addLayout(btn_row)
        
        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(dialog.accept)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            total_seconds = minutes_spin.value() * 60 + seconds_spin.value()
            # 更新值和按钮文本
            if field == "interval_min":
                self.interval_min_seconds = total_seconds
                self.interval_min_btn.setText(f"{minutes_spin.value()}分{seconds_spin.value()}秒")
            elif field == "interval_max":
                self.interval_max_seconds = total_seconds
                self.interval_max_btn.setText(f"{minutes_spin.value()}分{seconds_spin.value()}秒")
            elif field == "answer_min":
                self.answer_min_seconds = total_seconds
                self.answer_min_btn.setText(f"{minutes_spin.value()}分{seconds_spin.value()}秒")
            else:  # answer_max
                self.answer_max_seconds = total_seconds
                self.answer_max_btn.setText(f"{minutes_spin.value()}分{seconds_spin.value()}秒")

    def update_config(self, cfg: RuntimeConfig):
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        
        # 直接使用秒数变量
        cfg.submit_interval = (
            max(0, self.interval_min_seconds),
            max(self.interval_min_seconds, self.interval_max_seconds),
        )
        
        cfg.answer_duration = (
            max(0, self.answer_min_seconds),
            max(self.answer_min_seconds, self.answer_max_seconds),
        )
        
        cfg.timed_mode_enabled = self.timed_switch.isChecked()
        cfg.random_ip_enabled = self.random_ip_switch.isChecked()
        cfg.random_ua_enabled = self.random_ua_switch.isChecked()
        cfg.random_ua_keys = [k for k, cb in self.ua_checkboxes.items() if cb.isChecked()] if cfg.random_ua_enabled else []
        cfg.fail_stop_enabled = self.fail_stop_switch.isChecked()
        
        # 保存代理源设置
        try:
            cfg.proxy_source = self.proxy_source_combo.currentData() or "default"
        except Exception:
            cfg.proxy_source = "default"

    def apply_config(self, cfg: RuntimeConfig):
        self.target_spin.setValue(max(1, cfg.target))
        self.thread_spin.setValue(max(1, cfg.threads))
        
        # 更新秒数变量和按钮文本
        interval_min_seconds = max(0, cfg.submit_interval[0])
        self.interval_min_seconds = interval_min_seconds
        self.interval_min_btn.setText(f"{interval_min_seconds // 60}分{interval_min_seconds % 60}秒")
        
        interval_max_seconds = max(cfg.submit_interval[0], cfg.submit_interval[1])
        self.interval_max_seconds = interval_max_seconds
        self.interval_max_btn.setText(f"{interval_max_seconds // 60}分{interval_max_seconds % 60}秒")
        
        answer_min_seconds = max(0, cfg.answer_duration[0])
        self.answer_min_seconds = answer_min_seconds
        self.answer_min_btn.setText(f"{answer_min_seconds // 60}分{answer_min_seconds % 60}秒")
        
        answer_max_seconds = max(cfg.answer_duration[0], cfg.answer_duration[1])
        self.answer_max_seconds = answer_max_seconds
        self.answer_max_btn.setText(f"{answer_max_seconds // 60}分{answer_max_seconds % 60}秒")
        
        self.timed_switch.setChecked(cfg.timed_mode_enabled)
        self._sync_timed_mode(cfg.timed_mode_enabled)
        # 阻塞信号避免加载配置时触发弹窗
        self.random_ip_switch.blockSignals(True)
        self.random_ip_switch.setChecked(cfg.random_ip_enabled)
        self.random_ip_switch.blockSignals(False)
        self.random_ua_switch.setChecked(cfg.random_ua_enabled)
        # 应用 UA 选项
        active = set(cfg.random_ua_keys or [])
        for key, cb in self.ua_checkboxes.items():
            cb.setChecked((not active and key == "pc_web") or key in active)
            cb.setEnabled(self.random_ua_switch.isChecked())
        self.fail_stop_switch.setChecked(cfg.fail_stop_enabled)
        
        # 应用代理源设置
        try:
            proxy_source = getattr(cfg, "proxy_source", "default")
            idx = self.proxy_source_combo.findData(proxy_source)
            if idx >= 0:
                self.proxy_source_combo.setCurrentIndex(idx)
            from wjx.network.random_ip import set_proxy_source
            set_proxy_source(proxy_source)
        except Exception:
            pass

    def _show_timed_mode_help(self):
        """显示定时模式说明TeachingTip"""
        # 获取触发按钮
        sender = self.sender()
        if not sender or not isinstance(sender, QWidget):
            return
        
        # 创建内容文本
        content = (
            "启用后，程序会忽略「提交间隔」和「作答时长」设置，改为高频刷新并在开放后立即提交。\n\n"
            "典型应用场景：\n"
            "• 抢志愿填报名额\n"
            "• 抢课程选课名额（如大学选课问卷）\n"
            "• 抢活动报名名额（如讲座、比赛报名）\n"
            "• 其他在特定时间点开放的问卷"
        )
        
        TeachingTip.create(
            target=sender,
            icon=FluentIcon.INFO,
            title='定时模式说明',
            content=content,
            isClosable=True,
            tailPosition=TeachingTipTailPosition.BOTTOM,
            duration=-1,
            parent=self.view
        )
    
    def _pin_switch_label(self, sw: SwitchButton, text: str):
        """保持开关两侧文本一致，避免切换为 On/Off。"""
        try:
            sw.setOnText(text)
            sw.setOffText(text)
            sw.setText(text)
        except Exception:
            sw.setText(text)


class QuestionPage(ScrollArea):
    """题目配置页，支持简单编辑。"""

    entriesChanged = Signal(int)  # 当前题目配置条目数

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: List[QuestionEntry] = []
        self.questions_info: List[Dict[str, Any]] = []
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(SubtitleLabel("题目配置", self))
        layout.addWidget(BodyLabel("双击单元格即可编辑；自定义权重用逗号分隔，例如 3,2,1", self))

        self.table = TableWidget(self.view)
        self.table.setRowCount(0)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["题号", "类型", "选项数", "配置详情"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.add_btn = PrimaryPushButton("新增题目", self.view)
        self.del_btn = PushButton("删除选中", self.view)
        self.reset_btn = PushButton("恢复默认", self.view)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.add_btn.clicked.connect(self._add_entry)
        self.del_btn.clicked.connect(self._delete_selected)
        self.reset_btn.clicked.connect(self._reset_from_source)

    # ---------- data helpers ----------
    def set_questions(self, info: List[Dict[str, Any]], entries: List[QuestionEntry]):
        self.questions_info = info or []
        self.set_entries(entries, info)

    def set_entries(self, entries: List[QuestionEntry], info: Optional[List[Dict[str, Any]]] = None):
        self.questions_info = info or self.questions_info
        self.entries = list(entries or [])
        self._refresh_table()

    def get_entries(self) -> List[QuestionEntry]:
        result: List[QuestionEntry] = []
        for row in range(self.table.rowCount()):
            entry = self._entry_from_row(row)
            result.append(entry)
        return result

    # ---------- UI actions ----------
    def _reset_from_source(self):
        self._refresh_table()

    def _add_entry(self):
        """显示新增题目的交互式弹窗"""
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle("新增题目")
        dialog.resize(550, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel("新增题目配置", dialog))

        # 题目类型
        type_row = QHBoxLayout()
        type_row.addWidget(BodyLabel("题目类型：", dialog))
        type_combo = ComboBox(dialog)
        for value, label in TYPE_CHOICES:
            type_combo.addItem(label, value)
        type_combo.setCurrentIndex(0)
        type_row.addWidget(type_combo, 1)
        layout.addLayout(type_row)

        # 选项数量
        option_row = QHBoxLayout()
        option_row.addWidget(BodyLabel("选项数量：", dialog))
        option_spin = NoWheelSpinBox(dialog)
        option_spin.setRange(1, 20)
        option_spin.setValue(4)
        option_row.addWidget(option_spin, 1)
        layout.addLayout(option_row)

        # 策略选择
        strategy_row = QHBoxLayout()
        strategy_label = BodyLabel("填写策略：", dialog)
        strategy_row.addWidget(strategy_label)
        strategy_combo = ComboBox(dialog)
        for value, label in STRATEGY_CHOICES:
            strategy_combo.addItem(label, value)
        strategy_combo.setCurrentIndex(1)  # 默认选择"自定义配比"
        strategy_row.addWidget(strategy_combo, 1)
        layout.addLayout(strategy_row)

        # 填空题答案列表区域（简洁布局，无卡片）
        text_area_widget = QWidget(dialog)
        text_area_layout = QVBoxLayout(text_area_widget)
        text_area_layout.setContentsMargins(0, 8, 0, 0)
        text_area_layout.setSpacing(6)
        text_area_layout.addWidget(BodyLabel("答案列表（执行时随机选择一个）：", dialog))
        
        text_edits: List[LineEdit] = []
        text_rows_container = QWidget(dialog)
        text_rows_layout = QVBoxLayout(text_rows_container)
        text_rows_layout.setContentsMargins(0, 0, 0, 0)
        text_rows_layout.setSpacing(4)
        text_area_layout.addWidget(text_rows_container)
        
        def add_text_row(initial_text: str = ""):
            row_widget = QWidget(text_rows_container)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            edit = LineEdit(row_widget)
            edit.setPlaceholderText('输入答案')
            edit.setText(initial_text)
            del_btn = PushButton("×", row_widget)
            del_btn.setFixedWidth(32)
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(del_btn)
            text_rows_layout.addWidget(row_widget)
            text_edits.append(edit)
            
            def remove_row():
                if len(text_edits) > 1:
                    text_edits.remove(edit)
                    row_widget.deleteLater()
            del_btn.clicked.connect(remove_row)
        
        add_text_row()  # 默认添加一行
        
        add_text_btn = PushButton("+ 添加", dialog)
        add_text_btn.setFixedWidth(80)
        add_text_btn.clicked.connect(lambda: add_text_row())
        text_area_layout.addWidget(add_text_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(text_area_widget)

        # 自定义配比滑块区域
        slider_card = CardWidget(dialog)
        slider_card_layout = QVBoxLayout(slider_card)
        slider_card_layout.setContentsMargins(12, 12, 12, 12)
        slider_card_layout.setSpacing(8)
        slider_hint_label = BodyLabel("", dialog)
        slider_card_layout.addWidget(slider_hint_label)
        
        slider_scroll = ScrollArea(dialog)
        slider_scroll.setWidgetResizable(True)
        slider_scroll.setMinimumHeight(180)
        slider_scroll.setMaximumHeight(300)
        slider_container = QWidget(dialog)
        slider_inner_layout = QVBoxLayout(slider_container)
        slider_inner_layout.setContentsMargins(0, 0, 0, 0)
        slider_inner_layout.setSpacing(6)
        slider_scroll.setWidget(slider_container)
        slider_card_layout.addWidget(slider_scroll)
        layout.addWidget(slider_card)

        sliders: List[NoWheelSlider] = []
        slider_labels: List[BodyLabel] = []

        def rebuild_sliders():
            for i in reversed(range(slider_inner_layout.count())):
                item = slider_inner_layout.itemAt(i)
                if item.widget():
                    item.widget().deleteLater()
            sliders.clear()
            slider_labels.clear()
            
            count = option_spin.value()
            for idx in range(count):
                row = QHBoxLayout()
                row.setSpacing(8)
                row.addWidget(BodyLabel(f"选项 {idx + 1}：", slider_container))
                slider = NoWheelSlider(Qt.Orientation.Horizontal, slider_container)
                slider.setRange(0, 100)
                slider.setValue(50)
                value_label = BodyLabel("50", slider_container)
                value_label.setMinimumWidth(30)
                slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(str(v)))
                row.addWidget(slider, 1)
                row.addWidget(value_label)
                
                row_widget = QWidget(slider_container)
                row_widget.setLayout(row)
                slider_inner_layout.addWidget(row_widget)
                sliders.append(slider)
                slider_labels.append(value_label)

        def do_update_visibility():
            type_idx = type_combo.currentIndex()
            strategy_idx = strategy_combo.currentIndex()
            q_type = TYPE_CHOICES[type_idx][0] if 0 <= type_idx < len(TYPE_CHOICES) else "single"
            strategy = STRATEGY_CHOICES[strategy_idx][0] if 0 <= strategy_idx < len(STRATEGY_CHOICES) else "random"
            is_text = q_type in ("text", "multi_text")
            is_custom = strategy == "custom"
            # 填空题时隐藏策略选择，显示答案列表
            strategy_label.setVisible(not is_text)
            strategy_combo.setVisible(not is_text)
            text_area_widget.setVisible(is_text)
            slider_card.setVisible(not is_text and is_custom)
            # 根据题目类型更新提示标签
            if q_type == "multiple":
                slider_hint_label.setText("拖动滑块设置各选项被选中的概率（数值越大概率越高）：")
            else:
                slider_hint_label.setText("拖动滑块设置答案分布比例（数值越大概率越高）：")
            if not is_text and is_custom:
                rebuild_sliders()

        def on_option_changed():
            strategy_idx = strategy_combo.currentIndex()
            strategy = STRATEGY_CHOICES[strategy_idx][0] if 0 <= strategy_idx < len(STRATEGY_CHOICES) else "random"
            if strategy == "custom":
                rebuild_sliders()

        text_area_widget.setVisible(False)
        slider_card.setVisible(False)
        type_combo.currentIndexChanged.connect(lambda _: do_update_visibility())
        strategy_combo.currentIndexChanged.connect(lambda _: do_update_visibility())
        option_spin.valueChanged.connect(on_option_changed)
        
        # 初始化时调用一次以显示滑块（因为默认是自定义配比）
        do_update_visibility()

        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", dialog)
        ok_btn = PrimaryPushButton("添加", dialog)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(dialog.accept)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            q_type = type_combo.currentData() or "single"
            option_count = max(1, option_spin.value())
            strategy = strategy_combo.currentData() or "random"

            if q_type in ("text", "multi_text"):
                # 从答案列表中收集文本
                texts = [e.text().strip() or "无" for e in text_edits]
                texts = [t for t in texts if t] or [DEFAULT_FILL_TEXT]
                new_entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=[1.0],
                    texts=texts,
                    rows=1,
                    option_count=max(option_count, len(texts)),
                    distribution_mode="random",
                    custom_weights=None,
                    question_num=str(len(self.entries) + 1),
                )
            else:
                custom_weights = None
                if strategy == "custom" and sliders:
                    custom_weights = [float(max(1, s.value())) for s in sliders]
                    if all(w == custom_weights[0] for w in custom_weights):
                        custom_weights = None
                new_entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=-1 if strategy == "random" else [1.0] * option_count,
                    texts=None,
                    rows=1,
                    option_count=option_count,
                    distribution_mode=strategy,
                    custom_weights=custom_weights,
                    question_num=str(len(self.entries) + 1),
                )

            self.entries.append(new_entry)
            self._refresh_table()

    def _delete_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            InfoBar.warning("", "请先选择要删除的题目", parent=self.window(), position=InfoBarPosition.TOP, duration=1800)
            return
        for row in rows:
            if 0 <= row < len(self.entries):
                self.entries.pop(row)
        self._refresh_table()

    # ---------- table helpers ----------
    def _refresh_table(self):
        self.table.setRowCount(0)
        for idx, entry in enumerate(self.entries):
            self._insert_row(idx, entry)
        self.table.resizeColumnsToContents()
        try:
            self.entriesChanged.emit(int(self.table.rowCount()))
        except Exception:
            pass

    def _insert_row(self, row: int, entry: QuestionEntry):
        self.table.insertRow(row)
        info = self.questions_info[row] if row < len(self.questions_info) else {}
        qnum = str(info.get("num") or entry.question_num or row + 1)
        num_item = QTableWidgetItem(qnum)
        num_item.setData(Qt.ItemDataRole.UserRole, qnum)
        self.table.setItem(row, 0, num_item)

        # 类型
        type_label = _get_entry_type_label(entry)
        self.table.setItem(row, 1, QTableWidgetItem(type_label))

        # 选项数
        option_count = max(1, int(entry.option_count or 1))
        self.table.setItem(row, 2, QTableWidgetItem(str(option_count)))

        # 配置详情 - 显示有意义的摘要
        detail = ""
        if entry.question_type in ("text", "multi_text"):
            texts = entry.texts or []
            if texts:
                detail = f"答案: {' | '.join(texts[:3])}"
                if len(texts) > 3:
                    detail += f" (+{len(texts)-3})"
            else:
                detail = "答案: 无"
        elif entry.custom_weights:
            weights = entry.custom_weights
            detail = f"自定义配比: {','.join(str(int(w)) for w in weights[:5])}"
            if len(weights) > 5:
                detail += "..."
        else:
            strategy = entry.distribution_mode or "random"
            if getattr(entry, "probabilities", None) == -1:
                strategy = "random"
            detail = "完全随机" if strategy == "random" else "均匀分布"
        self.table.setItem(row, 3, QTableWidgetItem(detail))

    def _entry_from_row(self, row: int) -> QuestionEntry:
        # 表格现在是只读显示，直接返回 entries 中的条目
        if row < len(self.entries):
            return self.entries[row]
        # 兜底：返回一个默认条目
        return QuestionEntry(
            question_type="single",
            probabilities=-1,
            texts=None,
            rows=1,
            option_count=4,
            distribution_mode="random",
            custom_weights=None,
            question_num=str(row + 1),
        )


class QuestionWizardDialog(QDialog):
    """配置向导：用滑块快速设置权重。"""

    @staticmethod
    def _shorten(text: str, limit: int = 120) -> str:
        if not text:
            return ""
        text = str(text).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def __init__(self, entries: List[QuestionEntry], info: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置向导")
        self.resize(900, 700)
        self.entries = entries
        self.info = info or []
        self.slider_map: Dict[int, List[NoWheelSlider]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget(self)
        scroll.setWidget(container)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(10)

        intro = BodyLabel(
            "拖动滑块为每个选项设置权重：数值越大，被选中的概率越高；默认均为 1，可根据需要调整。",
            self,
        )
        intro.setWordWrap(True)
        inner.addWidget(intro)

        for idx, entry in enumerate(entries):
            if entry.question_type in ("text", "multi_text"):
                continue
            card = CardWidget(container)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(8)
            qnum = ""
            title_text = ""
            option_texts: List[str] = []
            if idx < len(self.info):
                qnum = str(self.info[idx].get("num") or "")
                title_text = str(self.info[idx].get("title") or "")
                opt_raw = self.info[idx].get("option_texts")
                if isinstance(opt_raw, list):
                    option_texts = [str(x) for x in opt_raw]
            title = SubtitleLabel(f"第{qnum or idx + 1}题 · {_get_entry_type_label(entry)}", card)
            card_layout.addWidget(title)
            if title_text:
                title_label = BodyLabel(self._shorten(title_text, 200), card)
                title_label.setWordWrap(True)
                title_label.setStyleSheet("color:#444;")
                card_layout.addWidget(title_label)

            options = max(1, int(entry.option_count or 1))
            weights = list(entry.custom_weights or [])
            if len(weights) < options:
                weights += [1] * (options - len(weights))
            if all(w <= 0 for w in weights):
                weights = [1] * options

            sliders: List[NoWheelSlider] = []
            for opt_idx in range(options):
                row = QHBoxLayout()
                row.setSpacing(8)
                opt_label_text = option_texts[opt_idx] if opt_idx < len(option_texts) else ""
                prefix = f"{opt_idx + 1}. "
                display_text = prefix + self._shorten(opt_label_text or "选项", 140)
                row.addWidget(BodyLabel(display_text, card))
                slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
                slider.setRange(0, 100)
                slider.setValue(int(weights[opt_idx]))
                value_label = BodyLabel(str(slider.value()), card)
                slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(str(v)))
                row.addWidget(slider, 1)
                row.addWidget(value_label)
                card_layout.addLayout(row)
                sliders.append(slider)

            self.slider_map[idx] = sliders
            inner.addWidget(card)

        if not self.slider_map:
            inner.addWidget(BodyLabel("当前题目类型无需配置向导。", container))
        inner.addStretch(1)
        layout.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = PrimaryPushButton("保存", self)
        cancel_btn = PushButton("取消", self)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

    def get_results(self) -> Dict[int, List[int]]:
        result: Dict[int, List[int]] = {}
        for idx, sliders in self.slider_map.items():
            weights = [max(0, s.value()) for s in sliders]
            if all(w <= 0 for w in weights):
                weights = [1] * len(weights)
            result[idx] = weights
        return result


class DashboardPage(QWidget):
    """主页：左侧配置 + 底部状态，不再包含日志。"""

    def __init__(self, controller: RunController, question_page: "QuestionPage", settings_page: "SettingsPage", parent=None):
        super().__init__(parent)
        self.controller = controller
        self.question_page = question_page
        self.settings_page = settings_page
        self._open_wizard_after_parse = False
        self._build_ui()
        self._bind_events()
        self._sync_start_button_state()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(10)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget(self)
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        link_card = CardWidget(self)
        link_layout = QVBoxLayout(link_card)
        link_layout.setContentsMargins(12, 12, 12, 12)
        link_layout.setSpacing(8)
        link_layout.addWidget(SubtitleLabel("问卷入口", self))
        link_layout.addWidget(BodyLabel("问卷链接：", self))
        self.url_edit = LineEdit(self)
        self.url_edit.setPlaceholderText("在此处输入问卷链接")
        self.url_edit.setClearButtonEnabled(True)
        link_layout.addWidget(self.url_edit)
        self.qr_btn = PushButton("上传问卷二维码图片", self)
        link_layout.addWidget(self.qr_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.parse_btn = PrimaryPushButton("自动配置问卷", self)
        self.load_cfg_btn = PushButton("载入配置", self)
        self.save_cfg_btn = PushButton("保存配置", self)
        btn_row.addWidget(self.parse_btn)
        btn_row.addWidget(self.load_cfg_btn)
        btn_row.addWidget(self.save_cfg_btn)
        btn_row.addStretch(1)
        link_layout.addLayout(btn_row)
        layout.addWidget(link_card)

        exec_card = CardWidget(self)
        exec_layout = QVBoxLayout(exec_card)
        exec_layout.setContentsMargins(12, 12, 12, 12)
        exec_layout.setSpacing(10)
        exec_layout.addWidget(SubtitleLabel("执行设置", self))

        spin_row = QHBoxLayout()
        spin_row.addWidget(BodyLabel("目标份数：", self))
        self.target_spin = NoWheelSpinBox(self)
        self.target_spin.setRange(1, 99999)
        self.target_spin.setMinimumWidth(140)
        self.target_spin.setMinimumHeight(36)
        spin_row.addWidget(self.target_spin)
        spin_row.addSpacing(12)
        spin_row.addWidget(BodyLabel("线程数（提交速度）：", self))
        self.thread_spin = NoWheelSpinBox(self)
        self.thread_spin.setRange(1, 12)
        self.thread_spin.setMinimumWidth(140)
        self.thread_spin.setMinimumHeight(36)
        spin_row.addWidget(self.thread_spin)
        spin_row.addStretch(1)
        exec_layout.addLayout(spin_row)

        self.random_ip_cb = CheckBox("启用随机 IP 提交", self)
        exec_layout.addWidget(self.random_ip_cb)
        ip_row = QHBoxLayout()
        ip_row.setSpacing(8)
        ip_row.addWidget(BodyLabel("随机IP计数：", self))
        self.random_ip_hint = BodyLabel("--/--", self)
        self.random_ip_hint.setMinimumWidth(120)
        ip_row.addWidget(self.random_ip_hint)
        self.card_btn = PushButton("解锁大额IP", self)
        ip_row.addWidget(self.card_btn)
        ip_row.addStretch(1)
        exec_layout.addLayout(ip_row)
        layout.addWidget(exec_card)

        list_card = CardWidget(self)
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(12, 12, 12, 12)
        list_layout.setSpacing(8)
        title_row = QHBoxLayout()
        self.title_label = SubtitleLabel("题目清单与操作", self)
        self.count_label = BodyLabel("0 题", self)
        self.count_label.setStyleSheet("color: #6b6b6b;")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        title_row.addWidget(self.count_label)
        list_layout.addLayout(title_row)
        # 使用 CommandBar 替代普通按钮布局
        self.command_bar = CommandBar(self)
        self.command_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        
        # 新增题目
        self.add_action = Action(FluentIcon.ADD, "新增题目")
        self.command_bar.addAction(self.add_action)
        
        # 编辑选中
        self.edit_action = Action(FluentIcon.EDIT, "编辑选中")
        self.command_bar.addAction(self.edit_action)
        
        # 删除选中
        self.del_action = Action(FluentIcon.DELETE, "删除选中")
        self.command_bar.addAction(self.del_action)
        
        # 分隔符
        self.command_bar.addSeparator()
        
        # 全选（可勾选）
        self.select_all_action = Action(FluentIcon.CHECKBOX, "全选", checkable=True)
        self.command_bar.addAction(self.select_all_action)
        
        # 隐藏操作：配置向导
        self.wizard_action = Action(FluentIcon.SETTING, "配置向导")
        self.command_bar.addHiddenAction(self.wizard_action)
        
        list_layout.addWidget(self.command_bar)
        hint = BodyLabel("提示：排序题/滑块题会自动随机填写", self)
        hint.setStyleSheet("padding:8px; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;")
        list_layout.addWidget(hint)
        self.entry_table = TableWidget(self)
        self.entry_table.setRowCount(0)
        self.entry_table.setColumnCount(3)
        self.entry_table.setHorizontalHeaderLabels(["选择", "类型", "策略"])
        self.entry_table.verticalHeader().setVisible(False)
        self.entry_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.entry_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.entry_table.setAlternatingRowColors(True)
        self.entry_table.setMinimumHeight(360)
        # 设置列宽策略：前2列固定宽度，最后一列自动拉伸填充剩余空间
        header = self.entry_table.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.Fixed)
        header.setSectionResizeMode(1, header.ResizeMode.Fixed)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)
        self.entry_table.setColumnWidth(0, 100)
        self.entry_table.setColumnWidth(1, 180)
        list_layout.addWidget(self.entry_table)
        layout.addWidget(list_card, 1)

        layout.addStretch(1)
        outer.addWidget(scroll, 1)

        bottom = CardWidget(self)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 10, 12, 10)
        bottom_layout.setSpacing(10)
        self.status_label = StrongBodyLabel("等待配置...", self)
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_pct = StrongBodyLabel("0%", self)
        self.progress_pct.setMinimumWidth(50)
        self.progress_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_pct.setStyleSheet("font-size: 13pt; font-weight: bold;")
        self.start_btn = PrimaryPushButton("开始执行", self)
        self.stop_btn = PushButton("停止", self)
        self.stop_btn.setEnabled(False)
        self.start_btn.setToolTip("请先配置题目（至少 1 题）")
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addWidget(self.progress_bar, 1)
        bottom_layout.addWidget(self.progress_pct)
        bottom_layout.addWidget(self.start_btn)
        bottom_layout.addWidget(self.stop_btn)
        outer.addWidget(bottom)

    def _bind_events(self):
        self.parse_btn.clicked.connect(self._on_parse_clicked)
        self.load_cfg_btn.clicked.connect(self._on_load_config)
        self.save_cfg_btn.clicked.connect(self._on_save_config)
        self.qr_btn.clicked.connect(self._on_qr_clicked)
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.stop_btn.clicked.connect(lambda: self.controller.stop_run())
        self.target_spin.valueChanged.connect(lambda v: self.settings_page.target_spin.setValue(int(v)))
        self.thread_spin.valueChanged.connect(lambda v: self.settings_page.thread_spin.setValue(int(v)))
        self.random_ip_cb.stateChanged.connect(self._on_random_ip_toggled)
        self.card_btn.clicked.connect(self._on_card_code_clicked)
        # CommandBar Actions
        self.select_all_action.triggered.connect(self._toggle_select_all_action)
        self.add_action.triggered.connect(self._show_add_question_dialog)
        self.edit_action.triggered.connect(self._edit_selected_entry)
        self.del_action.triggered.connect(self._delete_selected_entries)
        self.wizard_action.triggered.connect(self._open_question_wizard)
        try:
            self.question_page.entriesChanged.connect(self._on_question_entries_changed)
        except Exception:
            pass

    def _has_question_entries(self) -> bool:
        try:
            return bool(self.question_page.table.rowCount())
        except Exception:
            try:
                return bool(self.question_page.get_entries())
            except Exception:
                return False

    def _sync_start_button_state(self, running: Optional[bool] = None):
        if running is None:
            running = bool(getattr(self.controller, "running", False))
        can_start = (not running) and self._has_question_entries()
        self.start_btn.setEnabled(bool(can_start))

    def _on_question_entries_changed(self, _count: int):
        self._refresh_entry_table()
        self._sync_start_button_state()

    def _on_parse_clicked(self):
        url = self.url_edit.text().strip()
        if not url:
            self._toast("请粘贴问卷链接", "warning")
            return
        self._toast("正在解析问卷...", "info", duration=1800)
        self._open_wizard_after_parse = True
        self.controller.parse_survey(url)

    def _on_qr_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择二维码图片", get_runtime_directory(), "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        url = decode_qrcode(path)
        if not url:
            self._toast("未能识别二维码中的链接", "error")
            return
        self.url_edit.setText(url)
        self._on_parse_clicked()

    def _on_load_config(self):
        configs_dir = os.path.join(get_runtime_directory(), "configs")
        if not os.path.exists(configs_dir):
            os.makedirs(configs_dir, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, "载入配置", configs_dir, "JSON 文件 (*.json);;所有文件 (*.*)")
        if not path:
            return
        try:
            cfg = self.controller.load_saved_config(path)
        except Exception as exc:
            self._toast(f"载入失败：{exc}", "error")
            return
        # 应用到界面
        self.settings_page.apply_config(cfg)
        self.apply_config(cfg)
        self.question_page.set_entries(cfg.question_entries or [], self.question_page.questions_info)
        self._refresh_entry_table()
        self._sync_start_button_state()
        refresh_ip_counter_display(self.controller.adapter)
        self._toast("已载入配置", "success")

    def _on_save_config(self):
        cfg = self._build_config()
        cfg.question_entries = list(self.question_page.get_entries())
        self.controller.config = cfg
        path, _ = QFileDialog.getSaveFileName(self, "保存配置", os.path.join(get_runtime_directory(), "config.json"), "JSON 文件 (*.json);;所有文件 (*.*)")
        if not path:
            return
        try:
            self.controller.save_current_config(path)
            self._toast("配置已保存", "success")
        except Exception as exc:
            self._toast(f"保存失败：{exc}", "error")

    def _on_start_clicked(self):
        cfg = self._build_config()
        cfg.question_entries = list(self.question_page.get_entries())
        if not cfg.question_entries:
            self._toast("未配置任何题目，无法开始执行（请先在“题目配置”页添加/配置题目）", "warning")
            self._sync_start_button_state(running=False)
            return
        try:
            configure_probabilities(cfg.question_entries)
        except Exception as exc:
            self._toast(str(exc), "error")
            return
        self.controller.start_run(cfg)

    def update_status(self, text: str, current: int, target: int):
        self.status_label.setText(text)
        progress = 0
        if target > 0:
            progress = min(100, int((current / max(target, 1)) * 100))
        self.progress_bar.setValue(progress)
        self.progress_pct.setText(f"{progress}%")

    def on_run_state_changed(self, running: bool):
        self._sync_start_button_state(running=running)
        self.stop_btn.setEnabled(running)
        if running:
            self._toast("已启动任务", "success", 1500)
        else:
            self._toast("任务结束", "info", 1500)

    def update_question_meta(self, title: str, count: int):
        self.count_label.setText(f"{count} 题")
        self.title_label.setText(title or "已配置的题目")
        self._refresh_entry_table()
        self._sync_start_button_state()

    def apply_config(self, cfg: RuntimeConfig):
        self.url_edit.setText(cfg.url)
        self.target_spin.setValue(max(1, int(cfg.target or 1)))
        self.thread_spin.setValue(max(1, int(cfg.threads or 1)))
        # 阻塞信号避免加载配置时触发弹窗
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(bool(cfg.random_ip_enabled))
        self.random_ip_cb.blockSignals(False)
        self._refresh_entry_table()
        self._sync_start_button_state()

    def _build_config(self) -> RuntimeConfig:
        cfg = RuntimeConfig()
        cfg.url = self.url_edit.text().strip()
        self.settings_page.update_config(cfg)
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        cfg.random_ip_enabled = self.random_ip_cb.isChecked()
        return cfg

    def update_random_ip_counter(self, count: int, limit: int, unlimited: bool, custom_api: bool):
        if custom_api:
            self.random_ip_hint.setText("自定义接口")
            self.random_ip_hint.setStyleSheet("color:#ff8c00;")
            return
        if unlimited:
            self.random_ip_hint.setText("∞（无限额度）")
            self.random_ip_hint.setStyleSheet("color:green;")
            return
        self.random_ip_hint.setText(f"{count}/{limit}")
        self.random_ip_hint.setStyleSheet("color:#6b6b6b;")

    def _on_random_ip_toggled(self, state: int):
        enabled = state != 0
        try:
            self.controller.adapter.random_ip_enabled_var.set(bool(enabled))
            on_random_ip_toggle(self.controller.adapter)
            enabled = bool(self.controller.adapter.random_ip_enabled_var.get())
        except Exception:
            enabled = bool(enabled)
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(enabled)
        self.random_ip_cb.blockSignals(False)
        try:
            self.settings_page.random_ip_switch.blockSignals(True)
            self.settings_page.random_ip_switch.setChecked(enabled)
            self.settings_page.random_ip_switch.blockSignals(False)
        except Exception:
            pass
        # 刷新计数显示
        refresh_ip_counter_display(self.controller.adapter)

    def _ask_card_code(self) -> Optional[str]:
        """向主窗口请求卡密输入，兜底弹出输入框。"""
        win = self.window()
        if hasattr(win, "_ask_card_code"):
            try:
                return win._ask_card_code()  # type: ignore[union-attr]
            except Exception:
                pass
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_card_code()
        return None

    def request_card_code(self) -> Optional[str]:
        return self._ask_card_code()

    def _open_contact_dialog(self, default_type: str = "报错反馈"):
        """打开联系对话框"""
        win = self.window()
        if hasattr(win, "_open_contact_dialog"):
            try:
                return win._open_contact_dialog(default_type)  # type: ignore[union-attr]
            except Exception:
                pass
        dlg = ContactDialog(self, default_type=default_type, status_fetcher=get_status, status_formatter=_format_status_payload)
        dlg.exec()

    def _on_card_code_clicked(self):
        """用户主动输入卡密解锁大额随机IP。"""
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        code = dialog.get_card_code()
        if not code:
            self._toast("未输入卡密", "warning")
            return
        if _validate_card(code):
            RegistryManager.set_quota_unlimited(True)
            RegistryManager.reset_submit_count()
            refresh_ip_counter_display(self.controller.adapter)
            self.random_ip_cb.setChecked(True)
            try:
                self.settings_page.random_ip_switch.setChecked(True)
            except Exception:
                pass
            self._toast("卡密验证通过，已解锁额度", "success")
        else:
            self._toast("卡密验证失败，请重试", "error")

    def _edit_selected_entry(self):
        """编辑选中的题目"""
        selected_rows = self._checked_rows()
        if not selected_rows:
            self._toast("请先勾选要编辑的题目", "warning")
            return
        if len(selected_rows) > 1:
            self._toast("一次只能编辑一个题目", "warning")
            return
        
        row = selected_rows[0]
        entries = self.question_page.get_entries()
        if row >= len(entries):
            return
        
        entry = entries[row]
        
        # 获取题目信息
        info = self.question_page.questions_info
        qnum = ""
        title_text = ""
        option_texts: List[str] = []
        if row < len(info):
            qnum = str(info[row].get("num") or "")
            title_text = str(info[row].get("title") or "")
            opt_raw = info[row].get("option_texts")
            if isinstance(opt_raw, list):
                option_texts = [str(x) for x in opt_raw]
        
        # 创建编辑对话框
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle(f"编辑题目 - 第{qnum or row + 1}题")
        dialog.resize(720, 680)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel("编辑题目配置", dialog))

        # 显示题目标题
        if title_text:
            title_card = CardWidget(dialog)
            title_card_layout = QVBoxLayout(title_card)
            title_card_layout.setContentsMargins(12, 12, 12, 12)
            title_card_layout.setSpacing(4)
            title_card_layout.addWidget(BodyLabel("题目内容：", dialog))
            title_label = BodyLabel(QuestionWizardDialog._shorten(title_text, 200), dialog)
            title_label.setWordWrap(True)
            title_label.setStyleSheet("color: #444; padding: 4px;")
            title_card_layout.addWidget(title_label)
            layout.addWidget(title_card)

        # 题目类型（可编辑）
        type_row = QHBoxLayout()
        type_row.addWidget(BodyLabel("题目类型：", dialog))
        type_combo = ComboBox(dialog)
        for value, label in TYPE_CHOICES:
            type_combo.addItem(label, value)
        # 设置当前题目类型
        current_type_idx = 0
        for idx, (value, _) in enumerate(TYPE_CHOICES):
            if value == entry.question_type:
                current_type_idx = idx
                break
        type_combo.setCurrentIndex(current_type_idx)
        type_row.addWidget(type_combo, 1)
        layout.addLayout(type_row)

        # 选项数量（可编辑）
        option_row = QHBoxLayout()
        option_row.addWidget(BodyLabel("选项数量：", dialog))
        option_spin = NoWheelSpinBox(dialog)
        option_spin.setRange(1, 20)
        option_spin.setValue(int(entry.option_count or 1))
        option_row.addWidget(option_spin, 1)
        layout.addLayout(option_row)
        
        # 填空题答案列表编辑
        text_area_widget = QWidget(dialog)
        text_area_layout = QVBoxLayout(text_area_widget)
        text_area_layout.setContentsMargins(0, 8, 0, 0)
        text_area_layout.setSpacing(6)
        text_area_layout.addWidget(BodyLabel("答案列表（执行时随机选择一个）：", dialog))
        
        text_edits: List[LineEdit] = []
        text_rows_container = QWidget(dialog)
        text_rows_layout = QVBoxLayout(text_rows_container)
        text_rows_layout.setContentsMargins(0, 0, 0, 0)
        text_rows_layout.setSpacing(4)
        text_area_layout.addWidget(text_rows_container)
        
        def add_text_row(initial_text: str = ""):
            row_widget = QWidget(text_rows_container)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            edit = LineEdit(row_widget)
            edit.setPlaceholderText('输入答案')
            edit.setText(initial_text)
            del_btn = PushButton("×", row_widget)
            del_btn.setFixedWidth(32)
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(del_btn)
            text_rows_layout.addWidget(row_widget)
            text_edits.append(edit)
            
            def remove_row():
                if len(text_edits) > 1:
                    text_edits.remove(edit)
                    row_widget.deleteLater()
            del_btn.clicked.connect(remove_row)
        
        # 预填充答案
        if entry.question_type in ("text", "multi_text") and entry.texts:
            for text in entry.texts:
                add_text_row(text)
        else:
            add_text_row()
        
        add_text_btn = PushButton("+ 添加", dialog)
        add_text_btn.setFixedWidth(80)
        add_text_btn.clicked.connect(lambda: add_text_row())
        text_area_layout.addWidget(add_text_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(text_area_widget)

        # 策略选择（仅非填空题）
        strategy_row = QHBoxLayout()
        strategy_label = BodyLabel("填写策略：", dialog)
        strategy_row.addWidget(strategy_label)
        strategy_combo = ComboBox(dialog)
        for value, label in STRATEGY_CHOICES:
            strategy_combo.addItem(label, value)
        # 根据当前条目设置默认策略
        current_strategy = entry.distribution_mode or "random"
        if entry.custom_weights:
            current_strategy = "custom"
        strategy_idx = 0 if current_strategy == "random" else 1
        strategy_combo.setCurrentIndex(strategy_idx)
        strategy_row.addWidget(strategy_combo, 1)
        layout.addLayout(strategy_row)

        # 自定义配比滑块区域
        slider_card = CardWidget(dialog)
        slider_card_layout = QVBoxLayout(slider_card)
        slider_card_layout.setContentsMargins(12, 12, 12, 12)
        slider_card_layout.setSpacing(8)
        slider_hint_label = BodyLabel("", dialog)
        slider_card_layout.addWidget(slider_hint_label)
        
        slider_scroll = ScrollArea(dialog)
        slider_scroll.setWidgetResizable(True)
        slider_scroll.setMinimumHeight(180)
        slider_scroll.setMaximumHeight(300)
        slider_container = QWidget(dialog)
        slider_inner_layout = QVBoxLayout(slider_container)
        slider_inner_layout.setContentsMargins(0, 0, 0, 0)
        slider_inner_layout.setSpacing(6)
        slider_scroll.setWidget(slider_container)
        slider_card_layout.addWidget(slider_scroll)
        layout.addWidget(slider_card)

        sliders: List[NoWheelSlider] = []
        
        # 动态创建滑块的函数
        def rebuild_sliders():
            # 清除旧滑块
            for i in reversed(range(slider_inner_layout.count())):
                item = slider_inner_layout.itemAt(i)
                if item.widget():
                    item.widget().deleteLater()
            sliders.clear()
            
            # 获取当前题目类型
            current_type = type_combo.currentData() or "single"
            if current_type not in ("text", "multi_text"):
                count = option_spin.value()
                weights = entry.custom_weights or [50] * count
                
                for idx in range(count):
                    row_layout = QHBoxLayout()
                    row_layout.setSpacing(8)
                    # 显示选项内容
                    opt_label_text = option_texts[idx] if idx < len(option_texts) else ""
                    prefix = f"{idx + 1}. "
                    display_text = prefix + QuestionWizardDialog._shorten(opt_label_text or "选项", 80)
                    row_layout.addWidget(BodyLabel(display_text, slider_container))
                    slider = NoWheelSlider(Qt.Orientation.Horizontal, slider_container)
                    slider.setRange(0, 100)
                    slider.setValue(int(weights[idx]) if idx < len(weights) else 50)
                    value_label = BodyLabel(str(slider.value()), slider_container)
                    value_label.setMinimumWidth(30)
                    slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(str(v)))
                    row_layout.addWidget(slider, 1)
                    row_layout.addWidget(value_label)
                    
                    row_widget = QWidget(slider_container)
                    row_widget.setLayout(row_layout)
                    slider_inner_layout.addWidget(row_widget)
                    sliders.append(slider)

        # 动态显示/隐藏逻辑
        def update_visibility():
            # 获取当前题目类型
            current_type = type_combo.currentData() or "single"
            is_text = current_type in ("text", "multi_text")
            strategy_idx = strategy_combo.currentIndex()
            strategy = STRATEGY_CHOICES[strategy_idx][0] if 0 <= strategy_idx < len(STRATEGY_CHOICES) else "random"
            is_custom = strategy == "custom"
            
            text_area_widget.setVisible(is_text)
            strategy_label.setVisible(not is_text)
            strategy_combo.setVisible(not is_text)
            slider_card.setVisible(not is_text and is_custom)
            
            # 根据题目类型更新提示标签
            if current_type == "multiple":
                slider_hint_label.setText("拖动滑块设置各选项被选中的概率（数值越大概率越高）：")
            else:
                slider_hint_label.setText("拖动滑块设置答案分布比例（数值越大概率越高）：")
            
            # 当切换到自定义配比时，总是重建滑块
            if not is_text and is_custom:
                rebuild_sliders()
        
        type_combo.currentIndexChanged.connect(lambda _: update_visibility())
        strategy_combo.currentIndexChanged.connect(lambda _: update_visibility())
        option_spin.valueChanged.connect(lambda _: update_visibility())
        # 初始化时调用一次 update_visibility 来设置正确的显示状态
        update_visibility()

        layout.addStretch(1)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", dialog)
        ok_btn = PrimaryPushButton("保存", dialog)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(dialog.accept)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 获取新的题目类型和选项数
            new_type = type_combo.currentData() or entry.question_type
            new_option_count = option_spin.value()
            
            # 更新条目
            entry.question_type = new_type
            entry.option_count = new_option_count
            
            if new_type in ("text", "multi_text"):
                texts = [e.text().strip() or "无" for e in text_edits]
                texts = [t for t in texts if t] or [DEFAULT_FILL_TEXT]
                entry.texts = texts
                entry.option_count = max(new_option_count, len(texts))
            else:
                strategy = strategy_combo.currentData() or "random"
                if strategy == "random":
                    entry.custom_weights = None
                    entry.distribution_mode = "random"
                    entry.probabilities = -1
                else:
                    custom_weights = [float(max(1, s.value())) for s in sliders]
                    if all(w == custom_weights[0] for w in custom_weights):
                        entry.custom_weights = None
                        entry.distribution_mode = "random"
                        entry.probabilities = -1
                    else:
                        entry.custom_weights = custom_weights
                        entry.distribution_mode = "custom"
                        entry.probabilities = [1.0] * len(custom_weights)
            
            self.question_page._refresh_table()
            self._refresh_entry_table()
            self._toast("已更新题目配置", "success")

    def _show_add_question_dialog(self):
        """显示新增题目的交互式弹窗"""
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle("新增题目")
        dialog.resize(550, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel("新增题目配置", dialog))

        # 题目类型
        type_row = QHBoxLayout()
        type_row.addWidget(BodyLabel("题目类型：", dialog))
        type_combo = ComboBox(dialog)
        for value, label in TYPE_CHOICES:
            type_combo.addItem(label, value)
        type_combo.setCurrentIndex(0)  # 默认单选题
        type_row.addWidget(type_combo, 1)
        layout.addLayout(type_row)

        # 选项数量
        option_row = QHBoxLayout()
        option_row.addWidget(BodyLabel("选项数量：", dialog))
        option_spin = NoWheelSpinBox(dialog)
        option_spin.setRange(1, 20)
        option_spin.setValue(4)
        option_row.addWidget(option_spin, 1)
        layout.addLayout(option_row)

        # 策略选择
        strategy_row = QHBoxLayout()
        strategy_label2 = BodyLabel("填写策略：", dialog)
        strategy_row.addWidget(strategy_label2)
        strategy_combo = ComboBox(dialog)
        for value, label in STRATEGY_CHOICES:
            strategy_combo.addItem(label, value)
        strategy_combo.setCurrentIndex(1)  # 默认选择"自定义配比"
        strategy_row.addWidget(strategy_combo, 1)
        layout.addLayout(strategy_row)

        # 填空题答案列表区域（简洁布局，无卡片）
        text_area_widget2 = QWidget(dialog)
        text_area_layout2 = QVBoxLayout(text_area_widget2)
        text_area_layout2.setContentsMargins(0, 8, 0, 0)
        text_area_layout2.setSpacing(6)
        text_area_layout2.addWidget(BodyLabel("答案列表（执行时随机选择一个）：", dialog))
        
        text_edits2: List[LineEdit] = []
        text_rows_container2 = QWidget(dialog)
        text_rows_layout2 = QVBoxLayout(text_rows_container2)
        text_rows_layout2.setContentsMargins(0, 0, 0, 0)
        text_rows_layout2.setSpacing(4)
        text_area_layout2.addWidget(text_rows_container2)
        
        def add_text_row2(initial_text: str = ""):
            row_widget = QWidget(text_rows_container2)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            edit = LineEdit(row_widget)
            edit.setPlaceholderText('输入答案')
            edit.setText(initial_text)
            del_btn = PushButton("×", row_widget)
            del_btn.setFixedWidth(32)
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(del_btn)
            text_rows_layout2.addWidget(row_widget)
            text_edits2.append(edit)
            
            def remove_row():
                if len(text_edits2) > 1:
                    text_edits2.remove(edit)
                    row_widget.deleteLater()
            del_btn.clicked.connect(remove_row)
        
        add_text_row2()  # 默认添加一行
        
        add_text_btn2 = PushButton("+ 添加", dialog)
        add_text_btn2.setFixedWidth(80)
        add_text_btn2.clicked.connect(lambda: add_text_row2())
        text_area_layout2.addWidget(add_text_btn2, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(text_area_widget2)

        # 自定义配比滑块区域
        slider_card = CardWidget(dialog)
        slider_card_layout = QVBoxLayout(slider_card)
        slider_card_layout.setContentsMargins(12, 12, 12, 12)
        slider_card_layout.setSpacing(8)
        slider_hint_label2 = BodyLabel("", dialog)
        slider_card_layout.addWidget(slider_hint_label2)
        
        slider_scroll = ScrollArea(dialog)
        slider_scroll.setWidgetResizable(True)
        slider_scroll.setMinimumHeight(180)
        slider_scroll.setMaximumHeight(300)
        slider_container = QWidget(dialog)
        slider_inner_layout = QVBoxLayout(slider_container)
        slider_inner_layout.setContentsMargins(0, 0, 0, 0)
        slider_inner_layout.setSpacing(6)
        slider_scroll.setWidget(slider_container)
        slider_card_layout.addWidget(slider_scroll)
        layout.addWidget(slider_card)

        # 存储滑块引用
        sliders: List[QSlider] = []
        slider_labels: List[BodyLabel] = []

        def rebuild_sliders():
            # 清除旧滑块
            for i in reversed(range(slider_inner_layout.count())):
                item = slider_inner_layout.itemAt(i)
                if item.widget():
                    item.widget().deleteLater()
            sliders.clear()
            slider_labels.clear()
            
            count = option_spin.value()
            for idx in range(count):
                row = QHBoxLayout()
                row.setSpacing(8)
                row.addWidget(BodyLabel(f"选项 {idx + 1}：", slider_container))
                slider = NoWheelSlider(Qt.Orientation.Horizontal, slider_container)
                slider.setRange(0, 100)
                slider.setValue(50)
                value_label = BodyLabel("50", slider_container)
                value_label.setMinimumWidth(30)
                slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(str(v)))
                row.addWidget(slider, 1)
                row.addWidget(value_label)
                
                row_widget = QWidget(slider_container)
                row_widget.setLayout(row)
                slider_inner_layout.addWidget(row_widget)
                sliders.append(slider)
                slider_labels.append(value_label)

        def do_update_visibility():
            # 直接获取当前选中的索引和值
            type_idx = type_combo.currentIndex()
            strategy_idx = strategy_combo.currentIndex()
            
            q_type = TYPE_CHOICES[type_idx][0] if 0 <= type_idx < len(TYPE_CHOICES) else "single"
            strategy = STRATEGY_CHOICES[strategy_idx][0] if 0 <= strategy_idx < len(STRATEGY_CHOICES) else "random"
            
            is_text = q_type in ("text", "multi_text")
            is_custom = strategy == "custom"
            
            # 填空题时隐藏策略选择，显示答案列表
            strategy_label2.setVisible(not is_text)
            strategy_combo.setVisible(not is_text)
            text_area_widget2.setVisible(is_text)
            slider_card.setVisible(not is_text and is_custom)
            
            # 根据题目类型更新提示标签
            if q_type == "multiple":
                slider_hint_label2.setText("拖动滑块设置各选项被选中的概率（数值越大概率越高）：")
            else:
                slider_hint_label2.setText("拖动滑块设置答案分布比例（数值越大概率越高）：")
            
            # 如果是自定义配比且不是填空题，重建滑块
            if not is_text and is_custom:
                rebuild_sliders()

        def on_option_changed():
            strategy_idx = strategy_combo.currentIndex()
            strategy = STRATEGY_CHOICES[strategy_idx][0] if 0 <= strategy_idx < len(STRATEGY_CHOICES) else "random"
            if strategy == "custom":
                rebuild_sliders()

        # 初始化 - 默认隐藏两个区域
        text_area_widget2.setVisible(False)
        slider_card.setVisible(False)

        # 绑定事件 - 使用 lambda 确保每次都重新获取状态
        type_combo.currentIndexChanged.connect(lambda _: do_update_visibility())
        strategy_combo.currentIndexChanged.connect(lambda _: do_update_visibility())
        option_spin.valueChanged.connect(on_option_changed)
        
        # 初始化时调用一次以显示滑块（因为默认是自定义配比）
        do_update_visibility()

        layout.addStretch(1)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", dialog)
        ok_btn = PrimaryPushButton("添加", dialog)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(dialog.accept)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            q_type = type_combo.currentData() or "single"
            option_count = max(1, option_spin.value())
            strategy = strategy_combo.currentData() or "random"

            if q_type in ("text", "multi_text"):
                # 从答案列表中收集文本
                texts = [e.text().strip() or "无" for e in text_edits2]
                texts = [t for t in texts if t] or [DEFAULT_FILL_TEXT]
                new_entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=[1.0],
                    texts=texts,
                    rows=1,
                    option_count=max(option_count, len(texts)),
                    distribution_mode="random",
                    custom_weights=None,
                    question_num=str(len(self.question_page.entries) + 1),
                )
            else:
                custom_weights = None
                if strategy == "custom" and sliders:
                    custom_weights = [float(max(1, s.value())) for s in sliders]
                    if all(w == custom_weights[0] for w in custom_weights):
                        custom_weights = None  # 全部相同则不需要自定义
                new_entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=-1 if strategy == "random" else [1.0] * option_count,
                    texts=None,
                    rows=1,
                    option_count=option_count,
                    distribution_mode=strategy,
                    custom_weights=custom_weights,
                    question_num=str(len(self.question_page.entries) + 1),
                )

            self.question_page.entries.append(new_entry)
            self.question_page._refresh_table()
            self._refresh_entry_table()
            self._toast("已添加新题目", "success")

    def _open_question_editor(self):
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle("题目配置")
        dialog.resize(980, 700)
        page = QuestionPage(dialog)
        page.set_questions(self.question_page.questions_info, self.question_page.get_entries())
        layout = QVBoxLayout(dialog)
        layout.addWidget(page, 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = PrimaryPushButton("保存", dialog)
        cancel_btn = PushButton("取消", dialog)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.question_page.set_entries(page.get_entries(), self.question_page.questions_info)
            self._refresh_entry_table()

    def _open_question_wizard(self):
        if not self.question_page.entries:
            self._toast("请先解析问卷或手动添加题目", "warning")
            return
        dlg = QuestionWizardDialog(self.question_page.entries, self.question_page.questions_info, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updates = dlg.get_results()
            for idx, weights in updates.items():
                if 0 <= idx < len(self.question_page.entries):
                    entry = self.question_page.entries[idx]
                    entry.custom_weights = [float(w) for w in weights]
                    entry.distribution_mode = "custom"
            self._refresh_entry_table()

    def _delete_selected_entries(self):
        selected_rows = self._checked_rows()
        if not selected_rows:
            self._toast("请先勾选要删除的题目", "warning")
            return
        
        # 添加确认对话框
        count = len(selected_rows)
        box = MessageBox(
            "确认删除",
            f"确定要删除选中的 {count} 个题目吗？\n此操作无法撤销。",
            self.window() or self
        )
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        
        entries = self.question_page.get_entries()
        for row in sorted(selected_rows, reverse=True):
            if 0 <= row < len(entries):
                entries.pop(row)
        self.question_page.set_entries(entries, self.question_page.questions_info)
        self._refresh_entry_table()
        self._toast(f"已删除 {count} 个题目", "success")

    def _refresh_entry_table(self):
        entries = self.question_page.get_entries()
        info = self.question_page.questions_info
        self.entry_table.setRowCount(len(entries))
        for idx, entry in enumerate(entries):
            type_label = _get_entry_type_label(entry)
            summary = _question_summary(entry)
            check_item = QTableWidgetItem("")
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            check_item.setCheckState(Qt.CheckState.Unchecked)
            check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.entry_table.setItem(idx, 0, check_item)
            type_item = QTableWidgetItem(type_label)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.entry_table.setItem(idx, 1, type_item)
            self.entry_table.setItem(idx, 2, QTableWidgetItem(summary))
        # 不使用 resizeColumnsToContents，保持固定列宽
        self._sync_start_button_state()

    def _checked_rows(self) -> List[int]:
        rows: List[int] = []
        for r in range(self.entry_table.rowCount()):
            item = self.entry_table.item(r, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                rows.append(r)
        if not rows:
            rows = [idx.row() for idx in self.entry_table.selectionModel().selectedRows()]
        return rows

    def _toggle_select_all_action(self):
        """CommandBar 全选 Action 触发时切换所有行的选中状态"""
        checked = self.select_all_action.isChecked()
        for r in range(self.entry_table.rowCount()):
            item = self.entry_table.item(r, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _toast(self, text: str, level: str = "info", duration: int = 2000):
        parent = self.window() or self
        kind = level.lower()
        if kind == "success":
            InfoBar.success("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "warning":
            InfoBar.warning("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "error":
            InfoBar.error("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
        else:
            InfoBar.info("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)


class LogPage(QWidget):
    """独立的日志页，放在侧边栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._bind_events()
        self._load_last_session_logs()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1200)
        self._refresh_timer.timeout.connect(self.refresh_logs)
        self._refresh_timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("日志", self))
        header.addStretch(1)
        self.refresh_btn = PushButton("刷新", self)
        self.clear_btn = PushButton("清空", self)
        self.save_btn = PrimaryPushButton("保存到文件", self)
        header.addWidget(self.refresh_btn)
        header.addWidget(self.clear_btn)
        header.addWidget(self.save_btn)
        layout.addLayout(header)

        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.log_view.setPlaceholderText("日志输出会显示在这里，便于排查问题。")
        layout.addWidget(self.log_view, 1)

    def _bind_events(self):
        self.refresh_btn.clicked.connect(self.refresh_logs)
        self.clear_btn.clicked.connect(self.clear_logs)
        self.save_btn.clicked.connect(self.save_logs)

    def refresh_logs(self):
        # 如果用户正在选择文本，跳过自动刷新
        cursor = self.log_view.textCursor()
        if cursor.hasSelection():
            return
        
        records = LOG_BUFFER_HANDLER.get_records()
        # 保存当前滚动位置
        scrollbar = self.log_view.verticalScrollBar()
        old_scroll_value = scrollbar.value()
        was_at_bottom = old_scroll_value >= scrollbar.maximum() - 10
        
        self.log_view.clear()
        cursor = self.log_view.textCursor()
        for entry in records:
            level = str(getattr(entry, "level", getattr(entry, "category", "")) or "").upper()
            if level.startswith("ERROR"):
                color = "#dc2626"  # red-600
            elif level.startswith("WARN"):
                color = "#ca8a04"  # amber-600
            elif level.startswith("INFO"):
                color = "#2563eb"  # blue-600
            else:
                color = "#6b7280"  # gray-500
            cursor.insertHtml(f'<span style="color:{color};">{entry.text}</span><br>')
        
        # 恢复滚动位置
        if was_at_bottom:
            # 只有在用户原本就在底部时才自动滚动到底部
            self.log_view.moveCursor(cursor.MoveOperation.End)
        else:
            # 恢复原来的滚动位置
            scrollbar.setValue(old_scroll_value)

    def clear_logs(self):
        try:
            LOG_BUFFER_HANDLER.records.clear()
        except Exception:
            pass
        self.refresh_logs()

    def save_logs(self):
        try:
            file_path = save_log_records_to_file(LOG_BUFFER_HANDLER.get_records(), get_runtime_directory())
            InfoBar.success("", f"日志已保存：{file_path}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
        except Exception as exc:
            InfoBar.error("", f"保存失败：{exc}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _load_last_session_logs(self):
        """加载上次会话的日志"""
        try:
            log_path = os.path.join(get_runtime_directory(), "logs", "last_session.log")
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if content.strip():
                    self.log_view.setPlainText(content)
        except Exception:
            pass


class HelpPage(ScrollArea):
    """帮助页面，包含使用说明、联系开发者、QQ群。"""

    _statusLoaded = Signal(str, str)  # text, color

    def __init__(self, on_contact, parent=None):
        super().__init__(parent)
        self.on_contact = on_contact
        self._first_load = True
        self._status_loaded_once = False
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._statusLoaded.connect(self._on_status_loaded)
        self._build_ui()
        # 定时刷新状态（每5秒），但不立即启动
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._load_status_async)

    def showEvent(self, event):
        """页面显示时触发首次状态查询"""
        super().showEvent(event)
        if not self._status_loaded_once:
            self._status_loaded_once = True
            self._load_status_async()
            self._status_timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 联系开发者卡片
        contact_card = CardWidget(self.view)
        contact_layout = QVBoxLayout(contact_card)
        contact_layout.setContentsMargins(16, 16, 16, 16)
        contact_layout.setSpacing(12)
        contact_layout.addWidget(SubtitleLabel("联系开发者", self))
        
        desc = BodyLabel(
            "遇到问题、有建议、或者想聊天？直接点击下方按钮联系作者！\n"
            "消息会实时推送到作者手机上，回复很快哦~",
            self
        )
        desc.setWordWrap(True)
        contact_layout.addWidget(desc)

        # 在线状态
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_spinner = IndeterminateProgressRing(self)
        self.status_spinner.setFixedSize(16, 16)
        self.status_spinner.setStrokeWidth(2)
        self.status_label = BodyLabel("作者当前在线状态：查询中...", self)
        self.status_label.setStyleSheet("color:#BA8303;")
        status_row.addWidget(self.status_spinner)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        contact_layout.addLayout(status_row)

        self.contact_btn = PrimaryPushButton("发送消息给作者", self)
        contact_layout.addWidget(self.contact_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(contact_card)

        # QQ群交流卡片
        community_card = CardWidget(self.view)
        community_layout = QVBoxLayout(community_card)
        community_layout.setContentsMargins(16, 16, 16, 16)
        community_layout.setSpacing(12)
        community_layout.addWidget(SubtitleLabel("加入QQ群", self))
        
        community_desc = BodyLabel(
            "扫描下方二维码加入QQ交流群，和其他用户一起交流使用心得！\n"
            "群里可以获取最新版本、反馈问题、提出建议~",
            self
        )
        community_desc.setWordWrap(True)
        community_layout.addWidget(community_desc)

        # QQ群二维码图片
        self.qq_group_label = QLabel(self)
        self.qq_group_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qq_group_label.setMinimumSize(280, 280)
        self.qq_group_label.setStyleSheet("border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px;")
        self.qq_group_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.qq_group_label.mousePressEvent = lambda ev: self._on_qq_group_clicked(ev)  # type: ignore[method-assign]
        self._load_qq_group_image()
        
        click_hint = BodyLabel("点击图片查看原图", self)
        click_hint.setStyleSheet("color: #888; font-size: 12px;")
        community_layout.addWidget(self.qq_group_label, alignment=Qt.AlignmentFlag.AlignLeft)
        community_layout.addWidget(click_hint, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(community_card)

        layout.addStretch(1)

        # 绑定事件
        self.contact_btn.clicked.connect(lambda: self.on_contact())
        # 状态查询在 showEvent 中触发，这里不调用

    def _on_status_loaded(self, text: str, color: str):
        """信号槽：在主线程更新状态标签"""
        self.status_spinner.hide()
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};")

    def _on_qq_group_clicked(self, event):
        """点击二维码查看原图"""
        try:
            qq_group_path = os.path.join(get_runtime_directory(), "assets", "QQ_group.jpg")
            if os.path.exists(qq_group_path):
                self._show_full_image(qq_group_path)
        except Exception:
            pass

    def _show_full_image(self, image_path: str):
        """显示原图弹窗"""
        from PySide6.QtGui import QPixmap
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle("QQ群二维码")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        
        img_label = QLabel(dialog)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(image_path)
        # 限制最大尺寸为 600x600，保持原图清晰度
        if pixmap.width() > 600 or pixmap.height() > 600:
            pixmap = pixmap.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        img_label.setPixmap(pixmap)
        layout.addWidget(img_label)
        
        close_btn = PushButton("关闭", dialog)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        dialog.adjustSize()
        dialog.exec()

    def _load_qq_group_image(self):
        """加载QQ群二维码图片"""
        try:
            from PySide6.QtGui import QPixmap
            qq_group_path = os.path.join(get_runtime_directory(), "assets", "QQ_group.jpg")
            if os.path.exists(qq_group_path):
                pixmap = QPixmap(qq_group_path)
                # 放大显示尺寸为 280x280
                scaled = pixmap.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.qq_group_label.setPixmap(scaled)
            else:
                self.qq_group_label.setText("QQ群二维码图片未找到\n请检查 assets/QQ_group.jpg")
        except Exception as e:
            self.qq_group_label.setText(f"加载图片失败：{e}")

    def _load_status_async(self):
        import time
        def _worker():
            text = "作者当前在线状态：未知"
            color = "#666666"
            start = time.time()
            try:
                payload = get_status()
                text, color = _format_status_payload(payload)
            except Exception:
                text = "作者当前在线状态：获取失败"
                color = "#cc0000"
            # 确保加载动画至少显示 800ms，让用户能看到
            elapsed = time.time() - start
            if elapsed < 0.8:
                time.sleep(0.8 - elapsed)
            # 使用信号跨线程通信
            self._statusLoaded.emit(text, color)

        threading.Thread(target=_worker, daemon=True).start()


class AboutPage(ScrollArea):
    """关于页面，包含版本号、链接、检查更新等。"""

    _updateCheckFinished = Signal(object)  # update_info or None
    _updateCheckError = Signal(str)  # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updateCheckFinished.connect(self._on_update_result)
        self._updateCheckError.connect(self._on_update_error)
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._checking_update = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 软件信息
        layout.addWidget(SubtitleLabel("软件信息", self))
        version_text = BodyLabel(f"fuck-wjx（问卷星速填）\n当前版本：v{__VERSION__}", self)
        version_text.setWordWrap(True)
        layout.addWidget(version_text)

        # 检查更新按钮
        update_row = QHBoxLayout()
        update_row.setSpacing(8)
        self.update_btn = PrimaryPushButton("检查更新", self)
        self.update_spinner = IndeterminateProgressRing(self)
        self.update_spinner.setFixedSize(18, 18)
        self.update_spinner.setStrokeWidth(2)
        self.update_spinner.hide()
        update_row.addWidget(self.update_btn)
        update_row.addWidget(self.update_spinner)
        update_row.addStretch(1)
        layout.addLayout(update_row)

        layout.addSpacing(16)

        # 界面设置
        settings_card = CardWidget(self.view)
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(12)
        settings_layout.addWidget(SubtitleLabel("界面设置", self))
        
        # 侧边栏展开设置
        sidebar_row = QHBoxLayout()
        self.sidebar_switch = SwitchButton("始终展开侧边栏", self)
        self._pin_switch_label(self.sidebar_switch, "始终展开侧边栏")
        self.sidebar_switch.setChecked(True)
        sidebar_row.addWidget(self.sidebar_switch)
        sidebar_row.addStretch(1)
        settings_layout.addLayout(sidebar_row)
        
        # 重启程序按钮
        restart_row = QHBoxLayout()
        self.restart_btn = PushButton("重新启动程序", self)
        restart_row.addWidget(self.restart_btn)
        restart_row.addStretch(1)
        settings_layout.addLayout(restart_row)
        
        layout.addWidget(settings_card)
        layout.addSpacing(16)

        # 相关链接
        layout.addWidget(SubtitleLabel("相关链接", self))
        links_text = BodyLabel(
            f"GitHub: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}\n"
            f"官网: https://www.hungrym0.top/fuck-wjx.html\n"
            f"邮箱: hungrym0@qq.com",
            self
        )
        links_text.setWordWrap(True)
        layout.addWidget(links_text)

        link_btn_row = QHBoxLayout()
        link_btn_row.setSpacing(10)
        self.github_btn = PushButton("访问 GitHub", self)
        self.website_btn = PushButton("访问官网", self)
        link_btn_row.addWidget(self.github_btn)
        link_btn_row.addWidget(self.website_btn)
        link_btn_row.addStretch(1)
        layout.addLayout(link_btn_row)

        layout.addStretch(1)

        # 版权信息
        copyright_text = BodyLabel("©2026 HUNGRY_M0 版权所有  MIT License", self)
        copyright_text.setStyleSheet("color: #888;")
        layout.addWidget(copyright_text)

        # 绑定事件
        self.update_btn.clicked.connect(self._check_updates)
        self.sidebar_switch.checkedChanged.connect(self._on_sidebar_toggled)
        self.restart_btn.clicked.connect(self._restart_program)
        self.github_btn.clicked.connect(lambda: webbrowser.open(f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"))
        self.website_btn.clicked.connect(lambda: webbrowser.open("https://www.hungrym0.top/fuck-wjx.html"))

    def _set_update_loading(self, loading: bool):
        self._checking_update = loading
        self.update_btn.setEnabled(not loading)
        if loading:
            self.update_btn.setText("检查中...")
            self.update_spinner.show()
        else:
            self.update_btn.setText("检查更新")
            self.update_spinner.hide()

    def _on_update_result(self, update_info):
        """处理更新检查结果（在主线程中执行）"""
        self._set_update_loading(False)
        win = self.window()
        if update_info:
            if hasattr(win, 'update_info'):
                win.update_info = update_info  # type: ignore[union-attr]
            msg = (
                f"检测到新版本！\n\n"
                f"当前版本: v{update_info['current_version']}\n"
                f"新版本: v{update_info['version']}\n\n"
                f"是否立即更新？"
            )
            dlg = MessageBox("检查到更新", msg, win)
            dlg.yesButton.setText("立即更新")
            dlg.cancelButton.setText("稍后再说")
            if dlg.exec():
                from wjx.utils.updater import perform_update
                perform_update(win)
        else:
            InfoBar.success("", f"当前已是最新版本 v{__VERSION__}", parent=win, position=InfoBarPosition.TOP, duration=3000)

    def _on_update_error(self, error_msg: str):
        """处理更新检查错误（在主线程中执行）"""
        self._set_update_loading(False)
        InfoBar.error("", f"检查更新失败：{error_msg}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _check_updates(self):
        if self._checking_update:
            return
        self._set_update_loading(True)
        
        def _do_check():
            try:
                from wjx.utils.updater import UpdateManager
                update_info = UpdateManager.check_updates()
                self._updateCheckFinished.emit(update_info)
            except Exception as exc:
                self._updateCheckError.emit(str(exc))
        
        threading.Thread(target=_do_check, daemon=True).start()

    def _open_donate(self):
        try:
            payment_path = os.path.join(get_runtime_directory(), "assets", "payment.png")
            if os.path.exists(payment_path):
                webbrowser.open(payment_path)
                return
        except Exception:
            pass
        webbrowser.open("https://github.com/hungryM0/fuck-wjx")

    def _open_card_dialog(self):
        win = self.window()
        if hasattr(win, "_ask_card_code"):
            win._ask_card_code()  # type: ignore[union-attr]

    def _pin_switch_label(self, sw: SwitchButton, text: str):
        """保持开关两侧文本一致"""
        try:
            sw.setOnText(text)
            sw.setOffText(text)
            sw.setText(text)
        except Exception:
            sw.setText(text)

    def _on_sidebar_toggled(self, checked: bool):
        """侧边栏展开切换"""
        win = self.window()
        if hasattr(win, "navigationInterface"):
            try:
                if checked:
                    win.navigationInterface.setCollapsible(False)  # type: ignore[union-attr]
                    win.navigationInterface.expand()  # type: ignore[union-attr]
                else:
                    win.navigationInterface.setCollapsible(True)  # type: ignore[union-attr]
                InfoBar.success("", f"侧边栏已设置为{'始终展开' if checked else '可折叠'}", parent=win, position=InfoBarPosition.TOP, duration=2000)
            except Exception:
                pass

    def _restart_program(self):
        """重启程序"""
        import sys
        box = MessageBox("重启程序", "确定要重新启动程序吗？\n未保存的配置将会丢失。", self.window() or self)
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if box.exec():
            try:
                win = self.window()
                if hasattr(win, '_skip_save_on_close'):
                    win._skip_save_on_close = True  # type: ignore[attr-defined]
                import subprocess
                subprocess.Popen([sys.executable] + sys.argv)
                QApplication.quit()
            except Exception as exc:
                InfoBar.error("", f"重启失败：{exc}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)


class ContactPage(ScrollArea):
    """联系与支持页面，提供入口按钮和在线状态。"""

    _statusLoaded = Signal(str, str)  # text, color

    def __init__(self, on_contact, parent=None):
        super().__init__(parent)
        self.on_contact = on_contact
        self._statusLoaded.connect(self._on_status_loaded)
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._build_ui()

        # 定时刷新状态（每3秒）
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(3000)
        self._status_timer.timeout.connect(self._load_status_async)
        self._status_timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 联系开发者卡片
        contact_card = CardWidget(self.view)
        contact_layout = QVBoxLayout(contact_card)
        contact_layout.setContentsMargins(16, 16, 16, 16)
        contact_layout.setSpacing(12)
        contact_layout.addWidget(SubtitleLabel("联系开发者", self))
        
        desc = BodyLabel(
            "遇到问题、有建议、或者想聊天？直接点击下方按钮联系作者！\n"
            "消息会实时推送到作者手机上，回复很快哦~",
            self
        )
        desc.setWordWrap(True)
        contact_layout.addWidget(desc)

        # 在线状态
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_spinner = IndeterminateProgressRing(self)
        self.status_spinner.setFixedSize(16, 16)
        self.status_spinner.setStrokeWidth(2)
        self.status_label = BodyLabel("作者当前在线状态：查询中...", self)
        self.status_label.setStyleSheet("color:#BA8303;")
        status_row.addWidget(self.status_spinner)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        contact_layout.addLayout(status_row)

        self.contact_btn = PrimaryPushButton("发送消息给作者", self)
        contact_layout.addWidget(self.contact_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(contact_card)

        # 捐助支持卡片
        donate_card = CardWidget(self.view)
        donate_layout = QVBoxLayout(donate_card)
        donate_layout.setContentsMargins(16, 16, 16, 16)
        donate_layout.setSpacing(12)
        donate_layout.addWidget(SubtitleLabel("捐助支持", self))
        
        donate_desc = BodyLabel(
            "作者是一名大一学生，维护这个项目需要投入大量时间和精力。\n"
            "如果这个工具对你有帮助，欢迎请作者喝杯奶茶 ☕\n"
            "捐助后可以获得大额随机IP提交额度的卡密！",
            self
        )
        donate_desc.setWordWrap(True)
        donate_layout.addWidget(donate_desc)

        donate_btn_row = QHBoxLayout()
        donate_btn_row.setSpacing(10)
        self.donate_btn = PrimaryPushButton("捐助支持", self)
        self.card_btn = PushButton("输入卡密", self)
        donate_btn_row.addWidget(self.donate_btn)
        donate_btn_row.addWidget(self.card_btn)
        donate_btn_row.addStretch(1)
        donate_layout.addLayout(donate_btn_row)
        layout.addWidget(donate_card)

        # QQ群交流卡片
        community_card = CardWidget(self.view)
        community_layout = QVBoxLayout(community_card)
        community_layout.setContentsMargins(16, 16, 16, 16)
        community_layout.setSpacing(12)
        community_layout.addWidget(SubtitleLabel("加入QQ群", self))
        
        community_desc = BodyLabel(
            "扫描下方二维码加入QQ交流群，和其他用户一起交流使用心得！\n"
            "群里可以获取最新版本、反馈问题、提出建议~",
            self
        )
        community_desc.setWordWrap(True)
        community_layout.addWidget(community_desc)

        # QQ群二维码图片
        self.qq_group_label = QLabel(self)
        self.qq_group_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qq_group_label.setMinimumSize(280, 280)
        self.qq_group_label.setStyleSheet("border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px;")
        self.qq_group_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.qq_group_label.mousePressEvent = lambda ev: self._on_qq_group_clicked(ev)  # type: ignore[method-assign]
        self._load_qq_group_image()
        
        click_hint = BodyLabel("点击图片查看原图", self)
        click_hint.setStyleSheet("color: #888; font-size: 12px;")
        community_layout.addWidget(self.qq_group_label, alignment=Qt.AlignmentFlag.AlignLeft)
        community_layout.addWidget(click_hint, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(community_card)

        layout.addStretch(1)

        # 绑定事件
        self.contact_btn.clicked.connect(lambda: self.on_contact())
        self.donate_btn.clicked.connect(self._open_donate)
        self.card_btn.clicked.connect(self._open_card_dialog)
        self._load_status_async()

    def _on_qq_group_clicked(self, ev):
        """点击二维码查看原图"""
        try:
            qq_group_path = os.path.join(get_runtime_directory(), "assets", "QQ_group.jpg")
            if os.path.exists(qq_group_path):
                self._show_full_image(qq_group_path)
        except Exception:
            pass

    def _show_full_image(self, image_path: str):
        """显示原图弹窗"""
        from PySide6.QtGui import QPixmap
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle("QQ群二维码")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        
        img_label = QLabel(dialog)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(image_path)
        if pixmap.width() > 600 or pixmap.height() > 600:
            pixmap = pixmap.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        img_label.setPixmap(pixmap)
        layout.addWidget(img_label)
        
        close_btn = PushButton("关闭", dialog)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        dialog.adjustSize()
        dialog.exec()

    def _load_qq_group_image(self):
        """加载QQ群二维码图片"""
        try:
            from PySide6.QtGui import QPixmap
            qq_group_path = os.path.join(get_runtime_directory(), "assets", "QQ_group.jpg")
            if os.path.exists(qq_group_path):
                pixmap = QPixmap(qq_group_path)
                scaled = pixmap.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.qq_group_label.setPixmap(scaled)
            else:
                self.qq_group_label.setText("QQ群二维码图片未找到\n请检查 assets/QQ_group.jpg")
        except Exception as e:
            self.qq_group_label.setText(f"加载图片失败：{e}")

    def _open_donate(self):
        try:
            payment_path = os.path.join(get_runtime_directory(), "assets", "payment.png")
            if os.path.exists(payment_path):
                webbrowser.open(payment_path)
                return
        except Exception:
            pass
        webbrowser.open("https://github.com/hungryM0/fuck-wjx")

    def _open_card_dialog(self):
        win = self.window()
        if hasattr(win, "_ask_card_code"):
            win._ask_card_code()  # type: ignore[union-attr]

    def _on_status_loaded(self, text: str, color: str):
        """信号槽：在主线程更新状态标签"""
        self.status_spinner.hide()
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};")

    def _load_status_async(self):
        def _worker():
            text = "作者当前在线状态：未知"
            color = "#666666"
            try:
                payload = get_status()
                text, color = _format_status_payload(payload)
            except Exception:
                text = "作者当前在线状态：获取失败"
                color = "#cc0000"
            self._statusLoaded.emit(text, color)

        threading.Thread(target=_worker, daemon=True).start()


class MainWindow(FluentWindow):
    """主窗口，PowerToys 风格导航 + 圆角布局，支持主题动态切换。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        qconfig.load(os.path.join(get_runtime_directory(), "wjx", "ui", "theme.json"))
        setTheme(Theme.AUTO)
        setThemeColor("#2563EB")
        self._skip_save_on_close = False
        
        self.setWindowTitle(f"问卷星速填 v{__VERSION__}")
        icon_path = get_resource_path(APP_ICON_RELATIVE_PATH)
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(1080, 720)

        self.controller = RunController(self)
        self.controller.on_ip_counter = None  # will be set after dashboard creation
        self.controller.card_code_provider = self._ask_card_code

        self.settings_page = SettingsPage(self.controller, self)
        self.question_page = QuestionPage(self)
        # QuestionPage 仅用作题目配置的数据载体，不作为主界面子页面展示；
        # 若不隐藏会以默认几何 (0,0,100,30) 叠在窗口左上角，造成标题栏错乱。
        self.question_page.hide()
        self.dashboard = DashboardPage(self.controller, self.question_page, self.settings_page, self)
        self.log_page = LogPage(self)
        self.help_page = HelpPage(self._open_contact_dialog, self)
        self.about_page = AboutPage(self)

        self.dashboard.setObjectName("dashboard")
        self.question_page.setObjectName("question")
        self.settings_page.setObjectName("settings")
        self.log_page.setObjectName("logs")
        self.help_page.setObjectName("help")
        self.about_page.setObjectName("about")

        self._init_navigation()
        # 设置侧边栏宽度和默认不可折叠
        try:
            self.navigationInterface.setExpandWidth(140)
            self.navigationInterface.setCollapsible(False)
        except Exception:
            pass
        self._sidebar_expanded = False  # 标记侧边栏是否已展开
        self._bind_controller_signals()
        # 确保初始 adapter 也能回调随机 IP 计数
        self.controller.adapter.update_random_ip_counter = self.dashboard.update_random_ip_counter
        self._register_popups()
        self._load_saved_config()
        self._center_on_screen()

    def showEvent(self, e):
        """窗口显示时展开侧边栏"""
        super().showEvent(e)
        if not self._sidebar_expanded:
            self._sidebar_expanded = True
            try:
                self.navigationInterface.expand(useAni=False)
            except Exception:
                pass

    def closeEvent(self, e):
        """窗口关闭时询问用户是否保存配置"""
        # 先停止所有定时器，防止在关闭过程中触发回调
        try:
            if hasattr(self.log_page, '_refresh_timer'):
                self.log_page._refresh_timer.stop()
            if hasattr(self.help_page, '_status_timer'):
                self.help_page._status_timer.stop()
        except Exception:
            pass
        
        if not self._skip_save_on_close:
            # 询问用户是否保存配置
            box = MessageBox("保存配置", "是否保存当前配置？", self)
            box.yesButton.setText("保存")
            box.cancelButton.setText("取消")
            
            # 添加"不保存"按钮
            no_btn = PushButton("不保存", self)
            box.buttonLayout.insertWidget(1, no_btn)
            no_btn.clicked.connect(lambda: box.done(2))  # 2 表示"不保存"
            
            reply = box.exec()
            
            if reply == 0 or not reply:  # 取消
                # 用户取消关闭
                e.ignore()
                return
            elif reply == 1 or reply == True:  # 保存
                # 用户选择保存
                try:
                    cfg = self.dashboard._build_config()
                    cfg.question_entries = list(self.question_page.get_entries())
                    self.controller.config = cfg
                    
                    # 弹出文件保存对话框，默认位置在 configs 目录
                    configs_dir = os.path.join(get_runtime_directory(), "configs")
                    os.makedirs(configs_dir, exist_ok=True)
                    
                    # 使用问卷标题作为默认文件名
                    from wjx.utils.load_save import _sanitize_filename
                    survey_title = self.dashboard.title_label.text()
                    if survey_title and survey_title != "题目清单与操作" and survey_title != "已配置的题目":
                        default_filename = f"{_sanitize_filename(survey_title)}.json"
                    else:
                        default_filename = f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    default_path = os.path.join(configs_dir, default_filename)
                    
                    path, _ = QFileDialog.getSaveFileName(
                        self,
                        "保存配置",
                        default_path,
                        "JSON 文件 (*.json);;所有文件 (*.*)"
                    )
                    
                    if path:
                        from wjx.utils.load_save import save_config
                        save_config(cfg, path)
                        import logging
                        logging.info(f"配置已保存到: {path}")
                    else:
                        # 用户取消了保存对话框，询问是否继续退出
                        continue_box = MessageBox("确认", "未保存配置，是否继续退出？", self)
                        continue_box.yesButton.setText("退出")
                        continue_box.cancelButton.setText("取消")
                        if not continue_box.exec():
                            e.ignore()
                            return
                except Exception as exc:
                    import logging
                    logging.error(f"保存配置失败: {exc}", exc_info=True)
                    error_box = MessageBox("错误", f"保存配置失败：{exc}\n\n是否继续退出？", self)
                    error_box.yesButton.setText("退出")
                    error_box.cancelButton.setText("取消")
                    if not error_box.exec():
                        e.ignore()
                        return
            
            # 自动保存日志到固定文件
            try:
                log_path = os.path.join(get_runtime_directory(), "logs", "last_session.log")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                records = LOG_BUFFER_HANDLER.get_records()
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("\n".join([entry.text for entry in records]))
            except Exception as log_exc:
                import logging
                logging.warning(f"保存日志失败: {log_exc}")
        
        super().closeEvent(e)

    def _open_contact_dialog(self, default_type: str = "报错反馈"):
        dlg = ContactDialog(self, default_type=default_type, status_fetcher=get_status, status_formatter=_format_status_payload)
        dlg.exec()

    # ---------- init helpers ----------
    def _init_navigation(self):
        self.addSubInterface(self.dashboard, FluentIcon.HOME, "概览", NavigationItemPosition.TOP)
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, "运行参数", NavigationItemPosition.TOP)
        self.addSubInterface(self.log_page, FluentIcon.INFO, "日志", NavigationItemPosition.TOP)
        self.addSubInterface(self.help_page, FluentIcon.HELP, "帮助", NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.about_page, FluentIcon.INFO, "关于", NavigationItemPosition.BOTTOM)
        self.navigationInterface.setCurrentItem(self.dashboard.objectName())

    def _on_load_config(self):
        """载入配置文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, 
            "载入配置", 
            get_runtime_directory(), 
            "JSON 文件 (*.json);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            cfg = self.controller.load_saved_config(path)
            self.settings_page.apply_config(cfg)
            self.dashboard.apply_config(cfg)
            self.question_page.set_entries(cfg.question_entries or [], self.question_page.questions_info)
            self.dashboard._refresh_entry_table()
            self.dashboard._sync_start_button_state()
            refresh_ip_counter_display(self.controller.adapter)
            self._toast("已载入配置", "success")
        except Exception as exc:
            self._toast(f"载入失败：{exc}", "error")

    def _on_save_config(self):
        """保存配置文件"""
        cfg = self.dashboard._build_config()
        cfg.question_entries = list(self.question_page.get_entries())
        self.controller.config = cfg
        path, _ = QFileDialog.getSaveFileName(
            self, 
            "保存配置", 
            os.path.join(get_runtime_directory(), "config.json"), 
            "JSON 文件 (*.json);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            self.controller.save_current_config(path)
            self._toast("配置已保存", "success")
        except Exception as exc:
            self._toast(f"保存失败：{exc}", "error")

    def _check_updates(self):
        """检查更新"""
        try:
            from wjx.utils.updater import check_for_updates
            check_for_updates(self)
        except Exception as exc:
            self._toast(f"检查更新失败：{exc}", "error")

    def _open_feedback(self):
        """打开问题反馈"""
        message = (
            f"将打开浏览器访问 GitHub Issue 页面以反馈问题：\n"
            f"{ISSUE_FEEDBACK_URL}\n\n"
            "提醒：该网站可能在国内访问较慢或需要额外网络配置。\n"
            "是否继续？"
        )
        box = MessageBox("问题反馈", message, self)
        box.yesButton.setText("继续")
        box.cancelButton.setText("取消")
        if box.exec():
            try:
                webbrowser.open(ISSUE_FEEDBACK_URL)
            except Exception as exc:
                self._toast(f"打开失败：{exc}", "error")

    def _show_about(self):
        """显示关于对话框"""
        about_text = (
            f"fuck-wjx（问卷星速填）\n\n"
            f"当前版本 v{__VERSION__}\n\n"
            f"GitHub项目地址: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}\n"
            f"有问题可在 GitHub 提交 issue 或发送电子邮件至 hungrym0@qq.com\n\n"
            f"官方网站: https://www.hungrym0.top/fuck-wjx.html\n"
            f"©2025 HUNGRY_M0 版权所有  MIT License"
        )
        box = MessageBox("关于", about_text, self)
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()

    def _open_donation(self):
        """打开捐助窗口"""
        try:
            payment_path = os.path.join(get_runtime_directory(), "assets", "payment.png")
            if os.path.exists(payment_path):
                webbrowser.open(payment_path)
                return
        except Exception:
            pass
        webbrowser.open("https://github.com/hungryM0/fuck-wjx")

    def _center_on_screen(self):
        """窗口居中显示，适配多显示器与缩放。"""
        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if not screen:
                return
            available = screen.availableGeometry()
            frame = self.frameGeometry()
            frame.moveCenter(available.center())
            self.move(frame.topLeft())
        except Exception:
            pass

    def _bind_controller_signals(self):
        self.controller.surveyParsed.connect(self._on_survey_parsed)
        self.controller.surveyParseFailed.connect(self._on_survey_parse_failed)
        self.controller.runFailed.connect(lambda msg: self._toast(msg, "error"))
        self.controller.runStateChanged.connect(self.dashboard.on_run_state_changed)
        self.controller.statusUpdated.connect(self.dashboard.update_status)
        self.controller.on_ip_counter = self.dashboard.update_random_ip_counter

    def _register_popups(self):
        def handler(kind: str, title: str, message: str):
            def _show():
                if kind == "confirm":
                    box = MessageBox(title, message, self)
                    box.yesButton.setText("确定")
                    box.cancelButton.setText("取消")
                    return bool(box.exec())
                if kind == "error":
                    InfoBar.error(title, message, parent=self, position=InfoBarPosition.TOP, duration=3000)
                    return False
                if kind == "warning":
                    InfoBar.warning(title, message, parent=self, position=InfoBarPosition.TOP, duration=3000)
                    return True
                InfoBar.info(title, message, parent=self, position=InfoBarPosition.TOP, duration=2500)
                return True

            return self._dispatch_to_ui(_show)

        register_popup_handler(handler)

    def _load_saved_config(self):
        try:
            cfg = self.controller.load_saved_config()
        except Exception:
            cfg = RuntimeConfig()
        self.settings_page.apply_config(cfg)
        self.dashboard.apply_config(cfg)
        self.question_page.set_entries(cfg.question_entries or [], self.controller.questions_info)
        # 初始刷新随机 IP 计数
        refresh_ip_counter_display(self.controller.adapter)

    # ---------- controller callbacks ----------
    def _on_survey_parsed(self, info: List[Dict[str, Any]], title: str):
        self.question_page.set_questions(info, self.controller.question_entries)
        self.dashboard.update_question_meta(title or "问卷", len(info))
        self._toast("解析完成，可在“题目配置”页查看", "success")
        if getattr(self.dashboard, "_open_wizard_after_parse", False):
            self.dashboard._open_wizard_after_parse = False
            self.dashboard._open_question_wizard()

    def _on_survey_parse_failed(self, msg: str):
        self._toast(msg, "error")
        self.dashboard._open_wizard_after_parse = False

    def _ask_card_code(self) -> Optional[str]:
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_card_code()
        return None

    # ---------- utilities ----------
    def _dispatch_to_ui(self, func):
        if self.thread() == QThread.currentThread():
            return func()
        done = threading.Event()
        result: Dict[str, Any] = {}

        def _wrapper():
            try:
                result["value"] = func()
            finally:
                done.set()

        QTimer.singleShot(0, _wrapper)
        done.wait()
        return result.get("value")

    def _toast(self, text: str, level: str = "info", duration: int = 2000):
        kind = level.lower()
        if kind == "success":
            InfoBar.success("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "warning":
            InfoBar.warning("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "error":
            InfoBar.error("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)
        else:
            InfoBar.info("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)

    # ---------- updater 兼容方法 ----------
    def _log_popup_confirm(self, title: str, message: str) -> bool:
        """显示确认对话框，返回用户是否确认。"""
        box = MessageBox(title, message, self)
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        return bool(box.exec())

    def _log_popup_info(self, title: str, message: str):
        """显示信息对话框。"""
        box = MessageBox(title, message, self)
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()

    def _log_popup_error(self, title: str, message: str):
        """显示错误对话框。"""
        box = MessageBox(title, message, self)
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()


def create_window() -> MainWindow:
    """供入口调用的工厂函数。"""
    return MainWindow()
