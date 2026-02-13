# -*- coding: utf-8 -*-


import logging
from wjx.utils.logging.log_utils import log_suppressed_exception

"""GitHub 账号页面 - 登录与Issue提交"""

import platform
import webbrowser
from threading import Thread
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication, QPlainTextEdit, QTextBrowser, QStackedWidget, QStyle
import wjx.network.http_client as http_client
from qfluentwidgets import (
    BodyLabel,
    PushButton,
    PrimaryPushButton,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    HyperlinkButton,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    SubtitleLabel,
    ScrollArea,
    LineEdit,
    ComboBox,
    AvatarWidget,
    IconWidget,
    MessageBox,
)

from wjx.utils.integrations.github_auth import (
    get_github_auth,
    GitHubAuthError,
    GITHUB_DEVICE_VERIFY_URL,
)
from wjx.utils.integrations.github_issue import create_issue, GitHubIssueError, ISSUE_TYPES
from wjx.utils.app.version import __VERSION__
from wjx.utils.system.hosts_helper import check_hosts_status, run_hosts_operation_as_admin


class DeviceCodeWorker(QThread):
    """设备码请求 Worker"""
    
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._should_stop = False
    
    def stop(self):
        self._should_stop = True
    
    def run(self):
        if self._should_stop:
            return
        try:
            auth = get_github_auth()
            info = auth.request_device_code()
            if not self._should_stop:
                self.finished.emit(info)
        except GitHubAuthError as e:
            if not self._should_stop:
                self.error.emit(str(e))
        except Exception as e:
            if not self._should_stop:
                self.error.emit(f"请求失败: {e}")


class TokenPollWorker(QThread):
    """Token 轮询 Worker"""
    
    progress = Signal(str)
    finished = Signal(bool)
    error = Signal(str)
    
    def __init__(self, device_code: str, interval: int, expires_in: int, parent=None):
        super().__init__(parent)
        self._device_code = device_code
        self._interval = interval
        self._expires_in = expires_in
        self._should_stop = False
    
    def stop(self):
        self._should_stop = True
    
    def run(self):
        try:
            auth = get_github_auth()
            success = auth.poll_for_token(
                self._device_code,
                self._interval,
                self._expires_in,
                on_progress=lambda msg: self.progress.emit(msg),
                should_stop=lambda: self._should_stop
            )
            self.finished.emit(success)
        except GitHubAuthError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"认证失败: {e}")


class IssueSubmitWorker(QThread):
    """Issue 提交 Worker"""
    
    success = Signal(str)
    error = Signal(str)
    
    def __init__(self, access_token: str, title: str, body: str, labels: list, parent=None):
        super().__init__(parent)
        self._access_token = access_token
        self._title = title
        self._body = body
        self._labels = labels
    
    def run(self):
        try:
            result = create_issue(
                self._access_token,
                self._title,
                self._body,
                self._labels
            )
            issue_url = result.get("html_url", "")
            self.success.emit(issue_url)
        except GitHubIssueError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(str(e))


class AvatarLoadWorker(QThread):
    """头像加载 Worker"""
    
    finished = Signal(bytes)
    
    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
    
    def run(self):
        try:
            resp = http_client.get(self._url, timeout=10)
            if resp.status_code == 200:
                self.finished.emit(resp.content)
        except Exception as exc:
            log_suppressed_exception("run: resp = http_client.get(self._url, timeout=10)", exc, level=logging.WARNING)


class StarCheckWorker(QThread):
    """Star 状态检查 Worker"""
    
    finished = Signal(bool)
    
    def run(self):
        try:
            auth = get_github_auth()
            result = auth.check_starred_this_repo()
            self.finished.emit(result)
        except Exception:
            self.finished.emit(False)


class StarActionWorker(QThread):
    """Star/Unstar 操作 Worker"""
    
    finished = Signal(bool, bool)  # (success, is_starred_now)
    
    def __init__(self, do_star: bool, parent=None):
        super().__init__(parent)
        self._do_star = do_star
    
    def run(self):
        try:
            auth = get_github_auth()
            if self._do_star:
                success = auth.star_this_repo()
            else:
                success = auth.unstar_this_repo()
            self.finished.emit(success, self._do_star if success else not self._do_star)
        except Exception:
            self.finished.emit(False, not self._do_star)


class AccountPage(ScrollArea):
    """GitHub 账号页面"""
    
    loginSuccess = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("account")
        self.setWidgetResizable(True)
        
        self._device_code_worker: Optional[DeviceCodeWorker] = None
        self._token_poll_worker: Optional[TokenPollWorker] = None
        self._submit_worker: Optional[IssueSubmitWorker] = None
        self._avatar_worker: Optional[AvatarLoadWorker] = None
        self._star_check_worker: Optional[StarCheckWorker] = None
        self._star_action_worker: Optional[StarActionWorker] = None
        self._has_starred: bool = False
        
        self._build_ui()
        self._update_ui_state()
    
    def _build_ui(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(20)
        
        # 标题
        title = SubtitleLabel("GitHub 账号", self)
        layout.addWidget(title)
        
        # 登录卡片
        self.login_card = CardWidget(self)
        card_layout = QVBoxLayout(self.login_card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(16)
        
        # 已登录状态显示
        self.logged_in_widget = QWidget()
        logged_in_layout = QHBoxLayout(self.logged_in_widget)
        logged_in_layout.setContentsMargins(0, 0, 0, 0)
        logged_in_layout.setSpacing(16)
        
        # 头像
        self.avatar = AvatarWidget(self)
        self.avatar.setRadius(28)
        logged_in_layout.addWidget(self.avatar)
        
        # 用户信息
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        
        self.user_label = BodyLabel("", self)
        self.user_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        info_layout.addWidget(self.user_label)
        
        self.status_tip = CaptionLabel("GitHub 账号已连接", self)
        self.status_tip.setStyleSheet("color: #4caf50;")
        info_layout.addWidget(self.status_tip)
        
        # Star 状态
        self.star_label = CaptionLabel("", self)
        info_layout.addWidget(self.star_label)
        
        logged_in_layout.addLayout(info_layout)
        logged_in_layout.addStretch(1)
        
        # Star 操作转圈动画（放在按钮左边）
        self.star_spinner = IndeterminateProgressRing(self)
        self.star_spinner.setFixedSize(18, 18)
        self.star_spinner.setStrokeWidth(2)
        self.star_spinner.hide()
        logged_in_layout.addWidget(self.star_spinner)
        
        # Star 按钮（未 Star 时使用主题色，已 Star 时使用普通样式）
        self.star_btn_primary = PrimaryPushButton("星标", self)
        self.star_btn_primary.setIcon(FluentIcon.HEART)
        self.star_btn_primary.clicked.connect(self._toggle_star)
        logged_in_layout.addWidget(self.star_btn_primary)
        
        self.star_btn_normal = PushButton("已加星标", self)
        self.star_btn_normal.setIcon(FluentIcon.HEART)
        self.star_btn_normal.hide()
        logged_in_layout.addWidget(self.star_btn_normal)
        
        # 退出按钮
        logout_btn = PushButton("退出登录", self)
        logout_btn.setIcon(FluentIcon.CLOSE)
        logout_btn.clicked.connect(self._logout)
        logged_in_layout.addWidget(logout_btn)
        
        card_layout.addWidget(self.logged_in_widget)
        
        # 未登录状态显示
        self.not_logged_in_widget = QWidget()
        not_logged_in_layout = QHBoxLayout(self.not_logged_in_widget)
        not_logged_in_layout.setContentsMargins(0, 0, 0, 0)
        not_logged_in_layout.setSpacing(20)
        
        # 左侧图标
        github_icon = IconWidget(FluentIcon.GITHUB, self)
        github_icon.setFixedSize(48, 48)
        not_logged_in_layout.addWidget(github_icon)
        
        # 中间文字区域
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        
        login_title = BodyLabel("登录 GitHub 账号", self)
        login_title.setStyleSheet("font-size: 15px; font-weight: bold;")
        text_layout.addWidget(login_title)
        
        desc = CaptionLabel("🔔 登录后可便捷互动仓库", self)
        desc.setStyleSheet("color: #888;")
        text_layout.addWidget(desc)
        
        not_logged_in_layout.addLayout(text_layout)
        not_logged_in_layout.addStretch(1)
        
        # 右侧登录按钮
        self.start_login_btn = PrimaryPushButton("开始登录", self)
        self.start_login_btn.setIcon(FluentIcon.LINK)
        self.start_login_btn.clicked.connect(self._start_device_flow)
        not_logged_in_layout.addWidget(self.start_login_btn)
        
        card_layout.addWidget(self.not_logged_in_widget)
        
        # 登录流程显示
        self.login_flow_widget = QWidget()
        login_flow_layout = QVBoxLayout(self.login_flow_widget)
        login_flow_layout.setContentsMargins(0, 0, 0, 0)
        login_flow_layout.setSpacing(16)
        
        flow_desc = BodyLabel("请在浏览器中打开以下链接，并输入验证码完成授权：", self)
        flow_desc.setWordWrap(True)
        login_flow_layout.addWidget(flow_desc)
        
        self.link_btn = HyperlinkButton(GITHUB_DEVICE_VERIFY_URL, "打开 GitHub 授权页面", self)
        login_flow_layout.addWidget(self.link_btn)
        
        # 验证码显示
        code_row = QHBoxLayout()
        code_row.setSpacing(8)
        code_label = BodyLabel("验证码：", self)
        code_row.addWidget(code_label)
        
        self.code_display = BodyLabel("--------", self)
        self.code_display.setStyleSheet(
            "font-size: 24px; font-weight: bold; font-family: monospace; "
            "background: rgba(128, 128, 128, 0.2); padding: 8px 16px; border-radius: 4px; "
            "color: #2563eb;"
        )
        code_row.addWidget(self.code_display)
        
        self.copy_btn = PushButton("复制", self)
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._copy_code)
        code_row.addWidget(self.copy_btn)
        
        code_row.addStretch(1)
        login_flow_layout.addLayout(code_row)
        
        # 状态显示
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(16, 16)
        self.spinner.setStrokeWidth(2)
        self.status_label = CaptionLabel("正在获取验证码...", self)
        self.status_label.setStyleSheet("color: #888;")
        status_row.addWidget(self.spinner)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        login_flow_layout.addLayout(status_row)
        
        # 取消按钮
        cancel_btn = PushButton("取消", self)
        cancel_btn.clicked.connect(self._cancel_login)
        login_flow_layout.addWidget(cancel_btn)
        
        card_layout.addWidget(self.login_flow_widget)
        
        layout.addWidget(self.login_card)
        
        # 网络优化卡片
        self._build_network_card(layout)
        
        # Issue 提交卡片
        self._build_issue_card(layout)
        
        layout.addStretch(1)

        self.setWidget(container)
        self.enableTransparentBackground()
    
    def _build_network_card(self, parent_layout: QVBoxLayout):
        """构建网络优化卡片"""
        network_title = SubtitleLabel("网络优化", self)
        parent_layout.addWidget(network_title)
        
        self.network_card = CardWidget(self)
        card_layout = QVBoxLayout(self.network_card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)
        
        # 说明文字
        desc = BodyLabel("如果 GitHub 登录速度较慢，可以尝试优化网络连接", self)
        desc.setWordWrap(True)
        card_layout.addWidget(desc)
        
        # hosts 状态显示
        self.hosts_status_label = CaptionLabel("", self)
        self.hosts_status_label.setStyleSheet("color: #888;")
        card_layout.addWidget(self.hosts_status_label)
        
        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        
        self.hosts_add_btn = PrimaryPushButton("优化 GitHub 连接", self)
        self.hosts_add_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_VistaShield))
        self.hosts_add_btn.clicked.connect(self._on_hosts_add_clicked)
        btn_row.addWidget(self.hosts_add_btn)
        
        self.hosts_remove_btn = PushButton("撤销更改", self)
        self.hosts_remove_btn.setIcon(FluentIcon.DELETE)
        self.hosts_remove_btn.clicked.connect(self._on_hosts_remove_clicked)
        btn_row.addWidget(self.hosts_remove_btn)
        
        btn_row.addStretch(1)
        card_layout.addLayout(btn_row)
        
        # 加载状态行（按钮下方）
        self.hosts_loading_row = QHBoxLayout()
        self.hosts_loading_row.setSpacing(8)
        
        self.hosts_spinner = IndeterminateProgressRing(self)
        self.hosts_spinner.setFixedSize(16, 16)
        self.hosts_spinner.setStrokeWidth(2)
        self.hosts_spinner.hide()
        self.hosts_loading_row.addWidget(self.hosts_spinner)
        
        self.hosts_loading_label = CaptionLabel("", self)
        self.hosts_loading_label.setStyleSheet("color: #888;")
        self.hosts_loading_label.hide()
        self.hosts_loading_row.addWidget(self.hosts_loading_label)
        
        self.hosts_loading_row.addStretch(1)
        card_layout.addLayout(self.hosts_loading_row)
        
        parent_layout.addWidget(self.network_card)
        
        # 更新 hosts 状态显示
        self._update_hosts_status()
    
    def _update_hosts_status(self):
        """更新 hosts 状态显示"""
        has_config, _ = check_hosts_status()
        if has_config:
            self.hosts_status_label.setText("已配置 GitHub hosts 加速")
            self.hosts_status_label.setStyleSheet("color: #4caf50;")
            self.hosts_add_btn.setText("更新配置")
        else:
            self.hosts_status_label.setText("未配置 hosts 加速")
            self.hosts_status_label.setStyleSheet("color: #888;")
            self.hosts_add_btn.setText("优化 GitHub 连接")
    
    def _show_hosts_loading(self, text: str):
        """显示 hosts 操作加载状态"""
        self.hosts_spinner.show()
        self.hosts_loading_label.setText(text)
        self.hosts_loading_label.show()
        self.hosts_add_btn.setEnabled(False)
        self.hosts_remove_btn.setEnabled(False)
    
    def _hide_hosts_loading(self):
        """隐藏 hosts 操作加载状态"""
        self.hosts_spinner.hide()
        self.hosts_loading_label.hide()
        self.hosts_add_btn.setEnabled(True)
        self.hosts_remove_btn.setEnabled(True)

    def _on_hosts_add_clicked(self):
        """优化 GitHub 连接按钮点击"""
        box = MessageBox(
            "优化 GitHub 连接",
            "此操作将修改系统 hosts 文件以加速 GitHub 访问。\n\n"
            "注意事项：\n"
            "1. 需要管理员权限，请在弹出的 UAC 窗口中点击「是」\n"
            "2. 如果杀毒软件弹出提示，请选择「允许」\n"
            "3. 本程序安全无病毒，仅添加 GitHub 相关的 IP 映射\n\n"
            "是否继续？",
            self.window() or self
        )
        box.yesButton.setText("继续")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        # 显示加载状态
        self._show_hosts_loading("正在获取最优 IP 并更新 hosts...")

        def do_operation():
            success, msg = run_hosts_operation_as_admin("add")
            # 在主线程更新 UI
            app = QApplication.instance()
            if app:
                app.postEvent(self, _HostsResultEvent(success, msg))

        Thread(target=do_operation, daemon=True).start()
    
    def _on_hosts_remove_clicked(self):
        """撤销 hosts 更改按钮点击"""
        has_config, _ = check_hosts_status()
        if not has_config:
            InfoBar.info("", "未找到本程序添加的 hosts 配置", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        box = MessageBox(
            "撤销 hosts 更改",
            "确定要移除本程序添加的 GitHub hosts 配置吗？\n\n"
            "移除后 GitHub 访问速度可能会变慢。",
            self.window() or self
        )
        box.yesButton.setText("确定移除")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        # 显示加载状态
        self._show_hosts_loading("正在移除 hosts 配置...")

        def do_operation():
            success, msg = run_hosts_operation_as_admin("remove")
            app = QApplication.instance()
            if app:
                app.postEvent(self, _HostsResultEvent(success, msg))

        Thread(target=do_operation, daemon=True).start()
    
    def customEvent(self, event):
        """处理自定义事件"""
        if isinstance(event, _HostsResultEvent):
            # 隐藏加载状态
            self._hide_hosts_loading()

            # 使用气泡提示显示结果
            if event.success:
                InfoBar.success("", event.message, parent=self, position=InfoBarPosition.TOP, duration=2500)
            else:
                InfoBar.error("", event.message, parent=self, position=InfoBarPosition.TOP, duration=3000)

            # 更新状态显示
            self._update_hosts_status()
        else:
            super().customEvent(event)
    
    def _build_issue_card(self, parent_layout: QVBoxLayout):
        """构建Issue提交卡片"""
        self.issue_title = SubtitleLabel("提交 Issue", self)
        parent_layout.addWidget(self.issue_title)
        
        self.issue_card = CardWidget(self)
        card_layout = QVBoxLayout(self.issue_card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)
        
        # Issue 类型
        card_layout.addWidget(BodyLabel("Issue 类型：", self))
        self.type_combo = ComboBox(self)
        for key, info in ISSUE_TYPES.items():
            self.type_combo.addItem(info["label"], key)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        card_layout.addWidget(self.type_combo)
        
        # 标题
        card_layout.addWidget(BodyLabel("标题：", self))
        self.title_edit = LineEdit(self)
        self.title_edit.setPlaceholderText("请输入 Issue 标题")
        card_layout.addWidget(self.title_edit)
        
        # 内容
        self.content_label = BodyLabel("内容（支持 Markdown）：", self)
        card_layout.addWidget(self.content_label)
        
        # 使用 QStackedWidget 切换编辑/预览
        self.content_stack = QStackedWidget(self)
        self.content_stack.setMinimumHeight(200)
        
        # 编辑区
        self.body_edit = QPlainTextEdit(self)
        self.body_edit.setPlaceholderText("请描述问题或建议...")
        self.content_stack.addWidget(self.body_edit)
        
        # 预览区
        self.preview_browser = QTextBrowser(self)
        self.preview_browser.setOpenExternalLinks(True)
        self.content_stack.addWidget(self.preview_browser)
        
        card_layout.addWidget(self.content_stack)
        
        self._is_preview_mode = False
        
        # 提示
        tip = CaptionLabel("提交后将在 GitHub 仓库创建一个新的 Issue", self)
        tip.setStyleSheet("color: #888;")
        card_layout.addWidget(tip)
        
        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.preview_btn = PushButton("预览", self)
        self.preview_btn.clicked.connect(self._preview_issue)
        self.submit_btn = PrimaryPushButton("提交", self)
        self.submit_btn.clicked.connect(self._submit_issue)
        self.submit_spinner = IndeterminateProgressRing(self)
        self.submit_spinner.setFixedSize(20, 20)
        self.submit_spinner.setStrokeWidth(3)
        self.submit_spinner.hide()
        btn_row.addWidget(self.preview_btn)
        btn_row.addWidget(self.submit_btn)
        btn_row.addWidget(self.submit_spinner)
        card_layout.addLayout(btn_row)
        
        parent_layout.addWidget(self.issue_card)
        
        # 初始化模板
        self._on_type_changed()
    
    def _update_ui_state(self):
        """更新UI状态"""
        auth = get_github_auth()
        is_logged_in = auth.is_logged_in
        
        self.logged_in_widget.setVisible(is_logged_in)
        self.not_logged_in_widget.setVisible(not is_logged_in)
        self.login_flow_widget.setVisible(False)
        
        if is_logged_in:
            username = auth.username or "User"
            self.user_label.setText(username)
            self.avatar.setText(username)
            # 加载头像
            if auth.avatar_url:
                self._load_avatar(auth.avatar_url)
            # 检查 star 状态
            self._check_star_status()
        
        # 更新Issue提交部分的可见性
        self.issue_title.setVisible(is_logged_in)
        self.issue_card.setVisible(is_logged_in)
    
    def _load_avatar(self, url: str):
        """异步加载头像"""
        self._avatar_worker = AvatarLoadWorker(url, self)
        self._avatar_worker.finished.connect(self._on_avatar_loaded)
        self._avatar_worker.start()
    
    def _on_avatar_loaded(self, data: bytes):
        """头像加载完成"""
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.avatar.setImage(pixmap.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    
    def _check_star_status(self):
        """异步检查 star 状态"""
        self.star_label.setText("检查 Star 状态...")
        self.star_label.setStyleSheet("color: #888;")
        self._star_check_worker = StarCheckWorker(self)
        self._star_check_worker.finished.connect(self._on_star_checked)
        self._star_check_worker.start()
    
    def _on_star_checked(self, has_starred: bool):
        """Star 状态检查完成"""
        self._has_starred = has_starred
        self._update_star_btn()
        if has_starred:
            self.star_label.setText("已 Star 本项目")
            self.star_label.setStyleSheet("color: #ffc107;")
        else:
            self.star_label.setText("还没有 Star 本项目哦~")
            self.star_label.setStyleSheet("color: #888;")
    
    def _update_star_btn(self):
        """更新 Star 按钮状态"""
        if self._has_starred:
            # 已 Star 时显示禁用的按钮
            self.star_btn_primary.hide()
            self.star_btn_normal.setEnabled(False)
            self.star_btn_normal.show()
        else:
            # 未 Star 时显示主题色的 Star 按钮
            self.star_btn_normal.hide()
            self.star_btn_primary.show()
    
    def _toggle_star(self):
        """切换 Star 状态"""
        self.star_btn_primary.setEnabled(False)
        self.star_btn_normal.setEnabled(False)
        self.star_spinner.show()
        self._star_action_worker = StarActionWorker(not self._has_starred, self)
        self._star_action_worker.finished.connect(self._on_star_action_finished)
        self._star_action_worker.start()
    
    def _on_star_action_finished(self, success: bool, is_starred_now: bool):
        """Star 操作完成"""
        self.star_spinner.hide()
        self.star_btn_primary.setEnabled(True)
        self._has_starred = is_starred_now
        self._update_star_btn()
        if success:
            self.star_label.setText("已 Star 本项目")
            self.star_label.setStyleSheet("color: #ffc107;")
            InfoBar.success("", "感谢你的 Star！", parent=self, position=InfoBarPosition.TOP, duration=2000)
        else:
            InfoBar.error("", "操作失败，请重试", parent=self, position=InfoBarPosition.TOP, duration=2000)
    
    def _copy_code(self):
        code = self.code_display.text()
        if code and code != "--------":
            QApplication.clipboard().setText(code)
            InfoBar.success("", "验证码已复制", parent=self.window(), position=InfoBarPosition.TOP, duration=1500)
    
    def _start_device_flow(self):
        """开始设备码登录流程"""
        self.not_logged_in_widget.setVisible(False)
        self.login_flow_widget.setVisible(True)
        self.code_display.setText("--------")
        self.copy_btn.setEnabled(False)
        self.spinner.show()
        self.status_label.setText("正在获取验证码...")
        self.status_label.setStyleSheet("color: #888;")
        
        self._device_code_worker = DeviceCodeWorker(self)
        self._device_code_worker.finished.connect(self._on_device_code_received)
        self._device_code_worker.error.connect(self._on_device_code_error)
        self._device_code_worker.start()
    
    def _on_device_code_received(self, info: dict):
        user_code = info.get("user_code", "")
        device_code = info.get("device_code", "")
        interval = info.get("interval", 5)
        expires_in = info.get("expires_in", 900)
        
        self.code_display.setText(user_code)
        self.copy_btn.setEnabled(True)
        self.status_label.setText("请在浏览器中输入验证码...")
        
        # 自动打开授权页面
        webbrowser.open(GITHUB_DEVICE_VERIFY_URL)
        
        self._token_poll_worker = TokenPollWorker(device_code, interval, expires_in, self)
        self._token_poll_worker.progress.connect(self._on_poll_progress)
        self._token_poll_worker.finished.connect(self._on_poll_finished)
        self._token_poll_worker.error.connect(self._on_poll_error)
        self._token_poll_worker.start()
    
    def _on_device_code_error(self, error: str):
        self.spinner.hide()
        self.status_label.setText(f"获取验证码失败: {error}")
        self.status_label.setStyleSheet("color: #d32f2f;")
    
    def _on_poll_progress(self, msg: str):
        self.status_label.setText(msg)
    
    def _on_poll_finished(self, success: bool):
        if success:
            self.spinner.hide()
            self.status_label.setText("登录成功！")
            self.status_label.setStyleSheet("color: #4caf50;")
            self.loginSuccess.emit()
            QTimer.singleShot(1000, self._update_ui_state)
        else:
            self.spinner.hide()
            self.status_label.setText("登录已取消")
            QTimer.singleShot(1000, self._update_ui_state)
    
    def _on_poll_error(self, error: str):
        self.spinner.hide()
        self.status_label.setText(f"登录失败: {error}")
        self.status_label.setStyleSheet("color: #d32f2f;")
    
    def _cancel_login(self):
        """取消登录"""
        self._stop_workers()
        self._update_ui_state()
    
    def _logout(self):
        """退出登录"""
        auth = get_github_auth()
        auth.logout()
        self._update_ui_state()
        self.loginSuccess.emit()
        InfoBar.success("", "已退出登录", parent=self, position=InfoBarPosition.TOP, duration=2000)
    
    def _on_type_changed(self):
        """Issue类型变更"""
        idx = self.type_combo.currentIndex()
        type_key = self.type_combo.itemData(idx) if idx >= 0 else None
        if type_key and type_key in ISSUE_TYPES:
            template = ISSUE_TYPES[type_key]["template"]
            template = template.format(
                description="",
                os=platform.system(),
                version=__VERSION__
            )
            self.body_edit.setPlainText(template)
    
    def _submit_issue(self):
        """提交Issue"""
        auth = get_github_auth()
        if not auth.is_logged_in or not auth.access_token:
            InfoBar.warning("", "请先登录 GitHub", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        
        title = self.title_edit.text().strip()
        body = self.body_edit.toPlainText().strip()
        
        if not title:
            InfoBar.warning("", "请输入 Issue 标题", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        
        if not body:
            InfoBar.warning("", "请输入 Issue 内容", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        
        # 提交前确认弹窗
        w = MessageBox("确认提交", f"确定要提交 Issue 吗？\n\n标题：{title}", self)
        if not w.exec():
            return
        
        idx = self.type_combo.currentIndex()
        type_key = str(self.type_combo.itemData(idx)) if idx >= 0 else "bug"
        labels = ISSUE_TYPES.get(type_key, {}).get("labels", [])
        access_token = auth.access_token
        
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("提交中...")
        self.submit_spinner.show()
        
        self._submit_worker = IssueSubmitWorker(access_token, title, body, labels, self)
        self._submit_worker.success.connect(self._on_submit_success)
        self._submit_worker.error.connect(self._on_submit_error)
        self._submit_worker.start()
    
    def _preview_issue(self):
        """切换编辑/预览模式"""
        if self._is_preview_mode:
            # 切换回编辑模式
            self.content_stack.setCurrentIndex(0)
            self.preview_btn.setText("预览")
            self.content_label.setText("内容（支持 Markdown）：")
            self._is_preview_mode = False
        else:
            # 切换到预览模式
            body = self.body_edit.toPlainText()
            html = self._markdown_to_html(body)
            
            # 添加基本样式
            styled_html = f"""
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #e0e0e0; }}
                code {{ background: rgba(128,128,128,0.3); padding: 2px 6px; border-radius: 3px; }}
                pre {{ background: rgba(128,128,128,0.2); padding: 12px; border-radius: 6px; overflow-x: auto; }}
                h1, h2, h3 {{ margin-top: 16px; margin-bottom: 8px; color: #fff; }}
                h1 {{ font-size: 24px; }}
                h2 {{ font-size: 20px; }}
                h3 {{ font-size: 16px; }}
            </style>
            {html}
            """
            self.preview_browser.setHtml(styled_html)
            self.content_stack.setCurrentIndex(1)
            self.preview_btn.setText("编辑")
            self.content_label.setText("内容预览：")
            self._is_preview_mode = True
    
    def _markdown_to_html(self, text: str) -> str:
        """简单的 Markdown 转 HTML"""
        import re
        lines = text.split('\n')
        html_lines = []
        in_code_block = False
        
        for line in lines:
            # 代码块
            if line.startswith('```'):
                if in_code_block:
                    html_lines.append('</pre>')
                    in_code_block = False
                else:
                    html_lines.append('<pre>')
                    in_code_block = True
                continue
            
            if in_code_block:
                html_lines.append(line)
                continue
            
            # 标题
            if line.startswith('### '):
                html_lines.append(f'<h3>{line[4:]}</h3>')
            elif line.startswith('## '):
                html_lines.append(f'<h2>{line[3:]}</h2>')
            elif line.startswith('# '):
                html_lines.append(f'<h1>{line[2:]}</h1>')
            # 列表
            elif line.startswith('- '):
                html_lines.append('<li>' + line[2:] + '</li>')
            elif re.match(r'^\d+\. ', line):
                content = re.sub(r'^\d+\. ', '', line)
                html_lines.append('<li>' + content + '</li>')
            # 空行
            elif line.strip() == '':
                html_lines.append('<br>')
            else:
                # 行内代码
                line = re.sub(r'`([^`]+)`', r'<code>\1</code>', line)
                # 粗体
                line = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', line)
                # 斜体
                line = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', line)
                html_lines.append(f'{line}<br>')
        
        if in_code_block:
            html_lines.append('</pre>')
        
        return '\n'.join(html_lines)
    
    def _on_submit_success(self, issue_url: str):
        self.submit_spinner.hide()
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("提交")
        
        # 显示气泡弹窗
        InfoBar.success("", "Issue 提交成功！", parent=self, position=InfoBarPosition.TOP, duration=2500)
        if issue_url:
            webbrowser.open(issue_url)
        
        # 清空表单
        self.title_edit.clear()
        self._on_type_changed()
    
    def _on_submit_error(self, error: str):
        self.submit_spinner.hide()
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("提交")
        InfoBar.error("", f"提交失败: {error}", parent=self, position=InfoBarPosition.TOP, duration=3000)
    
    def _stop_workers(self):
        if self._device_code_worker:
            self._device_code_worker.stop()
            if self._device_code_worker.isRunning():
                self._device_code_worker.wait(2000)
        if self._token_poll_worker:
            self._token_poll_worker.stop()
            if self._token_poll_worker.isRunning():
                self._token_poll_worker.wait(2000)
    
    def hideEvent(self, event):
        """页面隐藏时停止 workers"""
        self._stop_workers()
        super().hideEvent(event)


# 自定义事件类型
_HOSTS_RESULT_EVENT_TYPE = QEvent.Type(QEvent.registerEventType())


class _HostsResultEvent(QEvent):
    """hosts 操作结果事件"""
    def __init__(self, success: bool, message: str):
        super().__init__(_HOSTS_RESULT_EVENT_TYPE)
        self.success = success
        self.message = message

