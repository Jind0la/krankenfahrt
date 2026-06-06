"""Tests for Chef-Bot driver/vehicle CRUD commands.

Uses tortoise-orm with in-memory SQLite for fast, isolated tests.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tortoise import Tortoise


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_env():
    """Ensure required env vars exist for config import."""
    os.environ["PATIENT_BOT_TOKEN"] = "test_patient_token"
    os.environ["DRIVER_BOT_TOKEN"] = "test_driver_token"
    os.environ["CHEF_BOT_TOKEN"] = "test_chef_token"
    os.environ["DEEPSEEK_API_KEY"] = "test_deepseek_key"
    os.environ["ADMIN_TELEGRAM_IDS"] = "111111,222222"


@pytest.fixture
async def db():
    """Initialize Tortoise with in-memory SQLite."""
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["krankenfahrt.models.schema"]},
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


def make_update(user_id: int, text: str = "") -> MagicMock:
    """Build a mock telegram.Update for testing."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    return update


def make_context(args: list[str] | None = None) -> MagicMock:
    """Build a mock ContextTypes.DEFAULT_TYPE."""
    ctx = MagicMock()
    ctx.args = args or []
    ctx.user_data = {}
    return ctx


# ---------------------------------------------------------------------------
# Authorization tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_is_authorized():
    """Admin users (in ADMIN_TELEGRAM_IDS) pass authorization check."""
    from krankenfahrt.config import config
    from krankenfahrt.bots.chef_bot import _require_admin

    update = make_update(user_id=111111)  # Admin
    ctx = make_context()

    @_require_admin
    async def handler(u, c):
        await u.message.reply_text("ok")

    await handler(update, ctx)
    update.message.reply_text.assert_called_once_with("ok")


@pytest.mark.asyncio
async def test_non_admin_is_denied():
    """Non-admin users get a permission-denied message."""
    from krankenfahrt.bots.chef_bot import _require_admin

    update = make_update(user_id=999999)  # Not admin
    ctx = make_context()

    @_require_admin
    async def handler(u, c):
        await u.message.reply_text("should not reach")

    await handler(update, ctx)
    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args[0][0]
    assert "keine berechtigung" in call_args.lower() or "permission" in call_args.lower()


# ---------------------------------------------------------------------------
# Driver CRUD tests (integration with SQLite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driver_add(db):
    """Create a new driver via the command handler."""
    from krankenfahrt.bots.chef_bot import _handle_driver_add
    from krankenfahrt.models.schema import Driver

    update = make_update(user_id=111111, text="/fahrer add Max Mustermann 49123456")
    ctx = make_context(args=["add", "Max", "Mustermann", "49123456"])
    ctx.user_data = {}

    await _handle_driver_add(update, ctx)

    # Verify driver was created
    driver = await Driver.filter(name="Max Mustermann").first()
    assert driver is not None
    assert driver.phone == "49123456"
    assert driver.telegram_id == 0  # Not linked to a Telegram account yet
    assert driver.active is True

    # Check response
    update.message.reply_text.assert_called()
    response = update.message.reply_text.call_args[0][0]
    assert "Max Mustermann" in response


@pytest.mark.asyncio
async def test_driver_add_duplicate_name_warns(db):
    """Adding a driver with an existing name warns the user."""
    from krankenfahrt.bots.chef_bot import _handle_driver_add
    from krankenfahrt.models.schema import Driver

    # Create existing driver
    await Driver.create(
        telegram_id=100001,
        name="Max Mustermann",
        phone="49123456",
    )

    update = make_update(user_id=111111)
    ctx = make_context(args=["add", "Max", "Mustermann", "49123456"])

    await _handle_driver_add(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "existiert bereits" in response.lower() or "already" in response.lower()


@pytest.mark.asyncio
async def test_driver_list(db):
    """List all drivers."""
    from krankenfahrt.bots.chef_bot import _handle_driver_list
    from krankenfahrt.models.schema import Driver

    await Driver.create(
        telegram_id=100001, name="Alice Fahrer", phone="49111", active=True
    )
    await Driver.create(
        telegram_id=100002, name="Bob Lenker", phone="49222", active=False
    )

    update = make_update(user_id=111111)
    ctx = make_context()

    await _handle_driver_list(update, ctx)
    update.message.reply_text.assert_called()
    response = update.message.reply_text.call_args[0][0]
    assert "Alice Fahrer" in response
    assert "Bob Lenker" in response


@pytest.mark.asyncio
async def test_driver_list_empty(db):
    """List drivers when none exist."""
    from krankenfahrt.bots.chef_bot import _handle_driver_list

    update = make_update(user_id=111111)
    ctx = make_context()

    await _handle_driver_list(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "keine" in response.lower() or "no" in response.lower()


@pytest.mark.asyncio
async def test_driver_update_name(db):
    """Update a driver's name."""
    from krankenfahrt.bots.chef_bot import _handle_driver_update
    from krankenfahrt.models.schema import Driver

    driver = await Driver.create(
        telegram_id=100001, name="Alice Fahrer", phone="49111"
    )

    update = make_update(user_id=111111)
    # Update by ID: /fahrer update 1 name Alice Schmidt
    ctx = make_context(args=["update", str(driver.id), "name", "Alice", "Schmidt"])

    await _handle_driver_update(update, ctx)

    await driver.refresh_from_db()
    assert driver.name == "Alice Schmidt"

    response = update.message.reply_text.call_args[0][0]
    assert "umbenannt" in response.lower() or "updated" in response.lower()


@pytest.mark.asyncio
async def test_driver_update_phone(db):
    """Update a driver's phone number."""
    from krankenfahrt.bots.chef_bot import _handle_driver_update
    from krankenfahrt.models.schema import Driver

    driver = await Driver.create(
        telegram_id=100001, name="Alice Fahrer", phone="49111"
    )

    update = make_update(user_id=111111)
    ctx = make_context(args=["update", str(driver.id), "phone", "49999"])

    await _handle_driver_update(update, ctx)

    await driver.refresh_from_db()
    assert driver.phone == "49999"


@pytest.mark.asyncio
async def test_driver_update_not_found(db):
    """Update a non-existent driver returns error."""
    from krankenfahrt.bots.chef_bot import _handle_driver_update

    update = make_update(user_id=111111)
    ctx = make_context(args=["update", "9999", "name", "Nobody"])

    await _handle_driver_update(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "nicht gefunden" in response.lower() or "not found" in response.lower()


@pytest.mark.asyncio
async def test_driver_delete_with_confirm(db):
    """Delete a driver with confirmation."""
    from krankenfahrt.bots.chef_bot import _handle_driver_delete
    from krankenfahrt.models.schema import Driver

    driver = await Driver.create(
        telegram_id=100001, name="Alice Fahrer", phone="49111"
    )

    update = make_update(user_id=111111)
    ctx = make_context(args=["delete", str(driver.id), "confirm"])

    await _handle_driver_delete(update, ctx)

    # Driver should be soft-deleted (deactivated) or hard-deleted
    exists = await Driver.filter(id=driver.id).first()
    # We deactivate rather than hard-delete to preserve trip history
    assert exists is None or exists.active is False

    response = update.message.reply_text.call_args[0][0]
    assert "gelöscht" in response.lower() or "deleted" in response.lower() or "deaktiviert" in response.lower()


@pytest.mark.asyncio
async def test_driver_delete_asks_confirm(db):
    """Delete without 'confirm' keyword asks for confirmation."""
    from krankenfahrt.bots.chef_bot import _handle_driver_delete
    from krankenfahrt.models.schema import Driver

    driver = await Driver.create(
        telegram_id=100001, name="Alice Fahrer", phone="49111"
    )

    update = make_update(user_id=111111)
    ctx = make_context(args=["delete", str(driver.id)])

    await _handle_driver_delete(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    # Should ask for confirmation, not actually delete
    assert "bestätigen" in response.lower() or "confirm" in response.lower()
    assert "confirm" in response.lower()


# ---------------------------------------------------------------------------
# Vehicle CRUD tests (integration with SQLite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vehicle_add(db):
    """Create a new vehicle."""
    from krankenfahrt.bots.chef_bot import _handle_vehicle_add
    from krankenfahrt.models.schema import Vehicle

    update = make_update(user_id=111111)
    ctx = make_context(args=["add", "VW", "Golf", "B-AB-1234"])

    await _handle_vehicle_add(update, ctx)

    vehicle = await Vehicle.filter(license_plate="B-AB-1234").first()
    assert vehicle is not None
    assert vehicle.vehicle_type == "Sitz"  # default

    response = update.message.reply_text.call_args[0][0]
    assert "B-AB-1234" in response


@pytest.mark.asyncio
async def test_vehicle_add_duplicate_plate(db):
    """Adding a vehicle with duplicate license plate is rejected."""
    from krankenfahrt.bots.chef_bot import _handle_vehicle_add
    from krankenfahrt.models.schema import Vehicle

    await Vehicle.create(license_plate="B-AB-1234", vehicle_type="Sitz")

    update = make_update(user_id=111111)
    ctx = make_context(args=["add", "VW", "Golf", "B-AB-1234"])

    await _handle_vehicle_add(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "existiert bereits" in response.lower() or "already" in response.lower()


@pytest.mark.asyncio
async def test_vehicle_add_with_type(db):
    """Create a vehicle with explicit type."""
    from krankenfahrt.bots.chef_bot import _handle_vehicle_add
    from krankenfahrt.models.schema import Vehicle

    update = make_update(user_id=111111)
    ctx = make_context(args=["add", "Mercedes", "Sprinter", "B-XY-5678", "KTW"])

    await _handle_vehicle_add(update, ctx)

    vehicle = await Vehicle.filter(license_plate="B-XY-5678").first()
    assert vehicle is not None
    assert vehicle.vehicle_type == "KTW"


@pytest.mark.asyncio
async def test_vehicle_list(db):
    """List all vehicles."""
    from krankenfahrt.bots.chef_bot import _handle_vehicle_list
    from krankenfahrt.models.schema import Vehicle

    await Vehicle.create(license_plate="B-AB-1234", vehicle_type="Sitz")
    await Vehicle.create(license_plate="B-CD-5678", vehicle_type="KTW")

    update = make_update(user_id=111111)
    ctx = make_context()

    await _handle_vehicle_list(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "B-AB-1234" in response
    assert "B-CD-5678" in response


@pytest.mark.asyncio
async def test_vehicle_update_type(db):
    """Update a vehicle's type."""
    from krankenfahrt.bots.chef_bot import _handle_vehicle_update
    from krankenfahrt.models.schema import Vehicle

    vehicle = await Vehicle.create(license_plate="B-AB-1234", vehicle_type="Sitz")

    update = make_update(user_id=111111)
    ctx = make_context(args=["update", str(vehicle.id), "type", "KTW"])

    await _handle_vehicle_update(update, ctx)

    await vehicle.refresh_from_db()
    assert vehicle.vehicle_type == "KTW"


@pytest.mark.asyncio
async def test_vehicle_delete(db):
    """Delete a vehicle."""
    from krankenfahrt.bots.chef_bot import _handle_vehicle_delete
    from krankenfahrt.models.schema import Vehicle

    vehicle = await Vehicle.create(license_plate="B-AB-1234", vehicle_type="Sitz")

    update = make_update(user_id=111111)
    ctx = make_context(args=["delete", str(vehicle.id), "confirm"])

    await _handle_vehicle_delete(update, ctx)

    exists = await Vehicle.filter(id=vehicle.id).first()
    assert exists is None


# ---------------------------------------------------------------------------
# Command router tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fahrer_help_shows_usage():
    """Calling /fahrer without subcommand shows help."""
    from krankenfahrt.bots.chef_bot import cmd_fahrer

    update = make_update(user_id=111111)
    ctx = make_context(args=[])

    await cmd_fahrer(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "add" in response.lower() or "hinzufügen" in response.lower()
    assert "list" in response.lower() or "liste" in response.lower() or "anzeigen" in response.lower()


@pytest.mark.asyncio
async def test_fahrzeug_help_shows_usage():
    """Calling /fahrzeug without subcommand shows help."""
    from krankenfahrt.bots.chef_bot import cmd_fahrzeug

    update = make_update(user_id=111111)
    ctx = make_context(args=[])

    await cmd_fahrzeug(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "add" in response.lower() or "hinzufügen" in response.lower()
    assert "list" in response.lower() or "liste" in response.lower() or "anzeigen" in response.lower()


@pytest.mark.asyncio
async def test_fahrer_unknown_subcommand():
    """Unknown subcommand gives error."""
    from krankenfahrt.bots.chef_bot import cmd_fahrer

    update = make_update(user_id=111111)
    ctx = make_context(args=["fly"])  # nonsense

    await cmd_fahrer(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "unbekannt" in response.lower() or "unknown" in response.lower() or "verfügbar" in response.lower()


# ---------------------------------------------------------------------------
# Export command tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_help_shows_usage():
    """Calling /export without subcommand shows help with csv+pdf options."""
    from krankenfahrt.bots.chef_bot import cmd_export

    update = make_update(user_id=111111)
    ctx = make_context(args=[])

    await cmd_export(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "CSV" in response
    assert "PDF" in response
    assert "Muster-4" in response


@pytest.mark.asyncio
async def test_export_csv_backward_compat():
    """Calling /export with a date (no subcommand) should still work as CSV."""
    from krankenfahrt.bots.chef_bot import cmd_export

    update = make_update(user_id=111111)
    ctx = make_context(args=["01.06.2026", "30.06.2026"])

    await cmd_export(update, ctx)
    # Should have started CSV export (progress message)
    update.message.reply_text.assert_called()
    first_call = update.message.reply_text.call_args_list[0][0][0]
    assert "Exportiere" in first_call or "export" in first_call.lower()


@pytest.mark.asyncio
async def test_export_unknown_subcommand():
    """Unknown subcommand shows error with available options."""
    from krankenfahrt.bots.chef_bot import cmd_export

    update = make_update(user_id=111111)
    ctx = make_context(args=["blah"])

    await cmd_export(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "unbekannt" in response.lower() or "Unknown" in response
    assert "CSV" in response


@pytest.mark.asyncio
async def test_export_pdf_invalid_patient_id(db):
    """PDF export with non-integer patient ID shows error."""
    from krankenfahrt.bots.chef_bot import cmd_export

    update = make_update(user_id=111111)
    ctx = make_context(args=["pdf", "abc"])

    await cmd_export(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "ungültige" in response.lower() or "invalid" in response.lower()


@pytest.mark.asyncio
async def test_export_pdf_patient_not_found(db):
    """PDF export for non-existent patient shows error."""
    from krankenfahrt.bots.chef_bot import cmd_export

    update = make_update(user_id=111111)
    ctx = make_context(args=["pdf", "999"])

    await cmd_export(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "nicht gefunden" in response.lower() or "not found" in response.lower()


@pytest.mark.asyncio
async def test_export_pdf_missing_patient_id(db):
    """PDF export without patient ID shows usage help."""
    from krankenfahrt.bots.chef_bot import cmd_export

    update = make_update(user_id=111111)
    ctx = make_context(args=["pdf"])

    await cmd_export(update, ctx)
    response = update.message.reply_text.call_args[0][0]
    assert "Patient-ID" in response


@pytest.mark.asyncio
async def test_export_pdf_no_trips_found(db):
    """PDF export for patient with no trips shows warning."""
    from krankenfahrt.bots.chef_bot import cmd_export
    from krankenfahrt.models.schema import Patient

    # Create a patient with no trips
    await Patient.create(
        telegram_id=200001,
        name="Test Patient",
        default_pickup_addr="Teststr 1",
        insurance_provider="AOK",
        insurance_number="T123",
    )
    # Get the created patient (id=1 since first in DB)
    patient = await Patient.first()
    assert patient is not None

    update = make_update(user_id=111111)
    ctx = make_context(args=["pdf", str(patient.id)])

    await cmd_export(update, ctx)
    # First call: progress message
    first_call = update.message.reply_text.call_args_list[0][0][0]
    assert "erstellt" in first_call.lower() or "creating" in first_call.lower()

    # Second call: no trips warning
    second_call = update.message.reply_text.call_args_list[1][0][0]
    assert "keine" in second_call.lower() or "no" in second_call.lower()


@pytest.mark.asyncio
async def test_export_pdf_with_trips(db, tmp_path):
    """PDF export generates a valid PDF for a patient with trips."""
    from datetime import datetime

    from krankenfahrt.bots.chef_bot import _handle_export_pdf
    from krankenfahrt.models.schema import Patient, Trip

    patient = await Patient.create(
        telegram_id=200001,
        name="Max Mustermann",
        default_pickup_addr="Teststraße 1, 12345 Stadt",
        insurance_provider="AOK",
        insurance_number="T123456789",
    )

    # Create a trip for this patient
    await Trip.create(
        patient=patient,
        pickup_addr="Teststraße 1, 12345 Stadt",
        dest_addr="Zielstraße 2, 12345 Stadt",
        scheduled_pickup=datetime(2026, 6, 1, 10, 0),
        fare_eur=45.00,
        status="abgeschlossen",
    )

    update = make_update(user_id=111111)
    ctx = make_context(args=["pdf", str(patient.id)])

    # Patch PROJECT_ROOT to use tmp_path for output
    import krankenfahrt.config as cfg

    orig_root = cfg.PROJECT_ROOT
    try:
        cfg.PROJECT_ROOT = tmp_path
        await _handle_export_pdf(update, ctx)
    finally:
        cfg.PROJECT_ROOT = orig_root

    # First call: progress
    progress = update.message.reply_text.call_args_list[0][0][0]
    assert "erstellt" in progress.lower() or "creating" in progress.lower()

    # Second call: reply_document with PDF
    assert update.message.reply_document.called
    doc_kwargs = update.message.reply_document.call_args[1]
    assert "filename" in doc_kwargs
    assert doc_kwargs["filename"].endswith(".pdf")

    # Verify PDF was created on disk
    exports_dir = tmp_path / "data" / "exports"
    pdf_files = list(exports_dir.glob("*.pdf"))
    assert len(pdf_files) == 1
    with open(pdf_files[0], "rb") as f:
        assert f.read(5) == b"%PDF-"
