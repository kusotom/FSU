from __future__ import annotations

from typing import Any

PROMETHEUS_ENABLED = True

try:
    from prometheus_client import (  # type: ignore[import-untyped]
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
except Exception:  # pragma: no cover - optional dependency fallback
    PROMETHEUS_ENABLED = False

    class _NoopMetric:
        def __init__(self, *_: Any, **__: Any):
            return None

        def labels(self, **_: Any) -> "_NoopMetric":
            return self

        def inc(self, _: float = 1.0):
            return None

        def observe(self, _: float):
            return None

        def set(self, _: float):
            return None

    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    Counter = Gauge = Histogram = _NoopMetric  # type: ignore[assignment]

    def generate_latest() -> bytes:
        return b"# Prometheus client is not installed\n"


ingest_requests_total = Counter(
    "fsu_ingest_requests_total",
    "Ingest API request count",
    labelnames=("endpoint", "mode", "result"),
)

ingest_duration_seconds = Histogram(
    "fsu_ingest_request_duration_seconds",
    "Ingest API request duration in seconds",
    labelnames=("endpoint", "mode"),
    buckets=(0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10),
)

ingest_metric_items_total = Counter(
    "fsu_ingest_metric_items_total",
    "Total metric items accepted by ingest API",
    labelnames=("endpoint", "mode"),
)

ingest_queue_size = Gauge(
    "fsu_ingest_queue_size",
    "Current ingest queue size",
)

ingest_queue_workers = Gauge(
    "fsu_ingest_queue_workers",
    "Configured ingest queue worker count",
)

ingest_queue_worker_failures_total = Counter(
    "fsu_ingest_queue_worker_failures_total",
    "Ingest queue worker failures",
    labelnames=("worker", "phase"),
)


def observe_ingest_request(
    *,
    endpoint: str,
    mode: str,
    result: str,
    duration_seconds: float,
    metric_count: int,
):
    ingest_requests_total.labels(endpoint=endpoint, mode=mode, result=result).inc()
    ingest_duration_seconds.labels(endpoint=endpoint, mode=mode).observe(max(duration_seconds, 0.0))
    if metric_count > 0:
        ingest_metric_items_total.labels(endpoint=endpoint, mode=mode).inc(metric_count)


def set_ingest_queue_size(size: int):
    ingest_queue_size.set(max(size, 0))


def set_ingest_queue_workers(worker_count: int):
    ingest_queue_workers.set(max(worker_count, 0))


def inc_ingest_queue_worker_failure(worker_index: int, phase: str):
    ingest_queue_worker_failures_total.labels(worker=str(worker_index), phase=phase).inc()


def render_prometheus() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
