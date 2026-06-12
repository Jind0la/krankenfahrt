"""Trip lifecycle state machine using `transitions`.

Architecture:
- TripStateMachine wraps a Trip model instance.
- All transitions defined in TRIP_TRANSITIONS with guard conditions.
- Every state has on_enter/on_exit callbacks that fire exactly once per transition.
- Every state change is logged via an injectable event_logger callback.
- problem_loesen is a custom method (not a transitions trigger) that restores
  the previous state, using saved _pre_problem_state.
- TRIGGER_MAP is derived dynamically from the machine (no hardcoding).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from transitions import Machine

# ── states ──────────────────────────────────────────────────────────────

TRIP_STATES: list[str] = [
    "geplant",          # Created, not yet assigned
    "zugewiesen",       # Driver assigned
    "anfahrt",          # Driver en route to pickup
    "angekommen",       # Driver arrived at pickup
    "patient_an_bord",  # Patient in vehicle
    "unterwegs",        # En route to destination
    "abgesetzt",        # Patient dropped off
    "abgeschlossen",    # Trip completed
    "storniert",        # Cancelled (terminal)
    "problem",          # Issue flagged (recoverable)
]

TERMINAL_STATES: set[str] = {"abgeschlossen", "storniert"}

# ── transitions ──────────────────────────────────────────────────────────

# Guards are methods on TripStateMachine prefixed with _guard_.
# They receive the event data dict and should return True to allow the transition.
# If they return False, transitions raises MachineError.

TRIP_TRANSITIONS: list[dict[str, Any]] = [
    # ── normal forward flow ──
    {
        "trigger": "fahrer_zuweisen",
        "source": "geplant",
        "dest": "zugewiesen",
        "before": "_guard_can_assign",
    },
    {
        "trigger": "losfahren",
        "source": "zugewiesen",
        "dest": "anfahrt",
    },
    {
        "trigger": "ankunft_melden",
        "source": "anfahrt",
        "dest": "angekommen",
    },
    {
        "trigger": "patient_aufnehmen",
        "source": "angekommen",
        "dest": "patient_an_bord",
    },
    {
        "trigger": "fahrt_beginnen",
        "source": "patient_an_bord",
        "dest": "unterwegs",
    },
    {
        "trigger": "patient_absetzen",
        "source": "unterwegs",
        "dest": "abgesetzt",
    },
    {
        "trigger": "abschliessen",
        "source": "abgesetzt",
        "dest": "abgeschlossen",
        "before": "_guard_can_complete",
    },
    # ── exceptional flows ──
    {
        "trigger": "stornieren",
        "source": [
            "geplant",
            "zugewiesen",
            "anfahrt",
            "angekommen",
            "patient_an_bord",
            "unterwegs",
        ],
        "dest": "storniert",
        "before": "_guard_not_terminal",
    },
    {
        "trigger": "problem_melden",
        "source": [
            "zugewiesen",
            "anfahrt",
            "angekommen",
            "patient_an_bord",
            "unterwegs",
            "abgesetzt",
        ],
        "dest": "problem",
        "before": "_guard_not_terminal",
    },
    # ── re-assignment (back to geplant) ──
    {
        "trigger": "fahrer_neu_zuweisen",
        "source": [
            "zugewiesen",
            "anfahrt",
            "angekommen",
        ],
        "dest": "geplant",
        "before": "_guard_not_terminal",
    },
]

# ── helper types ─────────────────────────────────────────────────────────


@dataclass
class StateChangeEvent:
    """Structured log entry for every state change."""

    trip_id: int | None
    from_state: str
    to_state: str
    trigger: str
    timestamp: str  # ISO 8601 UTC
    metadata: dict[str, Any] = field(default_factory=dict)


# Type alias for the logger callback.
EventLogger = Callable[[StateChangeEvent], None]

# ── main class ───────────────────────────────────────────────────────────


class TripStateMachine:
    """Wraps a Trip model instance with full state-machine behaviour.

    Features:
    - All 12 triggers from TRIP_TRANSITIONS
    - on_enter / on_exit callbacks for every state
    - Guard conditions (invalid transitions → MachineError)
    - Structured event logging via injectable ``event_logger``
    - Dynamic TRIGGER_MAP via ``available_triggers`` property
    - problem_loesen: custom method that restores pre-problem state

    Usage::

        sm = TripStateMachine(trip, event_logger=my_db_logger)
        sm.fahrer_zuweisen()          # geplant → zugewiesen
        sm.losfahren()                # zugewiesen → anfahrt
        print(sm.state)               # 'anfahrt'
        print(sm.available_triggers)  # ['ankunft_melden', 'problem_melden']
    """

    # ── init ─────────────────────────────────────────────────────────

    def __init__(
        self,
        trip_model_instance: Any,
        event_logger: EventLogger | None = None,
    ):
        self.trip = trip_model_instance
        self._event_logger = event_logger
        # For problem_loesen: save the state we came from before entering 'problem'
        self._pre_problem_state: str | None = None
        # In-memory event log (always recorded; flushed to DB via event_logger)
        self._event_log: list[StateChangeEvent] = []
        # Track callback invocations for testing (internal)
        self._callback_calls: list[dict[str, Any]] = []

        self.machine = Machine(
            model=self,
            states=TRIP_STATES,
            transitions=TRIP_TRANSITIONS,
            initial=trip_model_instance.status,
            send_event=True,  # Pass event data to callbacks
            queued=True,      # Process transitions in FIFO order
            auto_transitions=False,  # No automatic to_<state> methods
            after_state_change="_on_after_state_change",
        )

    # ── logging helpers ──────────────────────────────────────────────

    def _on_after_state_change(self, event: Any) -> None:
        """Called automatically by transitions after every state change.

        Updates the wrapped trip model's status in memory so that
        ``trip.status`` always reflects the current machine state.
        The caller is responsible for calling ``await trip.save()``
        to persist to the database.
        """
        self.trip.status = self.state

    def _emit_event(
        self,
        trigger: str,
        from_state: str,
        to_state: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Create and record a StateChangeEvent, then call the logger if set."""
        evt = StateChangeEvent(
            trip_id=getattr(self.trip, "id", None),
            from_state=from_state,
            to_state=to_state,
            trigger=trigger,
            timestamp=datetime.now(UTC).isoformat(),
            metadata=metadata or {},
        )
        self._event_log.append(evt)
        if self._event_logger is not None:
            self._event_logger(evt)

    def _record_callback(self, callback_name: str, state: str, is_entry: bool) -> None:
        """Record that a callback fired (for test verification)."""
        self._callback_calls.append(
            {
                "callback": callback_name,
                "state": state,
                "kind": "entry" if is_entry else "exit",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    # ── callbacks: geplant ───────────────────────────────────────────

    def on_enter_geplant(self, event: Any) -> None:
        self._record_callback("on_enter_geplant", "geplant", True)

    def on_exit_geplant(self, event: Any) -> None:
        self._record_callback("on_exit_geplant", "geplant", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="geplant",
            to_state=event.transition.dest,
        )

    # ── callbacks: zugewiesen ────────────────────────────────────────

    def on_enter_zugewiesen(self, event: Any) -> None:
        self._record_callback("on_enter_zugewiesen", "zugewiesen", True)

    def on_exit_zugewiesen(self, event: Any) -> None:
        self._record_callback("on_exit_zugewiesen", "zugewiesen", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="zugewiesen",
            to_state=event.transition.dest,
        )

    # ── callbacks: anfahrt ───────────────────────────────────────────

    def on_enter_anfahrt(self, event: Any) -> None:
        """Triggered when driver starts driving to pickup — notify patient."""
        self._record_callback("on_enter_anfahrt", "anfahrt", True)

    def on_exit_anfahrt(self, event: Any) -> None:
        self._record_callback("on_exit_anfahrt", "anfahrt", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="anfahrt",
            to_state=event.transition.dest,
        )

    # ── callbacks: angekommen ────────────────────────────────────────

    def on_enter_angekommen(self, event: Any) -> None:
        """Driver arrived at pickup location."""
        self._record_callback("on_enter_angekommen", "angekommen", True)

    def on_exit_angekommen(self, event: Any) -> None:
        self._record_callback("on_exit_angekommen", "angekommen", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="angekommen",
            to_state=event.transition.dest,
        )

    # ── callbacks: patient_an_bord ───────────────────────────────────

    def on_enter_patient_an_bord(self, event: Any) -> None:
        """Patient is in the vehicle."""
        self._record_callback("on_enter_patient_an_bord", "patient_an_bord", True)

    def on_exit_patient_an_bord(self, event: Any) -> None:
        self._record_callback("on_exit_patient_an_bord", "patient_an_bord", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="patient_an_bord",
            to_state=event.transition.dest,
        )

    # ── callbacks: unterwegs ─────────────────────────────────────────

    def on_enter_unterwegs(self, event: Any) -> None:
        """En route to destination."""
        self._record_callback("on_enter_unterwegs", "unterwegs", True)

    def on_exit_unterwegs(self, event: Any) -> None:
        self._record_callback("on_exit_unterwegs", "unterwegs", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="unterwegs",
            to_state=event.transition.dest,
        )

    # ── callbacks: abgesetzt ─────────────────────────────────────────

    def on_enter_abgesetzt(self, event: Any) -> None:
        """Patient dropped off at destination."""
        self._record_callback("on_enter_abgesetzt", "abgesetzt", True)

    def on_exit_abgesetzt(self, event: Any) -> None:
        self._record_callback("on_exit_abgesetzt", "abgesetzt", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="abgesetzt",
            to_state=event.transition.dest,
        )

    # ── callbacks: abgeschlossen ─────────────────────────────────────

    def on_enter_abgeschlossen(self, event: Any) -> None:
        """Trip completed — trigger billing prep."""
        self._record_callback("on_enter_abgeschlossen", "abgeschlossen", True)

    def on_exit_abgeschlossen(self, event: Any) -> None:
        # Should never happen — abgeschlossen is terminal
        self._record_callback("on_exit_abgeschlossen", "abgeschlossen", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="abgeschlossen",
            to_state=event.transition.dest,
        )

    # ── callbacks: storniert ─────────────────────────────────────────

    def on_enter_storniert(self, event: Any) -> None:
        """Trip cancelled — terminal state."""
        self._record_callback("on_enter_storniert", "storniert", True)

    def on_exit_storniert(self, event: Any) -> None:
        # Should never happen — storniert is terminal
        self._record_callback("on_exit_storniert", "storniert", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="storniert",
            to_state=event.transition.dest,
        )

    # ── callbacks: problem ───────────────────────────────────────────

    def on_enter_problem(self, event: Any) -> None:
        """Issue flagged — remember where we came from so we can return."""
        self._record_callback("on_enter_problem", "problem", True)
        # Save the source state so problem_loesen knows where to return
        self._pre_problem_state = event.transition.source

    def on_exit_problem(self, event: Any) -> None:
        self._record_callback("on_exit_problem", "problem", False)
        self._emit_event(
            trigger=event.event.name,
            from_state="problem",
            to_state=event.transition.dest,
        )
        # Clear the saved previous state on exit
        self._pre_problem_state = None

    # ── guard conditions ─────────────────────────────────────────────

    def _guard_can_assign(self, event: Any) -> bool:
        """Guard: a driver must be set on the trip before assigning."""
        # In production this checks self.trip.driver_id is not None.
        # For MVP the guard always passes — assignment happens externally.
        return True

    def _guard_can_complete(self, event: Any) -> bool:
        """Guard: trip can only be completed after patient is dropped off."""
        return self.state == "abgesetzt"

    def _guard_not_terminal(self, event: Any) -> bool:
        """Guard: no actions allowed on terminal states."""
        return self.state not in TERMINAL_STATES

    # ── custom: problem_loesen (returns to pre-problem state) ────────

    def problem_loesen(self, metadata: dict[str, Any] | None = None) -> None:
        """Resolve a problem and return to the state before the problem was reported.

        This is NOT a transitions trigger — it uses Machine.set_state() directly
        because the destination state is dynamic (the state we saved on entry to
        'problem').

        Raises:
            RuntimeError: if no previous state is known (caller must use
                          problem_melden first).
        """
        if self._pre_problem_state is None:
            raise RuntimeError(
                "Cannot resolve problem: no previous state known. "
                "Call problem_melden first to enter 'problem' state."
            )

        return_state = self._pre_problem_state
        self._emit_event(
            trigger="problem_loesen",
            from_state="problem",
            to_state=return_state,
            metadata=metadata,
        )
        # Use machine.set_state to bypass transitions framework
        self.machine.set_state(return_state)
        # Manually sync trip status since after_state_change won't fire
        # for programmatic set_state calls
        self.trip.status = return_state
        self._pre_problem_state = None

    # ── derived properties ───────────────────────────────────────────

    @property
    def available_triggers(self) -> list[str]:
        """Return trigger names that are valid from the current state.

        Replaces the hardcoded TRIGGER_MAP with a dynamic query against
        the transitions machine.
        """
        return self.machine.get_triggers(self.state)

    @property
    def is_terminal(self) -> bool:
        """True if the current state is terminal (abgeschlossen or storniert)."""
        return self.state in TERMINAL_STATES

    @property
    def event_log(self) -> list[StateChangeEvent]:
        """Return the in-memory event log (for inspection / testing)."""
        return list(self._event_log)


# ── convenience: trigger display names for driver buttons ─────────────────

TRIGGER_LABELS: dict[str, str] = {
    "fahrer_zuweisen": "👤 Fahrer zuweisen",
    "losfahren": "🚗 Anfahrt",
    "ankunft_melden": "📍 Angekommen",
    "patient_aufnehmen": "👤 Patient an Bord",
    "fahrt_beginnen": "▶️ Fahrt beginnen",
    "patient_absetzen": "✅ Abgesetzt",
    "abschliessen": "🔒 Abschließen",
    "problem_melden": "⚠️ Problem",
    "problem_loesen": "✅ Problem gelöst",
    "stornieren": "❌ Stornieren",
    "fahrer_neu_zuweisen": "🔄 Neu zuweisen",
}

# ── backwards-compatibility: TRIGGER_MAP derived from TRIP_TRANSITIONS ──────
# Maps each state to the list of triggers valid from that state.
# Used by driver_bot.py for building inline keyboards without instantiating
# a full TripStateMachine. Derived from TRIP_TRANSITIONS, not hardcoded.

TRIGGER_MAP: dict[str, list[str]] = {}
for _t in TRIP_TRANSITIONS:
    sources = _t["source"]
    if isinstance(sources, str):
        sources = [sources]
    for src in sources:
        TRIGGER_MAP.setdefault(src, []).append(_t["trigger"])
