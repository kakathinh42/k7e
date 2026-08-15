from k7e_api import config


def test_graph_settings_defaults():
    config.get_settings.cache_clear()
    s = config.Settings()
    assert s.link_top_k == 5
    assert s.link_min_similarity == 0.6
    assert s.search_w_importance == 0.0
    assert s.graph_expand_enabled is True
    assert s.graph_expand_top_hits == 5
    assert s.graph_expand_per_hit == 3
    assert s.graph_expand_decay == 0.5
