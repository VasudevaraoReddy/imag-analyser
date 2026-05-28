"""Decide which pipeline stage(s) to re-run for a given architect feedback.

The architect types something like:
  - "You missed the WAF in front of the App tier"        → vision_llm
  - "Component label should be 'Cosmos DB', not 'CosmosDB Doc'" → doc_intelligence + vision_llm
  - "Journey 2 has the arrow flipped"                    → vision_llm
  - "Front Door isn't labelled — OCR didn't read it"     → doc_intelligence + vision_llm

We use a tiny gpt-4o JSON call to classify the feedback. If Azure is
unreachable (or the call fails), we fall back to a keyword heuristic.

Returns:
    {
      "stages": ["doc_intelligence", "vision_llm"] | ["vision_llm"] | [...],
      "reason": "Architect reports a missed component, which is a vision-layer issue.",
      "source": "llm" | "heuristic",
    }
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import AzureOpenAI

from ..config import get_settings
from ..logging_setup import get_logger, safe_preview, time_block

log = get_logger("re_review_router")

ALL_STAGES = ("doc_intelligence", "vision_llm")


_ROUTER_SYSTEM = """You are a routing classifier for a diagram-extraction
pipeline. Read the architect's plain-English feedback on a previous
extraction, then decide which stage(s) of the pipeline should be re-run
to address it.

The pipeline stages you can route to:

  - doc_intelligence : OCR pass. Pick this when the feedback is about
                       text that was missed, misread, mis-labelled, or
                       when component labels are wrong.

  - vision_llm       : The icon/structure/flow extraction pass. Pick this
                       when the feedback is about a missed component,
                       an extra (hallucinated) component, a wrong icon
                       type, a wrong/reversed connection, a wrong
                       journey, or any structural issue.

Most feedback needs vision_llm. Add doc_intelligence ONLY when the
issue clearly involves text/labels/OCR. When in doubt, return both.

Reply with EXACTLY this JSON (no prose, no markdown):

  {
    "stages": ["doc_intelligence" | "vision_llm", ...],
    "reason": "<one short sentence, max 20 words>"
  }

Rules:
  - "stages" must be non-empty. If everything's fine and you can't tell,
    return ["vision_llm"] (the safe default).
  - Each stage name appears at most once.
"""


# Heuristic fallback ─ used when the LLM router is unavailable. Pretty
# crude but keeps the feature working in mock mode and during outages.
_OCR_KEYWORDS = re.compile(
    r"\b(ocr|text|label(?:led)?|name|spelling|misspell|read(?:ing)?|wording|"
    r"font|typo|mislabel|caption|title|misread)\b",
    re.IGNORECASE,
)


def _heuristic(feedback: str) -> dict[str, Any]:
    text = (feedback or "").strip()
    stages: list[str] = []
    if _OCR_KEYWORDS.search(text):
        stages.append("doc_intelligence")
    stages.append("vision_llm")  # almost always needed
    return {
        "stages": stages,
        "reason": "Heuristic: " + (
            "feedback mentions text/labels, re-OCR + vision."
            if "doc_intelligence" in stages and len(stages) > 1
            else "default to vision-only re-extraction."
        ),
        "source": "heuristic",
    }


def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
    stages_raw = payload.get("stages") or []
    if not isinstance(stages_raw, list):
        stages_raw = []
    seen: list[str] = []
    for s in stages_raw:
        if isinstance(s, str) and s in ALL_STAGES and s not in seen:
            seen.append(s)
    if not seen:
        seen = ["vision_llm"]
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "No reason returned."
    return {"stages": seen, "reason": reason.strip()}


def _call_router_llm(feedback: str) -> dict[str, Any]:
    s = get_settings()
    client = AzureOpenAI(
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
        azure_endpoint=s.azure_openai_endpoint,
        max_retries=0,
        timeout=30.0,
    )
    messages = [
        {"role": "system", "content": _ROUTER_SYSTEM},
        {"role": "user", "content": f"Architect feedback:\n{feedback.strip()}"},
    ]
    with time_block(log, "re_review_router.call", feedback_len=len(feedback)) as ctx:
        resp = client.chat.completions.create(
            model=s.azure_openai_deployment,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=120,
            timeout=30,
        )
        raw = resp.choices[0].message.content or "{}"
        ctx["response_chars"] = len(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("re_review_router.json_parse_failed",
                    preview=safe_preview(raw, 200))
        return {}


def decide_stages(feedback: str) -> dict[str, Any]:
    """Pick stage(s) to re-run for the given architect feedback.

    Always returns at least one stage. Never raises — falls back to a
    keyword heuristic if the LLM call fails or LLM creds are missing.
    """
    feedback = (feedback or "").strip()
    if not feedback:
        return {**_heuristic(""), "reason": "Empty feedback — defaulted to vision_llm."}

    if not get_settings().llm_available:
        return _heuristic(feedback)

    try:
        raw = _call_router_llm(feedback)
        out = _normalise(raw)
        out["source"] = "llm"
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("re_review_router.failed_fallback", error=str(exc))
        h = _heuristic(feedback)
        h["reason"] = f"LLM router failed ({type(exc).__name__}); used heuristic."
        return h
