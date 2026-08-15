from k7e_api import config


def test_search_settings_defaults():
    config.get_settings.cache_clear()
    s = config.Settings()
    assert s.wiki_embed_model == "wiki-embed"
    assert s.embed_timeout_seconds == 30.0
    assert s.search_w_keyword == 1.0
    assert s.search_w_vector == 1.0
    assert s.search_w_recency == 0.0
    assert s.search_recency_halflife_days == 30.0
    assert s.search_min_vector_similarity == 0.3
