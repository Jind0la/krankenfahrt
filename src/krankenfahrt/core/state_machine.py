"""Trip lifecycle state machine using `transitions`."""

from transitions import Machine
from transitions.extensions.asyncio import AsyncMachine


# States and valid transitions for a trip
TRIP_STATES = [
    "geplant",          # Created, not yet assigned
    "zugewiesen",       # Driver assigned
    "anfahrt",          # Driver en route to pickup
    "angekommen",       # Driver arrived at pickup
    "patient_an_bord",  # Patient in vehicle
    "unterwegs",        # En route to destination
    "abgesetzt",        # Patient dropped off
    "abgeschlossen",    # Trip completed
    "storniert",        # Cancelled
    "problem",          # Issue flagged
]

# Transitions: trigger → from → to
# Any state can go to 'storniert' or 'problem'
TRIP_TRANSITIONS = [
    # Normal flow
    {"trigger": "fahrer_zuweisen", "source": "geplant", "dest": "zugewiesen"},
    {"trigger": "losfahren", "source": "zugewiesen", "dest": "anfahrt"},
    {"trigger": "ankunft_melden", "source": "anfahrt", "dest": "angekommen"},
    {"trigger": "patient_aufnehmen", "source": "angekommen", "dest": "patient_an_bord"},
    {"trigger": "fahrt_beginnen", "source": "patient_an_bord", "dest": "unterwegs"},
    {"trigger": "patient_absetzen", "source": "unterwegs", "dest": "abgesetzt"},
    {"trigger": "abschliessen", "source": "abgesetzt", "dest": "abgeschlossen"},

    # Exceptional — from any active state
    {"trigger": "stornieren", "source": [
        "geplant", "zugewiesen", "anfahrt", "angekommen",
        "patient_an_bord", "unterwegs"
    ], "dest": "storniert"},
    {"trigger": "problem_melden", "source": [
        "zugewiesen", "anfahrt", "angekommen",
        "patient_an_bord", "unterwegs", "abgesetzt"
    ], "dest": "problem"},
    {"trigger": "problem_loesen", "source": "problem", "dest": None},  # Return to previous state

    # Re-assign
    {"trigger": "fahrer_neu_zuweisen", "source": [
        "zugewiesen", "anfahrt", "angekommen"
    ], "dest": "geplant"},
]


class TripStateMachine:
    """Wraps a Trip model instance with state machine behavior."""

    def __init__(self, trip_model_instance):
        self.trip = trip_model_instance
        self.machine = Machine(
            model=self,
            states=TRIP_STATES,
            transitions=TRIP_TRANSITIONS,
            initial=trip_model_instance.status,
            send_event=True,  # Callbacks get event data
        )

    # Optional: add callbacks
    def on_enter_anfahrt(self, event):
        """Triggered when driver starts driving to pickup — notify patient."""
        pass  # Implemented via notification service

    def on_enter_abgeschlossen(self, event):
        """Trip completed — trigger billing prep."""
        pass


# Convenience: trigger display names for driver buttons
TRIGGER_LABELS = {
    "losfahren": "🚗 Anfahrt",
    "ankunft_melden": "📍 Angekommen",
    "patient_aufnehmen": "👤 Patient an Bord",
    "patient_absetzen": "✅ Abgesetzt",
    "abschliessen": "🔒 Abschließen",
    "problem_melden": "⚠️ Problem",
    "stornieren": "❌ Stornieren",
}

# Which triggers are available at which state
TRIGGER_MAP = {
    "zugewiesen": ["losfahren", "stornieren"],
    "anfahrt": ["ankunft_melden", "problem_melden"],
    "angekommen": ["patient_aufnehmen", "problem_melden"],
    "patient_an_bord": ["fahrt_beginnen", "problem_melden"],
    "unterwegs": ["patient_absetzen", "problem_melden"],
    "abgesetzt": ["abschliessen"],
}
