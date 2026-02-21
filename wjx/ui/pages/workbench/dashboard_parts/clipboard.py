"""DashboardPage 剪贴板/拖拽二维码处理方法。"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QEvent, QMimeData, QTimer
from PySide6.QtGui import QClipboard, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog

from wjx.utils.io.load_save import get_runtime_directory
from wjx.utils.io.qrcode_utils import decode_qrcode
from wjx.utils.logging.log_utils import log_suppressed_exception


class DashboardClipboardMixin:
    """处理拖放、粘贴与二维码解析。"""

    if TYPE_CHECKING:
        from typing import Any
        _toast: Any
        url_edit: Any
        _on_parse_clicked: Any
        link_card: Any
        _clipboard_parse_ticket: int
        _link_entry_widgets: Any

    def eventFilter(self, watched, event):
        """处理拖放和粘贴事件"""
        if watched in getattr(self, "_link_entry_widgets", ()):
            # 处理拖入事件
            if event.type() == QEvent.Type.DragEnter:
                if isinstance(event, QDragEnterEvent):
                    mime_data = event.mimeData()
                    # 接受图片文件或图片数据
                    if mime_data.hasUrls() or mime_data.hasImage():
                        event.acceptProposedAction()
                        return True
                return False

            # 处理放下事件
            if event.type() == QEvent.Type.Drop:
                if isinstance(event, QDropEvent):
                    mime_data = event.mimeData()

                    # 优先处理文件路径
                    if mime_data.hasUrls():
                        urls = mime_data.urls()
                        if urls:
                            file_path = urls[0].toLocalFile()
                            if file_path and os.path.exists(file_path):
                                # 检查是否为图片文件
                                if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                                    self._process_qrcode_image(file_path)
                                    event.acceptProposedAction()
                                    return True

                    # 处理直接拖入的图片数据（兼容微信 MIME）
                    nd_image = self._extract_ndarray_from_clipboard(mime_data)
                    if nd_image is not None:
                        self._process_qrcode_image(nd_image)
                        event.acceptProposedAction()
                        return True
                return False

            # 处理粘贴事件（Ctrl+V）
            if event.type() == QEvent.Type.KeyPress:
                from PySide6.QtCore import Qt
                from PySide6.QtGui import QKeyEvent
                from PySide6.QtWidgets import QApplication

                if isinstance(event, QKeyEvent):
                    if event.key() == Qt.Key.Key_V and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        clipboard = QApplication.clipboard()
                        mime_data = clipboard.mimeData(QClipboard.Mode.Clipboard)
                        # 剪贴板有图片时拦截粘贴，转为二维码解析（兼容微信剪贴板格式）
                        pil_image = self._extract_ndarray_from_clipboard(mime_data, clipboard)
                        if pil_image is not None:
                            try:
                                # 递增 ticket，使 _on_clipboard_changed 的延迟任务失效，避免重复触发
                                self._clipboard_parse_ticket += 1
                                self._process_qrcode_image(pil_image)
                            except Exception:
                                pass
                            return True  # 拦截默认粘贴行为
                        # 剪贴板有图片文件路径时也处理（仅当没有图片数据时）
                        if mime_data.hasUrls():
                            urls = mime_data.urls()
                            if urls:
                                file_path = urls[0].toLocalFile()
                                if file_path and os.path.exists(file_path):
                                    if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                                        self._process_qrcode_image(file_path)
                                        return True

        return super().eventFilter(watched, event)  # type: ignore[attr-defined]

    def _on_clipboard_changed(self):
        """监听剪贴板变化，自动处理粘贴的图片"""
        # 仅当“问卷入口”卡片区域内控件获得焦点时才处理剪贴板
        if not self._is_focus_in_link_entry():
            return

        # 延迟读取剪贴板，避免系统尚未准备好时触发 Qt Warning
        self._schedule_clipboard_parse(delay_ms=30, retries=3)

    def _schedule_clipboard_parse(self, delay_ms: int = 30, retries: int = 3):
        self._clipboard_parse_ticket += 1
        ticket = self._clipboard_parse_ticket

        def _run():
            self._try_process_clipboard_image(ticket, retries)

        QTimer.singleShot(delay_ms, _run)

    def _try_process_clipboard_image(self, ticket: int, retries: int):
        # 只处理最新一次请求，旧任务直接丢弃
        if ticket != self._clipboard_parse_ticket:
            return
        if not self._is_focus_in_link_entry():
            return

        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData(QClipboard.Mode.Clipboard)
        if mime_data is None:
            if retries > 0:
                self._schedule_clipboard_parse(delay_ms=50, retries=retries - 1)
            return

        pil_image = self._extract_ndarray_from_clipboard(mime_data, clipboard)
        if pil_image is not None:
            try:
                self._process_qrcode_image(pil_image)
            except Exception:
                pass  # 图片处理失败，静默忽略

    def _is_focus_in_link_entry(self) -> bool:
        from PySide6.QtWidgets import QApplication

        focus_widget = QApplication.focusWidget()
        if focus_widget is None:
            return False
        current = focus_widget
        while current is not None:
            if current is self.link_card:
                return True
            current = current.parentWidget()
        return False

    def _qimage_to_ndarray(self, image):
        """将 QImage 安全转换为 OpenCV 兼容的 numpy ndarray (BGR)。"""
        import numpy as np
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QImage

        if not isinstance(image, QImage) or image.isNull():
            return None
        # 统一转换为 RGBA8888 以获得固定字节布局
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width, height = image.width(), image.height()
        ptr = image.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((height, width, 4))
        # RGBA -> BGR（OpenCV 默认格式）
        return arr[:, :, [2, 1, 0]].copy()

    def _extract_ndarray_from_clipboard(self, mime_data: QMimeData, clipboard: Optional[QClipboard] = None):
        """从剪贴板数据提取 OpenCV numpy ndarray，兼容微信常见图片格式。"""
        import numpy as np

        # 普通图片剪贴板（截图工具、浏览器等）
        if mime_data.hasImage():
            image = mime_data.imageData()
            nd = self._qimage_to_ndarray(image)
            if nd is not None:
                return nd

        # 微信等应用在 Windows 下可能使用自定义 MIME（PNG / DIB）
        windows_image_formats = [
            'application/x-qt-windows-mime;value="PNG"',
            'application/x-qt-windows-mime;value="DeviceIndependentBitmap"',
            "image/png",
            "image/bmp",
            "image/jpeg",
        ]
        for fmt in windows_image_formats:
            try:
                import cv2
                raw = mime_data.data(fmt)
                if raw.isEmpty():
                    continue
                buf = np.frombuffer(raw.data(), dtype=np.uint8)
                img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                if img is not None:
                    return img
            except Exception:
                continue

        # 兜底：有些来源能从 clipboard.image() 取到图，但 hasImage() 为 False
        if clipboard is not None:
            try:
                image = clipboard.image()
                nd = self._qimage_to_ndarray(image)
                if nd is not None:
                    return nd
            except Exception as exc:
                log_suppressed_exception("_extract_ndarray_from_clipboard: clipboard.image()", exc, level=logging.DEBUG)

        return None

    def _process_qrcode_image(self, image_source):
        """处理二维码图片（文件路径或PIL Image对象）"""
        try:
            url = decode_qrcode(image_source)
            if not url:
                self._toast("未能识别二维码中的链接", "error")
                return

            # 设置链接到输入框
            self.url_edit.setText(url)
            # 自动触发解析
            self._on_parse_clicked()
        except Exception as exc:
            self._toast(f"处理二维码图片失败：{exc}", "error")
            log_suppressed_exception("_process_qrcode_image", exc, level=logging.WARNING)

    def _on_qr_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择二维码图片", get_runtime_directory(), "含有二维码的图片 (*.png *.jpg *.jpeg *.bmp)")  # type: ignore[arg-type]
        if not path:
            return
        self._process_qrcode_image(path)
