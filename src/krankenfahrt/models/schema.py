"""Tortoise ORM database models."""

from datetime import time

from tortoise import fields, Model


class Patient(Model):
    """Customer / patient being transported."""
    id = fields.IntField(pk=True)
    telegram_id = fields.BigIntField(unique=True)
    name = fields.CharField(max_length=200)
    phone = fields.CharField(max_length=50, null=True)
    default_pickup_addr = fields.TextField()
    default_dest_addr = fields.TextField(null=True)
    insurance_provider = fields.CharField(max_length=200, null=True)
    insurance_number = fields.CharField(max_length=50, null=True)
    vehicle_type = fields.CharField(max_length=20, default="Sitz")  # Sitz | Liege | Rad | KTW
    special_needs = fields.TextField(null=True)
    notes = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "patients"


class Vehicle(Model):
    """Vehicle in the fleet."""
    id = fields.IntField(pk=True)
    license_plate = fields.CharField(max_length=20, unique=True)
    vehicle_type = fields.CharField(max_length=20, default="Sitz")  # Sitz | Liege | Rad | KTW
    capacity = fields.IntField(default=1)
    notes = fields.TextField(null=True)

    # Relations
    driver: fields.ReverseRelation["Driver"]

    class Meta:
        table = "vehicles"


class Driver(Model):
    """Driver with qualifications and availability."""
    id = fields.IntField(pk=True)
    telegram_id = fields.BigIntField(unique=True)
    name = fields.CharField(max_length=200)
    phone = fields.CharField(max_length=50)
    p_schein = fields.BooleanField(default=False)  # Personenbeförderungsschein
    work_hours_start = fields.TimeField(default="07:00")
    work_hours_end = fields.TimeField(default="16:00")
    work_days = fields.CharField(max_length=50, default="Mo,Di,Mi,Do,Fr")  # Comma-separated
    active = fields.BooleanField(default=True)

    # Last known GPS position (updated by driver bot location sharing)
    location_lat = fields.FloatField(null=True)
    location_lon = fields.FloatField(null=True)

    vehicle: fields.ForeignKeyRelation[Vehicle] = fields.ForeignKeyField(
        "models.Vehicle", related_name="driver", null=True
    )

    class Meta:
        table = "drivers"


class RecurringTrip(Model):
    """Template for repeating trips (e.g. dialysis Mon/Wed/Fri)."""
    id = fields.IntField(pk=True)
    patient: fields.ForeignKeyRelation[Patient] = fields.ForeignKeyField(
        "models.Patient", related_name="recurring_trips"
    )
    pickup_addr = fields.TextField()
    dest_addr = fields.TextField()
    cron_days = fields.CharField(max_length=50)  # "Mo,Mi,Fr"
    pickup_time = fields.TimeField()
    return_time = fields.TimeField(null=True)
    vehicle_type = fields.CharField(max_length=20, default="Sitz")
    active_until = fields.DateField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "recurring_trips"


class Trip(Model):
    """A single transport trip through its lifecycle."""
    id = fields.IntField(pk=True)

    # Participants
    patient: fields.ForeignKeyRelation[Patient] = fields.ForeignKeyField(
        "models.Patient", related_name="trips"
    )
    driver: fields.ForeignKeyNullableRelation[Driver] = fields.ForeignKeyField(
        "models.Driver", related_name="trips", null=True
    )
    vehicle: fields.ForeignKeyNullableRelation[Vehicle] = fields.ForeignKeyField(
        "models.Vehicle", related_name="trips", null=True
    )
    recurring_template: fields.ForeignKeyNullableRelation[RecurringTrip] = (
        fields.ForeignKeyField("models.RecurringTrip", related_name="trips", null=True)
    )

    # Route
    pickup_addr = fields.TextField()
    dest_addr = fields.TextField()

    # Timing
    scheduled_pickup = fields.DatetimeField()
    scheduled_dropoff = fields.DatetimeField(null=True)
    actual_pickup = fields.DatetimeField(null=True)
    actual_dropoff = fields.DatetimeField(null=True)

    # State Machine
    status = fields.CharField(max_length=30, default="geplant")
    # Lifecycle: geplant → zugewiesen → anfahrt → angekommen →
    #            patient_an_bord → unterwegs → abgesetzt → abgeschlossen
    #            (→ storniert / problem from any state)

    # Billing
    billing_status = fields.CharField(max_length=20, default="offen")  # offen | exportiert | abgerechnet
    fare_eur = fields.FloatField(null=True)

    # Metadata
    driver_location_lat = fields.FloatField(null=True)  # Last known driver position
    driver_location_lon = fields.FloatField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "trips"


class TripEvent(Model):
    """Audit log of state changes and incidents."""
    id = fields.IntField(pk=True)
    trip: fields.ForeignKeyRelation[Trip] = fields.ForeignKeyField(
        "models.Trip", related_name="events"
    )
    event_type = fields.CharField(max_length=50)  # status_change | problem | note | system
    message = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "trip_events"


class DriverBreak(Model):
    """Driver break records — tracks pause start/end during a shift."""
    id = fields.IntField(pk=True)
    driver: fields.ForeignKeyRelation[Driver] = fields.ForeignKeyField(
        "models.Driver", related_name="breaks"
    )
    start_time = fields.DatetimeField()
    end_time = fields.DatetimeField(null=True)  # null = break still active
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "driver_breaks"


class Escalation(Model):
    """Escalation record for a trip — tracks trigger, options chosen, and resolution.

    Each escalation is linked to a trip and records:
    - What triggered it (timeout, manual, system)
    - Current status (open, acknowledged, resolved)
    - Which option the chef chose (reassign, pause, cancel, acknowledge, resolve)
    - Resolution details and timestamps

    The full history of escalation events for a trip is queryable via
    Escalation.filter(trip_id=...).order_by('created_at').
    """
    id = fields.IntField(pk=True)

    # Which trip is escalated
    trip: fields.ForeignKeyRelation[Trip] = fields.ForeignKeyField(
        "models.Trip", related_name="escalations"
    )

    # What triggered the escalation
    trigger_reason = fields.CharField(max_length=50)  # timeout | manual | system
    trigger_detail = fields.TextField(null=True)  # Human-readable reason (e.g. "30 min ohne Status-Update")

    # Current status of this escalation
    status = fields.CharField(max_length=30, default="open")  # open | acknowledged | resolved

    # Which option the chef chose (null until a decision is made)
    chosen_option = fields.CharField(max_length=50, null=True)  # reassign | pause | cancel | acknowledge | resolve

    # Who resolved it and how
    resolved_by_telegram_id = fields.BigIntField(null=True)  # Chef's Telegram ID
    resolution_note = fields.TextField(null=True)

    # Timestamps
    created_at = fields.DatetimeField(auto_now_add=True)
    acknowledged_at = fields.DatetimeField(null=True)
    resolved_at = fields.DatetimeField(null=True)

    class Meta:
        table = "escalations"
