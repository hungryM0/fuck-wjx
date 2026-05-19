from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QByteArray, QBuffer, QEvent, QIODevice, QMimeData, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage, QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

import software.ui.pages.workbench.shared.clipboard as clipboard_module
from software.ui.pages.workbench.shared.clipboard import SurveyClipboardMixin


class _ClipboardHost(SurveyClipboardMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.link_card = QWidget(self)
        self.url_edit = SimpleNamespace(text="", setText=lambda value: setattr(self.url_edit, "text", value))
        self._link_entry_widgets = (self.link_card,)
        self._clipboard_parse_ticket = 0
        self.toasts: list[tuple[str, str]] = []
        self.parse_calls = 0
        self.processed: list[object] = []

    def _toast(self, text: str, level: str = "info") -> None:
        self.toasts.append((text, level))

    def _on_parse_clicked(self) -> None:
        self.parse_calls += 1


def _image() -> QImage:
    image = QImage(12, 12, QImage.Format.Format_RGB32)
    image.fill(QColor("blue"))
    return image


def _bmp_dib_bytes(image: QImage) -> QByteArray:
    data = QByteArray()
    buffer = QBuffer(data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "BMP")
    return QByteArray(bytes(data)[14:])


def test_clipboard_extracts_qimage_encoded_bytes_and_clipboard_fallback(qtbot, tmp_path) -> None:
    host = _ClipboardHost()
    qtbot.addWidget(host)
    image = _image()

    mime = QMimeData()
    mime.setImageData(image)
    assert isinstance(host._extract_image_from_clipboard(mime), QImage)

    encoded_path = tmp_path / "encoded.png"
    assert image.save(str(encoded_path))
    bytes_array = QByteArray(encoded_path.read_bytes())
    encoded_mime = QMimeData()
    encoded_mime.setData("image/png", bytes_array)
    assert isinstance(host._extract_image_from_clipboard(encoded_mime), QImage)

    dib_mime = QMimeData()
    dib_mime.setData('application/x-qt-windows-mime;value="DeviceIndependentBitmap"', _bmp_dib_bytes(image))
    assert isinstance(host._extract_image_from_clipboard(dib_mime), QImage)

    empty_mime = QMimeData()
    QApplication.clipboard().setImage(image)
    assert isinstance(host._extract_image_from_clipboard(empty_mime, QApplication.clipboard()), QImage)

    assert host._extract_qimage(QImage()) is None
    assert host._extract_image_from_clipboard(QMimeData()) is None


def test_clipboard_process_qrcode_success_empty_and_exception(monkeypatch, qtbot) -> None:
    host = _ClipboardHost()
    qtbot.addWidget(host)

    monkeypatch.setattr(clipboard_module, "decode_qrcode", lambda source: f"https://wjx.cn/{source}")
    host._process_qrcode_image("ok.png")
    assert host.url_edit.text == "https://wjx.cn/ok.png"
    assert host.parse_calls == 1

    monkeypatch.setattr(clipboard_module, "decode_qrcode", lambda _source: "")
    host._process_qrcode_image("empty.png")
    assert host.toasts[-1] == ("未能识别二维码中的链接", "error")

    monkeypatch.setattr(clipboard_module, "decode_qrcode", lambda _source: (_ for _ in ()).throw(RuntimeError("bad")))
    host._process_qrcode_image("bad.png")
    assert host.toasts[-1] == ("处理二维码图片失败：bad", "error")


def test_clipboard_drag_drop_and_keypress_paths(monkeypatch, qtbot, tmp_path) -> None:
    host = _ClipboardHost()
    qtbot.addWidget(host)
    image_path = tmp_path / "qr.png"
    image_path.write_text("not-real", encoding="utf-8")

    processed: list[object] = []
    monkeypatch.setattr(host, "_process_qrcode_image", lambda source: processed.append(source))

    url_mime = QMimeData()
    url_mime.setUrls([QUrl.fromLocalFile(str(image_path))])
    drag_event = QDragEnterEvent(
        QPoint(1, 1),
        Qt.DropAction.CopyAction,
        url_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert host.eventFilter(host.link_card, drag_event) is True
    assert drag_event.isAccepted()

    drop_event = QDropEvent(
        QPointF(1, 1),
        Qt.DropAction.CopyAction,
        url_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert host.eventFilter(host.link_card, drop_event) is True
    assert Path(processed[-1]) == image_path
    assert drop_event.isAccepted()

    image_mime = QMimeData()
    image_mime.setImageData(_image())
    image_drop = QDropEvent(
        QPointF(1, 1),
        Qt.DropAction.CopyAction,
        image_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert host.eventFilter(host.link_card, image_drop) is True
    assert isinstance(processed[-1], QImage)

    QApplication.clipboard().setMimeData(url_mime)
    key_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert host.eventFilter(host.link_card, key_event) is True
    assert Path(processed[-1]) == image_path

    assert host.eventFilter(QWidget(), key_event) is False


def test_clipboard_schedule_try_and_file_picker(monkeypatch, qtbot, tmp_path) -> None:
    host = _ClipboardHost()
    qtbot.addWidget(host)
    image = _image()
    QApplication.clipboard().setImage(image)
    monkeypatch.setattr(host, "_is_focus_in_link_entry", lambda: True)
    monkeypatch.setattr(clipboard_module.QTimer, "singleShot", lambda _delay, callback: callback())
    processed: list[object] = []
    monkeypatch.setattr(host, "_process_qrcode_image", lambda source: processed.append(source))

    host._schedule_clipboard_parse(delay_ms=1, retries=0)
    assert isinstance(processed[-1], QImage)

    stale_ticket = host._clipboard_parse_ticket - 1
    before = len(processed)
    host._try_process_clipboard_image(stale_ticket, retries=0)
    assert len(processed) == before

    path = tmp_path / "qr.jpg"
    path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(clipboard_module, "get_user_local_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(clipboard_module.QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(path), ""))
    host._on_qr_clicked()
    assert processed[-1] == str(path)

    monkeypatch.setattr(clipboard_module.QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: ("", ""))
    before = len(processed)
    host._on_qr_clicked()
    assert len(processed) == before
