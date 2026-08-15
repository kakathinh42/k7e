from types import SimpleNamespace

from k7e_api import config, llm_client


async def test_complete_json_passes_retries_and_timeout(monkeypatch):
    config.get_settings.cache_clear()
    monkeypatch.setenv("LLM_NUM_RETRIES", "4")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12")

    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )

    monkeypatch.setattr(llm_client.litellm, "acompletion", fake_acompletion)

    result = await llm_client.LiteLLMClient().complete_json(system="s", user="u", schema_name="X")
    assert result == {"ok": True}
    assert captured["num_retries"] == 4
    assert captured["timeout"] == 12.0
    config.get_settings.cache_clear()
