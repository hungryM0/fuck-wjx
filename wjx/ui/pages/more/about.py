"""关于页面"""
import threading
import webbrowser
import os
import sys
import requests
from datetime import datetime

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSizePolicy,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    TitleLabel,
    PushButton,
    PrimaryPushButton,
    HyperlinkButton,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    ImageLabel,
    CardWidget,
    StrongBodyLabel,
    FluentIcon
)

from wjx.utils.app.version import __VERSION__, GITHUB_OWNER, GITHUB_REPO
from wjx.ui.widgets.full_width_infobar import FullWidthInfoBar


def get_resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径，兼容打包后的环境"""
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return os.path.join(meipass, relative_path)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), relative_path)


class AboutPage(ScrollArea):
    """关于页面，包含版本号、链接、检查更新等。"""

    _updateCheckFinished = Signal(object)  # update_info or None
    _updateCheckError = Signal(str)  # error message
    _publishTimeLoaded = Signal(str)  # publish time string
    _ipBalanceLoaded = Signal(float)  # balance

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updateCheckFinished.connect(self._on_update_result)
        self._updateCheckError.connect(self._on_update_error)
        self._ipBalanceLoaded.connect(self._on_ip_balance_loaded)
        
        self.view = QWidget(self)
        self.view.setObjectName('view')
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.view.setStyleSheet("QWidget#view { background: transparent; }")
        
        self._checking_update = False
        
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self.view)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        content_widget = QWidget(self.view)
        content_widget.setObjectName("about_content")
        content_widget.setMaximumWidth(1000)
        content_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        main_layout.addWidget(content_widget, 0, Qt.AlignmentFlag.AlignHCenter)

        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(36, 20, 36, 20)
        content_layout.setSpacing(16)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 1. 顶部 Hero 区域
        hero_widget = QWidget()
        hero_layout = QVBoxLayout(hero_widget)
        hero_layout.setSpacing(10)
        hero_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        
        logo_path = get_resource_path("assets/icon.png")
        self.logo = ImageLabel(logo_path, self)
        self.logo.setFixedSize(96, 96)
        self.logo.scaledToHeight(96) 
        
        title = TitleLabel("fuck-wjx", self)
        
        desc = BodyLabel("问卷星速填 - 高效的自动化问卷填写工具", self)
        desc.setStyleSheet("color: #606060;")
        
        hero_layout.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        hero_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
        hero_layout.addWidget(desc, 0, Qt.AlignmentFlag.AlignHCenter)
        
        content_layout.addWidget(hero_widget)
        content_layout.addSpacing(10)

        # 警示声明 - 使用内嵌InfoBar样式
        disclaimer_bar = FullWidthInfoBar(
            icon=InfoBarIcon.WARNING,
            title="",
            content="本项目仅供学习交流使用，开源以供研究软件原理，禁止用于任何恶意滥用行为",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            position=InfoBarPosition.NONE,
            duration=-1,
            parent=content_widget
        )
        disclaimer_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        disclaimer_bar.setMinimumWidth(0)
        disclaimer_bar.setMaximumWidth(16777215)
        content_layout.addWidget(disclaimer_bar)

        # 2. 版本信息 + 相关链接（两个卡片并排）
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        
        # 左卡片：版本信息
        version_card = CardWidget(self)
        version_layout = QVBoxLayout(version_card)
        version_layout.setContentsMargins(20, 16, 20, 16)
        version_layout.setSpacing(8)
        version_layout.addWidget(StrongBodyLabel("当前版本", self))
        
        version_row = QHBoxLayout()
        v_num = BodyLabel(f"v{__VERSION__}", self)
        self.publish_time_label = CaptionLabel("", self)
        self.publish_time_label.setStyleSheet("color: #888;")
        version_row.addWidget(v_num)
        version_row.addWidget(self.publish_time_label)
        version_row.addStretch(1)
        self.update_spinner = IndeterminateProgressRing(self)
        self.update_spinner.setFixedSize(16, 16)
        self.update_spinner.setStrokeWidth(2)
        self.update_spinner.hide()
        self.update_btn = PrimaryPushButton("检查更新", self, FluentIcon.UPDATE)
        version_row.addWidget(self.update_spinner)
        version_row.addWidget(self.update_btn)
        version_layout.addLayout(version_row)
        
        # 右卡片：相关链接
        links_card = CardWidget(self)
        links_layout = QVBoxLayout(links_card)
        links_layout.setContentsMargins(20, 16, 20, 16)
        links_layout.setSpacing(8)
        links_layout.addWidget(StrongBodyLabel("相关链接", self))
        
        self.github_btn = PushButton("GitHub 仓库", self, FluentIcon.GITHUB)
        icon_path = get_resource_path("icon.ico")
        self.website_btn = PushButton("项目官网", self, QIcon(icon_path))
        
        links_row = QHBoxLayout()
        links_row.setSpacing(12)
        links_row.addWidget(self.github_btn)
        links_row.addWidget(self.website_btn)
        links_row.addStretch(1)
        links_layout.addLayout(links_row)
        links_layout.addStretch(1)
        
        cards_row.addWidget(version_card, 1)
        cards_row.addWidget(links_card, 1)
        
        content_layout.addLayout(cards_row)

        # 4. 致谢 & 许可
        credit_card = CardWidget(self)
        credit_layout = QVBoxLayout(credit_card)
        credit_layout.setContentsMargins(20, 16, 20, 16)
        credit_layout.setSpacing(12)
        
        credit_layout.addWidget(StrongBodyLabel("致谢与许可", self))
        
        inspire_layout = QHBoxLayout()
        inspire_layout.addWidget(BodyLabel("Inspired by：", self))
        inspire_link = HyperlinkButton("https://github.com/Zemelee/wjx", "Zemelee/wjx", self)
        inspire_layout.addWidget(inspire_link)
        inspire_layout.addStretch(1)
        credit_layout.addLayout(inspire_layout)
        
        # 服务条款链接
        terms_layout = QHBoxLayout()
        terms_layout.addWidget(BodyLabel("服务条款与隐私声明：", self))
        self.terms_btn = HyperlinkButton("", "查看详情", self)
        self.terms_btn.clicked.connect(self._show_terms_of_service)
        terms_layout.addWidget(self.terms_btn)
        terms_layout.addStretch(1)
        credit_layout.addLayout(terms_layout)
        
        license_layout = QHBoxLayout()
        license_layout.addWidget(BodyLabel("License：", self))
        license_layout.addWidget(BodyLabel("GPL-3.0 License", self))
        license_layout.addStretch(1)
        credit_layout.addLayout(license_layout)
        
        third_party_layout = QHBoxLayout()
        third_party_layout.addWidget(BodyLabel("Third-party：", self))
        pyside_link = HyperlinkButton("https://doc.qt.io/qtforpython-6/", "PySide6 (LGPL)", self)
        qfw_link = HyperlinkButton("https://qfluentwidgets.com", "QFluentWidgets (GPLv3)", self)
        third_party_layout.addWidget(pyside_link)
        third_party_layout.addWidget(qfw_link)
        third_party_layout.addStretch(1)
        credit_layout.addLayout(third_party_layout)
        
        content_layout.addWidget(credit_card)

        # Footer
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(8)
        copyright_text = CaptionLabel("© 2026 HUNGRY_M0", self)
        copyright_text.setStyleSheet("color: #888;")
        self.ip_balance_label = CaptionLabel("", self)
        self.ip_balance_label.setStyleSheet("color: #888;")
        footer_layout.addStretch(1)
        footer_layout.addWidget(copyright_text)
        footer_layout.addWidget(self.ip_balance_label)
        footer_layout.addStretch(1)
        content_layout.addSpacing(8)
        content_layout.addLayout(footer_layout)
        content_layout.addStretch(1)

        self.update_btn.clicked.connect(self._check_updates)
        self.github_btn.clicked.connect(lambda: webbrowser.open(f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"))
        self.website_btn.clicked.connect(lambda: webbrowser.open("https://www.hungrym0.top/fuck-wjx.html"))
        
        # 异步获取发布时间和IP余额
        self._load_publish_time()
        self._load_ip_balance()

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
            from wjx.utils.update.updater import show_update_notification
            show_update_notification(win)
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
                from wjx.utils.update.updater import UpdateManager
                update_info = UpdateManager.check_updates()
                self._updateCheckFinished.emit(update_info)
            except Exception as exc:
                self._updateCheckError.emit(str(exc))
        
        threading.Thread(target=_do_check, daemon=True).start()

    def _load_publish_time(self):
        """异步加载当前版本的发布时间"""
        self._publishTimeLoaded.connect(self._on_publish_time_loaded)
        
        def _do_load():
            try:
                from wjx.utils.update.updater import UpdateManager
                releases = UpdateManager.get_all_releases()
                for r in releases:
                    if r.get("version") == __VERSION__:
                        published_at = r.get("published_at", "")
                        if published_at:
                            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                            self._publishTimeLoaded.emit(dt.strftime("%Y-%m-%d"))
                        return
            except Exception:
                pass
        
        threading.Thread(target=_do_load, daemon=True).start()

    def _on_publish_time_loaded(self, time_str: str):
        """更新发布时间标签"""
        self.publish_time_label.setText(f"({time_str})")

    def _load_ip_balance(self):
        """异步加载IP余额"""
        def _do_load():
            try:
                response = requests.get(
                    "https://service.ipzan.com/userProduct-get",
                    params={"no": "20260112572376490874", "userId": "72FH7U4E0IG"},
                    timeout=5,
                )
                data = response.json()
                if data.get("code") in (0, 200) and data.get("status") in (200, "200", None):
                    balance = data.get("data", {}).get("balance", 0)
                    try:
                        self._ipBalanceLoaded.emit(float(balance))
                    except Exception:
                        pass
            except Exception:
                pass
        
        threading.Thread(target=_do_load, daemon=True).start()

    def _on_ip_balance_loaded(self, balance: float):
        """更新IP余额标签，显示剩余IP数"""
        try:
            # 计算剩余IP数：经费除以0.0035，截断小数部分
            ip_count = int(float(balance) / 0.0035)
            display = str(ip_count)
        except Exception:
            display = "--"
        self.ip_balance_label.setText(f"|  代理源剩余IP数：{display}")

    def _show_terms_of_service(self):
        """显示服务条款对话框"""
        from wjx.ui.dialogs import TermsOfServiceDialog
        dlg = TermsOfServiceDialog(self.window())
        dlg.exec()
