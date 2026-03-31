"""二维码生成与处理工具"""
import logging
import os
from typing import Optional, Union

import cv2
import numpy as np


def decode_qrcode(image_source: Union[str, np.ndarray]) -> Optional[str]:
    """
    解码二维码图片，提取其中的链接。

    参数:
        image_source: 图片文件路径(str) 或 OpenCV/numpy 图像数组 (np.ndarray)

    返回:
        str: 解码出的数据；如果解码失败返回 None

    示例:
        >>> url = decode_qrcode("qrcode.png")
        >>> url = decode_qrcode(cv2.imread("qrcode.png"))
    """
    try:
        if isinstance(image_source, str):
            if not os.path.exists(image_source):
                raise FileNotFoundError(f"图片文件不存在: {image_source}")
            # cv2.imdecode 支持中文路径，比 cv2.imread 更健壮
            buf = np.fromfile(image_source, dtype=np.uint8)
            img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError(f"无法读取图片: {image_source}")
        elif isinstance(image_source, np.ndarray):
            img = image_source
        else:
            raise TypeError(f"不支持的图片类型: {type(image_source)}")

        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(img)

        if data:
            return data

        return None

    except Exception as e:
        logging.error(f"二维码解码失败: {e}")
        return None
