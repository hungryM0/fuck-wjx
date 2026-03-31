"""更新日志页面"""
import threading
from datetime import datetime

from PySide6.QtCore import Signal, Qt, QSize, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    StrongBodyLabel,
    CaptionLabel,
    BodyLabel,
    CardWidget,
    IndeterminateProgressRing,
    FluentIcon,
    TransparentToolButton,
    IconWidget,
    TextBrowser,
    DrillInTransitionStackedWidget,
)

from software.io.markdown import strip_markdown


class ReleaseListItem(CardWidget):
    """发行版列表项"""
    itemClicked = Signal(dict)

    def __init__(self, release: dict, parent=None):
        super().__init__(parent)
        self.release = release
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 16, 16)
        layout.setSpacing(0)

        # 左侧：版本号 + 日期 + 摘要
        left_layout = QVBoxLayout()
        left_layout.setSpacing(5)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        version_layout = QHBoxLayout()
        version_layout.setSpacing(12)
        version_layout.setContentsMargins(0, 0, 0, 0)

        version = self.release.get("version", "")
        title = StrongBodyLabel(f"v{version}", self)
        version_layout.addWidget(title)

        published = self.release.get("published_at", "")
        date_str = ""
        if published:
            try:
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                date_str = published[:10] if len(published) >= 10 else published

        date_label = BodyLabel(date_str, self)
        date_label.setStyleSheet("color: #888;")
        version_layout.addWidget(date_label)
        version_layout.addStretch(1)

        left_layout.addLayout(version_layout)

        body_text = strip_markdown(self.release.get("body", "")).strip()
        body_text = " ".join(body_text.split())
        if body_text:
            snippet_text = body_text[:80] + "..." if len(body_text) > 80 else body_text
            snippet = CaptionLabel(snippet_text, self)
            snippet.setStyleSheet("color: #888;")
            snippet.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            snippet.setMinimumWidth(0)
            left_layout.addWidget(snippet)

        layout.addLayout(left_layout, stretch=1)

        # 右侧箭头图标（固定大小，不会超出）
        icon = IconWidget(FluentIcon.CHEVRON_RIGHT, self)
        icon.setFixedSize(14, 14)
        layout.addSpacing(12)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            self.itemClicked.emit(self.release)


# ─────────────────────── 列表页（内部用） ───────────────────────

class _ChangelogListPage(ScrollArea):
    """更新日志列表子页（由 ChangelogPage 托管）"""
    _releasesLoaded = Signal(list)
    detailRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._releasesLoaded.connect(self._on_releases_loaded)
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()
        self._build_ui()
        self._load_releases()

    def _build_ui(self):
        self._layout = QVBoxLayout(self.view)
        self._layout.setContentsMargins(36, 36, 36, 36)
        self._layout.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_label = SubtitleLabel("更新日志", self)
        header.addWidget(title_label)

        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(20, 20)
        self.spinner.setStrokeWidth(3)
        header.addWidget(self.spinner)
        header.addStretch(1)
        self._layout.addLayout(header)

        self.container = QVBoxLayout()
        self.container.setContentsMargins(0, 0, 0, 0)
        self.container.setSpacing(12)
        self._layout.addLayout(self.container)

        self._layout.addStretch(1)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        h_margin = max(24, min(int(self.width() * 0.04), 80))
        self._layout.setContentsMargins(h_margin, 36, h_margin, 36)

    def _load_releases(self):
        def _do_load():
            try:
                from software.update.updater import UpdateManager
                releases = UpdateManager.get_all_releases()
                self._releasesLoaded.emit(releases)
            except Exception:
                self._releasesLoaded.emit([])

        threading.Thread(target=_do_load, daemon=True).start()

    def _on_releases_loaded(self, releases: list):
        self.spinner.hide()

        if not releases:
            label = BodyLabel("暂无发行版信息", self)
            label.setStyleSheet("color: #888;")
            self.container.addWidget(label)
            return

        for release in releases:
            item = ReleaseListItem(release, self.view)
            item.itemClicked.connect(self.detailRequested.emit)
            self.container.addWidget(item)

    def save_scroll_pos(self) -> int:
        return self.verticalScrollBar().value()

    def restore_scroll_pos(self, pos: int):
        self.verticalScrollBar().setValue(pos)


# ─────────────────────── 详情页（内部用） ───────────────────────

class _ChangelogDetailPage(ScrollArea):
    """更新日志详情子页（由 ChangelogPage 托管）"""
    backRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()
        self._build_ui()

    def _build_ui(self):
        self._layout = QVBoxLayout(self.view)
        self._layout.setContentsMargins(36, 36, 36, 36)
        self._layout.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(16)
        back_btn = TransparentToolButton(FluentIcon.RETURN, self)
        back_btn.setFixedSize(36, 36)
        back_btn.setIconSize(QSize(16, 16))
        back_btn.clicked.connect(self.backRequested.emit)
        header.addWidget(back_btn)

        self.title_label = SubtitleLabel("", self)
        header.addWidget(self.title_label)
        header.addStretch(1)
        self._layout.addLayout(header)

        self.content_browser = TextBrowser(self)
        self.content_browser.setOpenExternalLinks(True)
        self.content_browser.setStyleSheet("border: none; background: transparent;")
        self._layout.addWidget(self.content_browser)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        h_margin = max(24, min(int(self.width() * 0.04), 80))
        self._layout.setContentsMargins(h_margin, 36, h_margin, 36)

    def setRelease(self, release: dict):
        version = release.get("version", "")
        body = release.get("body", "")
        self.title_label.setText(f"v{version}")
        processed_body = strip_markdown(body)

        html_style = """
        <style>
            body { line-height: 1.9; font-size: 14px; }
            p { margin-bottom: 10px; line-height: 1.9; }
            ul, ol { margin-top: 6px; margin-bottom: 10px; padding-left: 24px; }
            li { margin-bottom: 6px; line-height: 1.9; }
            h1, h2, h3, h4, h5, h6 { margin-top: 14px; margin-bottom: 10px; }
        </style>
        """
        self.content_browser.setMarkdown(processed_body)
        original_html = self.content_browser.toHtml()

        if "<head>" in original_html:
            final_html = original_html.replace("<head>", f"<head>{html_style}")
        else:
            final_html = f"<html><head>{html_style}</head><body>{original_html}</body></html>"

        self.content_browser.setHtml(final_html)
        # 详情页加载后滚动到顶部
        self.verticalScrollBar().setValue(0)


# ─────────────────────── 组合页（对外暴露） ───────────────────────

class ChangelogPage(QWidget):
    """
    更新日志主页面：内部用 DrillInTransitionStackedWidget 管理
    列表子页和详情子页，对外仍是一个普通 QWidget。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scroll_pos = 0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stacked = DrillInTransitionStackedWidget(self)

        self._list_page = _ChangelogListPage(self.stacked)
        self._detail_page = _ChangelogDetailPage(self.stacked)

        self.stacked.addWidget(self._list_page)
        self.stacked.addWidget(self._detail_page)

        # 连接信号
        self._list_page.detailRequested.connect(self._show_detail)
        self._detail_page.backRequested.connect(self._show_list)

        layout.addWidget(self.stacked)

    def _show_detail(self, release: dict):
        """点击列表项 -> 钻入详情页"""
        self._scroll_pos = self._list_page.save_scroll_pos()
        self._detail_page.setRelease(release)
        self.stacked.setCurrentWidget(self._detail_page, isBack=False)

    def _show_list(self):
        """点击返回 -> 退出详情页，恢复列表滚动位置"""
        self.stacked.setCurrentWidget(self._list_page, isBack=True)
        saved = self._scroll_pos
        # 等动画结束后恢复滚动位置（DrillIn 动画约 333ms）
        QTimer.singleShot(380, lambda: self._list_page.restore_scroll_pos(saved))


