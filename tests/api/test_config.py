from k7e_api import config


def test_new_settings_have_defaults():
    config.get_settings.cache_clear()
    s = config.Settings()
    assert s.llm_num_retries == 2
    assert s.llm_timeout_seconds == 60.0
    assert s.log_level == "INFO"


def test_vision_extraction_settings_have_defaults():
    config.get_settings.cache_clear()
    s = config.Settings()
    assert s.wiki_vision_model == "wiki-vision"
    assert s.max_pdf_pages == 50
