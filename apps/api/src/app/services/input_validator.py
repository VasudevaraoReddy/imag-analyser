"""Pre-flight input validation.

Runs BEFORE the expensive analysis pipeline. Three layers:

1. **Magic-byte / decode check** — image_prep.prepare() already raises on
   corrupt files. We catch that and surface a clean error.
2. **Deterministic checks** — size, blur (Laplacian variance). Microseconds.
3. **AI classifier** — one short gpt-4o call asking "is this an architecture
   diagram?" Costs ~$0.001 per check (detail=low, max_tokens=120).

The whole gate runs in ~2 seconds and prevents the analyzer from burning
budget on garbage uploads.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from PIL import Image

from ..config import get_settings
from ..logging_setup import get_logger, time_block

log = get_logger("input_validator")


# ---------------------------------------------------------------------------
# Thresholds — tune as needed
# ---------------------------------------------------------------------------

MIN_LONG_EDGE_PX = 800           # below this, OCR + LLM extraction degrade
MIN_TOTAL_PIXELS = 500_000       # ~700x700 minimum effective resolution
MAX_LONG_EDGE_PX = 12_000        # absurdly large — preprocessor caps anyway
MIN_BLUR_LAPLACIAN_VAR = 60.0    # < 60 = visibly blurred; 100+ = sharp
CLASSIFIER_MIN_CONFIDENCE = 0.55 # below this we reject as non-diagram


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    accepted: bool
    reason_code: str = ""                # "ok" | "image_too_small" | ...
    message: str = ""                    # human-readable
    category: str = ""                   # what the classifier thinks it is
    classifier_confidence: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason_code": self.reason_code,
            "message": self.message,
            "category": self.category,
            "classifier_confidence": self.classifier_confidence,
            "metrics": self.metrics,
        }


# ---------------------------------------------------------------------------
# Deterministic checks
# ---------------------------------------------------------------------------

def _dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) without holding the file open."""
    with Image.open(io.BytesIO(png_bytes)) as img:
        return img.size


def _laplacian_variance(png_bytes: bytes) -> float:
    """Compute Laplacian variance — a standard sharpness metric.

    No OpenCV dependency: we approximate with Pillow + numpy. Lower values
    mean more blur. < 100 ≈ visibly blurred; > 500 ≈ crisp screen capture.
    """
    try:
        import numpy as np
        from PIL import ImageFilter

        with Image.open(io.BytesIO(png_bytes)) as img:
            gray = img.convert("L")
            # Downsample large images so the metric runs fast (the variance
            # is roughly scale-invariant for the threshold we care about).
            gray.thumbnail((1024, 1024))
            edges = gray.filter(ImageFilter.FIND_EDGES)
            arr = np.asarray(edges, dtype=np.float32)
            return float(arr.var())
    except Exception:  # noqa: BLE001
        # If sharpness check fails for any reason, don't block the upload.
        return float("inf")


# ---------------------------------------------------------------------------
# AI classifier (cheap)
# ---------------------------------------------------------------------------

CLASSIFIER_SYSTEM = """You are a strict input gatekeeper for an
architecture-review tool. You classify a single image into one of:
  - cloud_architecture   (Azure/AWS/GCP/OCI/on-prem diagrams)
  - network_diagram      (network topologies, NSGs, subnets)
  - flowchart            (business process or state diagrams)
  - ui_screenshot        (apps, dashboards, websites)
  - photo                (people, places, objects)
  - document             (text-heavy PDF page, slides without diagrams)
  - other                (everything else)

You MUST reply with EXACTLY this JSON, no prose, no markdown:
{
  "is_architecture_diagram": true | false,
  "category": "<one of the above>",
  "confidence": 0.0 - 1.0,
  "reason": "<one short sentence>"
}

An "architecture diagram" depicts SYSTEMS connected by lines:
boxes/icons representing services / VMs / databases / users, with
arrows or lines showing flows between them. Whiteboard or
hand-sketched diagrams count if intent is to show architecture.
Anything else — selfies, screenshots of apps, slides of bullet
text, code screenshots, random photos — set is_architecture_diagram=false."""


async def _classify_with_llm(png_bytes: bytes) -> dict[str, Any]:
    """One gpt-4o call. Returns the parsed classification dict.

    Uses the existing AzureOpenAI client from vision_llm so we don't
    re-implement retry/timeout. Forces detail=low which costs ~$0.001
    per call regardless of image size.
    """
    s = get_settings()
    if not s.llm_available:
        # Mock mode — be permissive
        return {
            "is_architecture_diagram": True,
            "category": "cloud_architecture",
            "confidence": 0.9,
            "reason": "Mock classifier (no Azure OpenAI creds configured).",
        }

    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
        azure_endpoint=s.azure_openai_endpoint,
        max_retries=0,
        timeout=30.0,
    )

    b64 = base64.b64encode(png_bytes).decode("ascii")
    messages = [
        {"role": "system", "content": CLASSIFIER_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Classify this image."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{b64}",
                        "detail": "low",  # cheapest possible — ~85 tokens
                    },
                },
            ],
        },
    ]

    import asyncio

    def _call() -> str:
        resp = client.chat.completions.create(
            model=s.azure_openai_deployment,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=120,
            timeout=30,
        )
        return resp.choices[0].message.content or "{}"

    raw = await asyncio.to_thread(_call)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "is_architecture_diagram": False,
            "category": "other",
            "confidence": 0.0,
            "reason": "Classifier returned non-JSON output.",
        }


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def validate(png_bytes: bytes) -> ValidationResult:
    """Run all gates. Returns ValidationResult — caller decides what to do."""
    with time_block(log, "input_validator.validate") as ctx:
        # Layer 0: decode to confirm bytes are an image at all
        try:
            width, height = _dimensions(png_bytes)
        except Exception as exc:  # noqa: BLE001
            return ValidationResult(
                accepted=False,
                reason_code="not_an_image",
                message=f"Could not read this file as an image: {exc}",
            )

        ctx["width"] = width
        ctx["height"] = height
        long_edge = max(width, height)
        total_px = width * height

        # Layer 1a: resolution
        if long_edge < MIN_LONG_EDGE_PX or total_px < MIN_TOTAL_PIXELS:
            return ValidationResult(
                accepted=False,
                reason_code="image_too_small",
                message=(
                    f"Image is {width}×{height} pixels. The analyzer needs at "
                    f"least {MIN_LONG_EDGE_PX} px on the long edge so that text "
                    f"labels and icons are readable. Please re-export at a "
                    f"higher resolution or take a closer photo."
                ),
                metrics={"width": width, "height": height,
                         "long_edge": long_edge, "total_pixels": total_px},
            )

        if long_edge > MAX_LONG_EDGE_PX:
            return ValidationResult(
                accepted=False,
                reason_code="image_too_large",
                message=(
                    f"Image is {width}×{height} pixels — that's larger than "
                    f"what the analyzer can process. Please downscale to under "
                    f"{MAX_LONG_EDGE_PX} px on the long edge."
                ),
                metrics={"long_edge": long_edge},
            )

        # Layer 1b: blur
        blur = _laplacian_variance(png_bytes)
        ctx["blur_var"] = round(blur, 1)
        if blur < MIN_BLUR_LAPLACIAN_VAR:
            return ValidationResult(
                accepted=False,
                reason_code="image_too_blurred",
                message=(
                    "The image is too blurred — text labels likely won't be "
                    "readable by the analyzer. Try a higher-resolution export, "
                    "a sharper photo, or a screenshot instead of a phone "
                    "picture of a screen."
                ),
                metrics={"laplacian_variance": blur,
                         "threshold": MIN_BLUR_LAPLACIAN_VAR},
            )

        # Layer 2: AI classifier
        cls = await _classify_with_llm(png_bytes)
        is_diagram = bool(cls.get("is_architecture_diagram", False))
        confidence = float(cls.get("confidence") or 0.0)
        category = str(cls.get("category") or "other")
        reason = str(cls.get("reason") or "")
        ctx["classifier_category"] = category
        ctx["classifier_confidence"] = confidence
        ctx["classifier_says"] = "diagram" if is_diagram else "not_diagram"

        if not is_diagram or confidence < CLASSIFIER_MIN_CONFIDENCE:
            return ValidationResult(
                accepted=False,
                reason_code="not_an_architecture_diagram",
                message=(
                    "This doesn't appear to be an architecture diagram. The "
                    f"image looks like a {category.replace('_', ' ')}. "
                    f"{reason} Please upload a cloud / network architecture "
                    "diagram showing services as boxes with arrows between them."
                ),
                category=category,
                classifier_confidence=confidence,
                metrics={"width": width, "height": height,
                         "blur_var": blur,
                         "classifier_category": category,
                         "classifier_reason": reason},
            )

        # All gates passed.
        return ValidationResult(
            accepted=True,
            reason_code="ok",
            message="Image passed all pre-flight checks.",
            category=category,
            classifier_confidence=confidence,
            metrics={"width": width, "height": height,
                     "blur_var": blur,
                     "classifier_category": category},
        )
