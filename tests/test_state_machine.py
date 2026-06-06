"""Comprehensive tests for the TripStateMachine.

Covers:
- All defined transitions (forward flow, exceptional, re-assignment)
- Invalid transitions rejected with clear errors
- on_enter / on_exit callbacks fire exactly once per transition
- Guard conditions (terminal states, can_complete, can_assign)
- Event logging: every state change produces a StateChangeEvent
- problem_loesen: correctly restores pre-problem state
- Available triggers derived dynamically from machine
- Terminal state detection
- Chained transitions (full lifecycle walk-through)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from transitions import MachineError

from krankenfahrt.core.state_machine import (
    TERMINAL_STATES,
    TRIP_STATES,
    TRIP_TRANSITIONS,
    StateChangeEvent,
    TripStateMachine,
)


# ── mock trip ────────────────────────────────────────────────────────────


class MockTrip:
    """Minimal trip-like object for testing without a database."""

    def __init__(self, trip_id: int = 42, status: str = "geplant"):
        self.id = trip_id
        self.status = status
        # Fields the guards may inspect
        self.driver_id: int | None = None
        self.driver = None


def make_sm(status: str = "geplant", trip_id: int = 1) -> TripStateMachine:
    """Create a TripStateMachine with a mock trip in the given state."""
    trip = MockTrip(trip_id=trip_id, status=status)
    return TripStateMachine(trip)


# ── helpers ──────────────────────────────────────────────────────────────


def _transition_chain(sm: TripStateMachine, triggers: list[str]) -> None:
    """Convenience: call each trigger in sequence."""
    for trigger in triggers:
        getattr(sm, trigger)()


def _assert_event(
    evt: StateChangeEvent,
    from_state: str,
    to_state: str,
    trigger: str,
) -> None:
    """Assert that a StateChangeEvent matches expected fields."""
    assert evt.from_state == from_state, f"expected from {from_state}, got {evt.from_state}"
    assert evt.to_state == to_state, f"expected to {to_state}, got {evt.to_state}"
    assert evt.trigger == trigger, f"expected trigger {trigger}, got {evt.trigger}"
    assert evt.trip_id is not None
    assert isinstance(evt.timestamp, str)
    # ISO 8601 check
    assert "T" in evt.timestamp


# ══════════════════════════════════════════════════════════════════════════
# 1. Basic transitions — every trigger does what it should
# ══════════════════════════════════════════════════════════════════════════


class TestForwardFlowTransitions:
    """The 7-step normal lifecycle: geplant → … → abgeschlossen."""

    def test_geplant_to_zugewiesen(self):
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        assert sm.state == "zugewiesen"

    def test_zugewiesen_to_anfahrt(self):
        sm = make_sm("zugewiesen")
        sm.losfahren()
        assert sm.state == "anfahrt"

    def test_anfahrt_to_angekommen(self):
        sm = make_sm("anfahrt")
        sm.ankunft_melden()
        assert sm.state == "angekommen"

    def test_angekommen_to_patient_an_bord(self):
        sm = make_sm("angekommen")
        sm.patient_aufnehmen()
        assert sm.state == "patient_an_bord"

    def test_patient_an_bord_to_unterwegs(self):
        sm = make_sm("patient_an_bord")
        sm.fahrt_beginnen()
        assert sm.state == "unterwegs"

    def test_unterwegs_to_abgesetzt(self):
        sm = make_sm("unterwegs")
        sm.patient_absetzen()
        assert sm.state == "abgesetzt"

    def test_abgesetzt_to_abgeschlossen(self):
        sm = make_sm("abgesetzt")
        sm.abschliessen()
        assert sm.state == "abgeschlossen"


class TestExceptionalTransitions:
    """stornieren and problem_melden from various states."""

    @pytest.mark.parametrize(
        "from_state",
        [
            "geplant",
            "zugewiesen",
            "anfahrt",
            "angekommen",
            "patient_an_bord",
            "unterwegs",
        ],
    )
    def test_stornieren_from_active_states(self, from_state):
        sm = make_sm(from_state)
        sm.stornieren()
        assert sm.state == "storniert"

    @pytest.mark.parametrize(
        "from_state",
        [
            "zugewiesen",
            "anfahrt",
            "angekommen",
            "patient_an_bord",
            "unterwegs",
            "abgesetzt",
        ],
    )
    def test_problem_melden_from_active_states(self, from_state):
        sm = make_sm(from_state)
        sm.problem_melden()
        assert sm.state == "problem"


class TestReAssignmentTransitions:
    """fahrer_neu_zuweisen returns to geplant."""

    @pytest.mark.parametrize(
        "from_state",
        ["zugewiesen", "anfahrt", "angekommen"],
    )
    def test_fahrer_neu_zuweisen(self, from_state):
        sm = make_sm(from_state)
        sm.fahrer_neu_zuweisen()
        assert sm.state == "geplant"


# ══════════════════════════════════════════════════════════════════════════
# 2. Invalid transitions — rejected with clear errors
# ══════════════════════════════════════════════════════════════════════════


class TestInvalidTransitionsRejected:
    """Every invalid transition should raise MachineError."""

    def test_geplant_cannot_abschliessen(self):
        sm = make_sm("geplant")
        with pytest.raises(MachineError):
            sm.abschliessen()

    def test_geplant_cannot_patient_absetzen(self):
        sm = make_sm("geplant")
        with pytest.raises(MachineError):
            sm.patient_absetzen()

    def test_abgeschlossen_cannot_do_anything(self):
        sm = make_sm("abgeschlossen")
        for trigger in [
            "fahrer_zuweisen",
            "losfahren",
            "ankunft_melden",
            "patient_aufnehmen",
            "fahrt_beginnen",
            "patient_absetzen",
            "abschliessen",
        ]:
            with pytest.raises(MachineError):
                getattr(sm, trigger)()

    def test_storniert_cannot_do_anything(self):
        sm = make_sm("storniert")
        for trigger in [
            "fahrer_zuweisen",
            "losfahren",
            "ankunft_melden",
            "patient_aufnehmen",
            "fahrt_beginnen",
            "patient_absetzen",
            "abschliessen",
            "problem_melden",
        ]:
            with pytest.raises(MachineError):
                getattr(sm, trigger)()

    def test_abgesetzt_cannot_stornieren(self):
        sm = make_sm("abgesetzt")
        with pytest.raises(MachineError):
            sm.stornieren()

    def test_geplant_cannot_problem_melden(self):
        sm = make_sm("geplant")
        with pytest.raises(MachineError):
            sm.problem_melden()

    def test_abgeschlossen_cannot_stornieren(self):
        sm = make_sm("abgeschlossen")
        with pytest.raises(MachineError):
            sm.stornieren()

    def test_problem_cannot_abschliessen(self):
        sm = make_sm("problem")
        with pytest.raises(MachineError):
            sm.abschliessen()


# ══════════════════════════════════════════════════════════════════════════
# 3. Callbacks — on_enter / on_exit fire exactly once
# ══════════════════════════════════════════════════════════════════════════


class TestCallbackInvocation:
    """Every transition fires exactly one on_exit(from) and one on_enter(to)."""

    def test_single_transition_fires_two_callbacks(self):
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        assert len(sm._callback_calls) == 2
        # First: exit geplant, Second: enter zugewiesen
        assert sm._callback_calls[0]["kind"] == "exit"
        assert sm._callback_calls[0]["state"] == "geplant"
        assert sm._callback_calls[1]["kind"] == "entry"
        assert sm._callback_calls[1]["state"] == "zugewiesen"

    def test_full_lifecycle_callback_counts(self):
        """7 transitions = 14 callbacks (1 exit + 1 entry each)."""
        sm = make_sm("geplant")
        triggers = [
            "fahrer_zuweisen",
            "losfahren",
            "ankunft_melden",
            "patient_aufnehmen",
            "fahrt_beginnen",
            "patient_absetzen",
            "abschliessen",
        ]
        _transition_chain(sm, triggers)
        # 7 transitions × 2 callbacks = 14
        assert len(sm._callback_calls) == 14

    def test_stornieren_fires_entry_callback(self):
        sm = make_sm("geplant")
        sm.stornieren()
        assert any(
            c["kind"] == "entry" and c["state"] == "storniert"
            for c in sm._callback_calls
        )

    def test_no_duplicate_callbacks_on_internal_actions(self):
        """Callbacks fire exactly once per transition, never duplicated."""
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        # Count entry/exit for each state
        entry_counts: dict[str, int] = {}
        exit_counts: dict[str, int] = {}
        for call in sm._callback_calls:
            if call["kind"] == "entry":
                entry_counts[call["state"]] = entry_counts.get(call["state"], 0) + 1
            else:
                exit_counts[call["state"]] = exit_counts.get(call["state"], 0) + 1

        # Each state in the path should be entered at most once
        for state, count in entry_counts.items():
            assert count == 1, f"state {state} entered {count} times, expected 1"
        for state, count in exit_counts.items():
            assert count == 1, f"state {state} exited {count} times, expected 1"


# ══════════════════════════════════════════════════════════════════════════
# 4. Event logging
# ══════════════════════════════════════════════════════════════════════════


class TestEventLogging:
    """Every state change produces a log entry with correct fields."""

    def test_geplant_to_zugewiesen_creates_event(self):
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        assert len(sm._event_log) == 1
        _assert_event(sm._event_log[0], "geplant", "zugewiesen", "fahrer_zuweisen")

    def test_full_lifecycle_creates_seven_events(self):
        sm = make_sm("geplant")
        triggers = [
            "fahrer_zuweisen",
            "losfahren",
            "ankunft_melden",
            "patient_aufnehmen",
            "fahrt_beginnen",
            "patient_absetzen",
            "abschliessen",
        ]
        _transition_chain(sm, triggers)
        assert len(sm._event_log) == 7

    def test_stornieren_creates_event(self):
        sm = make_sm("zugewiesen")
        sm.stornieren()
        assert len(sm._event_log) == 1
        _assert_event(sm._event_log[0], "zugewiesen", "storniert", "stornieren")

    def test_event_timestamp_is_iso8601(self):
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        evt = sm._event_log[0]
        # Format: 2026-06-06T12:34:56.789012+00:00
        assert "T" in evt.timestamp
        assert "+" in evt.timestamp or evt.timestamp.endswith("Z")

    def test_event_has_trip_id(self):
        sm = make_sm("geplant", trip_id=7)
        sm.fahrer_zuweisen()
        assert sm._event_log[0].trip_id == 7

    def test_event_metadata_is_dict(self):
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        assert isinstance(sm._event_log[0].metadata, dict)


class TestExternalEventLogger:
    """The injectable event_logger callback is called on every transition."""

    def test_external_logger_called_on_transition(self):
        mock_logger = MagicMock()
        sm = TripStateMachine(MockTrip(status="geplant"), event_logger=mock_logger)
        sm.fahrer_zuweisen()
        mock_logger.assert_called_once()
        evt = mock_logger.call_args[0][0]
        assert isinstance(evt, StateChangeEvent)
        assert evt.from_state == "geplant"
        assert evt.to_state == "zugewiesen"

    def test_external_logger_called_on_every_transition(self):
        mock_logger = MagicMock()
        sm = TripStateMachine(MockTrip(status="geplant"), event_logger=mock_logger)
        triggers = [
            "fahrer_zuweisen",
            "losfahren",
            "ankunft_melden",
        ]
        _transition_chain(sm, triggers)
        assert mock_logger.call_count == 3

    def test_external_logger_called_on_stornieren(self):
        mock_logger = MagicMock()
        sm = TripStateMachine(MockTrip(status="zugewiesen"), event_logger=mock_logger)
        sm.stornieren()
        mock_logger.assert_called_once()
        evt = mock_logger.call_args[0][0]
        assert evt.to_state == "storniert"


# ══════════════════════════════════════════════════════════════════════════
# 5. Guard conditions
# ══════════════════════════════════════════════════════════════════════════


class TestGuardConditions:
    """Guards prevent invalid transitions."""

    def test_cannot_complete_unless_abgesetzt(self):
        """abschliessen only allowed from abgesetzt."""
        sm = make_sm("unterwegs")
        with pytest.raises(MachineError):
            sm.abschliessen()

    def test_cannot_transition_from_terminal(self):
        """Terminal states reject all transitions via _guard_not_terminal."""
        sm = make_sm("abgeschlossen")
        with pytest.raises(MachineError):
            sm.stornieren()
        with pytest.raises(MachineError):
            sm.problem_melden()
        with pytest.raises(MachineError):
            sm.fahrer_neu_zuweisen()


# ══════════════════════════════════════════════════════════════════════════
# 6. problem_loesen — restore previous state
# ══════════════════════════════════════════════════════════════════════════


class TestProblemLoesen:
    """problem_loesen returns to the state before problem_melden."""

    def test_problem_loesen_returns_to_zugewiesen(self):
        sm = make_sm("zugewiesen")
        sm.problem_melden()
        assert sm.state == "problem"
        sm.problem_loesen()
        assert sm.state == "zugewiesen"

    def test_problem_loesen_returns_to_anfahrt(self):
        sm = make_sm("anfahrt")
        sm.problem_melden()
        sm.problem_loesen()
        assert sm.state == "anfahrt"

    def test_problem_loesen_returns_to_unterwegs(self):
        sm = make_sm("unterwegs")
        sm.problem_melden()
        sm.problem_loesen()
        assert sm.state == "unterwegs"

    def test_problem_loesen_creates_event(self):
        sm = make_sm("anfahrt")
        sm.problem_melden()
        sm.problem_loesen()
        # Should have 2 events: problem_melden + problem_loesen
        # But problem_loesen is handled by _emit_event directly, not by
        # the transitions callback chain. Let's check:
        assert len(sm._event_log) >= 2
        # Find the problem_loesen event
        loesen_events = [e for e in sm._event_log if e.trigger == "problem_loesen"]
        assert len(loesen_events) == 1
        _assert_event(loesen_events[0], "problem", "anfahrt", "problem_loesen")

    def test_problem_loesen_without_problem_raises(self):
        sm = make_sm("geplant")
        with pytest.raises(RuntimeError, match="no previous state known"):
            sm.problem_loesen()

    def test_problem_loesen_then_problem_again(self):
        """After resolving, a new problem remembers the new source state."""
        sm = make_sm("zugewiesen")
        sm.losfahren()  # → anfahrt
        sm.problem_melden()  # → problem (save anfahrt)
        sm.problem_loesen()  # → anfahrt
        # Now trigger problem again — should save 'anfahrt' again
        sm.problem_melden()
        sm.problem_loesen()
        assert sm.state == "anfahrt"

    def test_problem_loesen_clears_pre_problem_state(self):
        sm = make_sm("anfahrt")
        sm.problem_melden()
        assert sm._pre_problem_state == "anfahrt"
        sm.problem_loesen()
        assert sm._pre_problem_state is None

    def test_problem_loesen_with_metadata(self):
        sm = make_sm("unterwegs")
        sm.problem_melden()
        sm.problem_loesen(metadata={"resolved_by": "driver_42", "note": "flat tire fixed"})
        loesen_events = [e for e in sm._event_log if e.trigger == "problem_loesen"]
        assert loesen_events[0].metadata == {
            "resolved_by": "driver_42",
            "note": "flat tire fixed",
        }


# ══════════════════════════════════════════════════════════════════════════
# 7. Available triggers — dynamic derivation
# ══════════════════════════════════════════════════════════════════════════


class TestAvailableTriggers:
    """available_triggers property returns correct triggers per state."""

    def test_geplant_available_triggers(self):
        sm = make_sm("geplant")
        assert "fahrer_zuweisen" in sm.available_triggers
        assert "stornieren" in sm.available_triggers
        assert "losfahren" not in sm.available_triggers

    def test_zugewiesen_available_triggers(self):
        sm = make_sm("zugewiesen")
        triggers = sm.available_triggers
        assert "losfahren" in triggers
        assert "problem_melden" in triggers
        assert "stornieren" in triggers
        assert "fahrer_neu_zuweisen" in triggers

    def test_abgesetzt_available_triggers(self):
        sm = make_sm("abgesetzt")
        triggers = sm.available_triggers
        assert "abschliessen" in triggers
        assert "problem_melden" in triggers
        assert "stornieren" not in triggers  # can't cancel once dropped off
        assert "losfahren" not in triggers

    def test_terminal_has_no_triggers(self):
        sm = make_sm("abgeschlossen")
        assert sm.available_triggers == []

        sm2 = make_sm("storniert")
        assert sm2.available_triggers == []

    def test_problem_available_triggers(self):
        sm = make_sm("problem")
        triggers = sm.available_triggers
        # problem has no outgoing transitions in TRIP_TRANSITIONS
        # (problem_loesen is a custom method, not a trigger)
        assert "problem_loesen" not in triggers
        assert "losfahren" not in triggers


# ══════════════════════════════════════════════════════════════════════════
# 8. Terminal state detection
# ══════════════════════════════════════════════════════════════════════════


class TestTerminalDetection:
    """is_terminal property correctly identifies terminal states."""

    @pytest.mark.parametrize("state", TERMINAL_STATES)
    def test_terminal_states(self, state):
        sm = make_sm(state)
        assert sm.is_terminal is True

    @pytest.mark.parametrize(
        "state",
        [
            "geplant",
            "zugewiesen",
            "anfahrt",
            "angekommen",
            "patient_an_bord",
            "unterwegs",
            "abgesetzt",
            "problem",
        ],
    )
    def test_non_terminal_states(self, state):
        sm = make_sm(state)
        assert sm.is_terminal is False


# ══════════════════════════════════════════════════════════════════════════
# 9. Full lifecycle walk-through
# ══════════════════════════════════════════════════════════════════════════


class TestFullLifecycle:
    """End-to-end: book → assign → drive → dropoff → complete."""

    def test_complete_happy_path(self):
        sm = make_sm("geplant")
        # geplant → zugewiesen
        sm.fahrer_zuweisen()
        assert sm.state == "zugewiesen"
        # zugewiesen → anfahrt
        sm.losfahren()
        assert sm.state == "anfahrt"
        # anfahrt → angekommen
        sm.ankunft_melden()
        assert sm.state == "angekommen"
        # angekommen → patient_an_bord
        sm.patient_aufnehmen()
        assert sm.state == "patient_an_bord"
        # patient_an_bord → unterwegs
        sm.fahrt_beginnen()
        assert sm.state == "unterwegs"
        # unterwegs → abgesetzt
        sm.patient_absetzen()
        assert sm.state == "abgesetzt"
        # abgesetzt → abgeschlossen
        sm.abschliessen()
        assert sm.state == "abgeschlossen"
        assert sm.is_terminal is True

    def test_geplant_to_storniert(self):
        sm = make_sm("geplant")
        sm.stornieren()
        assert sm.state == "storniert"
        assert sm.is_terminal is True

    def test_assign_drive_then_reassign(self):
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()  # → zugewiesen
        sm.losfahren()  # → anfahrt
        sm.fahrer_neu_zuweisen()  # → back to geplant
        assert sm.state == "geplant"

    def test_problem_during_transport_full_recovery(self):
        """Problem during transport → resolve → complete."""
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        sm.losfahren()
        sm.ankunft_melden()
        sm.patient_aufnehmen()
        sm.fahrt_beginnen()  # → unterwegs
        assert sm.state == "unterwegs"

        # Problem!
        sm.problem_melden()
        assert sm.state == "problem"
        assert sm._pre_problem_state == "unterwegs"

        # Resolve
        sm.problem_loesen(metadata={"note": "traffic cleared"})
        assert sm.state == "unterwegs"

        # Continue
        sm.patient_absetzen()
        sm.abschliessen()
        assert sm.state == "abgeschlossen"

    def test_multiple_problems_in_different_states(self):
        """Each problem remembers its own source state."""
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        # First problem
        sm.problem_melden()
        assert sm._pre_problem_state == "zugewiesen"
        sm.problem_loesen()
        assert sm.state == "zugewiesen"

        sm.losfahren()  # → anfahrt
        # Second problem
        sm.problem_melden()
        assert sm._pre_problem_state == "anfahrt"
        sm.problem_loesen()
        assert sm.state == "anfahrt"

    def test_event_log_completeness(self):
        """Every transition in a full lifecycle is logged."""
        sm = make_sm("geplant")
        triggers = [
            "fahrer_zuweisen",
            "losfahren",
            "ankunft_melden",
            "patient_aufnehmen",
            "fahrt_beginnen",
            "patient_absetzen",
            "abschliessen",
        ]
        _transition_chain(sm, triggers)
        # 7 triggers → 7 events
        assert len(sm._event_log) == 7
        expected_states = [
            ("geplant", "zugewiesen"),
            ("zugewiesen", "anfahrt"),
            ("anfahrt", "angekommen"),
            ("angekommen", "patient_an_bord"),
            ("patient_an_bord", "unterwegs"),
            ("unterwegs", "abgesetzt"),
            ("abgesetzt", "abgeschlossen"),
        ]
        for (frm, to), evt in zip(expected_states, sm._event_log):
            _assert_event(evt, frm, to, evt.trigger)


# ══════════════════════════════════════════════════════════════════════════
# 10. Edge cases & regression
# ══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Unusual but valid scenarios."""

    def test_reassign_after_arrival(self):
        """Can reassign driver even after arrival."""
        sm = make_sm("angekommen")
        sm.fahrer_neu_zuweisen()
        assert sm.state == "geplant"

    def test_double_reassign(self):
        """Assign → reassign → assign → reassign."""
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        sm.fahrer_neu_zuweisen()
        sm.fahrer_zuweisen()
        sm.fahrer_neu_zuweisen()
        assert sm.state == "geplant"

    def test_state_after_problem_is_still_problem(self):
        """After problem_melden, state is 'problem' until resolved."""
        sm = make_sm("anfahrt")
        sm.problem_melden()
        assert sm.state == "problem"
        # Can't drive while in problem state
        with pytest.raises(MachineError):
            sm.losfahren()
        with pytest.raises(MachineError):
            sm.ankunft_melden()

    def test_event_log_persists_across_sessions(self):
        """Event log accumulates across multiple state changes."""
        sm = make_sm("geplant")
        sm.fahrer_zuweisen()
        assert len(sm._event_log) == 1
        sm.losfahren()
        assert len(sm._event_log) == 2
        sm.stornieren()
        assert len(sm._event_log) == 3

    def test_machine_initial_state_respected(self):
        """Machine starts in the trip's actual status."""
        sm = make_sm("unterwegs")
        assert sm.state == "unterwegs"
        # Can only do things valid from unterwegs
        with pytest.raises(MachineError):
            sm.fahrer_zuweisen()
        sm.patient_absetzen()
        assert sm.state == "abgesetzt"
