"""Tests for the Prometheus metrics endpoint and MetricsServer."""

import asyncio
import socket
import time

import httpx
import pytest


@pytest.fixture
def unused_port():
    """Find an unused port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_metrics_returns_prometheus_format(unused_port):
    """GET /metrics returns Prometheus text format with expected metric names."""
    from krankenfahrt.metrics_server import MetricsServer

    server = MetricsServer(host="127.0.0.1", port=unused_port)
    await server.start()

    try:
        # Give server a moment to bind
        await asyncio.sleep(0.1)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://127.0.0.1:{unused_port}/metrics",
                timeout=5.0,
            )

        assert response.status_code == 200

        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type

        body = response.text

        # Verify core HTTP metrics exist
        assert "http_requests_total" in body, (
            f"Expected http_requests_total in metrics output, got: {body[:500]}"
        )
        assert "http_request_duration_seconds" in body, (
            f"Expected http_request_duration_seconds in metrics output"
        )
        assert "http_errors_total" in body

        # Verify app-specific metrics exist
        assert "krankenfahrt_trips_total" in body
        assert "krankenfahrt_active_drivers" in body
        assert "krankenfahrt_escalations_total" in body
        assert "krankenfahrt_bookings_created_total" in body
        assert "krankenfahrt_voice_messages_processed" in body
        assert "krankenfahrt_whisper_processing_seconds" in body
        assert "krankenfahrt_llm_requests_total" in body
        assert "krankenfahrt_llm_request_duration_seconds" in body
        assert "krankenfahrt_dispatch_attempts_total" in body

        # Verify Prometheus HELP/TYPE lines exist for core metrics
        assert '# HELP http_requests_total' in body
        assert '# TYPE http_requests_total counter' in body
        assert '# HELP http_request_duration_seconds' in body
        assert '# TYPE http_request_duration_seconds histogram' in body

    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_health_endpoint(unused_port):
    """GET /health returns JSON with status ok."""
    from krankenfahrt.metrics_server import MetricsServer

    server = MetricsServer(host="127.0.0.1", port=unused_port)
    await server.start()
    await asyncio.sleep(0.1)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://127.0.0.1:{unused_port}/health",
                timeout=5.0,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "krankenfahrt"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_metrics_middleware_records_request(unused_port):
    """The metrics middleware increments http_requests_total on each request."""
    from krankenfahrt.metrics_server import MetricsServer, http_requests_total

    server = MetricsServer(host="127.0.0.1", port=unused_port)
    await server.start()
    await asyncio.sleep(0.1)

    try:
        # Make a request to /health to trigger middleware
        async with httpx.AsyncClient() as client:
            await client.get(
                f"http://127.0.0.1:{unused_port}/health",
                timeout=5.0,
            )

        # Check that the counter was incremented
        sample = http_requests_total.labels(
            method="GET", endpoint="/health", status="200"
        )
        # sample._value.get() gives the current counter value
        count = sample._value.get()
        assert count >= 1, (
            f"Expected http_requests_total[method=GET,endpoint=/health,status=200] >= 1, got {count}"
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_app_metrics_exportable(unused_port):
    """App-specific metrics (trips, drivers, escalations) can be incremented
    and their values appear in the /metrics output."""
    from krankenfahrt.metrics_server import (
        MetricsServer,
        trips_total,
        active_drivers,
        escalations_total,
    )

    # Increment some app metrics before starting server
    trips_total.labels(status="completed").inc(3)
    trips_total.labels(status="cancelled").inc()
    active_drivers.set(2)
    escalations_total.inc()

    server = MetricsServer(host="127.0.0.1", port=unused_port)
    await server.start()
    await asyncio.sleep(0.1)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://127.0.0.1:{unused_port}/metrics",
                timeout=5.0,
            )

        body = response.text

        # Check that incremented values appear in the output
        # prometheus_client serializes counters/floats as-is
        assert 'krankenfahrt_trips_total{status="completed"} 3.0' in body or \
               'krankenfahrt_trips_total{status="completed"} 3' in body, (
            f"Expected trips_total[completed]=3 in output. Got snippet: ..."
        )
        assert 'krankenfahrt_active_drivers 2.0' in body or \
               'krankenfahrt_active_drivers 2' in body
        assert 'krankenfahrt_escalations_total 1.0' in body or \
               'krankenfahrt_escalations_total 1' in body
    finally:
        await server.stop()
        # Reset metrics to avoid polluting other tests
        active_drivers.set(0)


@pytest.mark.asyncio
async def test_404_on_unknown_path(unused_port):
    """Requests to unknown paths return 404."""
    from krankenfahrt.metrics_server import MetricsServer

    server = MetricsServer(host="127.0.0.1", port=unused_port)
    await server.start()
    await asyncio.sleep(0.1)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://127.0.0.1:{unused_port}/unknown",
                timeout=5.0,
            )

        assert response.status_code == 404
    finally:
        await server.stop()
