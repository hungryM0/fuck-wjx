"""MainWindow 懒加载页面与导航相关方法。"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from qfluentwidgets import (
    Action,
    FluentIcon,
    MenuAnimationType,
    NavigationAvatarWidget,
    NavigationItemPosition,
    RoundMenu,
)

from wjx.utils.integrations.github_auth import get_github_auth

if TYPE_CHECKING:
    from PySide6.QtWidgets import QStackedWidget, QWidget
    from wjx.ui.pages.workbench.dashboard import DashboardPage
    from wjx.ui.pages.workbench.runtime import RuntimePage


class MainWindowLazyPagesMixin:
    """主窗口中与页面懒加载、导航切换相关的方法集合。"""

    if TYPE_CHECKING:
        # 以下属性由 FluentWindow / MainWindow 主类提供，仅用于 Pylance 类型检查
        dashboard: DashboardPage
        runtime_page: RuntimePage
        stackedWidget: QStackedWidget
        navigationInterface: Any  # qfluentwidgets.NavigationInterface

        def addSubInterface(self, interface: QWidget, icon: Any, text: str, position: Any = ...) -> None: ...
        def switchTo(self, interface: QWidget) -> None: ...
        def close(self) -> bool: ...  # 继承自 QWidget

    def _init_navigation(self):
        self.addSubInterface(self.dashboard, FluentIcon.HOME, "概览", NavigationItemPosition.TOP)
        self.addSubInterface(self.runtime_page, FluentIcon.DEVELOPER_TOOLS, "运行参数", NavigationItemPosition.TOP)
        self.addSubInterface(self._get_result_page(), FluentIcon.PIE_SINGLE, "结果分析", NavigationItemPosition.TOP)
        self.addSubInterface(self._get_log_page(), FluentIcon.INFO, "日志", NavigationItemPosition.TOP)
        # 登录页面（动态更新）
        self._login_nav_widget = None
        self._network_manager = QNetworkAccessManager(self)  # type: ignore[arg-type]
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
            position=NavigationItemPosition.BOTTOM,
        )
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

    def _get_community_page(self):
        """懒加载社区页面"""
        if self._community_page is None:
            from wjx.ui.pages.more.community import CommunityPage

            self._community_page = CommunityPage(self)
            self._community_page.setObjectName("community")
            if self.stackedWidget.indexOf(self._community_page) == -1:
                self.stackedWidget.addWidget(self._community_page)
        return self._community_page

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
        changelog_detail_page.backRequested.connect(lambda: self._switch_to_more_page(changelog_page))

    def _show_changelog_detail(self, release: dict):
        """显示更新日志详情"""
        changelog_detail_page = self._get_changelog_detail_page()
        changelog_detail_page.setRelease(release)
        self._switch_to_more_page(changelog_detail_page)

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
        changelog_action.triggered.connect(lambda: self._switch_to_more_page(self._get_changelog_page()))
        menu.addAction(changelog_action)

        # 社区
        community_action = Action(FluentIcon.CHAT, "社区")
        community_action.triggered.connect(lambda: self._switch_to_more_page(self._get_community_page()))
        menu.addAction(community_action)

        # 客服与支持
        support_action = Action(FluentIcon.HELP, "客服与支持")
        support_action.triggered.connect(lambda: self._switch_to_more_page(self._get_support_page()))
        menu.addAction(support_action)

        # 捐助
        donate_action = Action(FluentIcon.HEART, "捐助")
        donate_action.triggered.connect(lambda: self._switch_to_more_page(self._get_donate_page()))
        menu.addAction(donate_action)

        # 关于
        about_action = Action(FluentIcon.INFO, "关于")
        about_action.triggered.connect(lambda: self._switch_to_more_page(self._get_about_page()))
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
                NavigationItemPosition.BOTTOM,
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
                position=NavigationItemPosition.BOTTOM,
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
                position=NavigationItemPosition.BOTTOM,
            )
            # 重新添加更多菜单
            self.navigationInterface.addItem(
                routeKey="about_menu",
                icon=FluentIcon.MORE,
                text="更多",
                onClick=self._show_about_menu,
                selectable=True,
                position=NavigationItemPosition.BOTTOM,
            )

    def _switch_to_more_page(self, page):
        """切换到“更多”相关页面，并同步侧边栏高亮"""
        self.switchTo(page)
        try:
            self.navigationInterface.setCurrentItem("about_menu")
        except Exception:
            logging.debug("同步“更多”侧边栏高亮失败", exc_info=True)

    def _load_avatar(self, url: str):
        """异步加载头像"""
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
