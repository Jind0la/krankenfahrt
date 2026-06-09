"""Tests for the health endpoint HTTP server."""
import asyncio
import json
import time

import pytest


@pytest.fixture
def unused_port():
    """Find an unused port for testing."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_health_returns_200_and_json(unused_port):
    """GET /health returns 200 with JSON status ok."""
    from krankenfahrt.health import HealthServer

    server = HealthServer(host="127.0.0.1", port=unused_port)
    server._start_time = time.time()

    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)  # Let server start

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_port)
        request = "GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()

        response = await asyncio.wait_for(reader.read(4096), timeout=2.0)
        writer.close()
        await writer.wait_closed()

        response_text = response.decode()

        # Check HTTP 200
        assert "200 OK" in response_text, f"Expected 200 OK, got: {response_text[:200]}"

        # Extract JSON body (after headers)
        body = response_text.split("\r\n\r\n", 1)[1]
        data = json.loads(body)

        assert data["status"] == "ok"
        assert "uptime" in data
        assert isinstance(data["uptime"], (int, float))
        assert data["uptime"] >= 0
    finally:
        await server.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_healthz_alias(unused_port):
    """GET /healthz also works as an alias."""
    from krankenfahrt.health import HealthServer

    server = HealthServer(host="127.0.0.1", port=unused_port)
    server._start_time = time.time()

    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_port)
        request = "GET /healthz HTTP/1.0\r\nHost: localhost\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()

        response = await asyncio.wait_for(reader.read(4096), timeout=2.0)
        writer.close()
        await writer.wait_closed()

        response_text = response.decode()
        assert "200 OK" in response_text

        body = response_text.split("\r\n\r\n", 1)[1]
        data = json.loads(body)
        assert data["status"] == "ok"
    finally:
        await server.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_health_includes_uptime(unused_port):
    """Uptime increases over time."""
    from krankenfahrt.health import HealthServer

    server = HealthServer(host="127.0.0.1", port=unused_port)
    server._start_time = time.time()

    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)

    try:
        async def fetch_health():
            reader, writer = await asyncio.open_connection("127.0.0.1", unused_port)
            request = "GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n"
            writer.write(request.encode())
            await writer.drain()
            response = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            writer.close()
            await writer.wait_closed()
            body = response.decode().split("\r\n\r\n", 1)[1]
            return json.loads(body)

        data1 = await fetch_health()
        await asyncio.sleep(0.5)
        data2 = await fetch_health()

        assert data2["uptime"] >= data1["uptime"], (
            f"Uptime should increase: {data1['uptime']} → {data2['uptime']}"
        )
    finally:
        await server.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_health_content_type_json(unused_port):
    """Response has Content-Type: application/json."""
    from krankenfahrt.health import HealthServer

    server = HealthServer(host="127.0.0.1", port=unused_port)
    server._start_time = time.time()

    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_port)
        request = "GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()
        response = await asyncio.wait_for(reader.read(4096), timeout=2.0)
        writer.close()
        await writer.wait_closed()

        response_text = response.decode()
        assert "Content-Type: application/json" in response_text
    finally:
        await server.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_unknown_path_returns_404(unused_port):
    """Requests to unknown paths return 404."""
    from krankenfahrt.health import HealthServer

    server = HealthServer(host="127.0.0.1", port=unused_port)
    server._start_time = time.time()

    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_port)
        request = "GET /unknown HTTP/1.0\r\nHost: localhost\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()
        response = await asyncio.wait_for(reader.read(4096), timeout=2.0)
        writer.close()
        await writer.wait_closed()

        response_text = response.decode()
        assert "404 Not Found" in response_text or "404" in response_text
    finally:
        await server.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
