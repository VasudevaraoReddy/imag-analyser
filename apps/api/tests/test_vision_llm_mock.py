import asyncio

from app.schemas import LLMExtraction
from app.services.doc_intelligence import MockOCRClient
from app.services.vision_llm import MockLLMClient


def test_mock_llm_returns_valid_extraction():
    client = MockLLMClient()
    ocr = asyncio.run(MockOCRClient().extract(b"x"))
    ex = asyncio.run(client.extract(b"sample bytes", ocr, 1600, 900))
    assert isinstance(ex, LLMExtraction)
    assert len(ex.components) >= 5
    assert any(c.service_type == "edge_waf" for c in ex.components)
    assert any(c.service_type == "database_relational" for c in ex.components)
    assert ex.overall_confidence > 0.5
