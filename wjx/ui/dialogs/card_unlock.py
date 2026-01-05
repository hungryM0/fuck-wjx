"""卡密解锁对话框"""
import os
import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLineEdit
from qfluentwidgets import (
    BodyLabel,
    SubtitleLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    PasswordLineEdit,
    IndeterminateProgressRing,
    Action,
    FluentIcon,
    RoundMenu,
)

from wjx.ui.widgets import StatusFetchWorker
from wjx.network.random_ip import get_status, _format_status_payload
from wjx.utils.load_save import get_runtime_directory
from wjx.utils.version import ISSUE_FEEDBACK_URL


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
        
        step1 = BodyLabel("1. 捐助任意金额（多少都行）", steps_card)
        step2 = BodyLabel("2. 在「联系」中找到开发者，并留下联系邮箱", steps_card)
        step3 = BodyLabel("3. 输入卡密后即可解锁大额随机IP提交额度，不够用可继续免费申请", steps_card)
        step4 = BodyLabel("4. 你也可以通过自己的口才白嫖卡密（误）", steps_card)
        step4.setStyleSheet("color: #888; text-decoration: line-through;")
        
        steps_layout.addWidget(step1)
        steps_layout.addWidget(step2)
        steps_layout.addWidget(step3)
        steps_layout.addWidget(step4)
        layout.addWidget(steps_card)

        thanks = BodyLabel("感谢您的支持与理解！", self)
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
        # 延迟导入避免循环依赖
        from wjx.ui.dialogs import ContactDialog
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
