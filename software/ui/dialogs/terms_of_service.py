"""服务条款对话框。"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QGuiApplication
from qfluentwidgets import (
    ScrollArea,
    BodyLabel,
    TitleLabel,
    MessageBoxBase,
)

from software.app.runtime_paths import get_resource_path


LEGAL_TEXT_FILES = (
    "software/assets/legal/service_terms.txt",
    "software/assets/legal/privacy_statement.txt",
)


def _read_legal_text(relative_path: str) -> str:
    """读取法律文本文件，缺失时给出可读提示。"""
    full_path = get_resource_path(relative_path)
    try:
        with open(full_path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except OSError:
        return (
            "【文件缺失】\n\n"
            f"未找到条款文件：{relative_path}\n"
            "请检查安装包是否完整。"
        )


def _load_terms_content() -> str:
    sections = [_read_legal_text(path) for path in LEGAL_TEXT_FILES]
    return "\n\n".join(section for section in sections if section).strip()


def _resolve_dialog_size(parent) -> QSize:
    """根据父窗口或屏幕大小，计算中等尺寸的条款弹窗。"""
    if parent is not None and parent.width() > 0 and parent.height() > 0:
        base_width = parent.width()
        base_height = parent.height()
    else:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            base_width = geometry.width()
            base_height = geometry.height()
        else:
            base_width = 1280
            base_height = 800

    width = min(1000, max(860, int(base_width * 0.78)))
    height = min(700, max(620, int(base_height * 0.78)))
    return QSize(width, height)


class TermsOfServiceDialog(MessageBoxBase):
    """服务条款弹窗，按官方推荐使用 MessageBoxBase 承载自定义内容。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("服务条款")

        self.titleLabel = TitleLabel("服务条款与隐私声明", self.widget)
        self.titleLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.contentWidget = BodyLabel(self.widget)
        self.contentWidget.setWordWrap(True)
        self.contentWidget.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.contentWidget.setText(_load_terms_content())
        self.contentWidget.setStyleSheet(
            """
            BodyLabel {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 15px;
                line-height: 1.6;
                padding: 12px;
            }
            """
        )

        self.scrollArea.setWidget(self.contentWidget)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.scrollArea, 1)

        self.yesButton.setText("关闭")
        self.hideCancelButton()
        self.widget.setFixedSize(_resolve_dialog_size(parent))
