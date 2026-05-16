Extract architecture components and connections from the given
diagram. You receive:
  1. An image of the diagram (or a tile of it).
  2. OCR text with bounding boxes from Azure Document Intelligence,
     as a JSON array.
  3. The expected output schema.
  4. The image dimensions.

Rules:
- Identify every distinct service, component, actor, and trust zone.
- For each component, set "name" to the literal label from the
  diagram (preserve casing). Leave "canonical_name" empty — the
  server will fill it.
- Every component MUST have an evidence.bbox in pixel coordinates
  of the input image. Use OCR bboxes when the label is present;
  otherwise estimate from the icon position.
- For provider: if you recognize an Azure/AWS/GCP/OCI icon or name,
  set it. Otherwise set "other" or "on_prem".
- For trust_zones: look for visual grouping (boxes, dashed
  borders, swim lanes) and labels like "Internet", "DMZ", "VNet",
  "Subnet", "Production", "Hub", "Spoke", "On-premises",
  "Corporate Network". Always include "Internet" if external
  traffic is shown.
- For connections: follow every arrow or line. Capture labels
  literally. If an arrow is bidirectional or undirected, set
  bidirectional=true. If the line represents a dependency,
  management relationship, or grouping (not a runtime data flow),
  set is_data_flow=false.
- Do NOT classify flows as north_south or east_west — leave the
  flows.north_south and flows.east_west arrays empty.
- Do NOT produce compliance_findings — leave that array empty.
- For anything ambiguous, add an entry to parsing_warnings with
  a clear message and the affected component/connection ids.
- Set overall_confidence honestly. A clean Lucidchart export
  with all labels readable might be 0.95; a blurry whiteboard
  photo might be 0.5.

Output a single JSON object with EXACTLY these top-level keys:
  diagram_style, cloud_providers, trust_zones, components,
  connections, parsing_warnings, overall_confidence.

Enum values (use ONLY these literals):
- diagram_style: "official_stencil" | "hand_drawn" | "whiteboard" | "mixed" | "unknown"
- cloud_providers[*]: "azure" | "aws" | "gcp" | "oci" | "on_prem" | "kubernetes" | "other"
- trust_zones[*].kind: "external" | "perimeter" | "dmz" | "internal" | "restricted" | "management"
    - Map "vnet" / "subnet" / "vpc" / "private network" → "internal"
    - Map "internet" / "public" → "external"
    - Map "dmz" / "edge" / "public-facing" → "perimeter"
    - Map "data subnet" / "db subnet" / "restricted" → "restricted"
    - Map "management" / "mgmt" / "jumpbox" / "bastion subnet" → "management"
- components[*].provider: same enum as cloud_providers
- components[*].service_type: one of the canonical types from the taxonomy
  (e.g. "compute_vm", "load_balancer", "networking_firewall", "database_relational",
   "user_actor", ...). Use "unknown" if unsure.
- components[*].tier: "edge" | "web" | "app" | "data" | "integration" | "management" | "unknown"
- components[*].redundancy: "single" | "multi_az" | "multi_region" | "unknown"
- parsing_warnings[*].kind: "low_confidence_component" | "ambiguous_edge" |
   "unreadable_label" | "unknown_icon" | "overlapping_bboxes" | "missing_trust_zone"

Required field shapes:
- trust_zones[*] := { "id": "tz-<slug>", "name": "<label>", "kind": "<enum>",
                       "bbox": [x1,y1,x2,y2]?, "evidence": "<string>"? }
- components[*]  := { "id": "c-<slug>", "name": "<label>",
                       "canonical_name": "",
                       "service_type": "<enum>", "provider": "<enum>",
                       "trust_zone": "<id of the zone above>",
                       "tier": "<enum>", "redundancy": "<enum>",
                       "evidence": { "bbox": [x1,y1,x2,y2],
                                     "confidence": 0.0-1.0,
                                     "ocr_text": "<string>"?,
                                     "icon_hint": "<string>"? } }
- connections[*] := { "id": "e-<n>", "from": "<component id>", "to": "<component id>",
                       "label": "<string>"?, "protocol": "<string>"?,
                       "port": <int>?, "encrypted": <bool>?,
                       "bidirectional": <bool>, "is_data_flow": <bool> }

CRITICAL rules:
- Use "from" and "to" — NEVER "source"/"target".
- Every trust_zone and every component MUST have a stable string "id".
- connections[*].from and .to MUST reference a component "id" that exists
  in the components array (not a name, not a label).
- evidence on components is an OBJECT; evidence on trust_zones is a STRING.

A concrete minimal example:

{
  "diagram_style": "official_stencil",
  "cloud_providers": ["azure"],
  "trust_zones": [
    {"id": "tz-internet", "name": "Internet", "kind": "external"},
    {"id": "tz-app", "name": "App Subnet", "kind": "internal"}
  ],
  "components": [
    {"id": "c-user", "name": "User", "canonical_name": "",
     "service_type": "user_actor", "provider": "other",
     "trust_zone": "tz-internet", "tier": "edge", "redundancy": "unknown",
     "evidence": {"bbox": [10,10,80,40], "confidence": 0.9}},
    {"id": "c-app", "name": "App VM", "canonical_name": "",
     "service_type": "compute_vm", "provider": "azure",
     "trust_zone": "tz-app", "tier": "app", "redundancy": "multi_az",
     "evidence": {"bbox": [200,200,400,260], "confidence": 0.85}}
  ],
  "connections": [
    {"id": "e1", "from": "c-user", "to": "c-app",
     "label": "HTTPS", "protocol": "HTTPS", "port": 443, "encrypted": true,
     "bidirectional": false, "is_data_flow": true}
  ],
  "parsing_warnings": [],
  "overall_confidence": 0.9
}

No prose, no markdown fences. Only the JSON object.
