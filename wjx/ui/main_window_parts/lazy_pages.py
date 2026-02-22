"""MainWindow 懒加载页面与导航相关方法。"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from qfluentwidgets import (
    Action,
    FluentIcon,
    MenuAnimationType,
    NavigationItemPosition,
    RoundMenu,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QStackedWidget, QWidget
    from wjx.ui.pages.workbench.answer_rules import AnswerRulesPage
    from wjx.ui.pages.workbench.dashboard import DashboardPage
    from wjx.ui.pages.workbench.runtime import RuntimePage


class MainWindowLazyPagesMixin:
    """主窗口中与页面懒加载、导航切换相关的方法集合。"""

    if TYPE_CHECKING:
        # 以下属性由 FluentWindow / MainWindow 主类提供，仅用于 Pylance 类型检查
        dashboard: DashboardPage
        runtime_page: RuntimePage
        answer_rules_page: AnswerRulesPage
        stackedWidget: QStackedWidget
        navigationInterface: Any  # qfluentwidgets.NavigationInterface

        def addSubInterface(self, interface: QWidget, icon: Any, text: str, position: Any = ..., parent: Any = None, isTransparent: bool = False) -> Any: ...
        def switchTo(self, interface: QWidget) -> None: ...
        def close(self) -> bool: ...  # 继承自 QWidget

    def _init_navigation(self):
        self.addSubInterface(self.dashboard, FluentIcon.HOME, "概览", NavigationItemPosition.TOP)
        self.addSubInterface(self.runtime_page, FluentIcon.DEVELOPER_TOOLS, "运行参数", NavigationItemPosition.TOP)
        self.addSubInterface(self.answer_rules_page, FluentIcon.PENCIL_INK, "作答规则", NavigationItemPosition.TOP)
        self.addSubInterface(self._get_log_page(), FluentIcon.INFO, "日志", NavigationItemPosition.TOP)
        # 社区页面
        self.addSubInterface(self._get_community_page(), FluentIcon.CHAT, "社区", NavigationItemPosition.BOTTOM)
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
            from wjx.ui.pages.community import CommunityPage

            self._community_page = CommunityPage(self)
            self._community_page.setObjectName("community")
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

    def _switch_to_more_page(self, page):
        """切换到“更多”相关页面，并同步侧边栏高亮"""
        self.switchTo(page)
        try:
            self.navigationInterface.setCurrentItem("about_menu")
        except Exception:
            logging.debug("同步“更多”侧边栏高亮失败", exc_info=True)
