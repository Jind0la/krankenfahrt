"""Prometheus metrics endpoint for Krankenfahrt system.

Exposes a /metrics endpoint in Prometheus text format for Railway monitoring.
Also serves /health for health checks.

Metrics collected:
  - http_requests_total   (counter, labeled by method/endpoint/status)
  - http_request_duration_seconds (histogram, labeled by method/endpoint)
  - http_errors_total      (counter, labeled by method/endpoint)
  - krankenfahrt_trips_total      (counter, labeled by status)
  - krankenfahrt_active_drivers   (gauge)
  - krankenfahrt_escalations_total (counter)

Usage:
    from krankenfahrt.metrics_server import MetricsServer

    server = MetricsServer(host="0.0.0.0", port=9090)
    await server.start()
    ...
    await server.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from aiohttp import web
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    REGISTRY,
)

logger = logging.getLogger(__name__)

# ── HTTP Metrics ─────────────────────────────────────────────
http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

http_errors_total = Counter(
    "http_errors_total",
    "Total number of HTTP errors (5xx)",
    ["method", "endpoint"],
)

# ── App-specific Metrics ─────────────────────────────────────
trips_total = Counter(
    "krankenfahrt_trips_total",
    "Total number of trips",
    ["status"],
)

active_drivers = Gauge(
    "krankenfahrt_active_drivers",
    "Number of drivers currently online/active",
)

escalations_total = Counter(
    "krankenfahrt_escalations_total",
    "Total number of escalations to chef",
)

bookings_created_total = Counter(
    "krankenfahrt_bookings_created_total",
    "Total number of bookings created by patients",
)

voice_messages_processed = Counter(
    "krankenfahrt_voice_messages_processed",
    "Total number of voice messages processed by Whisper",
)

whisper_processing_seconds = Histogram(
    "krankenfahrt_whisper_processing_seconds",
    "Whisper transcription latency in seconds",
    buckets=(1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 60.0),
)

llm_requests_total = Counter(
    "krankenfahrt_llm_requests_total",
    "Total number of LLM (DeepSeek) API calls",
    ["operation"],
)

llm_request_duration_seconds = Histogram(
    "krankenfahrt_llm_request_duration_seconds",
    "LLM API call latency in seconds",
    ["operation"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

dispatch_attempts_total = Counter(
    "krankenfahrt_dispatch_attempts_total",
    "Total number of dispatch attempts",
    ["engine"],
)


@web.middleware
async def metrics_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    """Middleware that tracks request counts, latency, and errors.

    Records http_requests_total, http_request_duration_seconds, and
    http_errors_total for every incoming HTTP request.
    """
    # Skip metrics endpoint itself to avoid recursion
    endpoint = request.path
    method = request.method

    start = time.monotonic()

    try:
        response = await handler(request)
        elapsed = time.monotonic() - start

        http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=str(response.status),
        ).inc()

        http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint,
        ).observe(elapsed)

        if response.status >= 500:
            http_errors_total.labels(
                method=method,
                endpoint=endpoint,
            ).inc()

        return response

    except Exception:
        elapsed = time.monotonic() - start
        http_requests_total.labels(
            method=method, endpoint=endpoint, status="500"
        ).inc()
        http_request_duration_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(elapsed)
        http_errors_total.labels(method=method, endpoint=endpoint).inc()
        raise


class MetricsServer:
    """Lightweight aiohttp server exposing Prometheus metrics.

    Runs in the same asyncio event loop as the Telegram bots.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9090,
    ) -> None:
        self.host = host
        self.port = port
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        """GET /metrics — Serve Prometheus text format."""
        data = generate_latest(REGISTRY)
        return web.Response(
            body=data,
            content_type="text/plain; charset=utf-8",
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /health — Health check endpoint for Railway."""
        return web.json_response({
            "status": "ok",
            "service": "krankenfahrt",
        })

    async def start(self) -> None:
        """Build and start the HTTP server."""
        self._app = web.Application(
            middlewares=[metrics_middleware],
        )
        self._app.router.add_get("/metrics", self._handle_metrics)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        logger.info(
            "Metrics server listening on http://%s:%d",
            self.host,
            self.port,
        )

    async def stop(self) -> None:
        """Gracefully shut down the HTTP server."""
        if self._runner is not None:
            await self._runner.cleanup()
            logger.info("Metrics server stopped")
