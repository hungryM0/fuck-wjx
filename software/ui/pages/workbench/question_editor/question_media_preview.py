"""题目图片缩略图组件。"""

from __future__ import annotations

import ipaddress
import socket
from itertools import count
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ImageLabel

import software.network.http as http_client

from .utils import _apply_label_color

_MEDIA_THREAD_POOL = QThreadPool.globalInstance()
_MEDIA_MAX_BYTES = 5 * 1024 * 1024
_MEDIA_REQUEST_COUNTER = count(1)
_ACTIVE_MEDIA_WORKERS: set["_MediaLoaderWorker"] = set()
_MEDIA_QUIT_BOUND = False
_MEDIA_SHUTTING_DOWN = False


def _is_public_http_url(url: str) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parsed = urlsplit(text)
    except Exception:
        return False
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        return False
    hostname = str(parsed.hostname or "").strip()
    if not hostname:
        return False
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_global
    except ValueError:
        pass
    try:
        for family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(hostname, None):
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            raw_ip = sockaddr[0]
            try:
                if not ipaddress.ip_address(raw_ip).is_global:
                    return False
            except ValueError:
                return False
    except Exception:
        return False
    return True


class _MediaLoaderDispatcher(QObject):
    finished = Signal(int, str, bytes)


_MEDIA_DISPATCHER = _MediaLoaderDispatcher()


def _mark_media_shutdown() -> None:
    global _MEDIA_SHUTTING_DOWN
    _MEDIA_SHUTTING_DOWN = True


def _bind_media_shutdown_guard() -> None:
    global _MEDIA_QUIT_BOUND
    if _MEDIA_QUIT_BOUND:
        return
    app = QCoreApplication.instance()
    if app is None:
        return
    app.aboutToQuit.connect(_mark_media_shutdown)
    _MEDIA_QUIT_BOUND = True


class _MediaLoaderWorker(QRunnable):
    def __init__(self, request_id: int, url: str) -> None:
        super().__init__()
        self._request_id = int(request_id)
        self._url = str(url or "").strip()
        self.setAutoDelete(True)

    def run(self) -> None:
        data = b""
        try:
            if self._url and _is_public_http_url(self._url):
                try:
                    response = http_client.get(
                        self._url,
                        timeout=8,
                        proxies={},
                        allow_redirects=False,
                        stream=True,
                    )
                    try:
                        response.raise_for_status()
                        content_length = response.headers.get("content-length")
                        if content_length:
                            try:
                                if int(content_length) > _MEDIA_MAX_BYTES:
                                    data = b""
                                else:
                                    data = self._read_response_bytes(response)
                            except Exception:
                                data = self._read_response_bytes(response)
                        else:
                            data = self._read_response_bytes(response)
                    finally:
                        try:
                            response.close()
                        except Exception:
                            pass
                except Exception:
                    data = b""
            if _MEDIA_SHUTTING_DOWN:
                return
            try:
                _MEDIA_DISPATCHER.finished.emit(self._request_id, self._url, data)
            except RuntimeError:
                return
        finally:
            _ACTIVE_MEDIA_WORKERS.discard(self)

    @staticmethod
    def _read_response_bytes(response: Any) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MEDIA_MAX_BYTES:
                return b""
            chunks.append(bytes(chunk))
        return b"".join(chunks) if chunks else b""


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
        self._worker: Optional[_MediaLoaderWorker] = None
        self._fixed_size = max(40, int(fixed_size))
        self._destroyed = False
        self._request_id = 0

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
        _bind_media_shutdown_guard()
        _MEDIA_DISPATCHER.finished.connect(self._on_loaded)
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
        self._request_id = next(_MEDIA_REQUEST_COUNTER)
        self._worker = _MediaLoaderWorker(self._request_id, source_url)
        _ACTIVE_MEDIA_WORKERS.add(self._worker)
        _MEDIA_THREAD_POOL.start(self._worker)

    def _clear_loader_refs(self, *_args) -> None:
        self._worker = None

    def _on_loaded(self, request_id: int, _url: str, payload: bytes) -> None:
        if self._destroyed or int(request_id) != self._request_id:
            return
        self._clear_loader_refs()
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
