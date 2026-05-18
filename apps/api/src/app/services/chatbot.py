"""Chatbot service.

Answers questions about a specific analysis (or in general) using Azure
OpenAI gpt-4o when available, with a deterministic local fallback that
reads the stored AnalysisResult JSON.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings
from ..schemas import AnalysisResult
from ..storage import load_analysis

log = structlog.get_logger()

CHAT_SYSTEM = """You are an internal assistant for YES BANK cloud-architecture review.
You help engineers and architects understand analysis results produced by the
diagram analyzer. You are concise, factual, and never invent components or
compliance findings that aren't present in the provided context.

When a specific analysis is attached, answer ONLY using its components,
connections, trust zones, flows, compliance findings, and parsing warnings.
If the user asks something the analysis cannot answer, say so plainly.

When no analysis is attached, you may give general architecture-security
guidance, but keep answers short and oriented to enterprise banking patterns
(WAF / private endpoints / defense in depth / N-S vs E-W segmentation).

Never output markdown headings (#). Plain prose with short bullet points is fine."""


def _analysis_context_text(a: AnalysisResult) -> str:
    """Compact JSON-ish text the LLM can ingest."""
    payload = {
        "filename": a.filename,
        "primary_provider": a.primary_provider,
        "cloud_providers": a.cloud_providers,
        "diagram_style": a.diagram_style,
        "overall_confidence": a.overall_confidence,
        "review_state": a.review_state,
        "trust_zones": [
            {"id": z.id, "name": z.name, "kind": z.kind} for z in a.trust_zones
        ],
        "components": [
            {
                "id": c.id, "name": c.name,
                "canonical_name": c.canonical_name,
                "service_type": c.service_type,
                "provider": c.provider, "trust_zone": c.trust_zone,
                "tier": c.tier, "redundancy": c.redundancy,
            } for c in a.components
        ],
        "connections": [
            {
                "id": e.id, "from": e.from_, "to": e.to,
                "label": e.label, "protocol": e.protocol, "port": e.port,
                "encrypted": e.encrypted, "is_data_flow": e.is_data_flow,
            } for e in a.connections
        ],
        "flows": {
            "north_south": a.flows.north_south,
            "east_west": a.flows.east_west,
        },
        "compliance_findings": [
            {
                "rule": f.rule, "status": f.status, "severity": f.severity,
                "message": f.message,
                "affected_component_ids": f.affected_component_ids,
                "affected_connection_ids": f.affected_connection_ids,
            } for f in a.compliance_findings
        ],
        "parsing_warnings": [
            {"kind": w.kind, "message": w.message, "affected_ids": w.affected_ids}
            for w in a.parsing_warnings
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Deterministic fallback ("smart mock") that can still answer common questions
# directly from the AnalysisResult JSON.
# ---------------------------------------------------------------------------

def _local_answer(message: str, a: AnalysisResult | None) -> str:
    m = message.lower().strip()

    if a is None:
        return (
            "I don't have an analysis in this conversation yet. "
            "Open an Arc Review and click 'Ask the bot' from the analysis page, "
            "or paste a question and I'll answer it generally."
        )

    def fmt_list(items: list[str], n: int = 8) -> str:
        if not items:
            return "none"
        if len(items) <= n:
            return ", ".join(items)
        return ", ".join(items[:n]) + f", … (+{len(items) - n} more)"

    # Component / count questions
    if any(k in m for k in ["how many components", "number of components", "components count"]):
        return f"This architecture has {len(a.components)} components across {len(a.trust_zones)} trust zones."

    if "list components" in m or "what components" in m or "show components" in m:
        names = [c.name for c in a.components]
        return f"Components ({len(names)}): {fmt_list(names, 20)}."

    # Compliance
    if "compliance" in m or "findings" in m or "controls" in m:
        fails = [f for f in a.compliance_findings if f.status == "fail"]
        warns = [f for f in a.compliance_findings if f.status == "warn"]
        passes = [f for f in a.compliance_findings if f.status == "pass"]
        lines = [
            f"Compliance summary for {a.filename}:",
            f"- Passes: {len(passes)}",
            f"- Warnings: {len(warns)}",
            f"- Failures: {len(fails)}",
            f"- Review state: {a.review_state}",
        ]
        if fails:
            lines.append("Failures:")
            for f in fails:
                lines.append(f"  • {f.rule} ({f.severity}): {f.message}")
        if warns:
            lines.append("Warnings:")
            for f in warns:
                lines.append(f"  • {f.rule} ({f.severity}): {f.message}")
        return "\n".join(lines)

    # Flows
    if "north-south" in m or "north south" in m or "ns flow" in m:
        return (
            f"North-south flows: {len(a.flows.north_south)} of "
            f"{len(a.connections)} connections. These cross trust boundaries."
        )
    if "east-west" in m or "east west" in m or "ew flow" in m:
        return (
            f"East-west flows: {len(a.flows.east_west)} of "
            f"{len(a.connections)} connections. These stay within a trust zone."
        )
    if "flow" in m or "connections" in m:
        return (
            f"{len(a.connections)} total connections — "
            f"{len(a.flows.north_south)} north-south, "
            f"{len(a.flows.east_west)} east-west, "
            f"{len(a.connections) - len(a.flows.north_south) - len(a.flows.east_west)} non-data-flow (management/dependency)."
        )

    # Providers / cloud
    if "provider" in m or "cloud" in m:
        return (
            f"Primary provider: {a.primary_provider}. "
            f"Detected providers: {', '.join(a.cloud_providers) or 'none'}."
        )

    # Trust zones
    if "zone" in m or "segmentation" in m:
        zs = [f"{z.name} ({z.kind})" for z in a.trust_zones]
        return f"Trust zones ({len(zs)}): {fmt_list(zs, 12)}."

    # Summary / overview
    if "summary" in m or "overview" in m or "describe" in m:
        return (
            f"{a.filename}: {len(a.components)} components, "
            f"{len(a.connections)} connections, {len(a.trust_zones)} trust zones. "
            f"Confidence {round(a.overall_confidence * 100)}%, "
            f"review state '{a.review_state}'. "
            f"Compliance: {sum(1 for f in a.compliance_findings if f.status == 'fail')} failures, "
            f"{sum(1 for f in a.compliance_findings if f.status == 'warn')} warnings."
        )

    # Default
    return (
        "I can answer questions about this analysis. Try:\n"
        "  • 'Show me the compliance findings'\n"
        "  • 'How many north-south flows?'\n"
        "  • 'List components'\n"
        "  • 'Which trust zones are present?'\n"
        "  • 'Give me a summary'\n"
        "(Mock mode — no Azure OpenAI credentials configured.)"
    )


# ---------------------------------------------------------------------------
# Real LLM path
# ---------------------------------------------------------------------------

class AzureOpenAIChatClient:
    def __init__(self) -> None:
        from openai import AzureOpenAI
        s = get_settings()
        self._client = AzureOpenAI(
            api_key=s.azure_openai_api_key,
            api_version=s.azure_openai_api_version,
            azure_endpoint=s.azure_openai_endpoint,
        )
        self._deployment = s.azure_openai_deployment
        self._settings = s

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    def _call(self, messages: list[dict[str, Any]]) -> str:
        resp = self._client.chat.completions.create(
            model=self._deployment,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.2,
            top_p=0.9,
            max_tokens=1024,
            timeout=60,
        )
        return resp.choices[0].message.content or ""

    def _build_messages(
        self,
        messages: list[dict[str, Any]],
        analysis: AnalysisResult | None,
    ) -> list[dict[str, Any]]:
        system = CHAT_SYSTEM
        if analysis is not None:
            system += (
                "\n\nThe following analysis is attached as context (JSON). "
                "Use ONLY this information to answer questions about the "
                "diagram or its findings.\n\n"
                + _analysis_context_text(analysis)
            )
        return [{"role": "system", "content": system}, *messages]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        analysis: AnalysisResult | None,
    ) -> str:
        full = self._build_messages(messages, analysis)
        return await asyncio.to_thread(self._call, full)

    async def astream(
        self,
        messages: list[dict[str, Any]],
        analysis: AnalysisResult | None,
    ) -> AsyncIterator[str]:
        """Yield response deltas as the model produces them."""
        full = self._build_messages(messages, analysis)
        # The SDK's stream is sync; pump it through a queue read from the
        # event loop so we don't block the async runtime.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _pump() -> None:
            try:
                stream = self._client.chat.completions.create(
                    model=self._deployment,
                    messages=full,  # type: ignore[arg-type]
                    temperature=self._settings.llm_temperature,
                    top_p=self._settings.llm_top_p,
                    seed=self._settings.llm_seed,
                    max_tokens=1024,
                    stream=True,
                    timeout=60,
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = getattr(chunk.choices[0].delta, "content", None)
                    if delta:
                        loop.call_soon_threadsafe(queue.put_nowait, delta)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    f"\n[stream error: {exc}]",
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        asyncio.get_running_loop().run_in_executor(None, _pump)

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item


class MockChatClient:
    async def chat(
        self,
        messages: list[dict[str, Any]],
        analysis: AnalysisResult | None,
    ) -> str:
        latest = _latest_user(messages)
        return _local_answer(latest, analysis)

    async def astream(
        self,
        messages: list[dict[str, Any]],
        analysis: AnalysisResult | None,
    ) -> AsyncIterator[str]:
        """Stream the deterministic answer word-by-word for a realistic
        typing feel even without Azure credentials."""
        latest = _latest_user(messages)
        text = _local_answer(latest, analysis)
        for token in _word_tokens(text):
            yield token
            await asyncio.sleep(0.025)


def _latest_user(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


def _word_tokens(text: str) -> list[str]:
    """Split on whitespace but keep the whitespace so the reassembled
    text matches the original exactly."""
    out: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in (" ", "\n"):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def get_client() -> AzureOpenAIChatClient | MockChatClient:
    s = get_settings()
    if s.llm_available:
        try:
            return AzureOpenAIChatClient()
        except Exception as exc:  # noqa: BLE001
            log.warning("chat_llm_init_failed", error=str(exc))
            return MockChatClient()
    log.info("chat_mock_mode")
    return MockChatClient()


async def answer(
    messages: list[dict[str, Any]],
    analysis_id: str | None,
) -> str:
    analysis: AnalysisResult | None = None
    if analysis_id:
        analysis = load_analysis(analysis_id)
        if analysis is None:
            log.warning("chat_analysis_not_found", analysis_id=analysis_id)
    client = get_client()
    return await client.chat(messages, analysis)


async def stream_answer(
    messages: list[dict[str, Any]],
    analysis_id: str | None,
) -> AsyncIterator[str]:
    """Streaming sibling of :func:`answer`. Yields response deltas."""
    analysis: AnalysisResult | None = None
    if analysis_id:
        analysis = load_analysis(analysis_id)
        if analysis is None:
            log.warning("chat_analysis_not_found", analysis_id=analysis_id)
    client = get_client()
    async for delta in client.astream(messages, analysis):
        yield delta
