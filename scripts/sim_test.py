#!/usr/bin/env python3
"""Local end-to-end simulation test for Krankenfahrt auto-dispatch pipeline.

Tests the full flow: patient booking → auto-dispatch → driver assignment.
No Telegram needed — exercises the exact code paths used in production.
"""
import asyncio
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# Use a test database
TEST_DB = "/tmp/krankenfahrt_sim_test.db"
os.environ["DATABASE_URL"] = f"sqlite://{TEST_DB}"
os.environ["ADMIN_TELEGRAM_IDS"] = "807191501"
# Set dummy tokens (needed for config init but not used in this test)
os.environ.setdefault("PATIENT_BOT_TOKEN", "test")
os.environ.setdefault("DRIVER_BOT_TOKEN", "test")
os.environ.setdefault("CHEF_BOT_TOKEN", "test")
os.environ.setdefault("DEEPSEEK_API_KEY", "test")

# Clean up previous test DB
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)


async def main():
    from tortoise import Tortoise
    from krankenfahrt.models.schema import Driver, Patient, Trip, TripEvent

    # Init DB
    await Tortoise.init(
        db_url=os.environ["DATABASE_URL"],
        modules={"models": ["krankenfahrt.models.schema"]},
    )
    await Tortoise.generate_schemas()

    print("=" * 60)
    print("Krankenfahrt — Simulation Test")
    print("=" * 60)

    # ── Step 1: Create driver ──────────────────────────────────
    driver = await Driver.create(
        telegram_id=807191501,
        name="Nimar Moradbakhti",
        phone="017222222",
        active=True,
        # NOTE: vehicle=None — this is the critical test!
        vehicle=None,
    )
    print(f"\n✅ Driver created: id={driver.id}, active={driver.active}, vehicle={driver.vehicle}")

    # ── Step 2: Create patient ─────────────────────────────────
    patient = await Patient.create(
        telegram_id=807191501,
        name="Nimar",
        default_pickup_addr="Musterstraße 1",
    )
    print(f"✅ Patient created: id={patient.id}")

    # ── Step 3: Create trip (simulates booking) ────────────────
    tomorrow = datetime.now() + timedelta(days=1)
    pickup = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)

    trip = await Trip.create(
        patient=patient,
        pickup_addr=patient.default_pickup_addr,
        dest_addr="Testklinik",
        scheduled_pickup=pickup,
        status="geplant",
        # driver NOT assigned — auto-dispatch should do this
    )
    print(f"✅ Trip created: id={trip.id}, status={trip.status}, driver={trip.driver}")

    # ── Step 4: Run auto-dispatch ──────────────────────────────
    from krankenfahrt.core.dispatch import GreedyDispatchEngine

    drivers = await Driver.filter(active=True).all()
    print(f"\n🔍 Active drivers: {len(drivers)}")
    for d in drivers:
        print(f"   Driver {d.id}: {d.name}, vehicle={d.vehicle}, active={d.active}")

    engine = GreedyDispatchEngine()

    try:
        assignment = await engine.find_best_driver(trip, drivers)
        print(f"\n🎯 Dispatch SUCCESS!")
        print(f"   Driver: {assignment.driver.name} (id={assignment.driver.id})")
        print(f"   Score: {assignment.score:.2f}")
        print(f"   Distance: {assignment.distance_km:.2f} km")

        # Apply assignment
        trip.driver = assignment.driver
        trip.status = "zugewiesen"
        await trip.save()

        await TripEvent.create(
            trip_id=trip.id,
            event_type="assigned",
            message=f"Auto-assigned to {assignment.driver.name}",
        )
        print(f"   Trip status: {trip.status}")

    except Exception as e:
        print(f"\n❌ Dispatch FAILED: {e}")
        return 1

    # ── Step 5: Verify ─────────────────────────────────────────
    trip2 = await Trip.get(id=trip.id).prefetch_related("driver")
    assert trip2.driver is not None, "Trip has no driver!"
    assert trip2.status == "zugewiesen", f"Wrong status: {trip2.status}"
    assert trip2.driver.id == driver.id, f"Wrong driver: {trip2.driver.id}"

    events = await TripEvent.filter(trip_id=trip.id).all()
    assert len(events) >= 1, "No TripEvent created!"

    print(f"\n✅ All assertions passed!")
    print(f"   Trip #{trip2.id}: {trip2.status} → driver {trip2.driver.name}")
    print(f"   Events: {len(events)}")

    # Cleanup
    await Tortoise.close_connections()
    os.remove(TEST_DB)
    print(f"\n🧹 Test DB cleaned up.")
    return 0


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
