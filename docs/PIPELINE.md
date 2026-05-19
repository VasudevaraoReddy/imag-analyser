# Analysis Pipeline — engineering reference

A walkthrough of the seven stages that turn an uploaded image into the
final `AnalysisResult` JSON. Each stage section covers:

- **What it does** — one paragraph
- **The Python logic** — actual code shape from the repo
- **Failure modes & guarantees**
- **Where to look** — file path, key functions, tests

---

## Pipeline at a glance

```
Image bytes
   │
   ▼ [1] image_prep.py     ── Pillow / pypdfium2 / cairosvg
   │
   ▼ [2] doc_intelligence  ── Azure AI Document Intelligence
   │
   ▼ [3] vision_llm        ── Azure OpenAI gpt-4o   ← the ONLY AI step
   │
   ▼ [4] normalize         ── deterministic Python
   │
   ▼ [5] classifier        ── deterministic Python
   │
   ▼ [6] compliance        ── data-driven rules engine
   │
   ▼ [7] journey_extractor ── graph walk + scoring
   │
   ▼
AnalysisResult JSON → saved to data/analyses/<uuid>.json
```

**Orchestrator**: `apps/api/src/app/services/analyzer.py` → `analyze_diagram(file_bytes, filename)`.

Design rule we live by: **the LLM is a perception layer. Every security-relevant decision is deterministic code we own.** Compliance verdicts cannot drift when the model is upgraded.

---

## [1] `image_prep.py` — image preprocessing

### What it does

Turns whatever the user uploaded — PNG, JPG, WEBP, BMP, GIF, SVG, PDF, draw.io XML, even a phone photo — into a normalized RGB PNG (or list of PNGs for multi-page PDFs) that downstream stages can rely on.

We need this because real uploads are messy: phones rotate JPEGs with EXIF metadata, PDFs need rendering, SVGs are vector, whiteboard photos are washed out. By the end of this stage every input looks the same to the rest of the pipeline.

### The Python logic

```python
# apps/api/src/app/services/image_prep.py

from PIL import Image, ImageOps

MAX_DIM = 4096
SVG_RENDER_WIDTH = 1600
PDF_DPI = 200


def _sniff_format(data: bytes, filename: str) -> str:
    """Magic-byte sniff — never trust the file extension."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":              return "png"
    if data[:3] == b"\xff\xd8\xff":                    return "jpg"
    if data[:4] == b"%PDF":                            return "pdf"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  return "webp"
    if data[:2] == b"BM":                              return "bmp"
    if b"<svg" in data[:2048].lower():                 return "svg"
    if b"<mxfile" in data[:2048].lower():              return "drawio"
    return "unknown"


def _is_photo_like(img: Image.Image) -> bool:
    """Detect photos vs. clean exports via histogram entropy."""
    gray = img.convert("L")
    hist = gray.histogram()
    total = sum(hist) or 1
    entropy = -sum((h / total) * math.log2(h / total) for h in hist if h)
    return entropy > 6.0          # photos > 6.0, clean exports < 6.0


def _prepare_pil(img: Image.Image, page_index: int, source: str) -> PreparedPage:
    img = ImageOps.exif_transpose(img)               # auto-rotate phone shots
    img = img.convert("RGB")                         # force standard colour mode
    if max(img.size) > MAX_DIM:
        scale = MAX_DIM / max(img.size)
        img = img.resize(
            (int(img.width * scale), int(img.height * scale)),
            Image.LANCZOS,                           # high-quality downscale
        )
    if _is_photo_like(img):
        img = ImageOps.autocontrast(img, cutoff=1)   # brighten only if needed
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return PreparedPage(png_bytes=buf.getvalue(), width=img.width,
                        height=img.height, page_index=page_index,
                        source_format=source)


def prepare(file_bytes: bytes, filename: str) -> tuple[str, list[PreparedPage]]:
    """Public entry point."""
    fmt = _sniff_format(file_bytes, filename)

    if fmt == "pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(file_bytes)
        pages = [pdf[i].render(scale=PDF_DPI / 72.0).to_pil() for i in range(len(pdf))]
        return fmt, [_prepare_pil(p, idx, "pdf") for idx, p in enumerate(pages)]

    if fmt == "svg":
        import cairosvg
        png_bytes = cairosvg.svg2png(bytestring=file_bytes, output_width=SVG_RENDER_WIDTH)
        return fmt, [_prepare_pil(Image.open(io.BytesIO(png_bytes)), 0, "svg")]

    if fmt in {"png", "jpg", "webp", "bmp", "gif"}:
        return fmt, [_prepare_pil(Image.open(io.BytesIO(file_bytes)), 0, fmt)]

    if fmt == "drawio":
        raise ValueError("draw.io XML cannot be rendered server-side. "
                         "Please export as PNG or PDF.")
    raise ValueError(f"Unsupported file format for {filename!r}.")
```

### Packages

| Package | Job |
|---|---|
| **Pillow** (`PIL`) | All raster ops — open, convert, rotate, resize, autocontrast |
| **pypdfium2** | PDF page → PIL image, using Google's PDFium engine |
| **cairosvg** | SVG → PNG via the Cairo 2D graphics library |

### Failure modes & guarantees

| Input | Outcome |
|---|---|
| `.drawio` XML | Clean `ValueError` → 415 with instructions to export as PNG |
| Corrupt PNG bytes | `ValueError` from Pillow → 415 |
| Massive 8000×6000 photo | Downscaled to 4096 px max edge, autocontrast applied |
| Multi-page PDF | Returns N pages; analyzer treats each as a tile and merges later |

**Output guarantee:** every page is a valid RGB PNG ≤ 4096 px on its long edge.

### Where to look

- File: `apps/api/src/app/services/image_prep.py`
- Tests: `apps/api/tests/test_image_prep.py`

---

## [2] `doc_intelligence.py` — OCR via Azure

### What it does

Sends the preprocessed PNG to Azure AI Document Intelligence (`prebuilt-layout` model) and gets back every text label on the diagram with its exact pixel bounding box.

The OCR result is later handed to the vision LLM as a *hint* — it tells gpt-4o "these labels exist at these locations" so the model doesn't have to re-OCR small text.

### The Python logic

```python
# apps/api/src/app/services/doc_intelligence.py

@dataclass
class OCRLine:
    text: str
    bbox: list[float]      # [x1, y1, x2, y2] in pixels
    confidence: float


@dataclass
class OCRResult:
    lines: list[OCRLine]


class AzureDocIntelligenceClient:
    def __init__(self):
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
        s = get_settings()
        self._client = DocumentIntelligenceClient(
            endpoint=s.doc_intel_endpoint,
            credential=AzureKeyCredential(s.doc_intel_api_key),
        )

    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=1, max=10))
    async def extract(self, png_bytes: bytes) -> OCRResult:
        import asyncio

        def _run() -> OCRResult:
            poller = self._client.begin_analyze_document(
                "prebuilt-layout",
                body=png_bytes,                            # whole PNG, full res
                content_type="application/octet-stream",
            )
            res = poller.result()
            lines = []
            for page in res.pages or []:
                for line in page.lines or []:
                    poly = line.polygon or []
                    if len(poly) >= 8:
                        xs, ys = poly[0::2], poly[1::2]
                        bbox = [min(xs), min(ys), max(xs), max(ys)]
                    else:
                        bbox = [0.0, 0.0, 0.0, 0.0]
                    lines.append(OCRLine(
                        text=line.content or "",
                        bbox=bbox,
                        confidence=line.confidence or 0.9,
                    ))
            return OCRResult(lines=lines)

        with time_block(log, "doc_intel.extract",
                        input_bytes=len(png_bytes)) as ctx:
            result = await asyncio.to_thread(_run)
            ctx["ocr_lines"] = len(result.lines)
            return result


class MockOCRClient:
    """Used when DOC_INTEL_API_KEY is missing — returns empty lines."""
    async def extract(self, png_bytes: bytes) -> OCRResult:
        return OCRResult(lines=[])


def get_client():
    return (AzureDocIntelligenceClient()
            if get_settings().doc_intel_available
            else MockOCRClient())
```

### Failure modes & guarantees

| Condition | Outcome |
|---|---|
| `DOC_INTEL_API_KEY` blank | Mock client used; pipeline still runs (LLM gets empty OCR hints) |
| 5xx from Azure | Tenacity retries 3× with exponential backoff |
| Timeout | 60 s `asyncio.wait_for` ceiling in the analyzer; this stage skipped if exceeded |
| Total network failure | Analyzer falls back to empty OCR and continues |

**Output guarantee:** `OCRResult.lines` is always a list, possibly empty, never `None`.

### Where to look

- File: `apps/api/src/app/services/doc_intelligence.py`
- The async-via-`to_thread` pattern keeps FastAPI's event loop free while the sync SDK waits.

---

## [3] `vision_llm.py` — the AI perception step

### What it does

The **only** AI in the pipeline. Sends the image + OCR result to Azure OpenAI gpt-4o and gets back a structured JSON listing every component, every connection, every trust zone, with bbox coordinates.

Everything else in the pipeline is deterministic Python. If we ever swap the LLM, only this file changes.

### The Python logic

```python
# apps/api/src/app/services/vision_llm.py

def _build_user_content(png_bytes, ocr, image_width, image_height):
    """Multimodal user message: text + image."""
    return [
        {
            "type": "text",
            "text": json.dumps({
                "image_dimensions": {"width": image_width, "height": image_height},
                "ocr_lines": ocr.to_prompt_payload(),     # [{text,bbox,confidence}, ...]
            }),
        },
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{base64.b64encode(png_bytes).decode()}",
                "detail": "auto",            # let gpt-4o pick cheap tile path
            },
        },
    ]


class AzureOpenAIVisionClient:
    def __init__(self):
        from openai import AzureOpenAI
        s = get_settings()
        self._client = AzureOpenAI(
            api_key=s.azure_openai_api_key,
            api_version=s.azure_openai_api_version,
            azure_endpoint=s.azure_openai_endpoint,
            max_retries=0,                   # we own retries via tenacity
            timeout=45.0,
        )
        self._deployment = s.azure_openai_deployment
        self._settings = s

    @retry(stop=stop_after_attempt(2),
           wait=wait_exponential(multiplier=1, min=1, max=4))
    def _call(self, messages: list[dict]) -> str:
        with time_block(log, "vision_llm.azure_call",
                        payload_bytes=len(json.dumps(messages))) as ctx:
            resp = self._client.chat.completions.create(
                model=self._deployment,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=self._settings.llm_temperature,    # 0.0
                top_p=self._settings.llm_top_p,                # 1.0
                max_tokens=self._settings.llm_max_tokens,      # 2500
                timeout=45,
            )
            content = resp.choices[0].message.content or "{}"
            ctx["prompt_tokens"] = resp.usage.prompt_tokens
            ctx["completion_tokens"] = resp.usage.completion_tokens
            ctx["model"] = resp.model
            ctx["system_fingerprint"] = resp.system_fingerprint
            return content

    async def extract(self, png_bytes, ocr, image_width, image_height):
        import asyncio
        system = _load_prompt("system_base.md") + "\n\n" + _load_prompt("extraction.md")
        user_content = _build_user_content(png_bytes, ocr, image_width, image_height)
        messages = [{"role": "system", "content": system},
                    {"role": "user",   "content": user_content}]

        raw = await asyncio.to_thread(self._call, messages)
        parsed = json.loads(raw)
        coerced, _ = _coerce_llm_json(parsed)            # see below

        try:
            return LLMExtraction.model_validate(coerced)
        except ValidationError as first_err:
            # ─── ONE-SHOT REPAIR PASS ──────────────────────────
            repair_prompt = _load_prompt("repair.md").replace("{errors}", str(first_err))
            messages_repair = [
                *messages,
                {"role": "assistant", "content": raw},
                {"role": "user",      "content": repair_prompt},
            ]
            raw2 = await asyncio.to_thread(self._call, messages_repair)
            coerced2, _ = _coerce_llm_json(json.loads(raw2))
            return LLMExtraction.model_validate(coerced2)   # if this fails → raise
```

### The coercion layer — `_coerce_llm_json()`

Before Pydantic validation, we normalize common LLM drift. This is what keeps production stable when the model is upgraded:

```python
# excerpts from vision_llm.py — the coercion functions

_PROVIDER_SYN = {                      # what the LLM might say → what we want
    "microsoft": "azure", "ms": "azure",
    "amazon": "aws", "google": "gcp", "oracle": "oci",
    "onprem": "on_prem", "on-prem": "on_prem",
    "k8s": "kubernetes",
}

_SERVICE_TYPE_SYN = {
    "messaging_email": "integration_service",
    "smtp":            "integration_service",
    "kubernetes":      "compute_k8s",
    "queue":           "messaging_queue",
    "lambda":          "compute_serverless",
    "vault":           "secrets_vault",
    # … ~70 more entries
}


def _coerce_service_type(v):
    if isinstance(v, str):
        vl = v.lower().strip()
        if vl in _SERVICE_TYPE_ENUM: return vl
        if vl in _SERVICE_TYPE_SYN:  return _SERVICE_TYPE_SYN[vl]
    return "unknown"


def _coerce_llm_json(raw):
    """
    Patches:
      - "source"/"target" → "from"/"to" on connections
      - "kind": "vnet"|"subnet" → "internal" on trust zones
      - missing component ids → auto-generated from slugified name
      - service_type drift (see _SERVICE_TYPE_SYN above)
      - missing evidence.confidence → 0.6
      - connections referencing components by name → resolved to id
    Emits parsing_warnings for anything it had to fix.
    """
    ...
```

### Why these settings

| Setting | Value | Reason |
|---|---|---|
| `max_retries=0` (SDK) | 0 | SDK retries compound with tenacity — was burning 10 minutes per failing call |
| `temperature` | 0.0 | Lowest variance for structured extraction |
| `top_p` | 1.0 | With temp=0, top_p shouldn't matter; explicit for clarity |
| `max_tokens` | 2500 | Enough for ~50-component diagram; was 4096 (hit timeout) |
| `detail` | `"auto"` | Lets gpt-4o pick cheap tile path; `"high"` was 3-4× slower |
| `response_format` | `json_object` | Forces JSON output, simplifies parsing |
| `timeout` | 45 s | Below TCP idle, above realistic completion |

### Failure modes & guarantees

| Condition | Outcome |
|---|---|
| Malformed JSON from LLM | One repair pass; if still bad → `RuntimeError` |
| Azure throttling (429) | Tenacity 2 attempts, exponential backoff, fail to caller in <90 s |
| Azure timeout | 45 s timeout per attempt; analyzer's per-tile ceiling is 120 s |
| LLM returns unknown enum value | Coerced to known value or `"unknown"`, parsing warning emitted |
| `AZURE_OPENAI_API_KEY` blank | `MockLLMClient` returns canned schema-valid output for a sample Azure 3-tier |

**Output guarantee:** an `LLMExtraction` Pydantic object — components, connections, trust zones, parsing warnings — never partial.

### Where to look

- File: `apps/api/src/app/services/vision_llm.py`
- Prompts: `apps/api/src/app/prompts/` (`system_base.md`, `extraction.md`, `repair.md`)
- Coercion tests: `apps/api/tests/test_vision_llm_coerce.py`

---

## [4] `normalize.py` — canonicalize names

### What it does

The LLM is helpful but inconsistent in vocabulary. For the same icon it might say "Azure SQL Database", "Azure SQL DB", "SQL Server on Azure", or "Microsoft SQL". The bank's compliance rules need one canonical name per service.

This stage replaces every component's raw name with the **bank-approved canonical name** and attaches two more facts: the `service_type` (e.g. `database_relational`) and the `provider` (e.g. `azure`). It uses a taxonomy of ~280 entries spread across five JSON files.

### The Python logic

```python
# apps/api/src/app/services/normalize.py

TAXONOMY_DIR = Path(__file__).resolve().parent.parent / "taxonomy"
PROVIDER_FILES = {"azure": "azure", "aws": "aws", "gcp": "gcp", "oci": "oci"}

SERVICE_TYPE_TO_TIER = {
    "edge_waf": "edge", "cdn": "edge", "api_gateway": "edge",
    "load_balancer": "edge", "dns": "edge",
    "compute_vm": "app", "compute_serverless": "app",
    "compute_container": "app", "compute_k8s": "app",
    "storage_object": "data", "database_relational": "data",
    "database_nosql": "data", "database_cache": "data", ...
    "identity": "management", "logging": "management", "siem": "management",
    "user_actor": "edge",
}


@lru_cache
def _lookup_index() -> list[tuple[str, str, str, str]]:
    """Flatten all taxonomy files into a search index sorted by alias length
    (longest first, so 'Cosmos DB' wins over 'DB')."""
    index = []
    for provider, fname in PROVIDER_FILES.items():
        data = json.loads((TAXONOMY_DIR / f"{fname}_services.json").read_text())
        for alias, stype in data.items():
            index.append((alias.lower(), alias, stype, provider))
    generic = json.loads((TAXONOMY_DIR / "generic_patterns.json").read_text())
    for alias, stype in generic.items():
        prov = "on_prem" if stype in ("mainframe", "on_prem_app") else "other"
        index.append((alias.lower(), alias, stype, prov))
    index.sort(key=lambda t: -len(t[0]))      # longest first
    return index


def _match_service(raw_name: str):
    key = raw_name.strip().lower()
    if not key: return None
    for alias_lower, alias, stype, prov in _lookup_index():
        if alias_lower == key:                # exact match wins
            return alias, stype, prov
    for alias_lower, alias, stype, prov in _lookup_index():
        if len(alias_lower) >= 3 and alias_lower in key:    # substring
            return alias, stype, prov
    return None


def canonicalize_components(result: AnalysisResult) -> AnalysisResult:
    new_components = []
    providers_seen = set()
    for c in result.components:
        match = _match_service(c.name) or _match_service(c.canonical_name)
        canonical = c.canonical_name or c.name
        stype = c.service_type
        prov = c.provider
        if match:
            canon_alias, stype_match, prov_match = match
            canonical = canon_alias
            if stype == "unknown":      stype = stype_match
            if prov  == "other":        prov  = prov_match
        tier = c.tier if c.tier != "unknown" else SERVICE_TYPE_TO_TIER.get(stype, "unknown")
        new_components.append(c.model_copy(update={
            "canonical_name": canonical,
            "service_type":   stype,
            "provider":       prov,
            "tier":           tier,
        }))
        if prov != "other":
            providers_seen.add(prov)
    return result.model_copy(update={
        "components":      new_components,
        "cloud_providers": list(providers_seen) or result.cloud_providers,
    })


def infer_trust_zones_if_missing(result):
    """
    If the LLM gave no trust zones (or components reference dangling zones),
    create auto-zones from each component's tier and emit a parsing_warning.
    """
    tier_to_zone = {
        "edge": ("auto-perimeter", "perimeter"),
        "app":  ("auto-internal", "internal"),
        "data": ("auto-restricted", "restricted"),
        "management": ("auto-management", "management"),
    }
    ...


def derive_primary_provider(result):
    """Pick azure | aws | gcp | oci | multi | on_prem | unknown."""
    cloud = [p for p in result.cloud_providers if p in {"azure","aws","gcp","oci"}]
    if len(cloud) == 1:   primary = cloud[0]
    elif len(cloud) >= 2: primary = "multi"
    elif "on_prem" in result.cloud_providers: primary = "on_prem"
    else: primary = "unknown"
    return result.model_copy(update={"primary_provider": primary})
```

### Failure modes & guarantees

| Condition | Outcome |
|---|---|
| Component name not in taxonomy | Kept as-is, `service_type` stays `"unknown"`, no crash |
| Tier missing | Inferred from service_type (`database_*` → `data`, etc.) |
| Provider blank / "other" | Promoted to taxonomy-known provider if alias matches |
| All zones missing | Synthesized from tier (`edge` → `perimeter` etc.) + parsing_warning |

**Output guarantee:** every component has a `canonical_name`, `service_type`, `provider`, and `tier` — no nulls.

### Where to look

- File: `apps/api/src/app/services/normalize.py`
- Taxonomy: `apps/api/src/app/taxonomy/{azure,aws,gcp,oci,generic_patterns}_services.json`
- Tests: `apps/api/tests/test_normalize.py`

---

## [5] `classifier.py` — north-south vs east-west

### What it does

Labels every data-flow connection as either **north-south** (crosses a trust boundary) or **east-west** (stays within one zone). This is foundational input for compliance rules and for the journey extractor.

We deliberately don't use AI here — the rule is mechanical and must be auditable.

### The Python logic

```python
# apps/api/src/app/services/classifier.py — all 60 lines of it

from ..schemas import AnalysisResult, Flows, ParsingWarning, TrustZoneKind

ZONE_LEVEL: dict[TrustZoneKind, int] = {
    "external":   0,
    "perimeter":  1,
    "dmz":        2,
    "internal":   3,
    "restricted": 4,
    "management": 3,           # parallel to internal, not stricter
}


def classify_flows(result: AnalysisResult) -> AnalysisResult:
    component_to_zone = {c.id: c.trust_zone for c in result.components}
    zones_by_id = {z.id: z for z in result.trust_zones}

    ns, ew = [], []
    warnings = list(result.parsing_warnings)

    for conn in result.connections:
        if not conn.is_data_flow:
            continue                          # skip mgmt / dependency lines

        from_zone_id = component_to_zone.get(conn.from_)
        to_zone_id   = component_to_zone.get(conn.to)
        from_zone    = zones_by_id.get(from_zone_id) if from_zone_id else None
        to_zone      = zones_by_id.get(to_zone_id)   if to_zone_id   else None

        if from_zone is None or to_zone is None:
            # missing data → fail safe (treat as boundary-crossing)
            ns.append(conn.id)
            warnings.append(ParsingWarning(
                kind="ambiguous_edge",
                message=f"Connection {conn.id!r}: zone unknown for one endpoint; "
                        "classified conservatively as north-south.",
                affected_ids=[conn.id],
            ))
            continue

        if from_zone.kind == "external" or to_zone.kind == "external":
            ns.append(conn.id)
        elif ZONE_LEVEL[from_zone.kind] != ZONE_LEVEL[to_zone.kind]:
            ns.append(conn.id)                # crosses a tier
        else:
            ew.append(conn.id)                # same tier, both sides

    return result.model_copy(update={
        "flows":            Flows(north_south=ns, east_west=ew),
        "parsing_warnings": warnings,
    })
```

### Failure modes & guarantees

| Condition | Outcome |
|---|---|
| Connection's `from_` or `to` component missing | Classified as N-S, parsing warning emitted |
| Component's `trust_zone` references a deleted zone | Same as above |
| `is_data_flow=False` (a dependency/admin line) | Skipped entirely — not in either list |

**Output guarantee:** `result.flows.north_south` and `result.flows.east_west` together contain every data-flow connection exactly once.

### Where to look

- File: `apps/api/src/app/services/classifier.py`
- Tests: `apps/api/tests/test_classifier.py` (6 fixtures: clean Azure, multi-cloud, hybrid on-prem, missing zones, external-to-external, all-internal)

---

## [6] `compliance.py` — data-driven rules engine

### What it does

Evaluates the bank's mandatory architecture controls against the analyzed diagram. Each rule returns pass / fail / warn / not-applicable plus the components or connections that triggered the verdict.

The rules **live in JSON**, not code. A new rule means editing one file — no Python change, no redeploy. There are five generic check functions; rules pick one and supply parameters.

### The Python logic

```python
# apps/api/src/app/services/compliance.py

from functools import lru_cache
from pathlib import Path
import json

RULES_FILE = Path(__file__).resolve().parent.parent / "policies" / "compliance_rules.json"


@lru_cache(maxsize=1)
def _load_rules_cached(mtime: float):
    raw = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    return list(raw.get("rules", []))


def load_rules():
    """Cached by file mtime so hot-edits during dev are picked up."""
    return _load_rules_cached(RULES_FILE.stat().st_mtime)


# ── shared helpers ─────────────────────────────────────────────────
ENCRYPTED_PROTOCOLS = {"HTTPS","TLS","MTLS","SSH","SFTP","GRPCS","AMQPS","WSS"}
INSECURE_PROTOCOLS  = {"HTTP","FTP","TELNET","AMQP","MQTT","WS"}


def _is_encrypted(c: Connection):
    if c.encrypted is True:  return True
    if c.encrypted is False: return False
    proto = (c.protocol or "").upper()
    if proto in ENCRYPTED_PROTOCOLS: return True
    if proto in INSECURE_PROTOCOLS:  return False
    return None                            # unknown


def _component_zone_kind(result, comp_id):
    for c in result.components:
        if c.id == comp_id:
            for z in result.trust_zones:
                if z.id == c.trust_zone:
                    return z.kind
    return None


# ── 5 generic check functions ──────────────────────────────────────
def _check_external_ingress_terminates_on(result, rule, params):
    """Used by WAF_BEFORE_APP."""
    allowed = set(params["allowed_service_types"])
    bad = []
    for cid in result.flows.north_south:
        conn = next((c for c in result.connections if c.id == cid), None)
        if not conn: continue
        if _component_zone_kind(result, conn.from_) != "external": continue
        dst = next((c for c in result.components if c.id == conn.to), None)
        if dst and dst.service_type not in allowed:
            bad.append(conn.id)
    return _pass(rule) if not bad else _fail(rule, affected_connection_ids=bad)


def _check_components_not_in_zones(result, rule, params):
    """Used by NO_PUBLIC_DATA_TIER."""
    types = set(params["service_types"])
    forbidden = set(params["forbidden_zone_kinds"])
    bad = [c.id for c in result.components
           if c.service_type in types
           and _zone_kind(result, c.trust_zone) in forbidden]
    return _pass(rule) if not bad else _fail(rule, affected_component_ids=bad)


def _check_edges_encrypted(result, rule, params):
    """Used by TLS_ON_EXTERNAL_EDGES and ENCRYPTION_TO_RESTRICTED."""
    scope = params.get("scope", "all_data_flows")
    into_kinds = set(params.get("into_zone_kinds", []))
    ns_ids = set(result.flows.north_south)
    edges = ([c for c in result.connections if c.id in ns_ids]
             if scope == "north_south"
             else [c for c in result.connections if c.is_data_flow])
    fails, unknowns = [], []
    for conn in edges:
        target = (_component_zone_kind(result, conn.to)
                  if scope != "north_south"
                  else (_component_zone_kind(result, conn.to)
                        if _component_zone_kind(result, conn.to) != "external"
                        else _component_zone_kind(result, conn.from_)))
        if target not in into_kinds: continue
        enc = _is_encrypted(conn)
        if   enc is False: fails.append(conn.id)
        elif enc is None:  unknowns.append(conn.id)
    if fails:
        return _fail(rule, affected_connection_ids=fails)
    if unknowns:
        return _finding(rule, status=rule.get("unknown_status","warn"),
                        severity=rule.get("unknown_severity","medium"),
                        message=rule.get("unknown_message",""),
                        affected_connection_ids=unknowns)
    return _pass(rule)


def _check_private_endpoint_peering(result, rule, params):
    """Used by PRIVATE_ENDPOINTS_FOR_PAAS."""
    provider = params.get("provider")
    types    = set(params["service_types"])
    peer     = params["peer_service_type"]
    if provider and not any(c.provider == provider for c in result.components):
        return _na(rule)
    zone_has_peer = {c.trust_zone: True for c in result.components
                     if c.service_type == peer}
    bad = [c.id for c in result.components
           if (not provider or c.provider == provider)
           and c.service_type in types
           and not zone_has_peer.get(c.trust_zone, False)]
    return _pass(rule) if not bad else _fail(rule, affected_component_ids=bad)


def _check_at_least_one_component_of_type(result, rule, params):
    """Used by IDENTITY_PRESENT, LOGGING_PRESENT, SECRETS_VAULT_PRESENT."""
    required = set(params["required_service_types"])
    applies_when = params.get("applies_when")
    # Optional gating predicate
    if applies_when == "any_external_ns_flow":
        if not any(_touches_external(result, cid) for cid in result.flows.north_south):
            return _na(rule)
    elif applies_when == "any_database_or_saas":
        if not any(c.service_type.startswith("database_")
                   or c.service_type == "third_party_saas"
                   for c in result.components):
            return _na(rule)
    if any(c.service_type in required for c in result.components):
        return _pass(rule)
    return _fail(rule)


# ── registry + dispatcher ──────────────────────────────────────────
CHECKS = {
    "external_ingress_terminates_on": _check_external_ingress_terminates_on,
    "components_not_in_zones":         _check_components_not_in_zones,
    "edges_encrypted":                 _check_edges_encrypted,
    "private_endpoint_peering":        _check_private_endpoint_peering,
    "at_least_one_component_of_type":  _check_at_least_one_component_of_type,
}


def run_all(result: AnalysisResult) -> list[ComplianceFinding]:
    """The single entry point — evaluates every enabled rule."""
    findings = []
    for rule in load_rules():
        if not rule.get("enabled", True):
            continue
        check_fn = CHECKS.get(rule.get("check"))
        if check_fn is None:
            findings.append(ComplianceFinding(
                rule=rule.get("id", "UNKNOWN_RULE"),
                status="not_applicable", severity="info",
                message=f"Unknown check type: {rule.get('check')!r}",
            ))
            continue
        findings.append(check_fn(result, rule, rule.get("params") or {}))
    return findings
```

### One rule in JSON

```json
// policies/compliance_rules.json
{
  "id":           "WAF_BEFORE_APP",
  "title":        "WAF / edge guard precedes application tier",
  "enabled":      true,
  "severity":     "high",
  "fail_status":  "fail",
  "check":        "external_ingress_terminates_on",
  "params": {
    "allowed_service_types": ["edge_waf", "cdn", "api_gateway", "load_balancer"]
  },
  "pass_message": "All external ingress passes through an edge guard.",
  "fail_message": "External traffic terminates on a component that is not an edge guard."
}
```

### The eight controls today

| Rule ID | Severity | Verdict on violation |
|---|---|---|
| `WAF_BEFORE_APP` | high | fail |
| `NO_PUBLIC_DATA_TIER` | **critical** | fail (→ analysis is *rejected*) |
| `TLS_ON_EXTERNAL_EDGES` | high | fail; warn if encryption unknown |
| `ENCRYPTION_TO_RESTRICTED` | high | fail; warn if encryption unknown |
| `PRIVATE_ENDPOINTS_FOR_PAAS` | medium | warn |
| `IDENTITY_PRESENT` | medium | warn |
| `LOGGING_PRESENT` | low | warn |
| `SECRETS_VAULT_PRESENT` | low | warn |

### Failure modes & guarantees

| Condition | Outcome |
|---|---|
| Rule disabled (`enabled: false`) | Skipped, no finding |
| Rule references unknown check function | Single `not_applicable` finding, doesn't crash |
| `enabled` flag missing | Treated as `true` (fail open) |
| File missing entirely | Empty findings list, log error |

**Output guarantee:** one finding per enabled rule, in JSON-file order. Each finding carries `affected_component_ids` and `affected_connection_ids` for UI linking.

### Where to look

- File: `apps/api/src/app/services/compliance.py`
- Rules: `apps/api/src/app/policies/compliance_rules.json`
- Tests: `apps/api/tests/test_compliance.py` + `test_compliance_rules_json.py` (rule validity, dispatch correctness, JSON structure)
- API exposure: `GET /api/policies/compliance` returns the active rule set for ops/UI.

---

## [7] `journey_extractor.py` — graph walk + scoring

### What it does

Walks the connection graph from every entry actor (a user, the public internet) to every meaningful sink (a database, identity provider, secrets vault, third-party SaaS) and turns each path into a named, narrated, scored user journey — e.g. *"Customer → Front Door → App Service → Murex DB"*.

This is what management actually wants to read. North-south vs east-west is a network-engineer view; journeys are the story view.

### The Python logic

```python
# apps/api/src/app/services/journey_extractor.py

_MAX_PATH_LEN       = 8     # max hops per journey (bounds DFS)
_MAX_PATHS_PER_PAIR = 3     # at most N shortest paths per (entry, sink)
_MIN_SCORE          = 10    # below this → don't surface

_SINK_SERVICE_TYPES = {
    "database_relational", "database_nosql", "database_cache", "database_warehouse",
    "storage_object", "storage_file", "storage_block",
    "identity", "secrets_vault", "key_management",
    "messaging_queue", "messaging_pubsub", "messaging_event_stream",
    "third_party_saas", "mainframe", "on_prem_app",
    "monitoring", "logging", "siem",
}

_ENTRY_SERVICE_TYPES = {"user_actor"}


# ── step 1: build the directed graph ─────────────────────────────────
def _direction_for_edge(edge, components):
    """For undirected/bidirectional edges, infer direction from service types:
       - user_actor is always a source
       - data tier is always a sink
       - identity is genuinely bidirectional
       - everything else: emit both directions
    """
    if not edge.bidirectional:
        return [(edge.from_, edge.to, edge, False)]
    f, t = components[edge.from_], components[edge.to]
    if f.service_type == "user_actor" and t.service_type != "user_actor":
        return [(edge.from_, edge.to, edge, True)]
    if t.service_type == "user_actor" and f.service_type != "user_actor":
        return [(edge.to, edge.from_, edge, True)]
    is_sink = lambda st: st in _SINK_SERVICE_TYPES
    if is_sink(t.service_type) and not is_sink(f.service_type):
        return [(edge.from_, edge.to, edge, True)]
    if is_sink(f.service_type) and not is_sink(t.service_type):
        return [(edge.to, edge.from_, edge, True)]
    return [(edge.from_, edge.to, edge, True),
            (edge.to, edge.from_, edge, True)]


def _build_graph(result):
    adj = defaultdict(list)
    components = {c.id: c for c in result.components}
    for edge in result.connections:
        if not edge.is_data_flow:
            continue
        for f, t, e, inferred in _direction_for_edge(edge, components):
            adj[f].append((t, e, inferred))
    return adj, components


# ── step 2: iterative bounded DFS path enumeration ───────────────────
def _all_simple_paths(adj, src, dst, max_len=_MAX_PATH_LEN):
    stack = [(src, [(src, None, False)], {src})]
    while stack:
        node, path, visited = stack.pop()
        if node == dst and len(path) > 1:
            yield path
            continue
        if len(path) >= max_len:
            continue
        for nbr, edge, inferred in adj.get(node, []):
            if nbr in visited:        # no cycles
                continue
            stack.append((nbr,
                          [*path, (nbr, edge, inferred)],
                          visited | {nbr}))


# ── step 3: annotate, score, narrate ─────────────────────────────────
def _annotate_journey(path, components, zones, findings_by_comp,
                      findings_by_conn, journey_id):
    nodes = [components[node_id] for node_id, _, _ in path]
    src, dst = nodes[0], nodes[-1]

    hops, protocols, hop_enc, comp_ids, conn_ids = [], [], [], [], []
    for idx, (node_id, edge, inferred) in enumerate(path):
        if idx == 0: continue
        prev = components[path[idx-1][0]]
        cur  = components[node_id]
        enc  = _hop_encrypted(edge)
        hop_enc.append(enc)
        if edge and edge.protocol and edge.protocol not in protocols:
            protocols.append(edge.protocol)
        if edge: conn_ids.append(edge.id)
        hops.append(JourneyHop(
            **{"from": prev.id, "to": cur.id},
            from_name=prev.name, to_name=cur.name,
            label=edge.label if edge else None,
            protocol=edge.protocol if edge else None,
            port=edge.port if edge else None,
            encrypted=enc,
            from_zone_kind=zones.get(prev.trust_zone, ""),
            to_zone_kind=zones.get(cur.trust_zone, ""),
            connection_id=edge.id if edge else None,
            direction_inferred=inferred,
        ))
        comp_ids.append(cur.id)
    comp_ids.insert(0, src.id)

    # Distinct zones traversed in order
    zones_in_order = []
    for c in nodes:
        zk = zones.get(c.trust_zone, "")
        if zk and (not zones_in_order or zones_in_order[-1] != zk):
            zones_in_order.append(zk)

    has_unenc = any(e is False for e in hop_enc)
    all_enc   = all(e is True  for e in hop_enc) if hop_enc else None

    # Attach compliance findings that touched any node/edge on this path
    related = set()
    for cid in comp_ids: related.update(findings_by_comp.get(cid, []))
    for eid in conn_ids: related.update(findings_by_conn.get(eid, []))

    # ── scoring ──
    score = (
        len(set(zones_in_order)) * 10            # diverse zones
        + (20 if zones.get(src.trust_zone) == "external" else 0)
        + (20 if "restricted" in zones_in_order else 0)
        + (15 if has_unenc else 0)               # risky path
        + min(len(hops), 6) * 2                  # mild length bonus
        + (5 if related else 0)                  # has compliance hit
    )

    return Journey(
        id=journey_id,
        title=f"{src.name} → {dst.name}",
        kind=_journey_kind(dst),                 # auth | read | write | admin | integration
        hops=hops,
        component_ids=comp_ids,
        connection_ids=conn_ids,
        zones_crossed=zones_in_order,
        protocols=protocols,
        is_fully_encrypted=all_enc,
        has_unencrypted_hop=has_unenc,
        enters_restricted="restricted" in zones_in_order,
        starts_external=zones.get(src.trust_zone) == "external",
        related_findings=sorted(related),
        score=score,
        narrative=_narrate(hops, zones_in_order, has_unenc, dst),
        warnings=(["One or more hop directions were inferred."]
                  if any(h.direction_inferred for h in hops) else []),
    )


# ── step 4: public entry ─────────────────────────────────────────────
def extract_journeys(result: AnalysisResult) -> list[Journey]:
    if not result.components or not result.connections:
        return []

    adj, components = _build_graph(result)
    zones = {z.id: z.kind for z in result.trust_zones}

    entries = [c for c in result.components
               if c.service_type in _ENTRY_SERVICE_TYPES
               or zones.get(c.trust_zone) == "external"]
    sinks   = [c for c in result.components
               if c.service_type in _SINK_SERVICE_TYPES]
    if not entries or not sinks:
        return []

    # Index compliance findings by component & connection
    findings_by_comp, findings_by_conn = defaultdict(list), defaultdict(list)
    for f in result.compliance_findings:
        if f.status in ("pass", "not_applicable"):
            continue
        for cid in f.affected_component_ids:  findings_by_comp[cid].append(f.rule)
        for eid in f.affected_connection_ids: findings_by_conn[eid].append(f.rule)

    journeys = []
    seen_sigs = set()
    counter = 1
    for src in entries:
        for dst in sinks:
            if src.id == dst.id: continue
            paths = []
            for path in _all_simple_paths(adj, src.id, dst.id):
                paths.append(path)
                if len(paths) >= _MAX_PATHS_PER_PAIR:
                    break
            for path in paths:
                sig = tuple(n for n, _, _ in path)
                if sig in seen_sigs: continue
                seen_sigs.add(sig)
                j = _annotate_journey(path, components, zones,
                                      findings_by_comp, findings_by_conn,
                                      f"j-{counter}")
                if j and j.score >= _MIN_SCORE:
                    journeys.append(j); counter += 1

    # Sort by score desc, length asc (cleanest of an importance tier wins)
    journeys.sort(key=lambda j: (-j.score, len(j.hops)))

    # Drop journeys that are a strict prefix of another
    deduped = []
    for j in journeys:
        sig = tuple(j.component_ids)
        if any(tuple(o.component_ids)[: len(sig)] == sig and len(o.component_ids) > len(sig)
               for o in deduped):
            continue
        deduped.append(j)

    return deduped[:25]    # cap to keep UI readable
```

### A `Journey` in the output

```json
{
  "id": "j-1",
  "title": "Customer → Azure SQL Database",
  "kind": "write",
  "hops": [
    {"from":"c-cust","to":"c-fd","from_name":"Customer","to_name":"Front Door",
     "protocol":"HTTPS","port":443,"encrypted":true,
     "from_zone_kind":"external","to_zone_kind":"perimeter","direction_inferred":false},
    {"from":"c-fd","to":"c-app","from_name":"Front Door","to_name":"App Service",
     "protocol":"HTTPS","port":443,"encrypted":true,
     "from_zone_kind":"perimeter","to_zone_kind":"internal","direction_inferred":false},
    {"from":"c-app","to":"c-sql","from_name":"App Service","to_name":"Azure SQL Database",
     "protocol":"TLS","port":1433,"encrypted":true,
     "from_zone_kind":"internal","to_zone_kind":"restricted","direction_inferred":false}
  ],
  "zones_crossed": ["external","perimeter","internal","restricted"],
  "protocols": ["HTTPS","TLS"],
  "is_fully_encrypted": true,
  "has_unencrypted_hop": false,
  "enters_restricted": true,
  "starts_external": true,
  "related_findings": ["PRIVATE_ENDPOINTS_FOR_PAAS"],
  "score": 95,
  "narrative": "Customer writes to Azure SQL Database crossing external → perimeter → internal → restricted with TLS at every hop.",
  "warnings": [],
  "kind": "write"
}
```

### Failure modes & guarantees

| Condition | Outcome |
|---|---|
| No entry actors / no sinks | Empty `journeys` list, no error |
| Cyclic graph | Bounded DFS (`max_len=8`) — guaranteed termination |
| Bidirectional edge with no obvious sink/source | Both directions emitted; scoring picks the meaningful one |
| Two paths share the same prefix | Shorter one dropped (kept only the most informative story) |
| > 25 viable journeys | Top 25 by score kept |

**Output guarantee:** `journeys` is a list ranked highest-score first, capped at 25 entries, each linked back to the compliance findings touching its path.

### Where to look

- File: `apps/api/src/app/services/journey_extractor.py`
- Tests: `apps/api/tests/test_journey_extractor.py` (8 fixtures: linear, multi-entry/sink, cyclic, undirected with inferred direction, unencrypted hop boosting score, isolated components, no-sinks, compliance binding)

---

## Orchestration — putting all seven together

```python
# apps/api/src/app/services/analyzer.py — the public entry point

async def analyze_diagram(file_bytes, filename, *, title="", description="",
                          submitted_by=None):
    diagram_id = uuid.uuid4().hex
    arc_number = next_arc_number()
    timings = {"image_prep": 0, "doc_intelligence": 0,
               "vision_llm": 0, "post_process": 0}

    # [1] image_prep
    t0 = time.perf_counter()
    detected_fmt, pages = image_prep.prepare(file_bytes, filename)
    timings["image_prep"] = int((time.perf_counter() - t0) * 1000)
    save_upload(diagram_id, _suffix_for(filename, detected_fmt), file_bytes)
    save_processed(diagram_id, pages[0].png_bytes)

    ocr_client = doc_intelligence.get_client()       # real or mock
    llm_client = vision_llm.get_client()              # real or mock

    # [2] + [3] per page (with tiling for huge images)
    page_extractions = []
    for page in pages:
        ex = await _extract_from_page(page, ocr_client, llm_client, timings)
        page_extractions.append(ex)
    merged = _merge_pages(page_extractions)

    # build the AnalysisResult skeleton
    result = _build_result(diagram_id, arc_number, title, description,
                           submitted_by, filename,
                           _detect_input_format(filename, detected_fmt),
                           pages[0], merged, total_tiles=...)

    # [4] normalize
    t1 = time.perf_counter()
    result = normalize.canonicalize_components(result)
    result = normalize.infer_trust_zones_if_missing(result)
    result = normalize.derive_primary_provider(result)

    # [5] classifier
    result = classifier.classify_flows(result)

    # [6] compliance
    findings = compliance.run_all(result)
    result = result.model_copy(update={"compliance_findings": findings})

    # [7] journey extractor (after compliance so journeys can reference findings)
    journeys = journey_extractor.extract_journeys(result)
    result = result.model_copy(update={"journeys": journeys})

    # confidence + review state
    confidence = _compute_confidence(result)
    review     = _compute_review_state(result)
    timings["post_process"] = int((time.perf_counter() - t1) * 1000)

    result = result.model_copy(update={
        "overall_confidence": confidence,
        "review_state":       review,
        "processing_ms":      ProcessingMs(**timings, total=sum(timings.values())),
    })

    save_analysis(result)
    return result
```

### Stage timings — typical 1200 × 800 diagram

| Stage | Wall-clock | Why |
|---|---|---|
| `image_prep` | 30–80 ms | One Pillow open + downscale + autocontrast |
| `doc_intelligence` | 3–5 s | Azure OCR; dominated by network + queue |
| `vision_llm` | 8–15 s | gpt-4o multimodal call; ~66 tokens/s output |
| `normalize` | < 5 ms | Pure lookups |
| `classifier` | < 1 ms | One pass over edges |
| `compliance` | < 5 ms | 8 rule evaluations, all O(n) |
| `journey_extractor` | < 10 ms | Bounded DFS, ≤ 25 final journeys |
| `save_analysis` | < 5 ms | Single JSON write |
| **Total** | **~12–20 s** | dominated by the two Azure calls |

---

## What lands in `data/analyses/<uuid>.json`

```json
{
  "diagram_id": "abc123…",
  "arc_number": "ARC-202605-012",
  "title": "eBranch Demo VNet — Prod",
  "submitted_by": {"employee_id": "VRC2106734", "name": "Vasu Reddy", ...},
  "submitted_at": "2026-05-19T05:42:01Z",
  "filename": "ebranch.png",
  "input_format": "png",
  "image_dimensions": {"width": 1247, "height": 838},
  "tiles_processed": 1,

  "cloud_providers": ["azure"],
  "primary_provider": "azure",
  "diagram_style": "official_stencil",

  "trust_zones":  [ {"id":"tz-ext","name":"Internet","kind":"external"}, ... ],
  "components":   [ {"id":"c-1","name":"Front Door","canonical_name":"Azure Front Door",
                     "service_type":"edge_waf","provider":"azure","tier":"edge",
                     "trust_zone":"tz-perim","evidence":{...}}, ... ],
  "connections":  [ {"id":"e-1","from":"c-user","to":"c-fd","protocol":"HTTPS",
                     "port":443,"encrypted":true,"is_data_flow":true,...}, ... ],
  "flows":        {"north_south":["e-1","e-2","e-3"], "east_west":["e-4"]},
  "journeys":     [ {"id":"j-1","title":"User → Azure SQL Database", ...} ],

  "compliance_findings": [
    {"rule":"WAF_BEFORE_APP","status":"pass","severity":"info","message":"...",
     "affected_component_ids":[], "affected_connection_ids":[]},
    ...
  ],
  "parsing_warnings": [
    {"kind":"low_confidence_component","message":"...","affected_ids":["c-7"]}
  ],

  "overall_confidence": 0.87,
  "review_state": "auto_review_recommended",
  "processing_ms": {"image_prep":47, "doc_intelligence":4112, "vision_llm":8915,
                    "post_process":12, "total":13086}
}
```

This JSON is the **single artifact** every downstream consumer (UI, report, chatbot, audit log, future caching layer) reads.

---

## Adding a new compliance rule — concrete example

Say the bank decides every external HTTPS edge must declare port 443 explicitly. No code change is needed if an existing check covers it:

```jsonc
// policies/compliance_rules.json
{
  "id": "EXPLICIT_PORT_ON_EXTERNAL_EDGES",
  "title": "External HTTPS edges must declare port 443",
  "enabled": true,
  "severity": "low",
  "fail_status": "warn",
  "check": "edges_encrypted",         // reuses existing check
  "params": {
    "scope": "north_south",
    "into_zone_kinds": ["perimeter", "dmz"],
    "require_port": 443                // new param the check would need to honor
  },
  "pass_message": "All external HTTPS edges declare port 443.",
  "fail_message": "External HTTPS edges with missing or non-443 port."
}
```

If the new param isn't yet supported by `_check_edges_encrypted`, that's the **one Python change** required — extend the check function, write tests, ship. Adding *more* rules of the same shape afterwards is purely JSON.

---

## Tests

| File | Coverage |
|---|---|
| `tests/test_image_prep.py` | Format sniffing, EXIF, downscale, autocontrast |
| `tests/test_doc_intelligence_mock.py` | Mock client returns valid `OCRResult` |
| `tests/test_vision_llm_coerce.py` | Every drift pattern in `_coerce_llm_json` |
| `tests/test_normalize.py` | Taxonomy lookups, tier inference, zone inference |
| `tests/test_classifier.py` | 6 graph fixtures including missing-zone and external-to-external |
| `tests/test_compliance.py` + `tests/test_compliance_rules_json.py` | Every rule, plus rule-file validity & dispatch |
| `tests/test_journey_extractor.py` | 8 graph fixtures including cycles & inferred direction |
| `tests/test_analyzer_integration.py` | End-to-end with mocks: bytes in → AnalysisResult out |

Run it:

```bash
cd apps/api
uv run pytest -q
# ... 65 passed in 1.85s
```

Every test runs **without network access** and **without Azure credentials** — mocks handle both external services.

---

## Logging — what to grep when things break

Every stage emits structured begin/end/error events to `data/logs/api.log`:

```jsonl
{"timestamp":"2026-05-19T05:42:01Z","logger":"vision_llm","event":"vision_llm.azure_call.end","request_id":"abc","employee_id":"VRC2106734","duration_ms":7314,"prompt_tokens":1532,"completion_tokens":712,"model":"gpt-4o-2024-11-20"}
```

Useful queries:

```bash
# Full timeline of one request
grep '"request_id": "abc"' data/logs/api.log | jq -c

# Slowest 10 LLM calls today
grep '"vision_llm.azure_call.end"' data/logs/api.log | jq -s 'sort_by(-.duration_ms)[0:10]'

# Everything an employee did
grep '"employee_id": "VRC2106734"' data/logs/api.log | jq -c

# Today's errors
grep '".error"' data/logs/api.log | jq -c '{ts:.timestamp,event,error,path}'
```

Or use the UI: sign in as an admin and open `/admin/logs`.

---

## Knobs you'll actually want to tune

All exposed via `apps/api/src/app/config.py` and `.env`:

| Setting | Default | Purpose |
|---|---|---|
| `LLM_TEMPERATURE` | `0.0` | Vision determinism |
| `LLM_TOP_P` | `1.0` | Same |
| `LLM_SEED` | `42` | (Set on chat path; vision currently strips it — see comment in `vision_llm.py`) |
| `LLM_MAX_TOKENS` | `2500` | Output budget; raise only if dense diagrams truncate |
| `TILE_THRESHOLD_PX` | `2400` | Images bigger than this get tiled before LLM |
| `TILE_SIZE_PX` | `2048` | Each tile size |
| `TILE_OVERLAP_PX` | `256` | Tile overlap to avoid components on the seam |
| `MAX_UPLOAD_MB` | `50` | Request body cap |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated |

Hot-reload of the rule set (`policies/compliance_rules.json`) is automatic — uvicorn doesn't need to restart, the loader is cached by mtime.

---

## When something is wrong, in this order

1. **Tail the log file**: `tail -f apps/api/data/logs/api.log | jq -c`
2. **Look for `.error` events**, grab the `request_id`
3. **Replay the timeline**: `grep '"request_id": "<id>"' data/logs/api.log | jq -c`
4. The narrowest answer is usually in the `.end` event of the failing stage — `duration_ms`, `payload_bytes`, `system_fingerprint` give you everything
5. If it's an LLM issue: blank `AZURE_OPENAI_API_KEY` in `.env`, restart, confirm the mock pipeline works. Now you know the code is fine and Azure is misbehaving.

Happy hacking.
