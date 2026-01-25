"""更新日志页面"""
import threading
from datetime import datetime

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    IndeterminateProgressRing,
    FluentIcon,
    TransparentToolButton,
    TextBrowser,
)

from wjx.utils.io.markdown_utils import strip_markdown


class ReleaseListItem(CardWidget):
    """发行版列表项"""
    itemClicked = Signal(dict)
    
    def __init__(self, release: dict, parent=None):
        super().__init__(parent)
        self.release = release
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()
    
    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        
        icon = TransparentToolButton(FluentIcon.CHEVRON_RIGHT_MED, self)
        icon.setFixedSize(24, 24)
        icon.setEnabled(False)
        layout.addWidget(icon)
        
        version = self.release.get("version", "")
        title = BodyLabel(f"v{version}", self)
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        
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
        layout.addWidget(date_label)
        layout.addStretch(1)
    
    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            self.itemClicked.emit(self.release)


class ChangelogPage(ScrollArea):
    """更新日志列表页"""
    _releasesLoaded = Signal(list)
    detailRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._releasesLoaded.connect(self._on_releases_loaded)
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._build_ui()
        self._load_releases()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(SubtitleLabel("更新日志", self))
        
        header = QHBoxLayout()
        header.setSpacing(8)
        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(18, 18)
        self.spinner.setStrokeWidth(2)
        header.addWidget(self.spinner)
        header.addStretch(1)
        layout.addLayout(header)
        
        self.container = QVBoxLayout()
        self.container.setSpacing(8)
        layout.addLayout(self.container)
        
        layout.addStretch(1)

    def _load_releases(self):
        """异步加载发行版列表"""
        def _do_load():
            try:
                from wjx.utils.update.updater import UpdateManager
                releases = UpdateManager.get_all_releases()
                self._releasesLoaded.emit(releases)
            except Exception:
                self._releasesLoaded.emit([])
        
        threading.Thread(target=_do_load, daemon=True).start()

    def _on_releases_loaded(self, releases: list):
        """处理发行版加载完成"""
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


class ChangelogDetailPage(ScrollArea):
    """更新日志详情页"""
    backRequested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        header = QHBoxLayout()
        back_btn = TransparentToolButton(FluentIcon.RETURN, self)
        back_btn.setFixedSize(32, 32)
        back_btn.clicked.connect(self.backRequested.emit)
        header.addWidget(back_btn)
        
        self.title_label = SubtitleLabel("", self)
        header.addWidget(self.title_label)
        header.addStretch(1)
        layout.addLayout(header)
        
        self.content_browser = TextBrowser(self)
        self.content_browser.setOpenExternalLinks(True)
        self.content_browser.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.content_browser)
    
    def setRelease(self, release: dict):
        version = release.get("version", "")
        body = release.get("body", "")
        self.title_label.setText(f"v{version}")
        processed_body = strip_markdown(body)
        self.content_browser.setMarkdown(processed_body)
