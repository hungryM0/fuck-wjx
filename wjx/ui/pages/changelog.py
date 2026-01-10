"""更新日志页面"""
import re
import threading
from datetime import datetime

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
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


def _convert_github_admonitions(text: str) -> str:
    """将 GitHub Flavored Markdown 的 admonition 语法转换为标准格式"""
    admonition_map = {
        "NOTE": "**注意：**",
        "TIP": "**提示：**",
        "IMPORTANT": "**重要：**",
        "WARNING": "**警告：**",
        "CAUTION": "**警告：**",
    }
    
    def replace_multiline(match):
        admonition_type = match.group(1).upper()
        content_lines = match.group(2)
        content = re.sub(r'^>\s?', '', content_lines, flags=re.MULTILINE).strip()
        prefix = admonition_map.get(admonition_type, f"**{admonition_type}：**")
        return f"{prefix}\n\n{content}"
    
    pattern = r'>\s*\[!(\w+)\]\s*\n((?:>.*\n?)*)'
    text = re.sub(pattern, replace_multiline, text)
    
    def replace_admonition(match):
        admonition_type = match.group(1).upper()
        content = match.group(2).strip()
        prefix = admonition_map.get(admonition_type, f"**{admonition_type}：**")
        return f"{prefix} {content}"
    
    single_pattern = r'>\s*\[!(\w+)\]\s*(.+)'
    text = re.sub(single_pattern, replace_admonition, text)
    
    return text


class ReleaseCard(CardWidget):
    """单个发行版卡片，支持展开/折叠"""
    
    def __init__(self, version: str, date: str, body: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._expanded = expanded
        self._body = body
        self._build_ui(version, date)
        self.setExpanded(expanded)
    
    def _build_ui(self, version: str, date: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        header = QHBoxLayout()
        header.setSpacing(8)
        
        self.expand_btn = TransparentToolButton(FluentIcon.CHEVRON_RIGHT_MED, self)
        self.expand_btn.setFixedSize(24, 24)
        self.expand_btn.clicked.connect(self._toggle)
        header.addWidget(self.expand_btn)
        
        title = BodyLabel(f"v{version}", self)
        title.setStyleSheet("font-weight: bold;")
        header.addWidget(title)
        
        date_label = BodyLabel(date, self)
        date_label.setStyleSheet("color: #888;")
        header.addWidget(date_label)
        header.addStretch(1)
        
        layout.addLayout(header)
        
        self.content = TextBrowser(self)
        processed_body = _convert_github_admonitions(self._body) if self._body else "暂无更新说明"
        self.content.setMarkdown(processed_body)
        self.content.setOpenExternalLinks(True)
        self.content.setStyleSheet("border: none; background: transparent; padding-left: 32px;")
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.content)
    
    def showEvent(self, event):
        """显示时调整高度"""
        super().showEvent(event)
        self._adjust_content_height()
    
    def resizeEvent(self, event):
        """窗口大小改变时调整高度"""
        super().resizeEvent(event)
        if self._expanded:
            self._adjust_content_height()
    
    def _adjust_content_height(self):
        """根据内容自动调整高度，最大300px"""
        self.content.document().setTextWidth(self.content.viewport().width())
        doc_height = self.content.document().size().height()
        height = min(int(doc_height) + 10, 300)
        self.content.setFixedHeight(height)
    
    def _toggle(self):
        self.setExpanded(not self._expanded)
    
    def setExpanded(self, expanded: bool):
        self._expanded = expanded
        self.content.setVisible(expanded)
        icon = FluentIcon.CHEVRON_DOWN_MED if expanded else FluentIcon.CHEVRON_RIGHT_MED
        self.expand_btn.setIcon(icon)


class ChangelogPage(ScrollArea):
    """更新日志页面"""

    _releasesLoaded = Signal(list)

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
                from wjx.utils.updater import UpdateManager
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
        
        for i, release in enumerate(releases):
            version = release.get("version", "")
            body = release.get("body", "")
            published = release.get("published_at", "")
            
            date_str = ""
            if published:
                try:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = published[:10] if len(published) >= 10 else published
            
            card = ReleaseCard(version, date_str, body, expanded=(i == 0), parent=self.view)
            self.container.addWidget(card)
