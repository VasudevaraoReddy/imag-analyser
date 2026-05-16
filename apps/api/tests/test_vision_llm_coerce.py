"""Coerce real-world LLM drift patterns into a valid LLMExtraction."""

from app.schemas import LLMExtraction
from app.services.vision_llm import _coerce_llm_json


def test_coerce_off_enum_style_and_zone_kinds():
    raw = {
        "diagram_style": "formal",
        "cloud_providers": ["Microsoft", "azure"],
        "trust_zones": [
            {"name": "eb-demo-vnet", "kind": "vnet",
             "evidence": {"bbox": [185, 132, 262, 144]}},
            {"name": "eb-demo-subnet-web", "kind": "subnet",
             "evidence": {"bbox": [292, 182, 407, 195]}},
            {"name": "eb-demo-subnet-data", "kind": "subnet"},
            {"name": "Internet", "kind": "public"},
        ],
        "components": [
            {"name": "web-nsg",
             "evidence": {"bbox": [320, 158, 368, 170]}},
            {"name": "web-vm-1", "trust_zone": "eb-demo-subnet-web",
             "evidence": {"bbox": [314, 277, 369, 290]}},
            {"name": "db-vm", "trust_zone": "eb-demo-subnet-data",
             "evidence": {"bbox": [841, 393, 876, 404]}},
            {"name": "User", "trust_zone": "Internet",
             "evidence": {"bbox": [34, 319, 61, 330]}},
        ],
        "connections": [
            {"source": "User", "target": "web-vm-1", "is_data_flow": True},
            {"source": "web-vm-1", "target": "db-vm",
             "protocol": "TLS", "encrypted": True, "is_data_flow": True},
        ],
        "overall_confidence": 0.88,
    }
    coerced, _ = _coerce_llm_json(raw)
    # Validates cleanly
    ex = LLMExtraction.model_validate(coerced)
    assert ex.diagram_style == "official_stencil"
    assert "azure" in ex.cloud_providers
    # vnet/subnet → internal; public → external
    kinds_by_name = {z.name: z.kind for z in ex.trust_zones}
    assert kinds_by_name["eb-demo-vnet"] == "internal"
    assert kinds_by_name["eb-demo-subnet-web"] == "internal"
    assert kinds_by_name["eb-demo-subnet-data"] in {"restricted", "internal"}
    assert kinds_by_name["Internet"] == "external"
    # all zones got ids
    assert all(z.id for z in ex.trust_zones)
    # zone evidence stringified
    web_zone = next(z for z in ex.trust_zones if z.name == "eb-demo-subnet-web")
    assert isinstance(web_zone.evidence, str)
    # all components got ids and confidences
    assert all(c.id for c in ex.components)
    assert all(0.0 <= c.evidence.confidence <= 1.0 for c in ex.components)
    # source/target renamed to from/to; refs remapped to component ids
    ids = {c.id for c in ex.components}
    for conn in ex.connections:
        assert conn.from_ in ids
        assert conn.to in ids
    # component trust_zone references remap from zone-name to zone-id
    user = next(c for c in ex.components if c.name == "User")
    internet_zone = next(z for z in ex.trust_zones if z.name == "Internet")
    assert user.trust_zone == internet_zone.id


def test_coerce_off_enum_service_types():
    raw = {
        "components": [
            {"name": "SMTP", "service_type": "messaging_email",
             "evidence": {"bbox": [0, 0, 10, 10], "confidence": 0.8}},
            {"name": "AKS", "service_type": "kubernetes",
             "evidence": {"bbox": [0, 0, 10, 10], "confidence": 0.8}},
            {"name": "MyApp", "service_type": "WeirdInventedType",
             "evidence": {"bbox": [0, 0, 10, 10], "confidence": 0.8}},
            {"name": "MQ", "service_type": "queue",
             "evidence": {"bbox": [0, 0, 10, 10], "confidence": 0.8}},
        ],
    }
    coerced, _ = _coerce_llm_json(raw)
    ex = LLMExtraction.model_validate(coerced)
    types = {c.name: c.service_type for c in ex.components}
    assert types["SMTP"] == "integration_service"
    assert types["AKS"] == "compute_k8s"
    assert types["MyApp"] == "unknown"
    assert types["MQ"] == "messaging_queue"
    # An "unknown_icon" warning was added for the invented type
    kinds = {w.kind for w in ex.parsing_warnings}
    assert "unknown_icon" in kinds


def test_coerce_handles_completely_minimal_input():
    raw = {
        "components": [{"name": "X"}],
    }
    coerced, _ = _coerce_llm_json(raw)
    ex = LLMExtraction.model_validate(coerced)
    assert len(ex.components) == 1
    assert ex.diagram_style == "unknown"
    assert ex.components[0].evidence.bbox == [0.0, 0.0, 0.0, 0.0]
