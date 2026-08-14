"""LLM client abstraction for the wiki pipeline.

Defines:
- ``LLMOutputError``: raised when the LLM returns content that cannot be parsed.
- ``LLMClient``: structural ``Protocol`` for type-checking.
- ``LiteLLMClient``: production implementation that delegates to LiteLLM.
- ``StubLLMClient``: deterministic in-process implementation for tests.
"""

from __future__ import annotations

import base64
import json
from typing import Protocol, runtime_checkable

import litellm

from k7e_api.config import get_settings


class LLMOutputError(Exception):
    """Raised when the LLM response cannot be parsed as valid JSON."""


@runtime_checkable
class LLMClient(Protocol):
    """Structural protocol for all LLM client implementations."""

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
    ) -> dict:
        """Send a prompt pair and return the parsed JSON response as a dict.

        Args:
            system: Content for the ``system`` role message.
            user: Content for the ``user`` role message.
            schema_name: Human-readable name of the expected schema (used for
                logging / error messages only).

        Returns:
            Parsed JSON object as a plain Python dict.

        Raises:
            LLMOutputError: If the model response cannot be decoded as JSON.
        """
        ...

    async def transcribe_image(
        self,
        *,
        system: str,
        user: str,
        image_mime: str,
        image_data: bytes,
    ) -> str:
        """Transcribe a single image to plain text via a vision model.

        Args:
            system: Content for the ``system`` role message.
            user: Text part of the user message (page context / instructions).
            image_mime: MIME type of ``image_data`` (e.g. ``image/jpeg``).
            image_data: Raw image bytes, sent base64-encoded as a data URL.

        Returns:
            The transcription as stripped plain text (may be empty for a
            blank page).

        Raises:
            LLMOutputError: If the model returns no usable text content.
        """
        ...


def _content_text(response) -> str | None:
    """Extract plain-text content from a completion response.

    Thinking-mode responses return a list of ``{"type": "thinking"|"text", ...}``
    blocks; join the text blocks. Returns None when there is no content.
    """
    raw_content = response.choices[0].message.content
    if isinstance(raw_content, list):
        raw_content = "".join(
            block["text"]
            for block in raw_content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return raw_content


def _empty_usage() -> dict:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}


class LiteLLMClient:
    """Production LLM client that calls the LiteLLM gateway.

    Settings are read via ``get_settings()`` so that environment overrides
    propagate correctly without reloading the module.

    Accumulates token ``usage`` across every ``complete_json`` call made on this
    instance, so a caller (e.g. the ingest activity) can total the cost of a
    multi-call pipeline by reading ``client.usage`` afterwards.
    """

    def __init__(self) -> None:
        self.usage = _empty_usage()

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
    ) -> dict:
        settings = get_settings()
        model = settings.wiki_model
        if "/" not in model:
            model = f"openai/{model}"

        response = await litellm.acompletion(
            model=model,
            api_base=settings.litellm_base_url,
            api_key=settings.litellm_api_key,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            num_retries=settings.llm_num_retries,
            timeout=settings.llm_timeout_seconds,
        )
        self._record_usage(getattr(response, "usage", None))
        raw_content = _content_text(response)
        # Normalise Claude's non-standard JSON output before parsing.
        #
        # Claude exhibits two quirks that break json.loads() even though the
        # content is semantically valid JSON:
        #
        # 1. Markdown code fences — Claude wraps the JSON in ```json ... ```
        #    even when response_format=json_object is requested.  Strip them.
        #
        # 2. Literal control characters — Claude embeds real newlines (\n) and
        #    tabs (\t) inside JSON string values instead of the JSON escape
        #    sequences (\\n / \\t).  json.loads(strict=False) accepts these.
        if isinstance(raw_content, str):
            stripped = raw_content.strip()
            if stripped.startswith("```"):
                # Remove opening fence line (```json or ```) and closing ```
                lines = stripped.splitlines()
                inner_lines = lines[1:]
                if inner_lines and inner_lines[-1].strip() == "```":
                    inner_lines = inner_lines[:-1]
                raw_content = "\n".join(inner_lines)
        try:
            # strict=False: accept literal control characters (raw newlines /
            # tabs) inside JSON string values — a common Claude output quirk.
            return json.loads(raw_content, strict=False)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise LLMOutputError(
                f"LLM returned non-JSON content for schema '{schema_name}': {raw_content!r}"
            ) from exc

    async def transcribe_image(
        self,
        *,
        system: str,
        user: str,
        image_mime: str,
        image_data: bytes,
    ) -> str:
        settings = get_settings()
        model = settings.wiki_vision_model
        if "/" not in model:
            model = f"openai/{model}"

        data_url = f"data:{image_mime};base64,{base64.b64encode(image_data).decode('ascii')}"
        response = await litellm.acompletion(
            model=model,
            api_base=settings.litellm_base_url,
            api_key=settings.litellm_api_key,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            num_retries=settings.llm_num_retries,
            timeout=settings.llm_timeout_seconds,
        )
        self._record_usage(getattr(response, "usage", None))
        raw_content = _content_text(response)
        if not isinstance(raw_content, str):
            raise LLMOutputError(f"vision model returned no text content: {raw_content!r}")
        return raw_content.strip()

    def _record_usage(self, usage) -> None:
        if usage is None:
            return
        self.usage["prompt_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
        self.usage["completion_tokens"] += int(getattr(usage, "completion_tokens", 0) or 0)
        self.usage["total_tokens"] += int(getattr(usage, "total_tokens", 0) or 0)
        self.usage["calls"] += 1


class StubLLMClient:
    """Deterministic in-process LLM client for tests.

    Returns a fixed dict that is always valid against the ``Interpretation``
    schema so that downstream unit tests can run without a real LLM. Tracks a
    deterministic ``usage`` (10 prompt + 5 completion tokens per call) so cost
    accounting can be unit-tested without a real model.
    """

    def __init__(self) -> None:
        self.usage = _empty_usage()

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
    ) -> dict:
        self.usage["prompt_tokens"] += 10
        self.usage["completion_tokens"] += 5
        self.usage["total_tokens"] += 15
        self.usage["calls"] += 1
        if schema_name == "OkfExtraction":
            return {
                "title": "Hot Cache Pattern",
                "slug": "hot-cache-pattern",
                "summary": "A rolling recent-context summary file for agents.",
                "tags": ["agent-memory"],
                "domain": "backend",
                "entities": [
                    {
                        "name": "Nate Herk",
                        "kind": "person",
                        "description": "Introduced the pattern.",
                    }
                ],
                "concepts": [
                    {
                        "name": "Hot Cache",
                        "description": "Rolling ~500-word context file.",
                    }
                ],
                "citations": ["Karpathy LLM wiki"],
                "references": ["k7e-pattern"],
            }
        if schema_name == "OkfCompose":
            return {"markdown_body": "## Overview\n\nA composed OKF page body.\n"}
        return self._default_json(schema_name)

    async def transcribe_image(
        self,
        *,
        system: str,
        user: str,
        image_mime: str,
        image_data: bytes,
    ) -> str:
        self.usage["prompt_tokens"] += 10
        self.usage["completion_tokens"] += 5
        self.usage["total_tokens"] += 15
        self.usage["calls"] += 1
        return f"Stub transcription of {image_mime} image ({len(image_data)} bytes)."

    def _default_json(self, schema_name: str) -> dict:
        if schema_name == "OkfRelate":
            return {"related": [], "aliases": {}}
        if schema_name == "ContradictionCheck":
            return {"contradiction": False, "explanation": ""}
        return {
            "title": "Example Wiki Entry",
            "slug": "example-wiki-entry",
            "summary": "A concise summary of the example source document.",
            "markdown_body": (
                "## Overview\n\nThis is the full Markdown body for the example wiki entry.\n"
            ),
            "tags": ["example", "stub"],
            "confidence": 0.9,
            "citations": [
                {
                    "raw_document_id": "00000000-0000-0000-0000-000000000001",
                    "quote": "This is a verbatim excerpt from the source document.",
                }
            ],
        }
