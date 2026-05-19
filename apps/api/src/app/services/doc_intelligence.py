"""Wrap Azure AI Document Intelligence (prebuilt-layout) for OCR.

Falls back to a MockOCRClient that returns synthetic OCR lines when
no DOC_INTEL_* credentials are configured. The mock is good enough for
the committed sample diagrams to flow end-to-end without Azure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import get_settings

from ..logging_setup import get_logger, time_block  # noqa: E402

log = get_logger("doc_intelligence")


@dataclass
class OCRLine:
    text: str
    bbox: list[float]  # [x1, y1, x2, y2] in pixels of input image
    confidence: float


@dataclass
class OCRResult:
    lines: list[OCRLine]

    def to_prompt_payload(self) -> list[dict[str, Any]]:
        return [
            {"text": l.text, "bbox": l.bbox, "confidence": l.confidence}
            for l in self.lines
        ]


class MockOCRClient:
    """Returns deterministic OCR-like data: empty lines.

    The vision LLM call is still able to extract structure from the
    image alone, and the MockLLMClient produces canned data for our
    sample images by filename.
    """

    async def extract(self, png_bytes: bytes) -> OCRResult:  # noqa: ARG002
        return OCRResult(lines=[])


class AzureDocIntelligenceClient:
    def __init__(self) -> None:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential

        s = get_settings()
        self._client = DocumentIntelligenceClient(
            endpoint=s.doc_intel_endpoint,
            credential=AzureKeyCredential(s.doc_intel_api_key),
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def extract(self, png_bytes: bytes) -> OCRResult:
        # The SDK is currently sync; run in a thread to keep the API async.
        import asyncio

        def _run() -> OCRResult:
            poller = self._client.begin_analyze_document(
                "prebuilt-layout",
                body=png_bytes,
                content_type="application/octet-stream",
            )
            res = poller.result()
            lines: list[OCRLine] = []
            for page in getattr(res, "pages", []) or []:
                for line in getattr(page, "lines", []) or []:
                    poly = getattr(line, "polygon", None) or []
                    # polygon is a flat list [x1,y1,x2,y2,...] in pixels
                    if poly and len(poly) >= 8:
                        xs = poly[0::2]
                        ys = poly[1::2]
                        bbox = [float(min(xs)), float(min(ys)),
                                float(max(xs)), float(max(ys))]
                    else:
                        bbox = [0.0, 0.0, 0.0, 0.0]
                    lines.append(
                        OCRLine(
                            text=getattr(line, "content", "") or "",
                            bbox=bbox,
                            confidence=float(getattr(line, "confidence", 0.9) or 0.9),
                        )
                    )
            return OCRResult(lines=lines)

        with time_block(log, "doc_intel.extract", input_bytes=len(png_bytes)) as ctx:
            result = await asyncio.to_thread(_run)
            ctx["ocr_lines"] = len(result.lines)
            return result


def get_client() -> AzureDocIntelligenceClient | MockOCRClient:
    s = get_settings()
    if s.doc_intel_available:
        try:
            return AzureDocIntelligenceClient()
        except Exception as exc:  # noqa: BLE001
            log.warning("doc_intel_init_failed", error=str(exc))
            return MockOCRClient()
    log.info("doc_intel_mock_mode")
    return MockOCRClient()
