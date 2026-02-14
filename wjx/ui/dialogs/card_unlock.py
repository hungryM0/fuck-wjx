"""卡密解锁对话框"""
import os
import webbrowser
from typing import Optional, Callable
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


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
    MessageBox,
    RoundMenu,
    InfoBar,
    InfoBarPosition,
)

from wjx.ui.widgets import StatusPollingMixin
from wjx.network.proxy import get_status, _format_status_payload
from wjx.utils.io.load_save import get_assets_directory
from wjx.utils.app.version import ISSUE_FEEDBACK_URL


class CardValidateWorker(QThread):
    """卡密验证 Worker"""


    finished = Signal(bool, object)  # 验证结果、额度

    def __init__(self, card_code: str, validator: Callable[[str], object]):
        super().__init__()
        self._card_code = card_code
        self._validator = validator

    def run(self):
        success = False
        quota = None
        try:
            result = self._validator(self._card_code)
            if isinstance(result, tuple):
                success = bool(result[0])
                if len(result) > 1:
                    quota = result[1]
            else:
                success = bool(result)
        except Exception:
            success = False
            quota = None
        self.finished.emit(success, quota)


class CardUnlockDialog(StatusPollingMixin, QDialog):
    """解锁大额随机 IP 的说明/输入弹窗。使用 StatusPollingMixin 处理状态轮询。"""

    _statusLoaded = Signal(str, str)  # text, color
    _validateFinished = Signal(bool, object)  # 验证结果信号（携带额度）

    def __init__(self, parent=None, status_fetcher=None, status_formatter=None, contact_handler=None, card_validator=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._validateFinished.connect(self._on_validate_finished)
        self.setWindowTitle("随机IP额度限制")
        self.resize(820, 600)
        
        # 初始化状态轮询 Mixin
        self._init_status_polling(status_fetcher, status_formatter)
        
        # 卡密验证相关
        self._card_validator = card_validator
        self._validate_thread: Optional[CardValidateWorker] = None
        self._validation_result: Optional[bool] = None
        self._validation_quota: Optional[int] = None
        
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
        
        step1 = BodyLabel("1. 捐助任意金额（🥹多少都行）", steps_card)
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
        self.contact_btn = PushButton("联系", self, FluentIcon.MESSAGE)
        self.donate_btn = PushButton("捐助", self, FluentIcon.HEART)
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
        self.cancel_btn = PushButton("取消", self)
        self.ok_btn = PrimaryPushButton("验证", self, FluentIcon.COMPLETED)
        # 验证按钮旁的转圈动画（放在右边）
        self.validate_spinner = IndeterminateProgressRing(self)
        self.validate_spinner.setFixedSize(20, 20)
        self.validate_spinner.setStrokeWidth(2)
        self.validate_spinner.hide()
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.ok_btn)
        action_row.addWidget(self.validate_spinner)
        layout.addLayout(action_row)

        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._on_validate_clicked)
        self.contact_btn.clicked.connect(contact_handler if callable(contact_handler) else self._open_contact)
        self.donate_btn.clicked.connect(self._open_donate)

        # 启动状态查询和定时刷新
        self._start_status_polling()

        try:
            self.card_edit.setFocus()
        except Exception as exc:
            log_suppressed_exception("__init__: self.card_edit.setFocus()", exc, level=logging.WARNING)

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

    def _on_status_loaded(self, text: str, color: str):
        """信号槽：在主线程更新状态标签"""
        try:
            self.status_spinner.hide()
            self.status_label.setText(text)
            self.status_label.setStyleSheet(f"color:{color};")
        except RuntimeError as exc:
            log_suppressed_exception("_on_status_loaded: self.status_spinner.hide()", exc, level=logging.WARNING)

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
            result = dlg.exec()
            sent_type = getattr(getattr(dlg, "form", None), "_current_message_type", "")
            if result == QDialog.DialogCode.Accepted and sent_type == "白嫖卡密（？）":
                self.accept()
        except Exception:
            webbrowser.open(ISSUE_FEEDBACK_URL)

    def _open_donate(self):
        confirm_box = MessageBox(
            "确认捐助",
            "请确保已经在本地充分测试并确认功能可正常使用后，再获取随机 IP 服务。\n\n是否继续打开捐助页？",
            self,
        )
        # 按钮文案改为中文，避免英文残留
        try:
            confirm_box.yesButton.setText("继续")
            confirm_box.cancelButton.setText("取消")
        except Exception as exc:
            log_suppressed_exception("_open_donate: confirm_box.yesButton.setText(\"继续\")", exc, level=logging.WARNING)
        if not confirm_box.exec():
            return
        try:
            payment_path = os.path.join(get_assets_directory(), "payment.png")
            if os.path.exists(payment_path):
                webbrowser.open(payment_path)
                return
        except Exception as exc:
            log_suppressed_exception("_open_donate: payment_path = os.path.join(get_assets_directory(), \"payment.png\")", exc, level=logging.WARNING)
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
                except Exception as exc:
                    log_suppressed_exception("_setup_toggle_password_button: btn.pressed.disconnect()", exc, level=logging.WARNING)
                try:
                    btn.released.disconnect()
                except Exception as exc:
                    log_suppressed_exception("_setup_toggle_password_button: btn.released.disconnect()", exc, level=logging.WARNING)
                
                # 使用点击切换模式
                self._password_visible = False
                def toggle_password():
                    self._password_visible = not self._password_visible
                    if self._password_visible:
                        self.card_edit.setEchoMode(QLineEdit.EchoMode.Normal)
                        try:
                            btn.setIcon(FluentIcon.VIEW)
                        except Exception as exc:
                            log_suppressed_exception("toggle_password: btn.setIcon(FluentIcon.VIEW)", exc, level=logging.WARNING)
                    else:
                        self.card_edit.setEchoMode(QLineEdit.EchoMode.Password)
                        try:
                            btn.setIcon(FluentIcon.HIDE)
                        except Exception as exc:
                            log_suppressed_exception("toggle_password: btn.setIcon(FluentIcon.HIDE)", exc, level=logging.WARNING)
                
                # 默认使用“隐藏”图标
                try:
                    btn.setIcon(FluentIcon.HIDE)
                except Exception as exc:
                    log_suppressed_exception("_setup_toggle_password_button: btn.setIcon(FluentIcon.HIDE)", exc, level=logging.WARNING)
                
                btn.clicked.connect(toggle_password)
        except Exception as exc:
            log_suppressed_exception("_setup_toggle_password_button: btn = getattr(self.card_edit, 'button', None)", exc, level=logging.WARNING)

    def _on_validate_clicked(self):
        """点击验证按钮时触发"""
        code = self.card_edit.text().strip()
        if not code:
            InfoBar.warning("", "请输入卡密", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        
        # 如果没有验证器，直接返回卡密（兼容旧逻辑）
        if not callable(self._card_validator):
            self._stop_status_polling()
            super().accept()
            return
        
        # 禁用按钮，显示转圈动画
        self.ok_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.validate_spinner.show()
        
        # 启动验证线程
        self._validate_thread = CardValidateWorker(code, self._card_validator)
        self._validate_thread.finished.connect(self._validateFinished.emit)
        self._validate_thread.start()

    def _on_validate_finished(self, success: bool, quota):
        """验证完成后的回调"""
        # 隐藏转圈动画，恢复按钮
        self.validate_spinner.hide()
        self.ok_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)

        self._validation_result = success
        try:
            self._validation_quota = None if quota is None else int(quota)
        except Exception:
            self._validation_quota = None

        if success:
            extra = ""
            if self._validation_quota is not None:
                extra = f"，额度 +{self._validation_quota}"
            InfoBar.success("", f"卡密验证通过{extra}", parent=self, position=InfoBarPosition.TOP, duration=2000)
            # 延迟关闭窗口，让用户看到成功提示
            QTimer.singleShot(1500, self._close_on_success)
        else:
            InfoBar.error("", "卡密验证失败，请重试", parent=self, position=InfoBarPosition.TOP, duration=2500)

    def _close_on_success(self):
        """验证成功后关闭窗口"""
        self._stop_status_polling()
        super().accept()

    def get_card_code(self) -> Optional[str]:
        return self.card_edit.text().strip() or None

    def get_validation_result(self) -> Optional[bool]:
        """获取验证结果"""
        return self._validation_result

    def get_validation_quota(self) -> Optional[int]:
        """获取验证额度"""
        return self._validation_quota

