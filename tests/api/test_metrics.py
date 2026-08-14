from prometheus_client import REGISTRY


def test_new_metric_series_registered():
    import k7e_api.metrics  # noqa: F401

    names = {m.name for m in REGISTRY.collect()}
    assert "wiki_http_requests" in names
    assert "wiki_http_request_duration_seconds" in names
    assert "wiki_review_queue_depth" in names
