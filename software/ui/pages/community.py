"""社区页面 - 网格卡片布局"""

import os
import webbrowser
from typing import Any, cast

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QDesktopServices
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
    ElevatedCardWidget,
    PushButton,
    FluentIcon,
    StrongBodyLabel,
    IconWidget,
    ImageLabel,
)

from software.app.config import STATUS_ENDPOINT
from software.app.version import GITHUB_OWNER, GITHUB_REPO
from software.app.runtime_paths import get_assets_directory
from software.ui.helpers.proxy_access import format_status_payload
from software.ui.widgets.adaptive_flow_layout import AdaptiveFlowLayout

_GITHUB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"


class CommunityPage(ScrollArea):
    """社区页面 - 网格卡片布局，展示QQ群、联系开发者、参与贡献、开源声明等"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.content_widget = QWidget(self.view)
        self._qq_pixmap = None

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self._build_ui()

    # ── 构建 UI ──────────────────────────────────────────────

    def _build_ui(self):
        root_layout = QVBoxLayout(self.view)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.content_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        root_layout.addWidget(self.content_widget)

        cl = QVBoxLayout(self.content_widget)
        cl.setContentsMargins(36, 20, 36, 28)
        cl.setSpacing(20)
        cl.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── 页面标题 ──
        page_title = SubtitleLabel("社区", self.content_widget)
        page_title.setStyleSheet("font-size: 28px; font-weight: bold; letter-spacing: 2px;")
        cl.addWidget(page_title)

        cl.addSpacing(8)

        # ── 网格卡片布局 ──
        grid_widget = QWidget(self.content_widget)
        card_layout = AdaptiveFlowLayout(
            grid_widget,
            minItemWidth=420,
            hSpacing=16,
            vSpacing=16,
        )
        card_layout.setContentsMargins(0, 0, 0, 0)

        # 自适应卡片流式布局（窗口变窄自动换行）
        self.qq_card = self._build_qq_card()
        card_layout.addWidget(self.qq_card)

        self.contact_card = self._build_contact_card()
        card_layout.addWidget(self.contact_card)

        self.contribute_card = self._build_contribute_card()
        card_layout.addWidget(self.contribute_card)

        self.license_card = self._build_license_card()
        card_layout.addWidget(self.license_card)

        cl.addWidget(grid_widget)

        # ── Footer ──
        footer = CaptionLabel(
            "欢迎加入社区，一起让这个项目变得更好",
            self.content_widget,
        )
        footer.setStyleSheet("color: #888; font-size: 13px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addSpacing(16)
        cl.addWidget(footer)

        cl.addStretch(1)

    # ── 卡片工厂方法 ──

    def _create_grid_card(self, title: str, icon=None) -> tuple[ElevatedCardWidget, QVBoxLayout]:
        """创建网格卡片"""
        card = ElevatedCardWidget(self.content_widget)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 标题行（带图标）
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        title_layout.setContentsMargins(0, 0, 0, 0)

        if icon:
            icon_label = IconWidget(icon, card)
            icon_label.setFixedSize(24, 24)
            title_layout.addWidget(icon_label)

        title_label = StrongBodyLabel(title, card)
        title_label.setStyleSheet("font-size: 16px; letter-spacing: 1px;")
        title_layout.addWidget(title_label)
        title_layout.addStretch(1)
        layout.addLayout(title_layout)

        return card, layout

    def _setup_card_button(self, button: PushButton):
        """统一按钮尺寸，样式交给 QFluentWidgets 原生控件。"""
        button.setFixedHeight(36)
        button.setIconSize(QSize(16, 16))
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setMinimumWidth(max(120, button.sizeHint().width() + 8))

    def _create_action_bar(
        self,
        parent: QWidget,
        primary_button: PushButton,
        secondary_button: PushButton | None = None,
    ) -> QWidget:
        """统一卡片按钮区，保持 QFluentWidgets 原生按钮风格。"""
        action_bar = QWidget(parent)

        layout = QVBoxLayout(action_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(10)
        button_row.addWidget(primary_button)

        if secondary_button is not None:
            button_row.addWidget(secondary_button)

        button_row.addStretch(1)
        layout.addLayout(button_row)
        return action_bar

    # ── QQ 群卡片 ──

    def _build_qq_card(self) -> ElevatedCardWidget:
        card, layout = self._create_grid_card("QQ 群交流", FluentIcon.CHAT)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(16)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(8)

        desc = BodyLabel(
            "扫码加入 QQ 交流群，实时获取最新版本、反馈问题、交流使用经验、订阅最新的服务情况",
            card,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; line-height: 1.6; color: #999;")
        text_layout.addWidget(desc)
        text_layout.addStretch(1)
        content_row.addLayout(text_layout, 1)

        # 二维码展示
        self.qq_qr_label = ImageLabel(card)
        self.qq_qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qq_qr_label.setFixedSize(144, 144)
        self._load_qr_image()
        content_row.addWidget(
            self.qq_qr_label,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        layout.addLayout(content_row)
        layout.addStretch(1)

        preview_btn = PushButton("打开二维码", card)
        preview_btn.setIcon(FluentIcon.PHOTO)
        self._setup_card_button(preview_btn)
        preview_btn.clicked.connect(self._open_qq_qr_image)

        action_bar = self._create_action_bar(
            card,
            preview_btn,
        )
        layout.addWidget(action_bar)

        return card

    def _load_qr_image(self):
        """加载QQ群二维码图片"""
        try:
            path = os.path.join(get_assets_directory(), "community_qr.jpg")
            if os.path.exists(path):
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    self._qq_pixmap = pixmap
                    scaled = pixmap.scaled(
                        144,
                        144,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.qq_qr_label.setPixmap(self._round_pixmap(scaled, radius=12))
                else:
                    self.qq_qr_label.setText("二维码")
                    self.qq_qr_label.setStyleSheet("font-size: 12px; color: #999;")
            else:
                self.qq_qr_label.setText("二维码")
                self.qq_qr_label.setStyleSheet("font-size: 12px; color: #999;")
        except Exception:
            self.qq_qr_label.setText("二维码")
            self.qq_qr_label.setStyleSheet("font-size: 12px; color: #999;")

    def _round_pixmap(self, pixmap: QPixmap, radius: int = 8) -> QPixmap:
        """圆角处理"""
        if pixmap.isNull():
            return pixmap
        output = QPixmap(pixmap.size())
        output.fill(Qt.GlobalColor.transparent)
        painter = QPainter(output)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(output.rect(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return output

    def _open_qq_qr_image(self):
        """打开QQ群二维码原图"""
        path = os.path.join(get_assets_directory(), "community_qr.jpg")
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ── 联系开发者卡片 ──

    def _build_contact_card(self) -> ElevatedCardWidget:
        card, layout = self._create_grid_card("联系开发者", FluentIcon.SEND)

        desc = BodyLabel(
            "遇到问题？有建议？不想加 QQ 群？\n可以直接在此处与我们沟通，我们会尽快回复。",
            card,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; line-height: 1.6; color: #999;")
        layout.addWidget(desc)
        layout.addStretch(1)

        btn = PushButton("发送消息", card)
        btn.setIcon(FluentIcon.SEND)
        self._setup_card_button(btn)
        btn.clicked.connect(self._open_contact_dialog)

        action_bar = self._create_action_bar(
            card,
            btn,
        )
        layout.addWidget(action_bar)

        return card

    def _open_contact_dialog(self):
        """打开联系开发者对话框"""
        window = self.window()
        if hasattr(window, "_open_contact_dialog"):
            cast(Any, window)._open_contact_dialog()
            return

        from software.ui.dialogs.contact import ContactDialog

        dialog = ContactDialog(
            self,
            status_endpoint=STATUS_ENDPOINT,
            status_formatter=format_status_payload,
        )
        dialog.exec()

    # ── 参与贡献卡片 ──

    def _build_contribute_card(self) -> ElevatedCardWidget:
        card, layout = self._create_grid_card("参与贡献", FluentIcon.DEVELOPER_TOOLS)

        desc = BodyLabel(
            "我们接受开发、设计、测试、提供创新性想法、反馈报错等任何贡献形式\n相信我们能够一起把项目做得更好。",
            card,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; line-height: 1.6; color: #999;")
        layout.addWidget(desc)
        layout.addStretch(1)

        repo_btn = PushButton("仓库主页", card)
        repo_btn.setIcon(FluentIcon.GITHUB)
        self._setup_card_button(repo_btn)
        repo_btn.clicked.connect(lambda: webbrowser.open(_GITHUB_URL))

        action_bar = self._create_action_bar(
            card,
            repo_btn,
        )
        layout.addWidget(action_bar)

        return card

    # ── 开源许可卡片 ──

    def _build_license_card(self) -> ElevatedCardWidget:
        card, layout = self._create_grid_card("开源许可", FluentIcon.CERTIFICATE)

        license_label = StrongBodyLabel("AGPL-3.0", card)
        license_label.setStyleSheet("font-size: 18px; letter-spacing: 1px;")
        layout.addWidget(license_label)

        desc = BodyLabel(
            "在分发程序或对其进行修改并通过网络向其他用户提供交互服务时，必须向这些用户提供相应的完整源代码，以确保用户获得与传统分发情形同等的自由与权利",
            card,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; line-height: 1.6; color: #999;")
        layout.addWidget(desc)
        layout.addStretch(1)

        license_btn = PushButton("查看协议", card)
        license_btn.setIcon(FluentIcon.INFO)
        self._setup_card_button(license_btn)
        license_btn.clicked.connect(lambda: webbrowser.open(f"{_GITHUB_URL}/blob/main/LICENSE"))

        action_bar = self._create_action_bar(
            card,
            license_btn,
        )
        layout.addWidget(action_bar)

        return card
