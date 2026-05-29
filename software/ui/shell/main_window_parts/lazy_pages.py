"""MainWindow 懒加载页面与导航相关方法。"""

from __future__ import annotations

import logging
import webbrowser
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QColor
from qfluentwidgets import (
    Action,
    FluentIcon,
    InfoBadge,
    InfoBadgePosition,
    MenuAnimationType,
    NavigationItemPosition,
    RoundMenu,
)
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from PySide6.QtWidgets import QStackedWidget
    from software.ui.pages.workbench.dashboard.page import DashboardPage
    from software.ui.pages.workbench.reverse_fill.page import ReverseFillPage
    from software.ui.pages.workbench.runtime_panel.main import RuntimePage
    from software.ui.pages.workbench.strategy.page import QuestionStrategyPage


class MainWindowLazyPagesMixin:
    """主窗口中与页面懒加载、导航切换相关的方法集合。"""

    if TYPE_CHECKING:
        # 以下属性由 FluentWindow / MainWindow 主类提供。
        dashboard: DashboardPage
        runtime_page: RuntimePage
        strategy_page: QuestionStrategyPage
        reverse_fill_page: ReverseFillPage
        stackedWidget: QStackedWidget
        navigationInterface: Any  # qfluentwidgets.NavigationInterface
        addSubInterface: Any
        switchTo: Any
        close: Any  # 继承自 QWidget

    def _init_navigation(self):
        self.addSubInterface(
            self.dashboard,
            FluentIcon.HOME,
            "概览",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.runtime_page,
            FluentIcon.DEVELOPER_TOOLS,
            "运行参数",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.strategy_page,
            FluentIcon.DICTIONARY_ADD,
            "题目策略",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.reverse_fill_page,
            FluentIcon.SYNC,
            "反填",
            position=NavigationItemPosition.TOP,
        )
        self._show_reverse_fill_preview_badge()
        self.navigationInterface.addItem(
            routeKey="logs",
            icon=FluentIcon.INFO,
            text="日志",
            onClick=lambda: self._switch_to_lazy_page("logs", self._get_log_page()),
            position=NavigationItemPosition.TOP,
        )
        # 社区页面
        self.navigationInterface.addItem(
            routeKey="community",
            icon=FluentIcon.CHAT,
            text="社区",
            onClick=lambda: self._switch_to_lazy_page("community", self._get_community_page()),
            position=NavigationItemPosition.BOTTOM,
        )
        # 设置页面
        self.navigationInterface.addItem(
            routeKey="settings",
            icon=FluentIcon.SETTING,
            text="设置",
            onClick=lambda: self._switch_to_lazy_page("settings", self._get_settings_page()),
            position=NavigationItemPosition.BOTTOM,
        )
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

    def _show_reverse_fill_preview_badge(self):
        nav_item = self.navigationInterface.widget("reverse_fill")
        if nav_item is None:
            return

        if getattr(self, "_reverse_fill_preview_badge", None) is not None:
            return

        try:
            badge_parent = nav_item.parentWidget() or self.navigationInterface
            self._reverse_fill_preview_badge = InfoBadge.custom(
                "预览",
                QColor("#fbbf24"),
                QColor("#fbbf24"),
                parent=badge_parent,
                target=nav_item,
                position=InfoBadgePosition.NAVIGATION_ITEM,
            )
            self._reverse_fill_preview_badge.show()
        except Exception:
            logging.info("显示反填预览徽章失败", exc_info=True)

    def _ensure_lazy_page_added(self, page: QWidget) -> QWidget:
        if self.stackedWidget.indexOf(page) == -1:
            self.stackedWidget.addWidget(page)
        return page

    def _switch_to_lazy_page(self, route_key: str, page: QWidget) -> None:
        self._ensure_lazy_page_added(page)
        self.switchTo(page)
        try:
            self.navigationInterface.setCurrentItem(route_key)
        except Exception:
            logging.info("同步懒加载页面侧边栏高亮失败", exc_info=True)

    def _get_log_page(self):
        """懒加载日志页面"""
        if self._log_page is None:
            from software.ui.pages.workbench.log_panel.page import LogPage

            self._log_page = LogPage(self)
            self._log_page.setObjectName("logs")
        return self._log_page

    def _get_settings_page(self):
        """懒加载设置页面"""
        if self._settings_page is None:
            from software.ui.pages.settings.settings import SettingsPage

            self._settings_page = SettingsPage(self)
            self._settings_page.setObjectName("settings")
        return self._settings_page

    def _get_community_page(self):
        """懒加载社区页面"""
        if self._community_page is None:
            from software.ui.pages.community import CommunityPage

            self._community_page = CommunityPage(self)
            self._community_page.setObjectName("community")
        return self._community_page

    def _get_about_page(self):
        """懒加载关于页面"""
        if self._about_page is None:
            from software.ui.pages.more.about import AboutPage

            self._about_page = AboutPage(self)
            self._about_page.setObjectName("about")
            if self.stackedWidget.indexOf(self._about_page) == -1:
                self.stackedWidget.addWidget(self._about_page)
        return self._about_page

    def _get_ip_usage_page(self):
        """懒加载 IP 使用记录页面"""
        if self._ip_usage_page is None:
            from software.ui.pages.more.ip_usage_page import IpUsagePage

            self._ip_usage_page = IpUsagePage(self)
            self._ip_usage_page.setObjectName("ip_usage")
            if self.stackedWidget.indexOf(self._ip_usage_page) == -1:
                self.stackedWidget.addWidget(self._ip_usage_page)
        return self._ip_usage_page

    def _get_donate_page(self):
        """懒加载捐助页面"""
        if self._donate_page is None:
            from software.ui.pages.more.donate import DonatePage

            self._donate_page = DonatePage(self)
            self._donate_page.setObjectName("donate")
            if self.stackedWidget.indexOf(self._donate_page) == -1:
                self.stackedWidget.addWidget(self._donate_page)
        return self._donate_page

    def _show_about_menu(self):
        """显示关于子菜单"""
        from software.app.version import __VERSION__

        menu = RoundMenu(parent=self)

        # 版本信息（不可点击）
        version_action = Action(FluentIcon.INFO, f"SurveyController v{__VERSION__}")
        version_action.setEnabled(False)
        menu.addAction(version_action)

        menu.addSeparator()

        # 更新日志
        changelog_action = Action(FluentIcon.HISTORY, "更新日志")
        changelog_action.triggered.connect(self._open_changelog_releases)
        menu.addAction(changelog_action)

        # 使用教程
        tutorial_action = Action(FluentIcon.LIBRARY, "使用教程")
        tutorial_action.triggered.connect(self._open_usage_tutorial)
        menu.addAction(tutorial_action)

        # IP 使用记录
        ip_usage_action = Action(FluentIcon.CALENDAR, "IP 使用记录")
        ip_usage_action.triggered.connect(
            lambda: self._switch_to_more_page(self._get_ip_usage_page())
        )
        menu.addAction(ip_usage_action)

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

    def _switch_to_more_page(self, page):
        """切换到更多相关页面，并同步侧边栏高亮"""
        self.switchTo(page)
        try:
            self.navigationInterface.setCurrentItem("about_menu")
        except Exception:
            logging.info("同步更多侧边栏高亮失败", exc_info=True)

    def _open_changelog_releases(self) -> None:
        from software.app.version import GITHUB_RELEASES_PAGE_URL

        webbrowser.open(GITHUB_RELEASES_PAGE_URL)

    def _open_usage_tutorial(self) -> None:
        webbrowser.open("https://surveydoc.hungrym0.top/")
