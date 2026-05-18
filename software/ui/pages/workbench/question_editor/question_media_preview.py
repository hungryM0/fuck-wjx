"""题目图片缩略图组件。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ImageLabel

import software.network.http as http_client

from .utils import _apply_label_color

_ACTIVE_MEDIA_THREADS: set[QThread] = set()


class _MediaLoaderWorker(QObject):
    finished = Signal(str, bytes)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = str(url or "").strip()

    def run(self) -> None:
        data = b""
        if self._url:
            try:
                response = http_client.get(self._url, timeout=8, proxies={})
                response.raise_for_status()
                data = bytes(response.content or b"")
            except Exception:
                data = b""
        self.finished.emit(self._url, data)


class QuestionMediaThumbnail(QWidget):
    def __init__(
        self,
        media_item: Dict[str, Any],
        *,
        fixed_size: int = 72,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._media_item = dict(media_item or {})
        self._thread: Optional[QThread] = None
        self._worker: Optional[_MediaLoaderWorker] = None
        self._fixed_size = max(40, int(fixed_size))
        self._destroyed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.image_label = ImageLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(self._fixed_size, self._fixed_size)
        self.image_label.setStyleSheet(
            "border: 1px solid rgba(128, 128, 128, 0.24); border-radius: 6px; background: transparent;"
        )
        layout.addWidget(self.image_label, 0, Qt.AlignmentFlag.AlignLeft)

        label_text = str(self._media_item.get("label") or "").strip()
        self.text_label = BodyLabel(label_text, self)
        self.text_label.setWordWrap(True)
        self.text_label.setMaximumWidth(self._fixed_size + 28)
        self.text_label.setStyleSheet("font-size: 12px;")
        _apply_label_color(self.text_label, "#666666", "#bfbfbf")
        layout.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignLeft)

        self._set_placeholder()
        self._load_async()
        self.destroyed.connect(self._mark_destroyed)

    def _mark_destroyed(self) -> None:
        self._destroyed = True

    def _set_placeholder(self) -> None:
        self.image_label.setText("图片")
        self.image_label.setStyleSheet(
            "border: 1px solid rgba(128, 128, 128, 0.24); border-radius: 6px; background: transparent; font-size: 12px; color: #888888;"
        )

    def _load_async(self) -> None:
        source_url = str(self._media_item.get("source_url") or "").strip()
        if not source_url:
            return
        self._thread = QThread()
        self._worker = _MediaLoaderWorker(source_url)
        _ACTIVE_MEDIA_THREADS.add(self._thread)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_loaded)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(lambda thread=self._thread: _ACTIVE_MEDIA_THREADS.discard(thread))
        self._thread.finished.connect(self._clear_loader_refs)
        self._thread.start()

    def _clear_loader_refs(self) -> None:
        self._thread = None
        self._worker = None

    def _on_loaded(self, _url: str, payload: bytes) -> None:
        if self._destroyed:
            return
        if not payload:
            return
        image = QImage()
        if not image.loadFromData(payload):
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.setText("")


class QuestionMediaStrip(CardWidget):
    def __init__(
        self,
        title: str,
        media_items: list[Dict[str, Any]],
        *,
        fixed_size: int = 72,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        title_label = BodyLabel(title, self)
        title_label.setStyleSheet("font-size: 12px;")
        _apply_label_color(title_label, "#666666", "#bfbfbf")
        layout.addWidget(title_label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        for item in media_items:
            row.addWidget(QuestionMediaThumbnail(item, fixed_size=fixed_size, parent=self))
        row.addStretch(1)
        layout.addLayout(row)
