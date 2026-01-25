import logging
import os
from typing import Optional, Union

from PIL import Image
from pyzbar.pyzbar import decode as pyzbar_decode


def decode_qrcode(image_source: Union[str, Image.Image]) -> Optional[str]:
    """
    解码二维码图片,提取其中的链接

    参数:
        image_source: 图片文件路径(str)或PIL Image对象

    返回:
        str: 解码出的链接,如果解码失败返回None

    示例:
        >>> url = decode_qrcode("qrcode.png")
        >>> url = decode_qrcode(Image.open("qrcode.png"))
    """
    try:
        # 如果是文件路径,打开图片
        if isinstance(image_source, str):
            if not os.path.exists(image_source):
                raise FileNotFoundError(f"图片文件不存在: {image_source}")
            image = Image.open(image_source)
        else:
            image = image_source

        # 解码二维码
        decoded_objects = pyzbar_decode(image)

        if not decoded_objects:
            return None

        # 获取第一个二维码的数据
        qr_data = decoded_objects[0].data.decode("utf-8")

        # 验证是否为有效URL
        if qr_data.startswith(("http://", "https://", "www.")):
            return qr_data

        return qr_data

    except Exception as e:
        logging.error(f"二维码解码失败: {str(e)}")
        return None
