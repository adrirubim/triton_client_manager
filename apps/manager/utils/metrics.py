from typing import Any, Callable, Dict, Optional

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

registry = CollectorRegistry()

# WebSocket-level metrics
WS_CONNECTIONS_TOTAL = Counter(
    "tcm_ws_connections_total",
    "Total WebSocket connections accepted",
    registry=registry,
)
WS_DISCONNECTIONS_TOTAL = Counter(
    "tcm_ws_disconnections_total",
    "Total WebSocket disconnections",
    registry=registry,
)
WS_MESSAGES_TOTAL = Counter(
    "tcm_ws_messages_total",
    "Total messages received over WebSocket",
    ["type"],
    registry=registry,
)
WS_ERRORS_TOTAL = Counter(
    "tcm_ws_errors_total",
    "Total errors while handling WebSocket clients",
    registry=registry,
)

AUTH_FAILURES_TOTAL = Counter(
    "tcm_auth_failures_total",
    "Total WebSocket auth failures (invalid payload or token)",
    ["reason"],
    registry=registry,
)

RATE_LIMIT_VIOLATIONS_TOTAL = Counter(
    "tcm_rate_limit_violations_total",
    "Total rate limit violations observed in WebSocket handling",
    ["scope"],
    registry=registry,
)

UNSAFE_CONFIG_STARTUPS_TOTAL = Counter(
    "tcm_unsafe_config_startups_total",
    "Total unsafe configuration patterns detected at startup",
    ["reason"],
    registry=registry,
)

# Job / backpressure metrics
JOBS_REJECTED_TOTAL = Counter(
    "tcm_jobs_rejected_total",
    "Total jobs rejected due to full queues or executors",
    ["type"],
    registry=registry,
)

JOB_PROCESSING_SECONDS = Histogram(
    "tcm_job_processing_seconds",
    "Job processing time in seconds by type",
    ["type"],
    registry=registry,
)

# Latencia de inferencia por modelo
INFERENCE_LATENCY_SECONDS = Histogram(
    "tcm_inference_latency_seconds",
    "Latency of inference requests by model",
    ["model"],
    registry=registry,
)

# Errores por backend
BACKEND_ERRORS_TOTAL = Counter(
    "tcm_backend_errors_total",
    "Total errors grouped by backend",
    ["backend"],
    registry=registry,
)

# Queue / executor metrics, refreshed on scrape
QUEUE_TOTAL_USERS = Gauge(
    "tcm_queue_total_users",
    "Total unique users across all job queues",
    registry=registry,
)
QUEUE_TOTAL_QUEUED = Gauge(
    "tcm_queue_total_queued",
    "Total number of queued jobs across all types",
    registry=registry,
)
QUEUE_INFO_USERS = Gauge(
    "tcm_queue_info_users",
    "Number of users with info queues",
    registry=registry,
)
QUEUE_MANAGEMENT_USERS = Gauge(
    "tcm_queue_management_users",
    "Number of users with management queues",
    registry=registry,
)
QUEUE_INFERENCE_USERS = Gauge(
    "tcm_queue_inference_users",
    "Number of users with inference queues",
    registry=registry,
)
QUEUE_INFO_TOTAL = Gauge(
    "tcm_queue_info_total",
    "Total queued info jobs",
    registry=registry,
)
QUEUE_MANAGEMENT_TOTAL = Gauge(
    "tcm_queue_management_total",
    "Total queued management jobs",
    registry=registry,
)
QUEUE_INFERENCE_TOTAL = Gauge(
    "tcm_queue_inference_total",
    "Total queued inference jobs",
    registry=registry,
)

EXECUTOR_INFO_PENDING = Gauge(
    "tcm_executor_info_pending",
    "Pending tasks in info executor queue",
    registry=registry,
)
EXECUTOR_MANAGEMENT_PENDING = Gauge(
    "tcm_executor_management_pending",
    "Pending tasks in management executor queue",
    registry=registry,
)
EXECUTOR_INFERENCE_PENDING = Gauge(
    "tcm_executor_inference_pending",
    "Pending tasks in inference executor queue",
    registry=registry,
)

EXECUTOR_INFO_AVAILABLE = Gauge(
    "tcm_executor_info_available",
    "Available worker slots in info executor",
    registry=registry,
)
EXECUTOR_MANAGEMENT_AVAILABLE = Gauge(
    "tcm_executor_management_available",
    "Available worker slots in management executor",
    registry=registry,
)
EXECUTOR_INFERENCE_AVAILABLE = Gauge(
    "tcm_executor_inference_available",
    "Available worker slots in inference executor",
    registry=registry,
)


def observe_ws_message(msg_type: str) -> None:
    WS_MESSAGES_TOTAL.labels(type=msg_type).inc()


def observe_job_rejected(job_type: str) -> None:
    """
    Increment the rejected jobs counter for the given job type.

    job_type is typically one of: "info", "management", "inference".
    """
    JOBS_REJECTED_TOTAL.labels(type=job_type).inc()


def observe_job_processing(job_type: str, duration_seconds: float) -> None:
    """
    Observe job processing duration for the given job type.
    """
    JOB_PROCESSING_SECONDS.labels(type=job_type).observe(duration_seconds)


def observe_inference_latency(model_name: str, duration_seconds: float) -> None:
    """Observe inference latency for a given model."""
    INFERENCE_LATENCY_SECONDS.labels(model=model_name).observe(duration_seconds)


def observe_backend_error(backend: str) -> None:
    """Increment error counter for a given backend (e.g. triton, docker, minio)."""
    BACKEND_ERRORS_TOTAL.labels(backend=backend).inc()


def generate_metrics_response(
    get_queue_stats: Optional[Callable[[], Dict[str, Any]]] = None,
) -> Response:
    """
    Generate a Prometheus metrics response.

    If get_queue_stats is provided, it will be called on each scrape to
    refresh queue/executor gauges with the latest values from JobThread.
    """
    if get_queue_stats is not None:
        try:
            stats = get_queue_stats()
        except Exception:
            # Do not break metrics endpoint if stats collection fails
            stats = {}

        total_users = int(stats.get("total_users", 0))
        total_queued = int(stats.get("total_queued", 0))

        info_users = int(stats.get("info_users", 0))
        management_users = int(stats.get("management_users", 0))
        inference_users = int(stats.get("inference_users", 0))

        info_total = int(stats.get("info_total_queued", 0))
        management_total = int(stats.get("management_total_queued", 0))
        inference_total = int(stats.get("inference_total_queued", 0))

        executor_info_pending = int(stats.get("executor_info_pending", 0))
        executor_management_pending = int(stats.get("executor_management_pending", 0))
        executor_inference_pending = int(stats.get("executor_inference_pending", 0))

        executor_info_available = int(stats.get("executor_info_available", 0))
        executor_management_available = int(
            stats.get("executor_management_available", 0)
        )
        executor_inference_available = int(stats.get("executor_inference_available", 0))

        QUEUE_TOTAL_USERS.set(total_users)
        QUEUE_TOTAL_QUEUED.set(total_queued)

        QUEUE_INFO_USERS.set(info_users)
        QUEUE_MANAGEMENT_USERS.set(management_users)
        QUEUE_INFERENCE_USERS.set(inference_users)

        QUEUE_INFO_TOTAL.set(info_total)
        QUEUE_MANAGEMENT_TOTAL.set(management_total)
        QUEUE_INFERENCE_TOTAL.set(inference_total)

        EXECUTOR_INFO_PENDING.set(executor_info_pending)
        EXECUTOR_MANAGEMENT_PENDING.set(executor_management_pending)
        EXECUTOR_INFERENCE_PENDING.set(executor_inference_pending)

        EXECUTOR_INFO_AVAILABLE.set(executor_info_available)
        EXECUTOR_MANAGEMENT_AVAILABLE.set(executor_management_available)
        EXECUTOR_INFERENCE_AVAILABLE.set(executor_inference_available)

    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
