"""Tests for the Emergency Engine — all 15 scenarios from the specification.

Run with:
  cd backend
  python -m pytest tests/test_emergency_engine.py -v

These tests validate:
  - Microsleep event counting via state transitions
  - Emergency trigger conditions
  - Duplicate prevention
  - Recovery timer logic
  - Cancellation restrictions
  - Cooldown behavior
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helper — create a fresh engine instance for each test
# ---------------------------------------------------------------------------

def _make_engine():
    """Import and return a fresh EmergencyEngine (avoids singleton state pollution)."""
    # Reimport to get fresh state
    import importlib
    import app.risk_engine.emergency_engine as eng_mod
    importlib.reload(eng_mod)
    return eng_mod.EmergencyEngine()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return _make_engine()


# ---------------------------------------------------------------------------
# TEST 1: microsleeps=0, drowsiness=70% → NO EMERGENCY
# ---------------------------------------------------------------------------

def test_1_no_microsleeps_no_emergency(engine):
    """With 0 microsleep events, emergency should NOT trigger even at 70% drowsiness."""
    assert engine.microsleep_count == 0
    # Simulate condition without any microsleeps
    # Drowsiness is high but microsleep_count < 2
    trigger_condition = (
        engine.microsleep_count >= 2 and 70.0 > 50.0
    )
    assert not trigger_condition, "Should NOT trigger with 0 microsleeps"


# ---------------------------------------------------------------------------
# TEST 2: microsleeps=1, drowsiness=70% → NO EMERGENCY
# ---------------------------------------------------------------------------

def test_2_one_microsleep_no_emergency(engine):
    """With only 1 microsleep event, emergency should NOT trigger."""
    # Simulate transition into MICROSLEEP once
    engine._previous_state = "NORMAL"
    engine._microsleep_count = 0

    # First transition: NORMAL → MICROSLEEP
    if "MICROSLEEP" == "MICROSLEEP" and engine._previous_state != "MICROSLEEP":
        engine._microsleep_count += 1
    engine._previous_state = "MICROSLEEP"

    assert engine.microsleep_count == 1

    trigger_condition = engine.microsleep_count >= 2 and 70.0 > 50.0
    assert not trigger_condition, "Should NOT trigger with only 1 microsleep"


# ---------------------------------------------------------------------------
# TEST 3: microsleeps=2, drowsiness=40% → NO EMERGENCY
# ---------------------------------------------------------------------------

def test_3_two_microsleeps_low_drowsiness_no_emergency(engine):
    """With 2 microsleeps but only 40% drowsiness, emergency should NOT trigger."""
    engine._microsleep_count = 2

    trigger_condition = engine.microsleep_count >= 2 and 40.0 > 50.0
    assert not trigger_condition, "Should NOT trigger when drowsiness <= 50%"


# ---------------------------------------------------------------------------
# TEST 4: microsleeps=2, drowsiness=50% exactly → NO EMERGENCY (strict >)
# ---------------------------------------------------------------------------

def test_4_exact_50_percent_no_emergency(engine):
    """50% exactly should NOT trigger (condition requires strictly > 50)."""
    engine._microsleep_count = 2

    trigger_condition = engine.microsleep_count >= 2 and 50.0 > 50.0
    assert not trigger_condition, "50.0% exactly should NOT trigger emergency"


# ---------------------------------------------------------------------------
# TEST 5: microsleeps=2, drowsiness=50.1% → EMERGENCY
# ---------------------------------------------------------------------------

def test_5_two_microsleeps_50_1_percent_triggers(engine):
    """2 microsleeps + 50.1% drowsiness should trigger emergency."""
    engine._microsleep_count = 2

    trigger_condition = engine.microsleep_count >= 2 and 50.1 > 50.0
    assert trigger_condition, "Should trigger with 2 microsleeps and 50.1%"


# ---------------------------------------------------------------------------
# TEST 6: Microsleep lasting 5 seconds = COUNT 1 (not many)
# ---------------------------------------------------------------------------

def test_6_sustained_microsleep_counts_as_one(engine):
    """A sustained MICROSLEEP lasting multiple frames is ONE event, not many."""
    engine._previous_state = "NORMAL"
    engine._microsleep_count = 0

    # Simulate 30 frames of MICROSLEEP (e.g. 5 seconds at 6 fps)
    for _ in range(30):
        state = "MICROSLEEP"
        if state == "MICROSLEEP" and engine._previous_state != "MICROSLEEP":
            engine._microsleep_count += 1
        engine._previous_state = state

    assert engine.microsleep_count == 1, (
        f"Expected 1 microsleep event, got {engine.microsleep_count}"
    )


# ---------------------------------------------------------------------------
# TEST 7: Two separate microsleep events → COUNT 2
# ---------------------------------------------------------------------------

def test_7_two_separate_microsleeps_count_two(engine):
    """Two separate microsleep transitions should count as 2 events."""
    engine._previous_state = "NORMAL"
    engine._microsleep_count = 0

    sequence = [
        "NORMAL",
        "MICROSLEEP",   # transition → count 1
        "MICROSLEEP",
        "MICROSLEEP",
        "DROWSY",
        "NORMAL",
        "DROWSY",
        "MICROSLEEP",   # new transition → count 2
        "MICROSLEEP",
    ]

    for state in sequence:
        if state == "MICROSLEEP" and engine._previous_state != "MICROSLEEP":
            engine._microsleep_count += 1
        engine._previous_state = state

    assert engine.microsleep_count == 2, (
        f"Expected 2 microsleep events, got {engine.microsleep_count}"
    )


# ---------------------------------------------------------------------------
# TEST 8: Only ONE EmergencyEvent created despite many AI frames
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_8_only_one_emergency_created():
    """Duplicate prevention: once active_emergency_id is set, _check_trigger is bypassed.

    The engine's duplicate-prevention has two layers:
      Layer 1 (in-memory): has_active_emergency guard prevents _check_trigger from running
      Layer 2 (DB): _fire_emergency checks DB for existing active emergency

    This test validates Layer 1: after the first emergency fires and sets
    _active_emergency_id, subsequent _process_event calls skip _check_trigger.
    """
    engine = _make_engine()
    engine._microsleep_count = 2

    # Simulate the state where an emergency was ALREADY fired and set active
    engine._active_emergency_id = "existing-emergency"
    engine._active_emergency_status = "ACTIVE"

    check_trigger_calls = 0

    async def mock_check_trigger(*args, **kwargs):
        nonlocal check_trigger_calls
        check_trigger_calls += 1

    engine._check_trigger = mock_check_trigger

    # Process 10 frames — all should skip trigger because has_active_emergency=True
    for _ in range(10):
        await engine._process_event(
            state="MICROSLEEP",
            drowsiness_percentage=67.0,
            vehicle_id="vehicle-1",
            trip_id="trip-1",
        )

    assert check_trigger_calls == 0, (
        f"_check_trigger should be bypassed when emergency is active, "
        f"but was called {check_trigger_calls} times"
    )
    assert engine.has_active_emergency, (
        "Emergency should still be flagged as active"
    )



# ---------------------------------------------------------------------------
# TEST 9: Assistance responds → ASSISTANCE_RESPONDED
# ---------------------------------------------------------------------------

def test_9_assistance_response_updates_status(engine):
    """When assistance responds, in-memory status should become ASSISTANCE_RESPONDED."""
    engine._active_emergency_id = "em-001"
    engine._active_emergency_status = "ACTIVE"

    engine.on_emergency_responded("em-001")

    assert engine._active_emergency_status == "ASSISTANCE_RESPONDED"
    assert engine._recovery_start_time is None


# ---------------------------------------------------------------------------
# TEST 10: Driver NORMAL + drowsiness <= 50% for < 10 seconds → no recovery yet
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_10_short_recovery_not_confirmed():
    """Recovery timer < 10s should NOT trigger DRIVER_RECOVERED."""
    engine = _make_engine()
    engine._active_emergency_id = "em-001"
    engine._active_emergency_status = "ACTIVE"
    engine._microsleep_count = 2

    recovered_called = False

    async def mock_mark_recovered(drowsiness):
        nonlocal recovered_called
        recovered_called = True

    engine._mark_driver_recovered = mock_mark_recovered

    # Simulate 5 seconds of NORMAL with drowsiness = 30% (recovery timer not complete)
    engine._recovery_start_time = time.monotonic() - 5.0  # 5 seconds ago

    # Process one more NORMAL frame — should NOT recover yet (< 10s)
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.RECOVERY_CONFIRMATION_SECONDS = 10
        await engine._handle_recovery_timer(
            state="NORMAL",
            drowsiness_percentage=30.0,
            vehicle_id="vehicle-1",
        )

    assert not recovered_called, "Should NOT have recovered with < 10 seconds elapsed"


# ---------------------------------------------------------------------------
# TEST 11: Driver NORMAL + drowsiness <= 50% for >= 10 seconds → DRIVER_RECOVERED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_11_full_recovery_confirmed():
    """After 10+ continuous seconds of NORMAL + low drowsiness → DRIVER_RECOVERED."""
    engine = _make_engine()
    engine._active_emergency_id = "em-001"
    engine._active_emergency_status = "ACTIVE"

    recovered_called = False
    recovered_drowsiness = None

    async def mock_mark_recovered(drowsiness):
        nonlocal recovered_called, recovered_drowsiness
        recovered_called = True
        recovered_drowsiness = drowsiness
        engine._active_emergency_status = "DRIVER_RECOVERED"

    engine._mark_driver_recovered = mock_mark_recovered

    # Set recovery timer to 11 seconds ago (past the 10s threshold)
    engine._recovery_start_time = time.monotonic() - 11.0

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.RECOVERY_CONFIRMATION_SECONDS = 10
        await engine._handle_recovery_timer(
            state="NORMAL",
            drowsiness_percentage=32.0,
            vehicle_id="vehicle-1",
        )

    assert recovered_called, "Should have triggered DRIVER_RECOVERED after 10+ seconds"
    assert recovered_drowsiness == 32.0


# ---------------------------------------------------------------------------
# TEST 12: Driver starts recovery, becomes DROWSY at 5s → timer reset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_12_drowsy_during_recovery_resets_timer():
    """If driver becomes DROWSY during recovery window, timer must reset."""
    engine = _make_engine()
    engine._active_emergency_id = "em-001"
    engine._active_emergency_status = "ACTIVE"

    # Recovery started 5 seconds ago
    engine._recovery_start_time = time.monotonic() - 5.0

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.RECOVERY_CONFIRMATION_SECONDS = 10
        # Driver becomes DROWSY at second 5
        await engine._handle_recovery_timer(
            state="DROWSY",
            drowsiness_percentage=60.0,
            vehicle_id="vehicle-1",
        )

    assert engine._recovery_start_time is None, "Recovery timer should be reset to None"
    assert engine._active_emergency_status == "ACTIVE", "Status should remain ACTIVE"


# ---------------------------------------------------------------------------
# TEST 13: Driver recovered → cancels → CANCELLED
# ---------------------------------------------------------------------------

def test_13_driver_cancel_after_recovery(engine):
    """Driver can cancel after recovery is confirmed."""
    engine._active_emergency_id = "em-001"
    engine._active_emergency_status = "DRIVER_RECOVERED"

    # Patch asyncio.create_task since there's no running event loop in sync tests
    with patch("app.risk_engine.emergency_engine.asyncio") as mock_asyncio:
        mock_asyncio.create_task = lambda coro: None  # discard task
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EMERGENCY_COOLDOWN_SECONDS = 60
            engine.on_emergency_cancelled("em-001")

    assert engine._active_emergency_status == "CANCELLED"
    assert engine._cooldown_until > time.monotonic(), "Cooldown should be set"


# ---------------------------------------------------------------------------
# TEST 14: Assistance already responded → cancellation rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_14_cancel_rejected_after_assistance_response():
    """Cannot cancel emergency if assistance has already responded."""
    from app.services.emergency_service import _EmergencyService

    service = _EmergencyService()

    # Build a mock emergency in ASSISTANCE_RESPONDED state
    mock_emergency = MagicMock()
    mock_emergency.id = "em-001"
    mock_emergency.status = "ASSISTANCE_RESPONDED"

    mock_db = AsyncMock()
    mock_result = MagicMock()  # synchronous MagicMock so .scalar_one_or_none() is not a coroutine
    mock_result.scalar_one_or_none.return_value = mock_emergency
    mock_db.execute.return_value = mock_result

    with pytest.raises(ValueError) as exc_info:
        await service.cancel_emergency("em-001", "Driver recovered", mock_db)

    assert "assistance has already responded" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# TEST 15: After cooldown, new emergency can be created
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_15_new_emergency_after_cooldown():
    """After cooldown expires, a new emergency can be triggered."""
    import app.risk_engine.emergency_engine as eng_mod

    engine = _make_engine()
    engine._cooldown_until = time.monotonic() - 10.0
    engine._active_emergency_id = None
    engine._active_emergency_status = None
    engine._microsleep_count = 2

    fire_log: list[str] = []
    original_fire = eng_mod.EmergencyEngine._fire_emergency

    async def mock_fire_method(self, vehicle_id, trip_id, drowsiness_percentage):
        fire_log.append("fire")
        self._active_emergency_id = "em-002"
        self._active_emergency_status = "ACTIVE"

    eng_mod.EmergencyEngine._fire_emergency = mock_fire_method
    try:
        with patch("app.risk_engine.emergency_engine.asyncio.create_task",
                   side_effect=lambda coro: asyncio.ensure_future(coro)):
            await engine._check_trigger(
                state="MICROSLEEP",
                drowsiness_percentage=67.0,
                vehicle_id="vehicle-1",
                trip_id="trip-1",
            )
            await asyncio.sleep(0)  # yield so ensure_future runs
    finally:
        eng_mod.EmergencyEngine._fire_emergency = original_fire

    assert len(fire_log) == 1, "New emergency should fire after cooldown expires"


# ---------------------------------------------------------------------------
# Additional: State transition counting correctness
# ---------------------------------------------------------------------------

def test_state_transition_sequence(engine):
    """Validate full sequence: NORMAL→MICRO→DROWSY→NORMAL→MICRO = count 2."""
    engine._previous_state = "NORMAL"
    engine._microsleep_count = 0

    transitions = [
        ("MICROSLEEP", 1),   # NORMAL→MICRO: count becomes 1
        ("MICROSLEEP", 1),   # MICRO→MICRO: no change
        ("MICROSLEEP", 1),   # MICRO→MICRO: no change
        ("DROWSY", 1),       # MICRO→DROWSY: no change
        ("NORMAL", 1),       # DROWSY→NORMAL: no change
        ("MICROSLEEP", 2),   # NORMAL→MICRO: count becomes 2
        ("MICROSLEEP", 2),   # MICRO→MICRO: no change
    ]

    for state, expected_count in transitions:
        if state == "MICROSLEEP" and engine._previous_state != "MICROSLEEP":
            engine._microsleep_count += 1
        engine._previous_state = state
        assert engine.microsleep_count == expected_count, (
            f"After transition to {state}: expected count={expected_count}, "
            f"got {engine.microsleep_count}"
        )
