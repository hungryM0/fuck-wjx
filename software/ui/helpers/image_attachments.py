"""图片附件处理 - 校验、限制、缩略图与导出"""
import os
from dataclasses import dataclass
from typing import List, Tuple

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap


@dataclass
class ImageAttachment:
  name: str
  mime: str
  data: bytes
  pixmap: QPixmap


class ImageAttachmentManager:
  """管理图片附件：校验、限制、生成缩略图、导出 requests files。"""

  def __init__(self, max_count: int = 3, max_size_bytes: int = 10 * 1024 * 1024):
    self.max_count = max_count
    self.max_size_bytes = max_size_bytes
    self.attachments: List[ImageAttachment] = []

  def clear(self):
    self.attachments.clear()

  def remove_at(self, index: int):
    if 0 <= index < len(self.attachments):
      self.attachments.pop(index)

  def _ensure_capacity(self):
    if len(self.attachments) >= self.max_count:
      return False, f"最多仅支持 {self.max_count} 张图片"
    return True, ""

  def _make_thumb(self, image: QImage) -> QPixmap:
    pixmap = QPixmap.fromImage(image)
    if pixmap.isNull():
      return QPixmap()
    return pixmap.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

  def add_qimage(self, image: QImage, name_hint: str = "clipboard.png"):
    ok, msg = self._ensure_capacity()
    if not ok:
      return False, msg
    if image.isNull():
      return False, "剪贴板内容不是有效图片"

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    saved = image.save(buffer, b"PNG")
    if not saved:
      return False, "图片保存失败"
    data = bytes(bytearray(buffer.data()))  # type: ignore[arg-type]
    if len(data) > self.max_size_bytes:
      return False, "图片超过 10MB 限制"

    thumb = self._make_thumb(image)
    self.attachments.append(
      ImageAttachment(name=name_hint or "clipboard.png", mime="image/png", data=data, pixmap=thumb)
    )
    return True, ""

  def add_file_path(self, path: str):
    ok, msg = self._ensure_capacity()
    if not ok:
      return False, msg
    if not path or not os.path.exists(path):
      return False, "文件不存在"

    reader = QImageReader(path)
    image = reader.read()
    if image.isNull():
      return False, "请选择有效的图片文件"

    try:
      with open(path, "rb") as f:
        data = f.read()
    except Exception:
      return False, "读取文件失败"

    if len(data) > self.max_size_bytes:
      return False, "图片超过 10MB 限制"

    fmt = bytearray(reader.format() or b"").decode("utf-8").lower()  # type: ignore[arg-type]
    mime = f"image/{fmt}" if fmt else "image/png"
    name = os.path.basename(path) or "image"
    thumb = self._make_thumb(image)

    self.attachments.append(ImageAttachment(name=name, mime=mime, data=data, pixmap=thumb))
    return True, ""

  def files_payload(self) -> List[Tuple[str, Tuple[str, bytes, str]]]:
    payload: List[Tuple[str, Tuple[str, bytes, str]]] = []
    for idx, att in enumerate(self.attachments, start=1):
      field = f"file{idx}"
      payload.append((field, (att.name, att.data, att.mime)))
    return payload
