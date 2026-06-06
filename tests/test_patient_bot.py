"""Tests for the Patient-Bot — profile management and recurring trip templates."""
import os
import sqlite3
from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tortoise import Tortoise


# ── SQLite time adapter ────────────────────────────────────────────────────

def _adapt_time(t: time) -> str:
    """Convert Python time to ISO string for SQLite storage, stripping tzinfo."""
    # Tortoise may attach UTC timezone to naive times — strip it for SQLite.
    if t.tzinfo is not None:
        t = t.replace(tzinfo=None)
    return t.isoformat()


def _convert_time(raw: bytes) -> time:
    """Convert SQLite bytes back to Python time."""
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    return time.fromisoformat(text)


# Register adapters for datetime.time <-> SQLite text
sqlite3.register_adapter(time, _adapt_time)
sqlite3.register_converter("time", _convert_time)


# ── Shared test fixtures ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_env():
    """Ensure test env vars are set before importing config."""
    os.environ.setdefault("PATIENT_BOT_TOKEN", "test_patient_token")
    os.environ.setdefault("DRIVER_BOT_TOKEN", "test_driver_token")
    os.environ.setdefault("CHEF_BOT_TOKEN", "test_chef_token")
    os.environ.setdefault("DEEPSEEK_API_KEY", "test_deepseek_key")
    # No admins by default in tests
    os.environ.setdefault("ADMIN_TELEGRAM_IDS", "")


@pytest.fixture
def admin_ids():
    """Override admin list for a test."""
    old = os.environ.get("ADMIN_TELEGRAM_IDS", "")
    os.environ["ADMIN_TELEGRAM_IDS"] = "111111"
    # Force reimport/reload — config uses dataclass defaults, so we need to reload
    import importlib
    import krankenfahrt.config
    importlib.reload(krankenfahrt.config)
    yield [111111]
    os.environ["ADMIN_TELEGRAM_IDS"] = old
    importlib.reload(krankenfahrt.config)


async def _init_test_db():
    """Initialize Tortoise with in-memory SQLite for tests."""
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["krankenfahrt.models.schema"]},
    )
    await Tortoise.generate_schemas()


async def _close_test_db():
    await Tortoise.close_connections()


# ── Authorization helper tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_admin_returns_true_for_admin(admin_ids):
    """_is_admin returns True for users in ADMIN_TELEGRAM_IDS."""
    from krankenfahrt.bots.patient_bot import _is_admin
    assert _is_admin(111111) is True


@pytest.mark.asyncio
async def test_is_admin_returns_false_for_regular_user(admin_ids):
    """_is_admin returns False for users not in ADMIN_TELEGRAM_IDS."""
    from krankenfahrt.bots.patient_bot import _is_admin
    assert _is_admin(999999) is False


@pytest.mark.asyncio
async def test_can_modify_owner_allowed(admin_ids):
    """A patient can modify their own data."""
    from krankenfahrt.bots.patient_bot import _can_modify
    assert _can_modify(111111, 111111) is True  # admin modifying own data
    assert _can_modify(999999, 999999) is True  # regular user modifying own data


@pytest.mark.asyncio
async def test_can_modify_admin_allowed(admin_ids):
    """An admin can modify any patient's data."""
    from krankenfahrt.bots.patient_bot import _can_modify
    assert _can_modify(111111, 999999) is True  # admin modifying another's data


@pytest.mark.asyncio
async def test_can_modify_others_blocked(admin_ids):
    """A non-admin patient cannot modify another patient's data."""
    from krankenfahrt.bots.patient_bot import _can_modify
    assert _can_modify(999999, 111111) is False  # regular user modifying admin's data


# ── /start command tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_new_patient_registers_and_welcomes():
    """A new patient gets auto-registered and welcomed."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_start
        from krankenfahrt.models.schema import Patient

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 555555
        update.effective_user.full_name = "Max Mustermann"
        update.message = AsyncMock()

        await cmd_start(update, MagicMock())

        # Check patient was created in DB
        patient = await Patient.filter(telegram_id=555555).first()
        assert patient is not None
        assert patient.name == "Max Mustermann"
        assert "Willkommen" in update.message.reply_text.call_args[0][0]

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_start_existing_patient_shows_profile():
    """An existing patient sees their profile on /start."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_start
        from krankenfahrt.models.schema import Patient

        # Pre-create patient
        await Patient.create(
            telegram_id=555555,
            name="Max Mustermann",
            default_pickup_addr="Musterstraße 1",
            phone="+49123456789",
        )

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 555555
        update.effective_user.full_name = "Max Mustermann"
        update.message = AsyncMock()

        await cmd_start(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Willkommen zurück" in text
        assert "Max Mustermann" in text
        assert "Musterstraße 1" in text

    finally:
        await _close_test_db()


# ── /profil command tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_profil_shows_existing_profile():
    """/profil shows the patient's saved data."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_profil
        from krankenfahrt.models.schema import Patient

        await Patient.create(
            telegram_id=555555,
            name="Anna Schmidt",
            default_pickup_addr="Parkstraße 5",
            vehicle_type="Liege",
            insurance_provider="AOK",
        )

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 555555
        update.message = AsyncMock()

        await cmd_profil(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Anna Schmidt" in text
        assert "Parkstraße 5" in text
        assert "Liege" in text
        assert "AOK" in text

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_profil_no_profile_returns_error():
    """/profil without a profile shows an error message."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_profil

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999999
        update.message = AsyncMock()

        await cmd_profil(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Kein Profil gefunden" in text

    finally:
        await _close_test_db()


# ── Profile editing conversation tests ─────────────────────────────────────

@pytest.mark.asyncio
async def test_profil_edit_start_shows_current_name():
    """/profil_edit starts by showing current name and asking for new one."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import profil_edit_start, PROFILE_EDIT_NAME
        from krankenfahrt.models.schema import Patient

        await Patient.create(
            telegram_id=555555,
            name="Anna Schmidt",
            default_pickup_addr="Parkstraße 5",
        )

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 555555
        update.message = AsyncMock()
        context = MagicMock()
        context.user_data = {}

        result = await profil_edit_start(update, context)

        assert result == PROFILE_EDIT_NAME
        assert context.user_data["edit_patient_id"] is not None
        text = update.message.reply_text.call_args[0][0]
        assert "Anna Schmidt" in text

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_profil_edit_full_flow_persists_changes():
    """Full profile edit flow persists all changes to DB."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import (
            profil_edit_name,
            profil_edit_phone,
            profil_edit_pickup,
            profil_edit_dest,
            profil_edit_insurance_provider,
            profil_edit_insurance_number,
            profil_edit_vehicle_type,
            profil_edit_special_needs,
            profil_edit_notes,
        )
        from krankenfahrt.models.schema import Patient

        patient = await Patient.create(
            telegram_id=555555,
            name="Alt Name",
            default_pickup_addr="Alt Adresse",
        )

        context = MagicMock()
        context.user_data = {
            "edit_patient_id": patient.id,
            "edit_telegram_id": 555555,
        }

        # Step 1: Name
        update = MagicMock()
        update.message = AsyncMock()
        update.message.text = "Neu Name"
        await profil_edit_name(update, context)
        assert context.user_data["profile_name"] == "Neu Name"

        # Step 2: Phone
        update.message.text = "+49999"
        await profil_edit_phone(update, context)
        assert context.user_data["profile_phone"] == "+49999"

        # Step 3: Pickup
        update.message.text = "Neue Straße 1"
        await profil_edit_pickup(update, context)
        assert context.user_data["profile_pickup"] == "Neue Straße 1"

        # Step 4: Dest
        update.message.text = "Klinik A"
        await profil_edit_dest(update, context)
        assert context.user_data["profile_dest"] == "Klinik A"

        # Step 5: Insurance provider
        update.message.text = "Barmer"
        await profil_edit_insurance_provider(update, context)
        assert context.user_data["profile_insurance_provider"] == "Barmer"

        # Step 6: Insurance number
        update.message.text = "V12345"
        await profil_edit_insurance_number(update, context)
        assert context.user_data["profile_insurance_number"] == "V12345"

        # Step 7: Vehicle type
        update.message.text = "Liege"
        await profil_edit_vehicle_type(update, context)
        assert context.user_data["profile_vehicle_type"] == "Liege"

        # Step 8: Special needs
        update.message.text = "Rollstuhl"
        await profil_edit_special_needs(update, context)
        assert context.user_data["profile_special_needs"] == "Rollstuhl"

        # Step 9: Notes (final step — persists)
        update.message.text = "Test Notiz"
        result = await profil_edit_notes(update, context)

        # Verify DB
        saved = await Patient.get(id=patient.id)
        assert saved.name == "Neu Name"
        assert saved.phone == "+49999"
        assert saved.default_pickup_addr == "Neue Straße 1"
        assert saved.default_dest_addr == "Klinik A"
        assert saved.insurance_provider == "Barmer"
        assert saved.insurance_number == "V12345"
        assert saved.vehicle_type == "Liege"
        assert saved.special_needs == "Rollstuhl"
        assert saved.notes == "Test Notiz"

        # Conversation ends
        from telegram.ext import ConversationHandler
        assert result == ConversationHandler.END

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_profil_edit_skip_all_fields_keeps_originals():
    """Skipping all fields preserves existing values."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import (
            profil_edit_name,
            profil_edit_phone,
            profil_edit_pickup,
            profil_edit_dest,
            profil_edit_insurance_provider,
            profil_edit_insurance_number,
            profil_edit_vehicle_type,
            profil_edit_special_needs,
            profil_edit_notes,
        )
        from telegram.ext import ConversationHandler
        from krankenfahrt.models.schema import Patient

        patient = await Patient.create(
            telegram_id=555555,
            name="Original Name",
            default_pickup_addr="Original Adresse",
            vehicle_type="Sitz",
        )

        context = MagicMock()
        context.user_data = {
            "edit_patient_id": patient.id,
            "edit_telegram_id": 555555,
        }

        update = MagicMock()
        update.message = AsyncMock()

        # Skip every field
        for handler in [
            profil_edit_name, profil_edit_phone, profil_edit_pickup,
            profil_edit_dest, profil_edit_insurance_provider,
            profil_edit_insurance_number, profil_edit_vehicle_type,
            profil_edit_special_needs,
        ]:
            update.message.text = "/skip"
            await handler(update, context)

        # Final step
        update.message.text = "/skip"
        result = await profil_edit_notes(update, context)

        # Verify nothing changed
        saved = await Patient.get(id=patient.id)
        assert saved.name == "Original Name"
        assert saved.default_pickup_addr == "Original Adresse"
        assert saved.vehicle_type == "Sitz"
        assert result == ConversationHandler.END

    finally:
        await _close_test_db()


# ── Template CRUD tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vorlagen_list_shows_templates():
    """/vorlagen lists all templates for the patient."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_vorlagen
        from krankenfahrt.models.schema import Patient, RecurringTrip

        patient = await Patient.create(
            telegram_id=555555,
            name="Test Patient",
            default_pickup_addr="Home",
        )

        await RecurringTrip.create(
            patient=patient,
            pickup_addr="Home",
            dest_addr="Dialyse Zentrum",
            cron_days="Mo,Mi,Fr",
            pickup_time=time(8, 30),
        )

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 555555
        update.message = AsyncMock()

        await cmd_vorlagen(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Dialyse Zentrum" in text
        assert "Mo,Mi,Fr" in text
        assert "08:30" in text

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_vorlagen_empty_shows_hint():
    """/vorlagen with no templates shows helpful message."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_vorlagen
        from krankenfahrt.models.schema import Patient

        await Patient.create(
            telegram_id=555555,
            name="Test Patient",
            default_pickup_addr="Home",
        )

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 555555
        update.message = AsyncMock()

        await cmd_vorlagen(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Keine Vorlagen" in text

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_vorlage_show_shows_template_detail():
    """/vorlage_show <id> shows full template details."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_vorlage_show
        from krankenfahrt.models.schema import Patient, RecurringTrip

        patient = await Patient.create(
            telegram_id=555555,
            name="Test Patient",
            default_pickup_addr="Home",
        )

        template = await RecurringTrip.create(
            patient=patient,
            pickup_addr="Home",
            dest_addr="Klinik",
            cron_days="Di,Do",
            pickup_time=time(14, 0),
            return_time=time(16, 0),
            vehicle_type="KTW",
        )

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 555555
        update.message = AsyncMock()
        context = MagicMock()
        context.args = [str(template.id)]

        await cmd_vorlage_show(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Klinik" in text
        assert "Di,Do" in text
        assert "14:00" in text
        assert "16:00" in text
        assert "KTW" in text

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_vorlage_show_wrong_owner_blocked():
    """A patient cannot view another patient's template."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_vorlage_show
        from krankenfahrt.models.schema import Patient, RecurringTrip

        patient_a = await Patient.create(
            telegram_id=111111,
            name="Patient A",
            default_pickup_addr="A-Straße",
        )
        patient_b = await Patient.create(
            telegram_id=222222,
            name="Patient B",
            default_pickup_addr="B-Straße",
        )

        template = await RecurringTrip.create(
            patient=patient_a,
            pickup_addr="A-Home",
            dest_addr="A-Klinik",
            cron_days="Mo",
            pickup_time=time(9, 0),
        )

        # Patient B tries to view Patient A's template
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 222222  # patient_b
        update.message = AsyncMock()
        context = MagicMock()
        context.args = [str(template.id)]

        await cmd_vorlage_show(update, context)

        text = update.message.reply_text.call_args[0][0]
        assert "Keine Berechtigung" in text

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_vorlage_del_requires_confirmation():
    """/vorlage_del <id> shows confirmation prompt before deleting."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_vorlage_del
        from krankenfahrt.models.schema import Patient, RecurringTrip

        patient = await Patient.create(
            telegram_id=555555,
            name="Test Patient",
            default_pickup_addr="Home",
        )
        template = await RecurringTrip.create(
            patient=patient,
            pickup_addr="Home",
            dest_addr="Klinik",
            cron_days="Mo",
            pickup_time=time(10, 0),
        )

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 555555
        update.message = AsyncMock()
        context = MagicMock()
        context.args = [str(template.id)]
        context.user_data = {}

        await cmd_vorlage_del(update, context)

        # Should show confirmation prompt
        text = update.message.reply_text.call_args[0][0]
        assert "wirklich löschen" in text
        assert "Klinik" in text

        # Should store template ID for callback
        assert context.user_data["del_template_id"] == template.id

        # Template should still exist (not deleted yet)
        still_exists = await RecurringTrip.filter(id=template.id).exists()
        assert still_exists is True

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_vorlage_new_conversation_persists_template():
    """Full template creation conversation persists to DB."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import (
            vorlage_neu_pickup,
            vorlage_neu_dest,
            vorlage_neu_days,
            vorlage_neu_pickup_time,
            vorlage_neu_return_time,
            vorlage_neu_vehicle_type,
            callback_vorlage_neu_confirm,
        )
        from telegram.ext import ConversationHandler
        from krankenfahrt.models.schema import Patient, RecurringTrip

        patient = await Patient.create(
            telegram_id=555555,
            name="Test Patient",
            default_pickup_addr="Home",
        )

        context = MagicMock()
        context.user_data = {"tpl_patient_id": patient.id}

        # Simulate the conversation flow
        handlers_with_inputs = [
            (vorlage_neu_pickup, "Home, Musterstraße 1"),
            (vorlage_neu_dest, "Dialyse Zentrum"),
            (vorlage_neu_days, "Mo,Mi,Fr"),
            (vorlage_neu_pickup_time, "08:30"),
            (vorlage_neu_return_time, "12:00"),
            (vorlage_neu_vehicle_type, "Liege"),
        ]

        for handler, input_text in handlers_with_inputs:
            update = MagicMock()
            update.message = AsyncMock()
            update.message.text = input_text
            await handler(update, context)

        # Verify context populated
        assert context.user_data["tpl_pickup"] == "Home, Musterstraße 1"
        assert context.user_data["tpl_dest"] == "Dialyse Zentrum"
        assert context.user_data["tpl_days"] == "Mo,Mi,Fr"
        assert context.user_data["tpl_pickup_time"] == time(8, 30)
        assert context.user_data["tpl_return_time"] == time(12, 0)
        assert context.user_data["tpl_vehicle_type"] == "Liege"

        # Now simulate the confirmation callback
        query_update = MagicMock()
        query = AsyncMock()
        query.data = "tpl_new_confirm"
        query_update.callback_query = query

        result = await callback_vorlage_neu_confirm(query_update, context)

        assert result == ConversationHandler.END

        # Verify template in DB
        templates = await RecurringTrip.filter(patient=patient).all()
        assert len(templates) == 1
        tpl = templates[0]
        assert tpl.pickup_addr == "Home, Musterstraße 1"
        assert tpl.dest_addr == "Dialyse Zentrum"
        assert tpl.cron_days == "Mo,Mi,Fr"
        assert tpl.pickup_time == time(8, 30)
        assert tpl.return_time == time(12, 0)
        assert tpl.vehicle_type == "Liege"

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_admin_can_view_any_patient_profile():
    """Admin can view another patient's profile."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import cmd_vorlagen
        from krankenfahrt.models.schema import Patient, RecurringTrip

        # Patient A (admin)
        admin = await Patient.create(
            telegram_id=111111,
            name="Admin User",
            default_pickup_addr="Office",
        )
        # Patient B (regular)
        patient_b = await Patient.create(
            telegram_id=222222,
            name="Regular Patient",
            default_pickup_addr="Home",
        )
        tpl = await RecurringTrip.create(
            patient=patient_b,
            pickup_addr="Home",
            dest_addr="Klinik",
            cron_days="Mo",
            pickup_time=time(9, 0),
        )

        # Admin tries to view Patient B's templates
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 111111  # admin
        update.message = AsyncMock()
        context = MagicMock()

        await cmd_vorlagen(update, context)

        # Admin should see their own templates (empty) — not Patient B's
        # This is correct: /vorlagen shows OWN templates.
        # Admin override would need a separate mechanism like /vorlagen_as <tg_id>
        # For now, test that ownership check works correctly

        # But /vorlage_show with admin override:
        from krankenfahrt.bots.patient_bot import cmd_vorlage_show
        update2 = MagicMock()
        update2.effective_user = MagicMock()
        update2.effective_user.id = 111111  # admin
        update2.message = AsyncMock()
        ctx2 = MagicMock()
        ctx2.args = [str(tpl.id)]
        ctx2.user_data = {}

        await cmd_vorlage_show(update2, ctx2)

        text = update2.message.reply_text.call_args[0][0]
        # Admin should be able to view Patient B's template
        assert "Klinik" in text

    finally:
        await _close_test_db()


# ── _format_profile and _format_template tests ─────────────────────────────

@pytest.mark.asyncio
async def test_format_profile_includes_all_fields():
    """_format_profile returns all expected fields."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import _format_profile
        from krankenfahrt.models.schema import Patient

        patient = await Patient.create(
            telegram_id=555555,
            name="Max",
            phone="+49123",
            default_pickup_addr="Street 1",
            default_dest_addr="Hospital",
            insurance_provider="TK",
            insurance_number="V999",
            vehicle_type="Rad",
            special_needs="Rollstuhl",
            notes="Test note",
        )

        text = _format_profile(patient)

        assert "Max" in text
        assert "+49123" in text
        assert "Street 1" in text
        assert "Hospital" in text
        assert "TK" in text
        assert "V999" in text
        assert "Rad" in text
        assert "Rollstuhl" in text
        assert "Test note" in text

    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_format_template_includes_all_fields():
    """_format_template returns all expected fields."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.patient_bot import _format_template
        from krankenfahrt.models.schema import Patient, RecurringTrip

        patient = await Patient.create(
            telegram_id=555555,
            name="Max",
            default_pickup_addr="Home",
        )

        template = await RecurringTrip.create(
            patient=patient,
            pickup_addr="Home",
            dest_addr="Klinik",
            cron_days="Mo,Mi,Fr",
            pickup_time=time(8, 30),
            return_time=time(12, 0),
            vehicle_type="KTW",
        )

        text = _format_template(template)

        assert "Home" in text
        assert "Klinik" in text
        assert "Mo,Mi,Fr" in text
        assert "08:30" in text
        assert "12:00" in text
        assert "KTW" in text

    finally:
        await _close_test_db()
