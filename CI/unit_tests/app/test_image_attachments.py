from __future__ import annotations

from PySide6.QtGui import QImage

from software.ui.helpers.image_attachments import ImageAttachmentManager


class ImageAttachmentManagerTests:
    def test_add_qimage_generates_png_payload_and_capacity_error(self, qapp) -> None:
        _ = qapp
        manager = ImageAttachmentManager(max_count=1)
        image = QImage(12, 10, QImage.Format.Format_ARGB32)
        image.fill(0xFF336699)

        ok, message = manager.add_qimage(image, "clip.png")
        assert ok is True
        assert message == ""
        assert len(manager.attachments) == 1
        assert manager.attachments[0].name == "clip.png"
        assert manager.attachments[0].mime == "image/png"
        assert manager.files_payload()[0][0] == "file1"

        ok, message = manager.add_qimage(image, "second.png")
        assert ok is False
        assert "最多仅支持 1 张图片" in message

    def test_add_qimage_rejects_null_and_oversized_images(self, qapp) -> None:
        _ = qapp
        manager = ImageAttachmentManager(max_size_bytes=1)

        ok, message = manager.add_qimage(QImage())
        assert ok is False
        assert message == "剪贴板内容不是有效图片"

        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(0xFFFFFFFF)
        ok, message = manager.add_qimage(image)
        assert ok is False
        assert message == "图片超过 10MB 限制"

    def test_add_file_path_handles_missing_invalid_valid_and_remove_clear(self, qapp, tmp_path) -> None:
        _ = qapp
        manager = ImageAttachmentManager(max_count=3)

        ok, message = manager.add_file_path("")
        assert ok is False
        assert message == "文件不存在"

        invalid = tmp_path / "bad.png"
        invalid.write_text("not image", encoding="utf-8")
        ok, message = manager.add_file_path(str(invalid))
        assert ok is False
        assert message == "请选择有效的图片文件"

        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(0xFF000000)
        valid = tmp_path / "ok.png"
        assert image.save(str(valid))

        ok, message = manager.add_file_path(str(valid))
        assert ok is True
        assert message == ""
        assert manager.attachments[0].name == "ok.png"
        assert manager.attachments[0].mime == "image/png"

        manager.remove_at(99)
        assert len(manager.attachments) == 1
        manager.remove_at(0)
        assert manager.attachments == []

        manager.add_file_path(str(valid))
        manager.clear()
        assert manager.files_payload() == []

    def test_add_file_path_rejects_oversized_file(self, qapp, tmp_path) -> None:
        _ = qapp
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(0xFF000000)
        valid = tmp_path / "big.png"
        assert image.save(str(valid))

        manager = ImageAttachmentManager(max_size_bytes=1)
        ok, message = manager.add_file_path(str(valid))

        assert ok is False
        assert message == "图片超过 10MB 限制"
