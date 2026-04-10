"""二维码生成与处理工具。"""
import logging
import os
from typing import Optional

from PySide6.QtGui import QImage

import zxingcpp


def _load_qimage(image_path: str) -> QImage:
    """从文件路径读取 QImage。"""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    image = QImage(image_path)
    if image.isNull():
        raise ValueError(f"无法读取图片: {image_path}")

    return image


def decode_qrcode(image_source: object) -> Optional[str]:
    """
    解码二维码图片，提取其中的链接。

    参数:
        image_source: 图片文件路径(str) 或 zxing-cpp 支持的图像对象
            （如 numpy 数组、PIL Image、QImage）

    返回:
        str: 解码出的数据；如果解码失败返回 None

    示例:
        >>> url = decode_qrcode("qrcode.png")
    """
    try:
        if isinstance(image_source, str):
            image = _load_qimage(image_source)
        elif isinstance(image_source, QImage):
            if image_source.isNull():
                raise ValueError("图片数据为空")
            image = image_source
        else:
            image = image_source

        result = zxingcpp.read_barcode(
            image,
            zxingcpp.BarcodeFormat.QRCode,
            try_rotate=True,
            try_downscale=True,
            try_invert=True,
        )

        if result and result.valid and result.text:
            return result.text

        return None

    except Exception as exc:
        logging.error(f"二维码解码失败: {exc}")
        return None
