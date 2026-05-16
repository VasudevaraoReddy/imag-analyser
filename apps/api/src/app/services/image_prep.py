"""Preprocess raw uploads into normalized RGB PNG pages.

Accepts PNG, JPG/JPEG, WEBP, BMP, GIF (first frame), SVG, PDF, and
draw.io XML (best-effort; falls back to a clear 415 if unrenderable).

Returns a list of pages with metadata. For single-page inputs the list
has length 1.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import List, Tuple

from PIL import Image, ImageOps

MAX_DIM = 4096
SVG_RENDER_WIDTH = 1600
PDF_DPI = 200


@dataclass
class PreparedPage:
    png_bytes: bytes
    width: int
    height: int
    page_index: int  # zero-based
    source_format: str  # png|jpg|svg|pdf|drawio|unknown


def _sniff_format(data: bytes, filename: str) -> str:
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if len(data) >= 4 and data[:4] == b"%PDF":
        return "pdf"
    if len(data) >= 4 and data[:4] in (b"GIF8",):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 2 and data[:2] == b"BM":
        return "bmp"
    # SVG/draw.io are text-based
    head = data[:512].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        if b"<svg" in data[:2048].lower():
            return "svg"
        if b"<mxfile" in data[:2048].lower() or b"mxGraphModel" in data[:4096]:
            return "drawio"
    if filename.lower().endswith(".drawio"):
        return "drawio"
    return "unknown"


def _is_photo_like(img: Image.Image) -> bool:
    """Detect photo/whiteboard inputs via histogram entropy.

    Clean exports (Lucid, draw.io) are mostly flat-color so the histogram
    is concentrated. Photos spread energy across many bins.
    """
    gray = img.convert("L")
    hist = gray.histogram()
    total = sum(hist) or 1
    entropy = 0.0
    for h in hist:
        if h == 0:
            continue
        p = h / total
        entropy -= p * math.log2(p)
    return entropy > 6.0


def _downscale(img: Image.Image, max_dim: int = MAX_DIM) -> Image.Image:
    w, h = img.size
    m = max(w, h)
    if m <= max_dim:
        return img
    scale = max_dim / m
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _pil_to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _prepare_pil(img: Image.Image, page_index: int, source: str) -> PreparedPage:
    img = ImageOps.exif_transpose(img) or img
    if img.mode != "RGB":
        img = img.convert("RGB")
    img = _downscale(img)
    if _is_photo_like(img):
        img = ImageOps.autocontrast(img, cutoff=1)
    png = _pil_to_png(img)
    return PreparedPage(
        png_bytes=png,
        width=img.size[0],
        height=img.size[1],
        page_index=page_index,
        source_format=source,
    )


def _render_svg(data: bytes) -> Image.Image:
    try:
        import cairosvg  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise ValueError(
            "SVG rendering is unavailable. Install cairosvg or export the diagram as PNG."
        ) from e
    png_bytes = cairosvg.svg2png(bytestring=data, output_width=SVG_RENDER_WIDTH)
    return Image.open(io.BytesIO(png_bytes))


def _render_pdf(data: bytes) -> List[Image.Image]:
    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise ValueError(
            "PDF rendering is unavailable. Install pypdfium2 or export the diagram as PNG."
        ) from e
    pdf = pdfium.PdfDocument(data)
    pages: List[Image.Image] = []
    scale = PDF_DPI / 72.0
    for i in range(len(pdf)):
        page = pdf[i]
        pil = page.render(scale=scale).to_pil()
        pages.append(pil)
    return pages


def prepare(file_bytes: bytes, filename: str) -> Tuple[str, List[PreparedPage]]:
    """Return (detected_format, [PreparedPage, ...])."""
    fmt = _sniff_format(file_bytes, filename)

    if fmt == "drawio":
        # We can't render mxgraph headless without a JS runtime. Give the
        # caller a clear, actionable error.
        raise ValueError(
            "draw.io XML cannot be rendered server-side. Please export the "
            "diagram as PNG or PDF and re-upload."
        )

    if fmt == "pdf":
        imgs = _render_pdf(file_bytes)
        pages = [_prepare_pil(im, idx, "pdf") for idx, im in enumerate(imgs)]
        return fmt, pages

    if fmt == "svg":
        img = _render_svg(file_bytes)
        return fmt, [_prepare_pil(img, 0, "svg")]

    if fmt in {"png", "jpg", "webp", "bmp", "gif"}:
        img = Image.open(io.BytesIO(file_bytes))
        if fmt == "gif":
            img.seek(0)
        page = _prepare_pil(img, 0, "jpg" if fmt == "jpg" else "png")
        return ("jpg" if fmt == "jpg" else "png"), [page]

    # Try PIL as a last resort
    try:
        img = Image.open(io.BytesIO(file_bytes))
        return "png", [_prepare_pil(img, 0, "png")]
    except Exception as e:  # noqa: BLE001
        raise ValueError(
            f"Unsupported or unreadable file format for {filename!r}. "
            "Accepted: PNG, JPG, WEBP, BMP, GIF, SVG, PDF."
        ) from e
