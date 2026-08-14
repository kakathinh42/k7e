from k7e_api.deps import get_object_store, get_workflow_starter
from k7e_api.main import app
from k7e_api.models import RawDocument
from k7e_api.object_store import LocalFileObjectStore
from sqlalchemy import select


def test_workflow_start_failure_marks_document_failed(api_client, sqlite_factory, tmp_path):
    def failing_starter():
        def _start(_rid):
            raise RuntimeError("temporal down")

        return _start

    app.dependency_overrides[get_object_store] = lambda: LocalFileObjectStore(str(tmp_path))
    app.dependency_overrides[get_workflow_starter] = failing_starter
    try:
        resp = api_client.post(
            "/ingest/upload",
            files={"file": ("n.md", b"# hi", "text/markdown")},
        )
        assert resp.status_code == 503
        with sqlite_factory() as s:
            docs = s.execute(select(RawDocument)).scalars().all()
            assert len(docs) == 1
            assert docs[0].status == "failed"
    finally:
        app.dependency_overrides.pop(get_object_store, None)
        app.dependency_overrides.pop(get_workflow_starter, None)
