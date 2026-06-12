"""Lightweight async HTTP health-check server.

Runs alongside the Telegram bots on a configurable port so load balancers
(Railway, Fly.io, etc.) can monitor liveness.

Endpoints:
  GET /health  → {"status": "ok", "uptime": <seconds>, "database": "connected"}
  GET /healthz → same (alias for K8s-style probes)
"""

import asyncio
import json
import logging
import time

logger = logging.getLogger(__name__)

# ── HTTP response helpers ──────────────────────────────────────────────────────

_HTTP_200 = b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n"
_HTTP_404 = b"HTTP/1.0 404 Not Found\r\nContent-Type: application/json\r\n\r\n"
_HTTP_503 = b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\n\r\n"
_HTTP_405 = b"HTTP/1.0 405 Method Not Allowed\r\nContent-Type: application/json\r\n\r\n"

_HEALTH_PATHS = {"/health", "/healthz"}


class HealthServer:
    """Minimal async HTTP server that responds to GET /health and /healthz.

    Parameters
    ----------
    host : str
        Bind address (default: "0.0.0.0").
    port : int
        Bind port (default: 8080).
    db_check : callable or None
        Optional async callable that returns ``True`` when the database is
        healthy.  If ``None``, the "database" key is omitted from the response.
    """

    def __init__(self, host="0.0.0.0", port=8080, db_check=None):
        self.host = host
        self.port = port
        self.db_check = db_check
        self._start_time: float = 0.0
        self._server: asyncio.AbstractServer | None = None
        self._ready = asyncio.Event()

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Bind and start accepting connections."""
        self._start_time = time.time()
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        self._ready.set()
        addr = self._server.sockets[0].getsockname()
        logger.info("Health server listening on %s:%s", *addr)

    async def stop(self) -> None:
        """Gracefully stop the server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self._ready.clear()
            logger.info("Health server stopped")

    async def wait_ready(self, timeout: float = 5.0) -> None:
        """Block until the server is bound and listening."""
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    # ── request handling ───────────────────────────────────────────────────

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request = await asyncio.wait_for(reader.read(1024), timeout=5.0)
        except TimeoutError:
            writer.close()
            await writer.wait_closed()
            return

        if not request:
            writer.close()
            await writer.wait_closed()
            return

        # Parse request line: "GET /health HTTP/1.0"
        try:
            request_line = request.split(b"\r\n")[0].decode()
            method, path, *_ = request_line.split(" ")
        except (ValueError, IndexError):
            writer.write(_HTTP_404)
            writer.write(json.dumps({"error": "bad request"}).encode())
            writer.close()
            await writer.wait_closed()
            return

        if method != "GET":
            writer.write(_HTTP_405)
            writer.write(json.dumps({"error": "method not allowed"}).encode())
            writer.close()
            await writer.wait_closed()
            return

        if path not in _HEALTH_PATHS:
            writer.write(_HTTP_404)
            writer.write(json.dumps({"error": "not found"}).encode())
            writer.close()
            await writer.wait_closed()
            return

        # Build health response
        await self._write_health(writer)

    async def _write_health(self, writer: asyncio.StreamWriter) -> None:
        """Write the health-check JSON payload."""
        uptime = time.time() - self._start_time

        payload: dict = {
            "status": "ok",
            "uptime": round(uptime, 3),
        }

        # Optional database liveness check
        if self.db_check is not None:
            try:
                db_ok = await self.db_check()
                payload["database"] = "connected" if db_ok else "disconnected"
            except Exception:
                payload["database"] = "disconnected"

        body = json.dumps(payload).encode()

        # Choose status code based on database health
        if payload.get("database") == "disconnected":
            writer.write(_HTTP_503)
        else:
            writer.write(_HTTP_200)

        writer.write(body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    # ── context manager ────────────────────────────────────────────────────

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()


# ── Database health check factory ──────────────────────────────────────────────


def make_db_health_check() -> callable:
    """Return an async callable that pings the Tortoise ORM database.

    Returns a no-op (always True) if Tortoise is not initialised.
    """
    async def _check() -> bool:
        try:
            from tortoise import Tortoise
            conn = Tortoise.get_connection("default")
            await conn.execute_query("SELECT 1")
            return True
        except Exception:
            logger.warning("Database health check failed", exc_info=True)
            return False

    return _check
