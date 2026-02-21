"""社区页面 - QQ群、开源声明、开发者招募"""
import os
import logging
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QBoxLayout,
    QLabel,
    QDialog,
    QSizePolicy,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    FluentIcon,
    StrongBodyLabel,
)

from wjx.utils.app.version import GITHUB_OWNER, GITHUB_REPO
from wjx.utils.io.load_save import get_assets_directory
from wjx.utils.logging.log_utils import log_suppressed_exception

_GITHUB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"


class CommunityPage(ScrollArea):
    """社区页面，展示QQ群、开源声明和开发者招募"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.content_widget = QWidget(self.view)
        self._compact = False
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


from wjx.utils.app.version import GITHUB_OWNER, GITHUB_REPO
from wjx.utils.io.load_save import get_assets_directory
from wjx.utils.logging.log_utils import log_suppressed_exception

_GITHUB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"


class CommunityPage(ScrollArea):
    """社区页面，展示QQ群、开源声明和开发者招募"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.content_widget = QWidget(self.view)
        self._compact = False
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
        cl.setSpacing(16)
        cl.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── 页面标题 ──
        page_title = SubtitleLabel("社区", self.content_widget)
        page_title.setStyleSheet("font-size: 28px; font-weight: bold; letter-spacing: 2px;")
        cl.addWidget(page_title)

        cl.addSpacing(8)

        # ── QQ 群卡片 ──
        self.qq_card = self._build_qq_card()
        cl.addWidget(self.qq_card)

        # ── 开发者招募卡片 ──
        self.dev_card = self._build_recruit_card()
        cl.addWidget(self.dev_card)

        # ── 开源声明卡片 ──
        self.os_card = self._build_opensource_card()
        cl.addWidget(self.os_card)

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
        self._update_layout()

    # ── QQ 群卡片 ──

    def _build_qq_card(self) -> CardWidget:
        card = CardWidget(self.content_widget)
        self.qq_inner = QHBoxLayout(card)
        self.qq_inner.setContentsMargins(40, 36, 40, 36)
        self.qq_inner.setSpacing(32)

        # 左侧文字
        left = QVBoxLayout()
        left.setSpacing(16)
        left.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title = StrongBodyLabel("加入 QQ 交流群", card)
        title.setStyleSheet("font-size: 24px; letter-spacing: 2px;")
        left.addWidget(title)

        desc = BodyLabel(
            "扫描二维码或搜索群号加入交流群。\n"
            "群内可获取版本更新推送、反馈使用中遇到的问题、\n"
            "以及与其他用户交流使用技巧和经验。",
            card,
        )
        desc.setStyleSheet("font-size: 16px; line-height: 1.8; letter-spacing: 2px;")
        desc.setWordWrap(True)
        left.addWidget(desc)

        hint = CaptionLabel("点击二维码可查看大图", card)
        hint.setStyleSheet("font-size: 14px; color: #888; letter-spacing: 1px;")
        left.addWidget(hint)

        self.qq_inner.addLayout(left, 1)

        # 右侧二维码
        self.qq_qr_label = QLabel(card)
        self.qq_qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qq_qr_label.setStyleSheet(
            "background: rgba(255,255,255,0.05); "
            "border: 1px solid rgba(128,128,128,0.1); "
            "border-radius: 12px; "
            "padding: 12px;"
        )
        self.qq_qr_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.qq_qr_label.mousePressEvent = lambda ev: self._on_qr_clicked()
        self._load_qr_image()

        self.qq_inner.addWidget(self.qq_qr_label, 0, Qt.AlignmentFlag.AlignVCenter)

        return card

    # ── 开源声明卡片 ──

    def _build_opensource_card(self) -> CardWidget:
        card = CardWidget(self.content_widget)
        self.os_inner = QHBoxLayout(card)
        self.os_inner.setContentsMargins(40, 36, 40, 36)
        self.os_inner.setSpacing(32)

        # 左侧：描述
        left = QVBoxLayout()
        left.setSpacing(16)
        left.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title = StrongBodyLabel("开源声明", card)
        title.setStyleSheet("font-size: 24px; letter-spacing: 2px;")
        left.addWidget(title)

        desc = BodyLabel(
            "本项目基于 GPL-3.0 许可证公开全部源代码！\n"
            "欢迎各位提出改进建议或直接贡献代码",
            card,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 16px; line-height: 1.8; letter-spacing: 2px;")
        left.addWidget(desc)

        license_row = QHBoxLayout()
        license_row.setSpacing(8)
        license_label = CaptionLabel("License：", card)
        license_label.setStyleSheet("font-size: 14px; color: #888; letter-spacing: 1px;")
        license_row.addWidget(license_label)
        gpl = StrongBodyLabel("GPL-3.0", card)
        gpl.setStyleSheet("font-size: 15px; letter-spacing: 1px;")
        license_row.addWidget(gpl)
        license_row.addStretch(1)
        left.addLayout(license_row)

        github_btn = PrimaryPushButton("GitHub 仓库", card, FluentIcon.GITHUB)
        github_btn.clicked.connect(lambda: webbrowser.open(_GITHUB_URL))
        left.addWidget(github_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self.os_inner.addLayout(left, 1)

        # 右侧：应用图标
        icon_label = QLabel(card)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_path = os.path.join(get_assets_directory(), "icon.png")
        if os.path.exists(icon_path):
            icon_pixmap = QPixmap(icon_path)
            if not icon_pixmap.isNull():
                icon_pixmap = icon_pixmap.scaled(
                    120, 120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                icon_label.setPixmap(icon_pixmap)
        icon_label.setFixedSize(160, 160)
        self.os_inner.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        return card

    # ── 开发者招募卡片（全宽）──

    def _build_recruit_card(self) -> CardWidget:
        card = CardWidget(self.content_widget)
        self.recruit_inner = QHBoxLayout(card)
        self.recruit_inner.setContentsMargins(40, 36, 40, 36)
        self.recruit_inner.setSpacing(32)

        # 左侧：招募说明
        left = QVBoxLayout()
        left.setSpacing(16)
        left.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title = StrongBodyLabel("✅ 参与开发贡献", card)
        title.setStyleSheet("font-size: 24px; letter-spacing: 2px;")
        left.addWidget(title)

        desc = BodyLabel(
            "我们正在寻找志同道合的开发者一起共创项目！\n"
            "无论你擅长开发、设计还是测试，都有你的位置。",
            card,
        )
        desc.setStyleSheet("font-size: 16px; line-height: 1.8; letter-spacing: 2px;")
        desc.setWordWrap(True)
        left.addWidget(desc)

        skills = CaptionLabel(
            "Python ·  UI 设计 · 题型支持 · 文档编写",
            card,
        )
        skills.setWordWrap(True)
        skills.setStyleSheet("font-size: 14px; color: #888; letter-spacing: 1px;")
        left.addWidget(skills)

        self.recruit_inner.addLayout(left, 1)

        # 右侧：参与方式 + 按钮
        right = QVBoxLayout()
        right.setSpacing(16)
        right.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        right_title = StrongBodyLabel("如何参与", card)
        right_title.setStyleSheet("font-size: 24px; letter-spacing: 2px;")
        right.addWidget(right_title)

        steps = BodyLabel(
            "1. Fork 并克隆仓库到本地\n"
            "2. 编码开发\n"
            "3. 在 GitHub 提交 Pull Request",
            card,
        )
        steps.setStyleSheet("font-size: 16px; line-height: 1.8; letter-spacing: 2px;")
        steps.setWordWrap(True)
        right.addWidget(steps)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        guide_btn = PrimaryPushButton("查看贡献指南", card, FluentIcon.DOCUMENT)
        guide_btn.clicked.connect(
            lambda: webbrowser.open(f"{_GITHUB_URL}/blob/main/CONTRIBUTING.md")
        )
        btn_row.addWidget(guide_btn)

        issues_btn = PushButton("提交 Issue", card, FluentIcon.CHAT)
        issues_btn.clicked.connect(
            lambda: webbrowser.open(f"{_GITHUB_URL}/issues/new")
        )
        btn_row.addWidget(issues_btn)
        btn_row.addStretch(1)

        right.addLayout(btn_row)
        self.recruit_inner.addLayout(right, 1)

        return card

    # ── 二维码相关 ──

    def _load_qr_image(self):
        """加载QQ群二维码图片"""
        try:
            path = os.path.join(get_assets_directory(), "community_qr.jpg")
            if os.path.exists(path):
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    self._qq_pixmap = pixmap
                    self._apply_qq_qr_pixmap()
                else:
                    self.qq_qr_label.setText("二维码加载失败\nassets/community_qr.jpg")
            else:
                self.qq_qr_label.setText("二维码未找到\nassets/community_qr.jpg")
        except Exception as exc:
            self.qq_qr_label.setText(f"加载失败：{exc}")

    def _apply_qq_qr_pixmap(self):
        if not self._qq_pixmap or self._qq_pixmap.isNull():
            return
        base_width = 200 if self._compact else 240
        ratio = self._qq_pixmap.height() / self._qq_pixmap.width() if self._qq_pixmap.width() else 1
        height = max(160, int(base_width * ratio))
        self.qq_qr_label.setFixedSize(base_width + 24, height + 24)
        scaled = self._qq_pixmap.scaled(
            base_width, height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.qq_qr_label.setPixmap(self._round_pixmap(scaled, radius=12))

    def _round_pixmap(self, pixmap: QPixmap, radius: int = 12) -> QPixmap:
        """圆角处理，避免直角二维码显得突兀"""
        if pixmap.isNull():
            return pixmap
        output = QPixmap(pixmap.size())
        output.fill(Qt.GlobalColor.transparent)
        painter = QPainter(output)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        rect = output.rect()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return output

    def _on_qr_clicked(self):
        """点击二维码查看原图"""
        try:
            path = os.path.join(get_assets_directory(), "community_qr.jpg")
            if os.path.exists(path):
                self._show_full_image(path)
        except Exception as exc:
            log_suppressed_exception("_on_qr_clicked", exc, level=logging.WARNING)

    def _show_full_image(self, image_path: str):
        """显示原图弹窗"""
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle("QQ群二维码")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)

        img_label = QLabel(dialog)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(image_path)
        if pixmap.width() > 600 or pixmap.height() > 600:
            pixmap = pixmap.scaled(
                600,
                600,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        img_label.setPixmap(pixmap)
        layout.addWidget(img_label)

        close_btn = PushButton("关闭", dialog)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        dialog.adjustSize()
        dialog.exec()

    # ── 响应式布局 ──

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_layout()

    def _update_layout(self):
        compact = self.viewport().width() < 750
        if compact == self._compact:
            return
        self._compact = compact

        if compact:
            self.recruit_inner.setDirection(QBoxLayout.Direction.TopToBottom)
            self.qq_inner.setDirection(QBoxLayout.Direction.TopToBottom)
            self.os_inner.setDirection(QBoxLayout.Direction.TopToBottom)
        else:
            self.recruit_inner.setDirection(QBoxLayout.Direction.LeftToRight)
            self.qq_inner.setDirection(QBoxLayout.Direction.LeftToRight)
            self.os_inner.setDirection(QBoxLayout.Direction.LeftToRight)
        self._apply_qq_qr_pixmap()
