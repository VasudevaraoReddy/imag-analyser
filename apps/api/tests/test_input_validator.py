"""Pre-flight input validator tests.

We mock the LLM classifier so these run with zero network. The
deterministic checks (size, blur) get real test fixtures.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from app.services import input_validator


def _png(width: int, height: int, color: str = "white") -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_with_shapes(width: int, height: int) -> bytes:
    """Generate a sharper image — boxes + lines, sufficient edge content."""
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    for i in range(8):
        x = 50 + i * 100
        d.rectangle((x, 100, x + 70, 200), outline="black", width=3)
        d.line((x + 70, 150, x + 100, 150), fill="black", width=2)
    return img.tobytes()  # not used for sharp content; below we save properly


def _png_sharp_diagram(width: int = 1200, height: int = 800) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    for i in range(8):
        x = 50 + i * 120
        d.rectangle((x, 100, x + 90, 220), outline="black", width=4)
        d.line((x + 90, 160, x + 170, 160), fill="black", width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Deterministic checks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rejects_too_small_image(monkeypatch):
    # No LLM call should happen for size failures — patch to assert
    async def _no_classify(_):
        raise AssertionError("classifier should not be reached for size failures")
    monkeypatch.setattr(input_validator, "_classify_with_llm", _no_classify)

    result = await input_validator.validate(_png(400, 400))
    assert result.accepted is False
    assert result.reason_code == "image_too_small"
    assert "400×400" in result.message


@pytest.mark.asyncio
async def test_rejects_too_blurred_image(monkeypatch):
    async def _no_classify(_):
        raise AssertionError("classifier should not be reached for blur failures")
    monkeypatch.setattr(input_validator, "_classify_with_llm", _no_classify)

    # Force the blur metric to fall below threshold
    monkeypatch.setattr(input_validator, "_laplacian_variance", lambda _: 10.0)

    result = await input_validator.validate(_png_sharp_diagram())
    assert result.accepted is False
    assert result.reason_code == "image_too_blurred"


@pytest.mark.asyncio
async def test_rejects_non_diagram_per_classifier(monkeypatch):
    monkeypatch.setattr(input_validator, "_laplacian_variance", lambda _: 500.0)

    async def _fake_classify(_):
        return {
            "is_architecture_diagram": False,
            "category": "ui_screenshot",
            "confidence": 0.92,
            "reason": "This appears to be a mobile-app screenshot.",
        }
    monkeypatch.setattr(input_validator, "_classify_with_llm", _fake_classify)

    result = await input_validator.validate(_png_sharp_diagram())
    assert result.accepted is False
    assert result.reason_code == "not_an_architecture_diagram"
    assert "ui screenshot" in result.message.lower()
    assert result.category == "ui_screenshot"


@pytest.mark.asyncio
async def test_rejects_low_confidence_diagram(monkeypatch):
    monkeypatch.setattr(input_validator, "_laplacian_variance", lambda _: 500.0)

    async def _fake_classify(_):
        return {
            "is_architecture_diagram": True,
            "category": "flowchart",
            "confidence": 0.30,  # below threshold
            "reason": "Unclear.",
        }
    monkeypatch.setattr(input_validator, "_classify_with_llm", _fake_classify)

    result = await input_validator.validate(_png_sharp_diagram())
    assert result.accepted is False
    assert result.reason_code == "not_an_architecture_diagram"


@pytest.mark.asyncio
async def test_accepts_real_architecture_diagram(monkeypatch):
    monkeypatch.setattr(input_validator, "_laplacian_variance", lambda _: 500.0)

    async def _fake_classify(_):
        return {
            "is_architecture_diagram": True,
            "category": "cloud_architecture",
            "confidence": 0.95,
            "reason": "Clear Azure 3-tier architecture with WAF, App Service, SQL DB.",
        }
    monkeypatch.setattr(input_validator, "_classify_with_llm", _fake_classify)

    result = await input_validator.validate(_png_sharp_diagram())
    assert result.accepted is True
    assert result.reason_code == "ok"
    assert result.category == "cloud_architecture"
    assert result.classifier_confidence == 0.95


@pytest.mark.asyncio
async def test_rejects_corrupt_bytes(monkeypatch):
    async def _no_classify(_):
        raise AssertionError("classifier should not be reached")
    monkeypatch.setattr(input_validator, "_classify_with_llm", _no_classify)

    result = await input_validator.validate(b"this is not an image at all")
    assert result.accepted is False
    assert result.reason_code == "not_an_image"


@pytest.mark.asyncio
async def test_rejects_too_large_image(monkeypatch):
    async def _no_classify(_):
        raise AssertionError("classifier should not be reached")
    monkeypatch.setattr(input_validator, "_classify_with_llm", _no_classify)

    # Skip the actual giant PIL allocation — patch _dimensions
    monkeypatch.setattr(input_validator, "_dimensions", lambda _: (15000, 10000))

    result = await input_validator.validate(_png_sharp_diagram())
    assert result.accepted is False
    assert result.reason_code == "image_too_large"
