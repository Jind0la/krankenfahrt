"""Shared test fixtures for the Krankenfahrt integration test suite.

Provides an in-memory SQLite database (mock API backend) that can be
started/stopped per test, plus helpers to create test data for the
Patient → Driver → Chef E2E flow.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, time, timezone
from typing import AsyncGenerator, Callable

import pytest
from tortoise import Tortoise


# ── Pytest configuration hook (runs before test collection) ─────────────────

def pytest_configure(config) -> None:
    """Set required environment variables before test collection."""
    os.environ.setdefault("PATIENT_BOT_TOKEN", "test_patient_token")
    os.environ.setdefault("DRIVER_BOT_TOKEN", "test_driver_token")
    os.environ.setdefault("CHEF_BOT_TOKEN", "test_chef_token")
    os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")
    os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
    os.environ.setdefault("ADMIN_TELEGRAM_IDS", "")


# ── SQLite time adapter ────────────────────────────────────────────────────

def _adapt_time(t: time) -> str:
    """Convert Python time to ISO string for SQLite storage."""
    if t.tzinfo is not None:
        t = t.replace(tzinfo=None)
    return t.isoformat()


def _convert_time(raw: bytes) -> time:
    """Convert SQLite bytes back to Python time."""
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    return time.fromisoformat(text)


sqlite3.register_adapter(time, _adapt_time)
sqlite3.register_converter("time", _convert_time)


# ── In-memory database fixture ─────────────────────────────────────────────

@pytest.fixture
async def init_db() -> AsyncGenerator[None, None]:
    """Initialize Tortoise with in-memory SQLite for each test.

    This is the "mock API" — starts an isolated database per test,
    runs the test, and tears it down.  No external dependencies.
    """
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["krankenfahrt.models.schema"]},
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


# ── Test data factories ────────────────────────────────────────────────────

@pytest.fixture
async def test_patient(init_db) -> Callable[..., "Patient"]:
    """Factory fixture to create a Patient record with sensible defaults."""
    from krankenfahrt.models.schema import Patient

    async def _create(**kwargs) -> Patient:
        defaults = {
            "telegram_id": 111111,
            "name": "Test Patient",
            "phone": "+491****7890",
            "default_pickup_addr": "Teststraße 1, 12345 Berlin",
            "default_dest_addr": "Charité, Berlin",
            "vehicle_type": "Sitz",
        }
        defaults.update(kwargs)
        return await Patient.create(**defaults)

    return _create


@pytest.fixture
async def test_vehicle(init_db) -> Callable[..., "Vehicle"]:
    """Factory fixture to create a Vehicle record with sensible defaults."""
    from krankenfahrt.models.schema import Vehicle

    async def _create(**kwargs) -> Vehicle:
        defaults = {
            "license_plate": "B-TEST-1",
            "vehicle_type": "Sitz",
            "capacity": 1,
        }
        defaults.update(kwargs)
        return await Vehicle.create(**defaults)

    return _create


@pytest.fixture
async def test_driver(init_db) -> Callable[..., "Driver"]:
    """Factory fixture to create a Driver record with sensible defaults."""
    from krankenfahrt.models.schema import Driver

    async def _create(**kwargs) -> Driver:
        defaults = {
            "telegram_id": 222222,
            "name": "Test Driver",
            "phone": "+491****1111",
            "p_schein": False,
            "work_hours_start": time(7, 0),
            "work_hours_end": time(18, 0),
            "work_days": "Mo,Di,Mi,Do,Fr,Sa,So",
            "active": True,
        }
        defaults.update(kwargs)
        return await Driver.create(**defaults)

    return _create


@pytest.fixture
async def test_trip(init_db) -> Callable[..., "Trip"]:
    """Factory fixture to create a Trip record with sensible defaults."""
    from krankenfahrt.models.schema import Trip

    async def _create(**kwargs) -> Trip:
        defaults = {
            "pickup_addr": "Teststraße 1, 12345 Berlin",
            "dest_addr": "Charité, Berlin",
            "scheduled_pickup": datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc),
            "status": "geplant",
        }
        defaults.update(kwargs)
        return await Trip.create(**defaults)

    return _create


# ── Full scenario setup (convenience) ───────────────────────────────────────

@pytest.fixture
async def scenario(
    test_patient, test_vehicle, test_driver, test_trip,
) -> dict:
    """Set up a complete Patient + Driver + Vehicle + Trip scenario.

    Returns a dict with all records ready for assertions.
    The trip starts in "geplant" status.
    """
    patient = await test_patient()
    vehicle = await test_vehicle()
    driver = await test_driver(vehicle=vehicle)
    trip = await test_trip(
        patient=patient,
        driver=None,  # Not assigned yet
        vehicle=None,
        pickup_addr=patient.default_pickup_addr,
        dest_addr=patient.default_dest_addr,
    )
    return {
        "patient": patient,
        "vehicle": vehicle,
        "driver": driver,
        "trip": trip,
    }
