"""Tests for the escalation management service."""

import os
from datetime import datetime, time, timezone

import pytest
from tortoise import Tortoise


@pytest.fixture(autouse=True)
def setup_env():
    """Ensure required env vars are set for imports."""
    os.environ.setdefault("PATIENT_BOT_TOKEN", "test_patient_token")
    os.environ.setdefault("DRIVER_BOT_TOKEN", "test_driver_token")
    os.environ.setdefault("CHEF_BOT_TOKEN", "test_chef_token")
    os.environ.setdefault("DEEPSEEK_API_KEY", "test_deepseek_key")


class TestEscalationConstants:
    """Verify escalation constants are correctly defined."""

    def test_escalation_options_defined(self):
        from krankenfahrt.core.escalation import ESCALATION_OPTIONS

        assert "reassign" in ESCALATION_OPTIONS
        assert "pause" in ESCALATION_OPTIONS
        assert "cancel" in ESCALATION_OPTIONS
        assert "acknowledge" in ESCALATION_OPTIONS
        assert "resolve" in ESCALATION_OPTIONS
        assert len(ESCALATION_OPTIONS) == 5

    def test_trigger_reasons_defined(self):
        from krankenfahrt.core.escalation import TRIGGER_REASONS

        assert "timeout" in TRIGGER_REASONS
        assert "manual" in TRIGGER_REASONS
        assert "system" in TRIGGER_REASONS
        assert len(TRIGGER_REASONS) == 3

    def test_config_has_escalation_settings(self):
        from krankenfahrt.config import config

        assert hasattr(config, "ESCALATION_TIMEOUT_MINUTES")
        assert hasattr(config, "ESCALATION_ENABLED")
        assert config.ESCALATION_TIMEOUT_MINUTES >= 1
        assert isinstance(config.ESCALATION_ENABLED, bool)


class TestEscalationModel:
    """Verify the Escalation model is importable and has expected fields."""

    def test_escalation_model_imports(self):
        from krankenfahrt.models.schema import Escalation

        assert Escalation is not None

    def test_escalation_model_has_required_fields(self):
        from krankenfahrt.models.schema import Escalation

        # Check that the Escalation table name and meta are correct
        assert Escalation._meta.db_table == "escalations"

        # Verify key fields exist via describe
        field_map = Escalation._meta.fields_map
        assert "id" in field_map
        assert "trip" in field_map  # FK field is named 'trip', not 'trip_id'
        assert "trigger_reason" in field_map
        assert "status" in field_map
        assert "created_at" in field_map

    def test_escalation_model_has_optional_fields(self):
        from krankenfahrt.models.schema import Escalation

        esc = Escalation()
        assert hasattr(esc, "trigger_detail")
        assert hasattr(esc, "chosen_option")
        assert hasattr(esc, "resolved_by_telegram_id")
        assert hasattr(esc, "resolution_note")
        assert hasattr(esc, "acknowledged_at")
        assert hasattr(esc, "resolved_at")


class TestEscalationServiceValidation:
    """Test input validation in escalation service functions (with in-memory DB)."""

    @pytest.mark.asyncio
    async def test_create_escalation_invalid_trigger(self):
        from krankenfahrt.core.escalation import create_escalation

        with pytest.raises(ValueError, match="Invalid trigger_reason"):
            await create_escalation(
                trip_id=1,
                trigger_reason="invalid_trigger",
                trigger_detail="test",
            )

    @pytest.mark.asyncio
    async def test_create_escalation_disabled(self):
        """When escalation is disabled, creation fails."""
        from krankenfahrt.config import config
        from krankenfahrt.core.escalation import create_escalation

        original = config.ESCALATION_ENABLED
        config.ESCALATION_ENABLED = False
        try:
            with pytest.raises(ValueError, match="disabled"):
                await create_escalation(1, "manual")
        finally:
            config.ESCALATION_ENABLED = original

    @pytest.mark.asyncio
    async def test_process_option_invalid_option(self):
        from krankenfahrt.core.escalation import process_escalation_option

        with pytest.raises(ValueError, match="Invalid option"):
            await process_escalation_option(
                escalation_id=1,
                option="invalid_option",
                telegram_id=12345,
            )


class TestEscalationServiceIntegration:
    """Integration tests with in-memory SQLite database."""

    @pytest.fixture(autouse=True)
    async def init_db(self):
        """Initialize in-memory DB for each test."""
        await Tortoise.init(
            db_url="sqlite://:memory:",
            modules={"models": ["krankenfahrt.models.schema"]},
        )
        await Tortoise.generate_schemas()
        yield
        await Tortoise.close_connections()

    async def _setup_test_data(self):
        """Create minimal test data: patient, vehicle, driver, trip."""
        from krankenfahrt.models.schema import Driver, Patient, Trip, Vehicle

        patient = await Patient.create(
            telegram_id=111111,
            name="Test Patient",
            default_pickup_addr="Teststraße 1, 12345 Berlin",
        )
        vehicle = await Vehicle.create(
            license_plate="B-TEST-1",
            vehicle_type="Sitz",
        )
        driver = await Driver.create(
            telegram_id=222222,
            name="Test Driver",
            phone="+491****6789",
            vehicle=vehicle,
        )
        trip = await Trip.create(
            patient=patient,
            driver=driver,
            vehicle=vehicle,
            pickup_addr="Teststraße 1, 12345 Berlin",
            dest_addr="Klinikum, 12345 Berlin",
            scheduled_pickup=datetime.now(timezone.utc),
            status="zugewiesen",
        )
        return patient, vehicle, driver, trip

    @pytest.mark.asyncio
    async def test_create_and_resolve_escalation_flow(self):
        """Full lifecycle: create escalation → acknowledge → resolve."""
        from krankenfahrt.core.escalation import (
            create_escalation,
            get_escalation_log,
            get_open_escalations,
            process_escalation_option,
        )

        _, _, _, trip = await self._setup_test_data()

        # Step 1: Create escalation
        esc = await create_escalation(
            trip_id=trip.id,
            trigger_reason="timeout",
            trigger_detail="30 Minuten ohne Status-Update",
        )
        assert esc.id is not None
        assert esc.trip_id == trip.id
        assert esc.trigger_reason == "timeout"
        assert esc.status == "open"
        assert esc.chosen_option is None

        # Step 2: Verify it appears in open escalations
        open_escs = await get_open_escalations()
        assert len(open_escs) >= 1
        assert any(e.id == esc.id for e in open_escs)

        # Step 3: Acknowledge
        esc = await process_escalation_option(
            escalation_id=esc.id,
            option="acknowledge",
            telegram_id=99999,
        )
        assert esc.status == "acknowledged"
        assert esc.chosen_option == "acknowledge"
        assert esc.resolved_by_telegram_id == 99999
        assert esc.acknowledged_at is not None
        assert esc.resolved_at is None  # Not resolved yet

        # Step 4: Resolve
        esc = await process_escalation_option(
            escalation_id=esc.id,
            option="resolve",
            telegram_id=99999,
            resolution_note="Fahrer hat sich gemeldet, alles ok.",
        )
        assert esc.status == "resolved"
        assert esc.chosen_option == "resolve"
        assert esc.resolved_at is not None
        assert esc.resolution_note == "Fahrer hat sich gemeldet, alles ok."

        # Step 5: Verify no longer in open escalations
        open_escs = await get_open_escalations()
        assert not any(e.id == esc.id for e in open_escs)

        # Step 6: Verify in audit log
        log = await get_escalation_log(trip_id=trip.id)
        assert len(log) >= 1
        assert log[0].id == esc.id

    @pytest.mark.asyncio
    async def test_cancel_option_sets_trip_storniert(self):
        """Choosing 'cancel' sets trip status to 'storniert'."""
        from krankenfahrt.models.schema import Trip
        from krankenfahrt.core.escalation import (
            create_escalation,
            process_escalation_option,
        )

        _, _, _, trip = await self._setup_test_data()

        esc = await create_escalation(
            trip_id=trip.id,
            trigger_reason="manual",
            trigger_detail="Chef manuelle Eskalation",
        )

        await process_escalation_option(
            escalation_id=esc.id,
            option="cancel",
            telegram_id=99999,
        )

        # Reload trip from DB
        trip = await Trip.get(id=trip.id)
        assert trip.status == "storniert"

    @pytest.mark.asyncio
    async def test_reassign_option_resets_trip_to_geplant(self):
        """Choosing 'reassign' resets trip to 'geplant' and clears driver."""
        from krankenfahrt.models.schema import Trip
        from krankenfahrt.core.escalation import (
            create_escalation,
            process_escalation_option,
        )

        _, _, _, trip = await self._setup_test_data()

        esc = await create_escalation(
            trip_id=trip.id,
            trigger_reason="timeout",
            trigger_detail="Fahrer reagiert nicht",
        )

        await process_escalation_option(
            escalation_id=esc.id,
            option="reassign",
            telegram_id=99999,
        )

        trip = await Trip.get(id=trip.id)
        assert trip.status == "geplant"
        assert trip.driver_id is None

    @pytest.mark.asyncio
    async def test_pause_option_sets_trip_to_problem(self):
        """Choosing 'pause' sets trip status to 'problem'."""
        from krankenfahrt.models.schema import Trip
        from krankenfahrt.core.escalation import (
            create_escalation,
            process_escalation_option,
        )

        _, _, _, trip = await self._setup_test_data()

        esc = await create_escalation(
            trip_id=trip.id,
            trigger_reason="manual",
            trigger_detail="Fahrzeug hat Panne",
        )

        await process_escalation_option(
            escalation_id=esc.id,
            option="pause",
            telegram_id=99999,
        )

        trip = await Trip.get(id=trip.id)
        assert trip.status == "problem"

    @pytest.mark.asyncio
    async def test_cannot_process_already_resolved_escalation(self):
        """Resolved escalations cannot be processed again."""
        from krankenfahrt.core.escalation import (
            create_escalation,
            process_escalation_option,
        )

        _, _, _, trip = await self._setup_test_data()

        esc = await create_escalation(
            trip_id=trip.id,
            trigger_reason="manual",
        )
        await process_escalation_option(esc.id, "resolve", 99999)

        # Try to process again — should fail
        with pytest.raises(ValueError, match="already resolved"):
            await process_escalation_option(esc.id, "acknowledge", 99999)

    @pytest.mark.asyncio
    async def test_audit_log_queryable_by_trip(self):
        """Escalation audit log can be filtered by trip_id."""
        from krankenfahrt.core.escalation import (
            create_escalation,
            get_escalation_log,
        )

        _, _, _, trip_a = await self._setup_test_data()

        # Create second trip on same patient/vehicle/driver
        patient = await trip_a.patient
        vehicle = await trip_a.vehicle
        driver = await trip_a.driver

        from krankenfahrt.models.schema import Trip
        trip_b = await Trip.create(
            patient=patient,
            driver=driver,
            vehicle=vehicle,
            pickup_addr="B-Straße",
            dest_addr="Klinikum B",
            scheduled_pickup=datetime.now(timezone.utc),
            status="zugewiesen",
        )

        # Escalations on both
        await create_escalation(trip_a.id, "timeout", "Trip A timeout")
        await create_escalation(trip_b.id, "manual", "Trip B manual")

        # Query by trip A
        log_a = await get_escalation_log(trip_id=trip_a.id)
        assert len(log_a) == 1
        assert log_a[0].trip_id == trip_a.id
        assert log_a[0].trigger_detail == "Trip A timeout"

        # Query all
        log_all = await get_escalation_log()
        assert len(log_all) == 2

    @pytest.mark.asyncio
    async def test_multiple_escalations_per_trip(self):
        """A trip can have multiple escalations (escalation history)."""
        from krankenfahrt.core.escalation import (
            create_escalation,
            get_escalation_log,
            process_escalation_option,
        )

        _, _, _, trip = await self._setup_test_data()

        # First escalation: timeout
        esc1 = await create_escalation(trip.id, "timeout", "Erster Timeout")
        await process_escalation_option(esc1.id, "acknowledge", 99999)

        # Second escalation: manual
        esc2 = await create_escalation(trip.id, "manual", "Fahrer abgelehnt")
        await process_escalation_option(esc2.id, "reassign", 99999)

        # Third escalation: timeout again after reassign
        esc3 = await create_escalation(trip.id, "timeout", "Zweiter Timeout")

        log = await get_escalation_log(trip_id=trip.id)
        assert len(log) == 3

    @pytest.mark.asyncio
    async def test_create_escalation_nonexistent_trip(self):
        """Creating escalation for nonexistent trip raises ValueError."""
        from krankenfahrt.core.escalation import create_escalation

        with pytest.raises(ValueError, match="not found"):
            await create_escalation(
                trip_id=99999,
                trigger_reason="manual",
                trigger_detail="test",
            )

    @pytest.mark.asyncio
    async def test_process_option_nonexistent_escalation(self):
        """Processing nonexistent escalation raises ValueError."""
        from krankenfahrt.core.escalation import process_escalation_option

        with pytest.raises(ValueError, match="not found"):
            await process_escalation_option(
                escalation_id=99999,
                option="acknowledge",
                telegram_id=12345,
            )

    @pytest.mark.asyncio
    async def test_escalation_log_returns_newest_first(self):
        """Audit log returns escalations newest first."""
        from krankenfahrt.core.escalation import (
            create_escalation,
            get_escalation_log,
        )

        _, _, _, trip = await self._setup_test_data()

        esc1 = await create_escalation(trip.id, "manual", "Erste")
        esc2 = await create_escalation(trip.id, "timeout", "Zweite")

        log = await get_escalation_log(trip_id=trip.id)
        assert len(log) >= 2
        # Newest first
        assert log[0].id == esc2.id
        assert log[1].id == esc1.id
