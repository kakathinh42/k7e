from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

INGEST_TOTAL = Counter("wiki_ingest_total", "Ingestions", ["source", "outcome"])
GATE_DECISIONS = Counter("wiki_gate_decisions_total", "Gate decisions", ["decision"])
RETRIEVAL_LATENCY = Histogram("wiki_retrieval_latency_seconds", "Retrieval latency")

# HTTP-level metrics (populated by the Prometheus middleware).
HTTP_REQUESTS_TOTAL = Counter(
    "wiki_http_requests", "HTTP requests", ["method", "endpoint", "status"]
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "wiki_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)
# Pending review-queue depth (set on each /review/pending read).
REVIEW_QUEUE_DEPTH = Gauge("wiki_review_queue_depth", "Pending review tasks")


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
