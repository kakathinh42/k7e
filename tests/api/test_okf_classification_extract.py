"""M4: extraction emits a domain, coerced against the governed enum."""

from __future__ import annotations

from k7e_api.okf_extract import OkfExtraction, build_extract_prompt, extract_okf


class _StubClient:
    """Returns a controllable OkfExtraction payload."""

    def __init__(self, domain):
        self._domain = domain

    async def complete_json(self, *, system, user, schema_name):
        return {
            "title": "Payment Retry",
            "slug": "payment-retry",
            "summary": "How retries work.",
            "tags": ["retry"],
            "domain": self._domain,
            "entities": [],
            "concepts": [],
            "citations": [],
            "references": [],
        }


async def test_valid_domain_is_kept():
    ex = await extract_okf(_StubClient("security"), "text")
    assert ex.domain == "security"


async def test_invalid_domain_coerced_to_none():
    ex = await extract_okf(_StubClient("nonsense"), "text")
    assert ex.domain is None


async def test_missing_domain_is_none():
    ex = await extract_okf(_StubClient(None), "text")
    assert ex.domain is None


def test_extract_prompt_lists_allowed_domains():
    prompt = build_extract_prompt("some source")
    assert "domain" in prompt
    assert "backend" in prompt and "security" in prompt


def test_extraction_schema_has_domain_field():
    assert "domain" in OkfExtraction.model_fields
