import asyncio

from app.services.chatbot import MockChatClient


def test_mock_stream_yields_full_text():
    client = MockChatClient()

    async def run():
        out = []
        async for delta in client.astream(
            [{"role": "user", "content": "summary"}],
            analysis=None,
        ):
            out.append(delta)
        return out

    chunks = asyncio.run(run())
    assert len(chunks) > 1, "stream should produce multiple deltas"
    assembled = "".join(chunks)
    # The mock returns a fixed help message when there's no analysis context
    assert "general questions" in assembled.lower() or "analysis" in assembled.lower()
