import io

import pytest
from PIL import Image

from app.services.image_prep import _sniff_format, prepare


def _png_bytes(size=(800, 600), color=(255, 255, 255)) -> bytes:
    im = Image.new("RGB", size, color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _jpg_bytes(size=(800, 600)) -> bytes:
    im = Image.new("RGB", size, (200, 200, 200))
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    return buf.getvalue()


def test_sniff_png():
    assert _sniff_format(_png_bytes(), "x.png") == "png"


def test_sniff_jpg():
    assert _sniff_format(_jpg_bytes(), "x.jpg") == "jpg"


def test_sniff_drawio_xml():
    data = b'<?xml version="1.0"?><mxfile></mxfile>'
    assert _sniff_format(data, "x.drawio") == "drawio"


def test_prepare_png_single_page():
    fmt, pages = prepare(_png_bytes(), "test.png")
    assert fmt == "png"
    assert len(pages) == 1
    assert pages[0].width == 800
    assert pages[0].source_format == "png"


def test_prepare_jpg_single_page():
    fmt, pages = prepare(_jpg_bytes(), "test.jpg")
    assert fmt == "jpg"
    assert len(pages) == 1


def test_prepare_drawio_raises_helpful_error():
    data = b'<?xml version="1.0"?><mxfile></mxfile>'
    with pytest.raises(ValueError, match="draw.io"):
        prepare(data, "test.drawio")


def test_prepare_downscales_large_images():
    fmt, pages = prepare(_png_bytes(size=(8000, 4500)), "big.png")
    assert max(pages[0].width, pages[0].height) <= 4096
