"""M5: ConfluenceConnector maps a space's pages to Tier-A FetchedDocuments."""

from __future__ import annotations

from k7e_api.connectors.confluence import ConfluenceConnector

BASE = "https://x.atlassian.net/wiki"


def _page(pid, title, body):
    return {
        "id": pid,
        "title": title,
        "body": {"storage": {"value": body, "representation": "storage"}},
        "version": {"number": 1},
    }


def _fake_http(pages_page1, pages_page2):
    """Return an http_get that paginates: page 1 links to page 2, page 2 ends."""
    url1 = f"{BASE}/rest/api/content?spaceKey=RCVN&expand=body.storage,version&limit=50&start=0"
    responses = {
        url1: {
            "results": pages_page1,
            "_links": {"next": "/rest/api/content?spaceKey=RCVN&start=50"},
        },
        f"{BASE}/rest/api/content?spaceKey=RCVN&start=50": {
            "results": pages_page2,
            "_links": {},
        },
    }
    calls = []

    def _get(url):
        calls.append(url)
        return responses[url]

    return _get, calls


def test_fetch_maps_pages_and_follows_pagination():
    http_get, calls = _fake_http(
        [_page("1", "Alpha", "<p>alpha</p>")],
        [_page("2", "Beta", "<p>beta</p>")],
    )
    conn = ConfluenceConnector(base_url=BASE, space_key="RCVN", http_get=http_get)
    docs = list(conn.fetch())
    assert conn.name == "confluence"
    assert {d.source_external_id for d in docs} == {"1", "2"}
    assert all(d.source_system == "confluence" and d.source_tier == "A" for d in docs)
    alpha = next(d for d in docs if d.source_external_id == "1")
    assert alpha.content == b"<p>alpha</p>"
    assert alpha.content_type == "text/html"
    assert len(calls) == 2  # followed _links.next


def test_fetch_skips_a_malformed_page_without_aborting():
    http_get, _ = _fake_http([_page("1", "Alpha", "<p>a</p>"), {"no_id": True}], [])
    conn = ConfluenceConnector(base_url=BASE, space_key="RCVN", http_get=http_get)
    docs = list(conn.fetch())
    assert {d.source_external_id for d in docs} == {"1"}  # bad page skipped
