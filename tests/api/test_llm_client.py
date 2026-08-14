"""Tests for k7e_api.llm_client and k7e_api.interpretation modules.

TDD: tests written before implementation.

Covers:
- StubLLMClient returns a dict that validates as Interpretation with citations and confidence in [0,1].
- LiteLLMClient raises LLMOutputError when litellm returns invalid JSON.
"""

from unittest.mock import MagicMock

import pytest
from k7e_api.interpretation import Interpretation
from k7e_api.llm_client import LiteLLMClient, LLMOutputError, StubLLMClient

# ---------------------------------------------------------------------------
# StubLLMClient tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_returns_expected_shape():
    """StubLLMClient.complete_json returns a dict that parses as Interpretation."""
    result = await StubLLMClient().complete_json(
        system="s",
        user="u",
        schema_name="Interpretation",
    )
    interp = Interpretation.model_validate(result)
    assert interp.title, "title must be non-empty"
    assert interp.slug, "slug must be non-empty"
    assert interp.summary, "summary must be non-empty"
    assert interp.markdown_body, "markdown_body must be non-empty"
    assert 0.0 <= interp.confidence <= 1.0, "confidence must be in [0, 1]"
    assert len(interp.citations) >= 1, "must have at least one citation"
    for citation in interp.citations:
        assert citation.quote, "each citation must have a non-empty quote"


# ---------------------------------------------------------------------------
# LiteLLMClient raises LLMOutputError on invalid JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_litellm_client_raises_on_invalid_json(monkeypatch):
    """LiteLLMClient.complete_json raises LLMOutputError when litellm returns non-JSON content."""
    # Build a fake response object whose choices[0].message.content is "not json"
    fake_message = MagicMock()
    fake_message.content = "not json"

    fake_choice = MagicMock()
    fake_choice.message = fake_message

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    # Monkeypatch litellm.acompletion to return the fake response
    import litellm

    async def fake_acompletion(**kwargs):
        return fake_response

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    client = LiteLLMClient()
    with pytest.raises(LLMOutputError):
        await client.complete_json(
            system="system prompt",
            user="user prompt",
            schema_name="Interpretation",
        )


@pytest.mark.asyncio
async def test_litellm_client_routes_aliases_through_proxy(monkeypatch):
    """LiteLLMClient prefixes local model aliases for OpenAI-compatible proxy routing."""
    calls = []

    fake_message = MagicMock()
    fake_message.content = '{"ok": true}'

    fake_choice = MagicMock()
    fake_choice.message = fake_message

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    import litellm

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return fake_response

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setenv("WIKI_MODEL", "wiki-anthropic")

    from k7e_api.config import get_settings

    get_settings.cache_clear()
    try:
        result = await LiteLLMClient().complete_json(
            system="system prompt",
            user="user prompt",
            schema_name="Interpretation",
        )
    finally:
        get_settings.cache_clear()

    assert result == {"ok": True}
    assert calls[0]["model"] == "openai/wiki-anthropic"


@pytest.mark.asyncio
async def test_litellm_client_strips_markdown_code_fence(monkeypatch):
    """LiteLLMClient.complete_json parses JSON wrapped in a ```json ... ``` fence.

    Claude returns valid JSON but wraps it in a markdown code fence even when
    response_format=json_object is requested. The client must strip the fence
    before parsing so ingest does not fail with JSONDecodeError.
    """
    fenced_content = '```json\n{"title": "Hello", "ok": true}\n```'

    fake_message = MagicMock()
    fake_message.content = fenced_content

    fake_choice = MagicMock()
    fake_choice.message = fake_message

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    import litellm

    async def fake_acompletion(**kwargs):
        return fake_response

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = await LiteLLMClient().complete_json(
        system="s",
        user="u",
        schema_name="OkfExtraction",
    )
    assert result == {"title": "Hello", "ok": True}


@pytest.mark.asyncio
async def test_litellm_client_strips_plain_code_fence(monkeypatch):
    """LiteLLMClient strips plain ``` fences (no language tag) too."""
    fenced_content = '```\n{"x": 1}\n```'

    fake_message = MagicMock()
    fake_message.content = fenced_content

    fake_choice = MagicMock()
    fake_choice.message = fake_message

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    import litellm

    async def fake_acompletion(**kwargs):
        return fake_response

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = await LiteLLMClient().complete_json(system="s", user="u", schema_name="X")
    assert result == {"x": 1}


@pytest.mark.asyncio
async def test_litellm_client_accepts_literal_newlines_in_strings(monkeypatch):
    """LiteLLMClient parses JSON with literal (unescaped) newlines in string values.

    Claude embeds real newline characters inside JSON string values instead of
    the JSON escape sequence \\n.  strict=False makes json.loads accept these
    without error so multi-line markdown_body fields don't fail ingest.
    """
    # Construct a JSON string with a REAL newline inside the string value
    # (not the two-char escape sequence \\n — a literal 0x0A byte).
    content_with_literal_newline = '{"markdown_body": "# Title\n\nSome text\n- bullet"}'
    assert "\n" in content_with_literal_newline  # confirm it's a real newline

    fake_message = MagicMock()
    fake_message.content = content_with_literal_newline

    fake_choice = MagicMock()
    fake_choice.message = fake_message

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    import litellm

    async def fake_acompletion(**kwargs):
        return fake_response

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = await LiteLLMClient().complete_json(system="s", user="u", schema_name="OkfCompose")
    assert "markdown_body" in result
    assert "Title" in result["markdown_body"]
    assert "bullet" in result["markdown_body"]


@pytest.mark.asyncio
async def test_litellm_client_accepts_literal_tabs_in_strings(monkeypatch):
    """LiteLLMClient parses JSON with literal tab characters in string values."""
    content_with_tab = '{"text": "col1\tcol2\tcol3"}'

    fake_message = MagicMock()
    fake_message.content = content_with_tab

    fake_choice = MagicMock()
    fake_choice.message = fake_message

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    import litellm

    async def fake_acompletion(**kwargs):
        return fake_response

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = await LiteLLMClient().complete_json(system="s", user="u", schema_name="X")
    assert result["text"] == "col1\tcol2\tcol3"


# ---------------------------------------------------------------------------
# transcribe_image (vision extraction)
# ---------------------------------------------------------------------------


def _fake_vision_response(content):
    fake_message = MagicMock()
    fake_message.content = content
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    return fake_response


@pytest.mark.asyncio
async def test_transcribe_image_sends_multimodal_content_parts(monkeypatch):
    """transcribe_image routes the vision alias and sends image_url content parts.

    The user message must be OpenAI-style content parts: a text part followed by
    an image_url part whose data URL carries the input bytes base64-encoded.
    No response_format is sent (plain text out, not JSON).
    """
    import base64

    import litellm

    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return _fake_vision_response("  Extracted page text.  ")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    image_bytes = b"\xff\xd8fake-jpeg-bytes"
    client = LiteLLMClient()
    text = await client.transcribe_image(
        system="transcribe faithfully",
        user="Transcribe page 1 of 3.",
        image_mime="image/jpeg",
        image_data=image_bytes,
    )

    assert text == "Extracted page text."
    kwargs = calls[0]
    assert kwargs["model"] == "openai/wiki-vision"
    assert "response_format" not in kwargs
    parts = kwargs["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "Transcribe page 1 of 3."}
    url = parts[1]["image_url"]["url"]
    prefix = "data:image/jpeg;base64,"
    assert url.startswith(prefix)
    assert base64.b64decode(url[len(prefix) :]) == image_bytes
    assert client.usage["calls"] == 1


@pytest.mark.asyncio
async def test_transcribe_image_joins_thinking_block_content(monkeypatch):
    """List-of-blocks (thinking mode) content is joined to plain text."""
    import litellm

    blocks = [
        {"type": "thinking", "thinking": "hmm"},
        {"type": "text", "text": "Part one. "},
        {"type": "text", "text": "Part two."},
    ]

    async def fake_acompletion(**kwargs):
        return _fake_vision_response(blocks)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    text = await LiteLLMClient().transcribe_image(
        system="s", user="u", image_mime="image/png", image_data=b"png"
    )
    assert text == "Part one. Part two."


@pytest.mark.asyncio
async def test_transcribe_image_raises_on_missing_content(monkeypatch):
    """None content raises LLMOutputError instead of returning 'None'."""
    import litellm

    async def fake_acompletion(**kwargs):
        return _fake_vision_response(None)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    with pytest.raises(LLMOutputError):
        await LiteLLMClient().transcribe_image(
            system="s", user="u", image_mime="image/png", image_data=b"png"
        )


@pytest.mark.asyncio
async def test_stub_transcribe_image_is_deterministic():
    """StubLLMClient.transcribe_image returns a stable string and tracks usage."""
    client = StubLLMClient()
    first = await client.transcribe_image(
        system="s", user="u", image_mime="image/png", image_data=b"abc"
    )
    second = await client.transcribe_image(
        system="s", user="u", image_mime="image/png", image_data=b"abc"
    )
    assert first == second
    assert first.strip()
    assert client.usage["calls"] == 2
    assert client.usage["total_tokens"] == 30
