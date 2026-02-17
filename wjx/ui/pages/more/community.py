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
    HyperlinkButton,
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

        self.content_widget.setMaximumWidth(1200)
        self.content_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        root_layout.addWidget(self.content_widget, 0, Qt.AlignmentFlag.AlignHCenter)

        cl = QVBoxLayout(self.content_widget)
        cl.setContentsMargins(36, 20, 36, 28)
        cl.setSpacing(16)
        cl.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── 页面标题 ──
        page_title = SubtitleLabel("社区", self.content_widget)
        page_title.setStyleSheet("font-size: 24px; font-weight: bold;")
        cl.addWidget(page_title)

        # ── 上半部分：QQ群 + 开源声明 并排 ──
        self.top_row = QHBoxLayout()
        self.top_row.setSpacing(16)

        self.qq_card = self._build_qq_card()
        self.os_card = self._build_opensource_card()

        self.top_row.addWidget(self.qq_card, 3)
        self.top_row.addWidget(self.os_card, 2)
        cl.addLayout(self.top_row)

        # ── 下半部分：开发者招募（全宽）──
        self.dev_card = self._build_recruit_card()
        cl.addWidget(self.dev_card)

        # ── Footer ──
        footer = CaptionLabel(
            "欢迎加入社区，一起让 fuck-wjx 变得更好",
            self.content_widget,
        )
        footer.setStyleSheet("color: #888;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addSpacing(4)
        cl.addWidget(footer)

        cl.addStretch(1)
        self._update_layout()

    # ── QQ 群卡片 ──

    def _build_qq_card(self) -> CardWidget:
        card = CardWidget(self.content_widget)
        self.qq_inner = QHBoxLayout(card)
        self.qq_inner.setContentsMargins(24, 20, 24, 20)
        self.qq_inner.setSpacing(20)

        # 左侧文字
        left = QVBoxLayout()
        left.setSpacing(10)
        left.setAlignment(Qt.AlignmentFlag.AlignTop)

        left.addWidget(StrongBodyLabel("加入 QQ 交流群", card))

        desc = BodyLabel(
            "扫描二维码或搜索群号加入交流群。\n"
            "群内可获取版本更新推送、反馈使用中遇到的问题、\n"
            "以及与其他用户交流使用技巧和经验。",
            card,
        )
        desc.setWordWrap(True)
        left.addWidget(desc)

        hint = CaptionLabel("点击二维码可查看大图", card)
        hint.setStyleSheet("color: #888;")
        left.addWidget(hint)
        left.addStretch(1)

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
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel("开源项目", card))

        desc = BodyLabel(
            "本项目基于 GPL-3.0 许可证开源。\n"
            "欢迎查看源代码、提出改进建议或直接贡献代码。",
            card,
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 许可证行
        license_row = QHBoxLayout()
        license_row.setSpacing(6)
        license_label = CaptionLabel("许可证", card)
        license_label.setStyleSheet("color: #888;")
        license_row.addWidget(license_label)
        gpl = StrongBodyLabel("GPL-3.0", card)
        gpl.setStyleSheet("font-size: 13px;")
        license_row.addWidget(gpl)
        license_row.addStretch(1)
        layout.addLayout(license_row)

        layout.addSpacing(4)

        github_btn = PrimaryPushButton("GitHub 仓库", card, FluentIcon.GITHUB)
        github_btn.clicked.connect(lambda: webbrowser.open(_GITHUB_URL))
        layout.addWidget(github_btn)

        star_btn = PushButton("Star 项目", card, FluentIcon.HEART)
        star_btn.clicked.connect(lambda: webbrowser.open(_GITHUB_URL))
        layout.addWidget(star_btn)

        layout.addStretch(1)

        philosophy = CaptionLabel(
            "开源不仅是代码公开，更是知识共享与社区协作。",
            card,
        )
        philosophy.setWordWrap(True)
        philosophy.setStyleSheet("color: #888;")
        layout.addWidget(philosophy)

        return card

    # ── 开发者招募卡片（全宽）──

    def _build_recruit_card(self) -> CardWidget:
        card = CardWidget(self.content_widget)
        self.recruit_inner = QHBoxLayout(card)
        self.recruit_inner.setContentsMargins(24, 20, 24, 20)
        self.recruit_inner.setSpacing(24)

        # 左侧：招募说明
        left = QVBoxLayout()
        left.setSpacing(8)
        left.setAlignment(Qt.AlignmentFlag.AlignTop)

        left.addWidget(StrongBodyLabel("参与贡献", card))

        desc = BodyLabel(
            "我们正在寻找志同道合的开发者加入项��共建。\n"
            "无论你擅长开发、设计还是测试，都有你的位置。",
            card,
        )
        desc.setWordWrap(True)
        left.addWidget(desc)

        skills = CaptionLabel(
            "Python / PySide6  ·  UI/UX 设计  ·  测试与质量  ·  文档编写",
            card,
        )
        skills.setWordWrap(True)
        skills.setStyleSheet("color: #888;")
        left.addWidget(skills)

        left.addStretch(1)
        self.recruit_inner.addLayout(left, 1)

        # 右侧：参与方式 + 按钮
        right = QVBoxLayout()
        right.setSpacing(8)
        right.setAlignment(Qt.AlignmentFlag.AlignTop)

        right.addWidget(StrongBodyLabel("如何参与", card))

        steps = BodyLabel(
            "1. Fork 并克隆仓库到本地\n"
            "2. 创建分支，编码开发\n"
            "3. 提交 Pull Request\n"
            "4. 加入 QQ 群交流反馈",
            card,
        )
        steps.setWordWrap(True)
        right.addWidget(steps)

        right.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        guide_btn = PrimaryPushButton("查看贡献指南", card, FluentIcon.DOCUMENT)
        guide_btn.clicked.connect(
            lambda: webbrowser.open(f"{_GITHUB_URL}/blob/main/CONTRIBUTING.md")
        )
        btn_row.addWidget(guide_btn)

        issues_btn = PushButton("浏览 Issues", card, FluentIcon.CHAT)
        issues_btn.clicked.connect(
            lambda: webbrowser.open(f"{_GITHUB_URL}/issues")
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
        base_width = 160 if self._compact else 180
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
            self.top_row.setDirection(QBoxLayout.Direction.TopToBottom)
            self.recruit_inner.setDirection(QBoxLayout.Direction.TopToBottom)
            self.qq_inner.setDirection(QBoxLayout.Direction.TopToBottom)
        else:
            self.top_row.setDirection(QBoxLayout.Direction.LeftToRight)
            self.recruit_inner.setDirection(QBoxLayout.Direction.LeftToRight)
            self.qq_inner.setDirection(QBoxLayout.Direction.LeftToRight)
        self._apply_qq_qr_pixmap()
