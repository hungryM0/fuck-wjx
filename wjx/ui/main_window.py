"""主窗口模块 - 精简版，使用拆分后的组件"""
from __future__ import annotations
from wjx.utils.logging.log_utils import log_suppressed_exception


import copy
import logging
import os
import sys
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QTimer, QSettings, Signal, QCoreApplication, QEvent
from PySide6.QtGui import QColor, QIcon, QGuiApplication, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from qfluentwidgets import (
    Action,
    AvatarWidget,
    FluentIcon,
    FluentWindow,
    IndeterminateProgressRing,
    InfoBadge,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    NavigationAvatarWidget,
    NavigationItemPosition,
    ProgressBar,
    PushButton,
    RoundMenu,
    Theme,
    qconfig,
    setTheme,
    setThemeColor,
    MenuAnimationType,
)

# 导入拆分后的页面
from wjx.ui.pages.workbench.dashboard import DashboardPage
from wjx.ui.pages.workbench.runtime import RuntimePage
from wjx.ui.pages.workbench.result import ResultPage
from wjx.ui.pages.settings.settings import SettingsPage
from wjx.ui.pages.workbench.question import QuestionPage
from wjx.ui.pages.workbench.log import LogPage
from wjx.ui.pages.more.support import SupportPage
from wjx.ui.pages.more.about import AboutPage
from wjx.ui.pages.account.account import AccountPage
from wjx.ui.pages.more.changelog import ChangelogPage, ChangelogDetailPage
from wjx.ui.pages.more.donate import DonatePage
from wjx.ui.pages.more.qq_group import QQGroupPage

# 导入对话框
from wjx.ui.dialogs.card_unlock import CardUnlockDialog
from wjx.ui.dialogs.contact import ContactDialog

# 导入控制器和工具
from wjx.ui.controller import RunController
from wjx.utils.app.config import APP_ICON_RELATIVE_PATH, get_bool_from_qsettings
from wjx.utils.io.load_save import RuntimeConfig, get_runtime_directory
from wjx.utils.logging.log_utils import LOG_BUFFER_HANDLER, register_popup_handler
from wjx.utils.app.version import __VERSION__, ISSUE_FEEDBACK_URL
from wjx.network.random_ip import (
    get_status,
    _format_status_payload,
    refresh_ip_counter_display,
)
from wjx.utils.app.runtime_paths import _get_resource_path as get_resource_path

# 导入启动画面模块
from wjx.boot import create_boot_splash, finish_boot_splash

# 导入GitHub认证
from wjx.utils.integrations.github_auth import get_github_auth


class MainWindow(FluentWindow):
    """主窗口，PowerToys 风格导航 + 圆角布局，支持主题动态切换。"""

    # 更新通知信号（用于跨线程通信）


    updateAvailable = Signal()
    # 最新版本信号
    isLatestVersion = Signal()
    # 下载开始信号（显示转圈动画）
    downloadStarted = Signal()
    # 下载进度信号
    downloadProgress = Signal(int, int, float)  # downloaded, total, speed
    # 下载完成信号
    downloadFinished = Signal(str)  # downloaded_file_path
    # 下载失败信号
    downloadFailed = Signal(str)  # error_message
    # 镜像源切换信号
    mirrorSwitched = Signal(str)  # new_mirror_key

    def __init__(self, parent=None):
        self._boot_splash = None
        super().__init__(parent)
        qconfig.load(os.path.join(get_runtime_directory(), "wjx", "ui", "theme.json"))
        self._theme_sync_pending = False
        self._apply_theme_mode(qconfig.get(qconfig.themeMode))
        setThemeColor("#2563EB")
        qconfig.themeChanged.connect(self._on_theme_changed)
        self._skip_save_on_close = False
        
        self.setWindowTitle(f"问卷星速填 v{__VERSION__}")
        icon_path = get_resource_path(APP_ICON_RELATIVE_PATH)
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(1080, 720)
        self._enable_window_material_effect()

        # 应用窗口置顶设置
        settings = QSettings("FuckWjx", "Settings")
        if get_bool_from_qsettings(settings.value("window_topmost"), False):
            self.apply_topmost_state(True, show=False)

        # 创建启动页面
        self._boot_splash = create_boot_splash(self)

        self.controller = RunController(self)
        self.controller.on_ip_counter = None  # will be set after dashboard creation
        self.controller.card_code_provider = self._ask_card_code

        # 立即初始化关键页面
        self.runtime_page = RuntimePage(self.controller, self)
        self.question_page = QuestionPage(self)
        # QuestionPage 仅用作题目配置的数据载体，不作为主界面子页面展示；
        # 若不隐藏会以默认几何 (0,0,100,30) 叠在窗口左上角，造成标题栏错乱。
        self.question_page.hide()
        self.dashboard = DashboardPage(self.controller, self.question_page, self.runtime_page, self)

        # 延迟初始化非关键页面（懒加载）
        self._result_page = None
        self._log_page = None
        self._support_page = None
        self._qq_group_page = None
        self._about_page = None
        self._changelog_page = None
        self._changelog_detail_page = None
        self._donate_page = None
        self._login_page = None
        self._settings_page = None

        # 设置对象名称
        self.dashboard.setObjectName("dashboard")
        self.question_page.setObjectName("question")
        self.runtime_page.setObjectName("runtime")

        self._init_navigation()
        self._init_changelog_navigation()

        self._init_github_avatar()
        # 设置侧边栏宽度和折叠策略（延迟到事件循环中，避免时序问题）
        self.navigationInterface.setExpandWidth(140)
        QTimer.singleShot(0, self._setup_sidebar_state)
        self._sidebar_expanded = False  # 标记侧边栏是否已展开
        self._bind_controller_signals()
        # 确保初始 adapter 也能回调随机 IP 计数
        self.controller.adapter.update_random_ip_counter = self.dashboard.update_random_ip_counter
        self._register_popups()
        self._load_saved_config()
        self._center_on_screen()

        finish_boot_splash(1500)

        # 连接更新通知信号
        self.updateAvailable.connect(self._do_show_update_notification)
        self.updateAvailable.connect(self._show_outdated_badge)
        # 连接最新版本信号
        self.isLatestVersion.connect(self._show_latest_version_badge)
        # 连接下载开始信号（显示转圈动画）
        self.downloadStarted.connect(self._on_download_started)
        # 连接下载进度信号
        self.downloadProgress.connect(self._update_download_progress)
        # 连接下载完成/失败信号
        self.downloadFinished.connect(self._on_download_finished)
        self.downloadFailed.connect(self._on_download_failed)
        # 连接镜像源切换信号
        self.mirrorSwitched.connect(self._on_mirror_switched)
        self._latest_badge = None
        self._outdated_badge = None
        self._preview_badge = None
        self._download_infobar = None
        self._download_progress_bar = None
        self._download_cancelled = False

        # 检查是否为预览版本，如果是则显示预览徽章
        self._check_preview_version()

        # 根据设置检查更新
        self._check_update_on_startup()

    def _apply_theme_mode(self, theme_mode: Theme):
        """按指定主题模式应用样式（不覆盖用户配置文件）。"""
        try:
            setTheme(theme_mode, save=False, lazy=False)
        except Exception:
            logging.debug("应用主题模式失败", exc_info=True)

    def _enable_window_material_effect(self):
        """启用窗口材质效果（Windows 下优先使用 Mica）。"""
        if not sys.platform.startswith("win"):
            return
        if not hasattr(self, "setMicaEffectEnabled"):
            return
        try:
            self.setMicaEffectEnabled(True)
        except Exception:
            logging.debug("启用窗口材质效果失败", exc_info=True)

    def _on_theme_changed(self, _theme: Theme):
        """主题变化后刷新主题敏感组件。"""
        self._enable_window_material_effect()
        try:
            drawer = getattr(getattr(self, "dashboard", None), "config_drawer", None)
            if drawer and hasattr(drawer, "_apply_theme"):
                drawer._apply_theme()
        except Exception:
            logging.debug("主题变更后刷新组件失败", exc_info=True)

    def changeEvent(self, event):
        """系统主题/调色板变化时，在 AUTO 模式下重同步主题。"""
        super().changeEvent(event)
        watched_events = {
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.PaletteChange,
        }
        if hasattr(QEvent.Type, "ThemeChange"):
            watched_events.add(QEvent.Type.ThemeChange)
        if event.type() in watched_events:
            self._schedule_auto_theme_sync()

    def _schedule_auto_theme_sync(self):
        if self._theme_sync_pending:
            return
        self._theme_sync_pending = True
        QTimer.singleShot(0, self._sync_auto_theme_if_needed)

    def _sync_auto_theme_if_needed(self):
        self._theme_sync_pending = False
        try:
            theme_mode = qconfig.get(qconfig.themeMode)
        except Exception:
            theme_mode = Theme.AUTO
        if theme_mode != Theme.AUTO:
            return
        # setTheme(AUTO) 在 themeMode 已经是 AUTO 时会被 qconfig.set 短路，
        # 导致内部 theme 属性不会被重新检测。这里手动强制刷新。
        from qfluentwidgets.common.style_sheet import updateStyleSheet
        old_theme = qconfig.theme
        qconfig.theme = Theme.AUTO          # 触发 darkdetect 重新检测
        if qconfig.theme != old_theme:
            updateStyleSheet()
            qconfig.themeChangedFinished.emit()
            qconfig._cfg.themeChanged.emit(Theme.AUTO)

    def resizeEvent(self, e):
        """调整启动页面组件位置"""
        super().resizeEvent(e)
        if self._boot_splash:
            self._boot_splash.update_layout(self.width(), self.height())

    def _setup_sidebar_state(self):
        """设置侧边栏折叠状态（在事件循环中调用以避免时序问题）"""
        try:
            settings = QSettings("FuckWjx", "Settings")
            always_expand = get_bool_from_qsettings(settings.value("sidebar_always_expand"), True)
            self.navigationInterface.setCollapsible(not always_expand)
            if always_expand:
                self.navigationInterface.expand(useAni=False)
        except Exception:
            logging.debug("设置侧边栏状态失败", exc_info=True)

    def showEvent(self, e):
        """窗口显示时展开侧边栏"""
        super().showEvent(e)
        if self._sidebar_expanded:
            return
        self._sidebar_expanded = True
        settings = QSettings("FuckWjx", "Settings")
        always_expand = get_bool_from_qsettings(settings.value("sidebar_always_expand"), True)
        if not always_expand:
            return
        try:
            self.navigationInterface.expand(useAni=False)
        except Exception:
            logging.debug("showEvent 展开侧边栏失败", exc_info=True)

    def closeEvent(self, e):
        """窗口关闭时询问用户是否保存配置"""
        # 先停止所有定时器和网络请求，防止在关闭过程中触发回调
        try:
            # 断开网络管理器的所有信号连接，避免回调对象析构警告
            if hasattr(self, '_network_manager') and self._network_manager:
                try:
                    self._network_manager.blockSignals(True)
                except Exception as exc:
                    log_suppressed_exception("closeEvent: self._network_manager.blockSignals(True)", exc)
            
            # 停止日志页面定时器
            if self._log_page and hasattr(self._log_page, '_refresh_timer'):
                self._log_page._refresh_timer.stop()
            
            # 停止联系表单轮询
            if self._support_page and hasattr(self._support_page, 'contact_form'):
                try:
                    self._support_page.contact_form.stop_status_polling()
                except Exception as exc:
                    log_suppressed_exception("closeEvent: self._support_page.contact_form.stop_status_polling()", exc)
        except Exception as exc:
            log_suppressed_exception("closeEvent: 清理资源时出错", exc)
        
        if not self._skip_save_on_close:
            settings = QSettings("FuckWjx", "Settings")
            ask_save = get_bool_from_qsettings(settings.value("ask_save_on_close"), True)
            if ask_save:
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
                        
                        default_path = configs_dir
                        
                        path, _ = QFileDialog.getSaveFileName(
                            self,
                            "保存配置",
                            default_path,
                            "JSON 文件 (*.json);;所有文件 (*.*)"
                        )
                        
                        if path:
                            from wjx.utils.io.load_save import save_config
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
        self.addSubInterface(self.runtime_page, FluentIcon.DEVELOPER_TOOLS, "运行参数", NavigationItemPosition.TOP)
        self.addSubInterface(self._get_result_page(), FluentIcon.PIE_SINGLE, "结果分析", NavigationItemPosition.TOP)
        self.addSubInterface(self._get_log_page(), FluentIcon.INFO, "日志", NavigationItemPosition.TOP)
        # 登录页面（动态更新）
        self._login_nav_widget = None
        self._network_manager = QNetworkAccessManager(self)
        self._add_login_navigation(is_init=True)
        # 设置页面
        self.addSubInterface(self._get_settings_page(), FluentIcon.SETTING, "设置", NavigationItemPosition.BOTTOM)
        # "更多"弹出式子菜单
        self.navigationInterface.addItem(
            routeKey="about_menu",
            icon=FluentIcon.MORE,
            text="更多",
            onClick=self._show_about_menu,
            selectable=False,
            position=NavigationItemPosition.BOTTOM
        )
        # 将 support_page、about_page、changelog_page 添加到 stackedWidget 但不显示在导航栏
        # 这些页面会在首次访问时懒加载
        self.navigationInterface.setCurrentItem(self.dashboard.objectName())

    def _get_result_page(self):
        """懒加载结果页面"""
        if self._result_page is None:
            from wjx.ui.pages.workbench.result import ResultPage
            self._result_page = ResultPage(self)
            self._result_page.setObjectName("result")
        return self._result_page

    def _get_log_page(self):
        """懒加载日志页面"""
        if self._log_page is None:
            from wjx.ui.pages.workbench.log import LogPage
            self._log_page = LogPage(self)
            self._log_page.setObjectName("logs")
        return self._log_page

    def _get_settings_page(self):
        """懒加载设置页面"""
        if self._settings_page is None:
            from wjx.ui.pages.settings.settings import SettingsPage
            self._settings_page = SettingsPage(self)
            self._settings_page.setObjectName("settings")
        return self._settings_page

    def _get_login_page(self):
        """懒加载登录页面"""
        if self._login_page is None:
            from wjx.ui.pages.account.account import AccountPage
            self._login_page = AccountPage(self)
            self._login_page.loginSuccess.connect(self._update_github_avatar)
            self._login_page.setObjectName("login")
            if self.stackedWidget.indexOf(self._login_page) == -1:
                self.stackedWidget.addWidget(self._login_page)
        return self._login_page

    def _get_support_page(self):
        """懒加载支持页面"""
        if self._support_page is None:
            from wjx.ui.pages.more.support import SupportPage
            self._support_page = SupportPage(self)
            self._support_page.setObjectName("support")
            if self.stackedWidget.indexOf(self._support_page) == -1:
                self.stackedWidget.addWidget(self._support_page)
        return self._support_page

    def _get_qq_group_page(self):
        """懒加载QQ群页面"""
        if self._qq_group_page is None:
            from wjx.ui.pages.more.qq_group import QQGroupPage
            self._qq_group_page = QQGroupPage(self)
            self._qq_group_page.setObjectName("qq_group")
            if self.stackedWidget.indexOf(self._qq_group_page) == -1:
                self.stackedWidget.addWidget(self._qq_group_page)
        return self._qq_group_page

    def _get_about_page(self):
        """懒加载关于页面"""
        if self._about_page is None:
            from wjx.ui.pages.more.about import AboutPage
            self._about_page = AboutPage(self)
            self._about_page.setObjectName("about")
            if self.stackedWidget.indexOf(self._about_page) == -1:
                self.stackedWidget.addWidget(self._about_page)
        return self._about_page

    def _get_changelog_page(self):
        """懒加载更新日志页面"""
        if self._changelog_page is None:
            from wjx.ui.pages.more.changelog import ChangelogPage
            self._changelog_page = ChangelogPage(self)
            self._changelog_page.setObjectName("changelog")
            if self.stackedWidget.indexOf(self._changelog_page) == -1:
                self.stackedWidget.addWidget(self._changelog_page)
        return self._changelog_page

    def _get_changelog_detail_page(self):
        """懒加载更新日志详情页面"""
        if self._changelog_detail_page is None:
            from wjx.ui.pages.more.changelog import ChangelogDetailPage
            self._changelog_detail_page = ChangelogDetailPage(self)
            self._changelog_detail_page.setObjectName("changelog_detail")
            if self.stackedWidget.indexOf(self._changelog_detail_page) == -1:
                self.stackedWidget.addWidget(self._changelog_detail_page)
        return self._changelog_detail_page

    def _get_donate_page(self):
        """懒加载捐助页面"""
        if self._donate_page is None:
            from wjx.ui.pages.more.donate import DonatePage
            self._donate_page = DonatePage(self)
            self._donate_page.setObjectName("donate")
            if self.stackedWidget.indexOf(self._donate_page) == -1:
                self.stackedWidget.addWidget(self._donate_page)
        return self._donate_page

    def _init_changelog_navigation(self):
        """初始化更新日志页面导航"""
        changelog_page = self._get_changelog_page()
        changelog_detail_page = self._get_changelog_detail_page()

        # 连接信号：点击列表项时切换到详情页
        changelog_page.detailRequested.connect(self._show_changelog_detail)
        # 连接信号：点击返回按钮时切换回列表页
        changelog_detail_page.backRequested.connect(lambda: self.switchTo(changelog_page))

    def _show_changelog_detail(self, release: dict):
        """显示更新日志详情"""
        changelog_detail_page = self._get_changelog_detail_page()
        changelog_detail_page.setRelease(release)
        self.switchTo(changelog_detail_page)

    def _show_about_menu(self):
        """显示关于子菜单"""
        from wjx.utils.app.version import __VERSION__

        menu = RoundMenu(parent=self)

        # 版本信息（不可点击）
        version_action = Action(FluentIcon.INFO, f"问卷星速填 v{__VERSION__}")
        version_action.setEnabled(False)
        menu.addAction(version_action)

        menu.addSeparator()

        # 更新日志
        changelog_action = Action(FluentIcon.HISTORY, "更新日志")
        changelog_action.triggered.connect(lambda: self.switchTo(self._get_changelog_page()))
        menu.addAction(changelog_action)

        # QQ群
        qq_group_action = Action(FluentIcon.CHAT, "QQ群")
        qq_group_action.triggered.connect(lambda: self.switchTo(self._get_qq_group_page()))
        menu.addAction(qq_group_action)

        # 客服与支持
        support_action = Action(FluentIcon.HELP, "客服与支持")
        support_action.triggered.connect(lambda: self.switchTo(self._get_support_page()))
        menu.addAction(support_action)

        # 捐助
        donate_action = Action(FluentIcon.HEART, "捐助")
        donate_action.triggered.connect(lambda: self.switchTo(self._get_donate_page()))
        menu.addAction(donate_action)

        # 关于
        about_action = Action(FluentIcon.INFO, "关于")
        about_action.triggered.connect(lambda: self.switchTo(self._get_about_page()))
        menu.addAction(about_action)

        menu.addSeparator()

        # 退出
        quit_action = Action(FluentIcon.CLOSE, "退出程序")
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

        # 获取导航项的位置并显示菜单
        nav_item = self.navigationInterface.widget("about_menu")
        if nav_item:
            pos = nav_item.mapToGlobal(nav_item.rect().topRight())
            menu.exec(pos, aniType=MenuAnimationType.DROP_DOWN)

    def _add_login_navigation(self, is_init: bool = False):
        """添加登录导航项（根据登录状态显示不同内容）"""
        auth = get_github_auth()

        # 移除旧的导航项（无论是 widget 还是普通 item）
        try:
            self.navigationInterface.removeWidget("login")
        except Exception:
            logging.debug("移除登录导航项失败", exc_info=True)

        # 如果不是初始化，需要先移除设置和更多菜单，然后按顺序重新添加
        if not is_init:
            try:
                self.navigationInterface.removeWidget("settings")
            except Exception:
                logging.debug("移除设置导航项失败", exc_info=True)
            try:
                self.navigationInterface.removeWidget("about_menu")
            except Exception:
                logging.debug("移除更多菜单导航项失败", exc_info=True)

        # 懒加载登录页面
        login_page = self._get_login_page()

        if auth.is_logged_in and auth.user_info:
            # 已登录：显示头像和用户名
            avatar_url = auth.user_info.get("avatar_url", "")
            username = auth.username or "用户"

            self._login_nav_widget = NavigationAvatarWidget(username, avatar_url, self)
            self.navigationInterface.addWidget(
                "login",
                self._login_nav_widget,
                lambda: self.switchTo(login_page),
                NavigationItemPosition.BOTTOM
            )

            # 异步加载头像
            if avatar_url:
                self._load_avatar(avatar_url)
        else:
            # 未登录：显示登录按钮
            self.navigationInterface.addItem(
                routeKey="login",
                icon=FluentIcon.GITHUB,
                text="登录",
                onClick=lambda: self.switchTo(login_page),
                position=NavigationItemPosition.BOTTOM
            )
            self._login_nav_widget = None

        # 如果不是初始化，重新添加设置和更多菜单
        if not is_init:
            settings_page = self._get_settings_page()
            # 重新添加设置导航项
            self.navigationInterface.addItem(
                routeKey="settings",
                icon=FluentIcon.SETTING,
                text="设置",
                onClick=lambda: self.switchTo(settings_page),
                position=NavigationItemPosition.BOTTOM
            )
            # 重新添加更多菜单
            self.navigationInterface.addItem(
                routeKey="about_menu",
                icon=FluentIcon.MORE,
                text="更多",
                onClick=self._show_about_menu,
                selectable=False,
                position=NavigationItemPosition.BOTTOM
            )

    def _load_avatar(self, url: str):
        """异步加载头像"""
        from PySide6.QtCore import QUrl
        request = QNetworkRequest(QUrl(url))
        reply = self._network_manager.get(request)
        # 使用直接方法引用而不是lambda，避免回调析构警告
        reply.finished.connect(lambda r=reply: self._on_avatar_loaded(r))


    def _on_avatar_loaded(self, reply: QNetworkReply):
        """头像加载完成"""
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            pixmap.loadFromData(data.data())
            if not pixmap.isNull() and self._login_nav_widget:
                self._login_nav_widget.avatar.setPixmap(pixmap)
        reply.deleteLater()

    def _init_github_avatar(self):
        """初始化GitHub认证"""
        self._github_auth = get_github_auth()

    def _update_github_avatar(self):
        """更新登录页面状态和侧边栏导航项"""
        account_page = self._get_login_page()
        if account_page:
            account_page._update_ui_state()
        self._add_login_navigation(is_init=False)

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
            logging.debug("窗口居中失败", exc_info=True)

    def apply_topmost_state(self, checked: bool, show: bool = False):
        """应用窗口置顶状态，并刷新无边框特效以保留圆角。"""
        flags = self.windowFlags()
        already_checked = bool(flags & Qt.WindowType.WindowStaysOnTopHint)
        if already_checked == checked:
            return
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if hasattr(self, "updateFrameless"):
            try:
                self.updateFrameless()
            except Exception:
                logging.debug("刷新无边框窗口状态失败", exc_info=True)
        self._enable_window_material_effect()
        if show:
            self.show()

    def _bind_controller_signals(self):
        self.controller.surveyParsed.connect(self._on_survey_parsed)
        self.controller.surveyParseFailed.connect(self._on_survey_parse_failed)
        self.controller.runFailed.connect(lambda msg: self._toast(msg, "error"))
        self.controller.runStateChanged.connect(self.dashboard.on_run_state_changed)
        self.controller.statusUpdated.connect(self.dashboard.update_status)
        self.controller.pauseStateChanged.connect(self.dashboard.on_pause_state_changed)
        self.controller.cleanupFinished.connect(self.dashboard.on_cleanup_finished)
        self.controller.askSaveStats.connect(self._on_ask_save_stats)  # 新增：询问保存统计
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
        cfg = RuntimeConfig()
        self.runtime_page.apply_config(cfg)
        self.dashboard.apply_config(cfg)
        self.question_page.set_entries(cfg.question_entries or [], self.controller.questions_info)
        # 后台异步刷新随机 IP 计数，避免阻塞启动
        threading.Thread(
            target=lambda: refresh_ip_counter_display(self.controller.adapter),
            daemon=True
        ).start()

    # ---------- controller callbacks ----------
    def _on_survey_parsed(self, info: List[Dict[str, Any]], title: str):
        parsed_title = title or "问卷"
        if getattr(self.dashboard, "_open_wizard_after_parse", False):
            self.dashboard._open_wizard_after_parse = False
            pending_entries = copy.deepcopy(self.controller.question_entries)
            accepted = self.dashboard._run_question_wizard(pending_entries, info)
            if accepted:
                self.question_page.set_questions(info, pending_entries)
                self.controller.question_entries = pending_entries
                self.dashboard.update_question_meta(parsed_title, len(pending_entries))
                self._toast("解析完成，可在'题目配置'页查看", "success")
            else:
                current_entries = self.question_page.get_entries()
                self.dashboard.update_question_meta(parsed_title, len(current_entries))
                self._toast("已取消自动配置，保留原有题目设置", "warning")
            return
        self.question_page.set_questions(info, self.controller.question_entries)
        self.dashboard.update_question_meta(parsed_title, len(self.controller.question_entries))
        self._toast("解析完成，可在'题目配置'页查看", "success")

    def _on_survey_parse_failed(self, msg: str):
        self._toast(msg, "error")
        self.dashboard._open_wizard_after_parse = False

    def _on_ask_save_stats(self):
        """用户手动停止时询问是否保存统计数据"""
        box = MessageBox("保存统计数据", "是否保存本次作答的统计数据？", self)
        box.yesButton.setText("保存")
        box.cancelButton.setText("不保存")
        if box.exec() == QDialog.DialogCode.Accepted:
            try:
                path = self.controller.save_stats_with_prompt()
                if path:
                    self._toast(f"统计数据已保存", "success")
                else:
                    self._toast("没有统计数据可保存", "info")
            except Exception as exc:
                self._toast(f"保存失败：{exc}", "error")

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
        # 若未启动 Qt 事件循环，直接执行以避免死锁
        if QCoreApplication.instance() is None:
            return func()
        done = threading.Event()
        result: Dict[str, Any] = {}

        def _wrapper():
            try:
                result["value"] = func()
            finally:
                done.set()

        # 使用 QTimer.singleShot 在主线程中执行回调
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _wrapper)
        
        if not done.wait(timeout=5):
            import logging
            logging.warning("UI 调度超时，放弃执行回调以避免阻塞")
            return None
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
        """显示确认对话框，返回用户是否确认（线程安全）。"""
        def _show():
            box = MessageBox(title, message, self)
            box.yesButton.setText("确定")
            box.cancelButton.setText("取消")
            return bool(box.exec())
        return bool(self._dispatch_to_ui(_show))

    def _log_popup_message(self, title: str, message: str):
        """显示消息对话框（线程安全）。"""
        def _show():
            box = MessageBox(title, message, self)
            box.yesButton.setText("确定")
            box.cancelButton.hide()
            box.exec()
        self._dispatch_to_ui(_show)

    # 保留别名以兼容现有调用
    def _log_popup_info(self, title: str, message: str):
        self._log_popup_message(title, message)

    def _log_popup_error(self, title: str, message: str):
        self._log_popup_message(title, message)

    def _check_update_on_startup(self):
        """根据设置在启动时检查更新（后台异步执行）"""
        settings = QSettings("FuckWjx", "Settings")
        if get_bool_from_qsettings(settings.value("auto_check_update"), True):
            from wjx.ui.workers.update_worker import UpdateCheckWorker

            # 创建后台Worker
            self._update_worker = UpdateCheckWorker(self)
            self._update_worker.update_checked.connect(self._on_update_checked)
            self._update_worker.check_failed.connect(self._on_update_check_failed)
            self._update_worker.start()

            logging.debug("已启动后台更新检查")

    def _on_update_checked(self, has_update: bool, update_info: dict):
        """更新检查完成的回调"""
        if has_update:
            self.update_info = update_info
            self._show_update_notification()
        else:
            self._show_latest_version_badge()

    def _on_update_check_failed(self, error_message: str):
        """更新检查失败的回调"""
        logging.debug(f"更新检查失败: {error_message}")
        # 失败时不显示任何通知，静默处理

    def _show_update_notification(self):
        """显示更新通知（从后台线程安全调用）"""
        self.updateAvailable.emit()

    def _do_show_update_notification(self):
        """实际显示更新通知（使用简单纯文本样式）"""
        if not getattr(self, "update_info", None):
            return
        from wjx.utils.update.updater import show_update_notification
        show_update_notification(self)

    def _show_latest_version_badge(self):
        """在标题栏显示最新版本徽章"""
        # 如果是预览版本，不显示"最新"徽章（预览版本优先显示"预览"）
        if self._preview_badge:
            return
        if self._latest_badge:
            return
        try:
            # 在标题栏添加彩色徽章（绿色）
            self._latest_badge = InfoBadge.custom(
                "最新",
                QColor("#10b981"),  # 浅色主题背景
                QColor("#34d399"),  # 深色主题背景（更亮的绿色）
                parent=self.titleBar
            )
            # 将徽章添加到标题栏布局
            self.titleBar.hBoxLayout.insertWidget(2, self._latest_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            logging.debug("显示最新版徽章失败", exc_info=True)

    def _show_outdated_badge(self):
        """在标题栏显示过时版本徽章（红色）"""
        if self._outdated_badge:
            return
        # 如果有预览徽章，先移除它（过时优先级更高）
        if self._preview_badge:
            try:
                self.titleBar.hBoxLayout.removeWidget(self._preview_badge)
                self._preview_badge.deleteLater()
                self._preview_badge = None
            except Exception:
                logging.debug("清理预览版徽章失败", exc_info=True)
        try:
            # 在标题栏添加红色徽章
            self._outdated_badge = InfoBadge.custom(
                "过时",
                QColor("#ef4444"),  # 浅色主题背景（红色）
                QColor("#fd3c3c"),  # 深色主题背景（更亮的红色）
                parent=self.titleBar
            )
            # 将徽章添加到标题栏布局
            self.titleBar.hBoxLayout.insertWidget(2, self._outdated_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            logging.debug("显示可更新徽章失败", exc_info=True)

    def _check_preview_version(self):
        """检查是否为预览版本，如果是则显示预览徽章"""
        if "pre" in __VERSION__.lower():
            self._show_preview_badge()

    def _show_preview_badge(self):
        """在标题栏显示预览版本徽章（黄色）"""
        if self._preview_badge:
            return
        try:
            # 在标题栏添加黄色徽章
            self._preview_badge = InfoBadge.custom(
                "预览",
                QColor("#f59e0b"),  # 浅色主题背景（黄色）
                QColor("#fbbf24"),  # 深色主题背景（更亮的黄色）
                parent=self.titleBar
            )
            # 将徽章添加到标题栏布局
            self.titleBar.hBoxLayout.insertWidget(2, self._preview_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            logging.debug("显示预览版徽章失败", exc_info=True)

    def _notify_latest_version(self):
        """通知已是最新版本（从后台线程安全调用）"""
        self.isLatestVersion.emit()

    def _show_download_toast(self, total_size: int = 0, show_spinner: bool = False):
        """显示下载进度Toast（右下角）"""
        if self._download_infobar:
            return
        from qfluentwidgets import InfoBarIcon, CaptionLabel, IndeterminateProgressBar
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        
        self._download_indeterminate = show_spinner or total_size == 0
        
        # 创建右下角InfoBar（使用蓝色主题色）
        self._download_infobar = InfoBar(
            icon=InfoBarIcon.INFORMATION,
            title="",
            content="正在下载文件中，请稍候...",
            orient=Qt.Orientation.Vertical,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=-1,
            parent=self
        )
        self._download_infobar.closeButton.clicked.connect(self._cancel_download)
        
        # 创建容器
        self._download_container = QWidget()
        self._download_layout = QVBoxLayout(self._download_container)
        self._download_layout.setContentsMargins(0, 4, 0, 0)
        self._download_layout.setSpacing(4)
        
        # 进度详情标签
        self._download_detail_label = CaptionLabel("正在连接服务器...")
        self._download_detail_label.setStyleSheet("color: gray;")
        self._download_layout.addWidget(self._download_detail_label)
        
        if self._download_indeterminate:
            # 不确定进度条（加载动画）
            self._download_indeterminate_bar = IndeterminateProgressBar()
            self._download_indeterminate_bar.setFixedSize(220, 4)
            self._download_layout.addWidget(self._download_indeterminate_bar)
            self._download_progress_bar = None
        else:
            # 确定进度条
            self._download_indeterminate_bar = None
            self._download_progress_bar = ProgressBar()
            self._download_progress_bar.setFixedSize(220, 4)
            self._download_progress_bar.setRange(0, 100)
            self._download_progress_bar.setValue(0)
            self._download_progress_bar.setTextVisible(False)
            self._download_layout.addWidget(self._download_progress_bar)
        
        self._download_infobar.addWidget(self._download_container)
        self._download_infobar.show()

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"

    def _format_speed(self, speed: float) -> str:
        """格式化下载速度"""
        if speed < 1024:
            return f"{speed:.0f} B/s"
        elif speed < 1024 * 1024:
            return f"{speed / 1024:.1f} KB/s"
        else:
            return f"{speed / (1024 * 1024):.1f} MB/s"

    def _update_download_progress(self, downloaded: int, total: int, speed: float = 0):
        """更新下载进度"""
        if not self._download_infobar:
            self._show_download_toast(total)
        
        # 如果当前是不确定进度条，切换到确定进度条
        if total > 0 and getattr(self, "_download_indeterminate", False):
            self._switch_to_determinate_progress()
        
        if total > 0 and self._download_progress_bar:
            percent = int((downloaded / total) * 100)
            self._download_progress_bar.setValue(percent)
        
        # 更新详情标签
        if hasattr(self, "_download_detail_label") and self._download_detail_label:
            detail = f"{self._format_size(downloaded)} / {self._format_size(total)}"
            if speed > 0:
                detail += f" | {self._format_speed(speed)}"
            self._download_detail_label.setText(detail)
        
        # 下载完成时延迟关闭Toast并显示成功提示
        if downloaded >= total and total > 0:
            QTimer.singleShot(100, self._on_download_complete)

    def _on_download_complete(self):
        """下载完成时关闭进度Toast并显示成功提示"""
        self._close_download_toast()
        self._toast("下载完成", "success")

    def _switch_to_determinate_progress(self):
        """从不确定进度条切换到确定进度条"""
        self._download_indeterminate = False
        
        # 移除不确定进度条
        if hasattr(self, "_download_indeterminate_bar") and self._download_indeterminate_bar:
            self._download_layout.removeWidget(self._download_indeterminate_bar)
            self._download_indeterminate_bar.deleteLater()
            self._download_indeterminate_bar = None
        
        # 添加确定进度条
        self._download_progress_bar = ProgressBar()
        self._download_progress_bar.setFixedSize(220, 4)
        self._download_progress_bar.setRange(0, 100)
        self._download_progress_bar.setValue(0)
        self._download_progress_bar.setTextVisible(False)
        self._download_layout.addWidget(self._download_progress_bar)

    def _on_download_started(self):
        """下载开始时显示转圈动画"""
        self._show_download_toast(0, show_spinner=True)

    def _cancel_download(self):
        """取消下载"""
        self._download_cancelled = True
        self._close_download_toast()
        self._toast("下载已取消", "warning")

    def _close_download_toast(self):
        """安全关闭下载进度Toast"""
        if self._download_infobar:
            try:
                self._download_infobar.close()
            except Exception:
                logging.debug("关闭下载进度提示失败", exc_info=True)
            self._download_infobar = None
            self._download_progress_bar = None
            self._download_detail_label = None
            self._download_indeterminate_bar = None
            self._download_indeterminate = False

    def _emit_download_progress(self, downloaded: int, total: int, speed: float = 0):
        """从后台线程安全地发送下载进度信号"""
        self.downloadProgress.emit(downloaded, total, speed)

    def _on_download_finished(self, downloaded_file: str):
        """下载完成后在主线程显示弹窗"""
        import subprocess
        import logging
        from wjx.utils.update.updater import UpdateManager
        
        should_launch = self._log_popup_confirm(
            "更新完成",
            f"新版本已下载到:\n{downloaded_file}\n\n是否立即运行新版本？",
        )
        UpdateManager.schedule_running_executable_deletion(downloaded_file)
        if should_launch:
            try:
                subprocess.Popen([downloaded_file])
                self._skip_save_on_close = True
                self.close()
            except Exception as exc:
                logging.error("[Action Log] Failed to launch downloaded update")
                self._log_popup_error("启动失败", f"无法启动新版本: {exc}")
        else:
            logging.debug("[Action Log] Deferred launching downloaded update")

    def _on_download_failed(self, error_msg: str):
        """下载失败后在主线程显示弹窗"""
        if not getattr(self, "_download_cancelled", False):
            self._log_popup_error("更新失败", error_msg)

    def _on_mirror_switched(self, new_mirror_key: str):
        """镜像源切换时更新设置页面的下拉框"""
        from wjx.utils.app.config import GITHUB_MIRROR_SOURCES
        try:
            # 更新设置页面的下拉框
            if hasattr(self, "_settings_page") and self._settings_page and hasattr(self._settings_page, "mirror_combo"):
                idx = self._settings_page.mirror_combo.findData(new_mirror_key)
                if idx >= 0:
                    self._settings_page.mirror_combo.blockSignals(True)
                    self._settings_page.mirror_combo.setCurrentIndex(idx)
                    self._settings_page.mirror_combo.blockSignals(False)
            # 显示提示
            mirror_label = GITHUB_MIRROR_SOURCES.get(new_mirror_key, {}).get("label", new_mirror_key)
            self._toast(f"已自动切换到镜像源: {mirror_label}", "info")
        except Exception:
            logging.warning("切换镜像源后同步 UI 状态失败", exc_info=True)


def create_window() -> MainWindow:
    """供入口调用的工厂函数。"""
    return MainWindow()
