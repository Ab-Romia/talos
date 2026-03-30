import base64
from io import BytesIO

from PIL.Image import Image
from qrcode.image.pil import PilImage


def img2base64(img: Image | PilImage) -> str:
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    b = buffered.getvalue()
    return "data:image/png;base64," + base64.b64encode(b).decode()
