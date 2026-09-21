"""Yawn detection tests -- validates the temporal YawnDetector state machine.

Tests that:
  - Short mouth openings (talking) do NOT trigger yawning
  - Genuine prolonged mouth openings DO trigger yawning
  - Yawn count increments exactly once per episode
  - State resets correctly after yawn ends
  - Multiple separate yawns are each counted once

Uses a simulated clock (fake_now) so tests run instantly without real sleep.

Run from the ai-service directory:
  python -m tests.test_yawn_detection

Or via pytest:
  pytest tests/test_yawn_detection.py -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.perception.mouth_state import YawnDetector
from src.temporal.temporal_analyzer import TemporalAnalyzer


# ----------------------------------------------------------------
# Simulated clock helpers
# ----------------------------------------------------------------

class FakeClock:
    """Monotonic clock whose value we control from the outside.

    Pass `clock.now` as the `time_fn` argument to YawnDetector.
    Advance simulated time with `clock.advance(seconds)`.
    """
    def __init__(self, start: float = 0.0):
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float):
        self._t += seconds


def make_detector_with_clock(clock: FakeClock) -> YawnDetector:
    """Create a YawnDetector backed by a controllable fake clock."""
    return YawnDetector(
        mar_threshold=0.60,
        min_duration=1.0,
        reset_duration=0.3,
        time_fn=clock.now,
    )


def feed_frames(detector: YawnDetector, clock: FakeClock,
                mar: float, duration: float, fps: float = 30.0):
    """Advance simulated time by `duration` seconds, feeding `mar` every frame.

    Returns list of result dicts from each frame.
    """
    frame_interval = 1.0 / fps
    frames = max(1, int(duration * fps))
    results = []
    for _ in range(frames):
        clock.advance(frame_interval)
        results.append(detector.update(mar))
    return results


def feed_and_count_yawns(sequence, fps: float = 30.0) -> tuple:
    """Run a sequence through YawnDetector + TemporalAnalyzer with a fake clock.

    Args:
        sequence: list of (mar, duration_seconds) tuples
        fps:      simulated frame rate

    Returns:
        (yawn_count, final_detector_state)
    """
    clock = FakeClock()
    detector = make_detector_with_clock(clock)
    temporal = TemporalAnalyzer()

    frame_interval = 1.0 / fps
    for mar, duration in sequence:
        frames = max(1, int(duration * fps))
        for _ in range(frames):
            clock.advance(frame_interval)
            result = detector.update(mar)
            temporal.update(eye_closed=False, yawning=result["yawning"])

    return temporal.yawn_count, detector.state


# ----------------------------------------------------------------
# TEST 1 -- MAR below threshold -> no yawn
# ----------------------------------------------------------------

def test_1_mar_below_threshold():
    """MAR below threshold at all times -> NO YAWN."""
    print("\n[TEST 1] MAR below threshold -> NO YAWN")
    clock = FakeClock()
    detector = make_detector_with_clock(clock)

    results = feed_frames(detector, clock, mar=0.45, duration=2.0)

    any_yawn = any(r["yawning"] for r in results)
    passed = not any_yawn
    print(f"  yawning at any point: {any_yawn}  (expected False)")
    print(f"  Final state: {detector.state}")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ----------------------------------------------------------------
# TEST 2 -- MAR above threshold for 0.2 sec -> no yawn
# ----------------------------------------------------------------

def test_2_short_opening_02s():
    """MAR above threshold for 0.2 s -> NO YAWN (talking behaviour)."""
    print("\n[TEST 2] MAR above threshold for 0.2 s -> NO YAWN")
    clock = FakeClock()
    detector = make_detector_with_clock(clock)

    feed_frames(detector, clock, mar=0.40, duration=0.5)    # below threshold
    results = feed_frames(detector, clock, mar=0.65, duration=0.2)  # above, 0.2 s
    feed_frames(detector, clock, mar=0.40, duration=0.5)    # below threshold

    any_yawn = any(r["yawning"] for r in results)
    passed = not any_yawn
    print(f"  yawning during open window: {any_yawn}  (expected False)")
    print(f"  Final state: {detector.state}")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ----------------------------------------------------------------
# TEST 3 -- MAR above threshold for 0.5 sec -> no yawn
# ----------------------------------------------------------------

def test_3_short_opening_05s():
    """MAR above threshold for 0.5 s -> NO YAWN (below min_duration=1.0)."""
    print("\n[TEST 3] MAR above threshold for 0.5 s -> NO YAWN")
    clock = FakeClock()
    detector = make_detector_with_clock(clock)

    feed_frames(detector, clock, mar=0.40, duration=0.3)
    results = feed_frames(detector, clock, mar=0.70, duration=0.5)
    feed_frames(detector, clock, mar=0.40, duration=0.5)

    any_yawn = any(r["yawning"] for r in results)
    passed = not any_yawn
    print(f"  yawning during 0.5 s window: {any_yawn}  (expected False)")
    print(f"  Final state: {detector.state}")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ----------------------------------------------------------------
# TEST 4 -- MAR above threshold for >= 1.0 sec -> YAWN
# ----------------------------------------------------------------

def test_4_long_opening_1s():
    """MAR above threshold for 1.2 s -> YAWN confirmed."""
    print("\n[TEST 4] MAR above threshold for 1.2 s -> YAWN")
    clock = FakeClock()
    detector = make_detector_with_clock(clock)

    feed_frames(detector, clock, mar=0.40, duration=0.3)
    results = feed_frames(detector, clock, mar=0.75, duration=1.2)
    feed_frames(detector, clock, mar=0.40, duration=0.5)

    yawn_occurred = any(r["yawning"] for r in results)
    passed = yawn_occurred
    print(f"  yawning occurred: {yawn_occurred}  (expected True)")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ----------------------------------------------------------------
# TEST 5 -- Yawn count = 1 for a 1.2 s opening
# ----------------------------------------------------------------

def test_5_yawn_count_is_1():
    """Mouth open 1.2 s -> yawn_count must be exactly 1."""
    print("\n[TEST 5] 1.2 s mouth opening -> yawn_count = 1")

    count, _ = feed_and_count_yawns([
        (0.40, 0.3),
        (0.75, 1.2),   # yawn
        (0.40, 0.6),   # mouth closes - episode ends
    ])

    passed = count == 1
    print(f"  yawn_count: {count}  (expected 1)")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ----------------------------------------------------------------
# TEST 6 -- Mouth open 3 seconds -> yawn_count = 1 (not multiple)
# ----------------------------------------------------------------

def test_6_mouth_open_3s_count_is_1():
    """Mouth remains open 3 s -> ONE yawn event, not multiple."""
    print("\n[TEST 6] Mouth open 3.0 s -> yawn_count = 1 (not multiple)")

    count, _ = feed_and_count_yawns([
        (0.40, 0.3),
        (0.80, 3.0),   # mouth open for 3 continuous seconds
        (0.40, 0.6),   # closes
    ])

    passed = count == 1
    print(f"  yawn_count: {count}  (expected 1)")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ----------------------------------------------------------------
# TEST 7 -- State resets after yawn
# ----------------------------------------------------------------

def test_7_state_resets_after_yawn():
    """After yawn episode ends (mouth closes), state returns to MOUTH_NORMAL."""
    print("\n[TEST 7] State resets to MOUTH_NORMAL after yawn closes")
    clock = FakeClock()
    detector = make_detector_with_clock(clock)

    feed_frames(detector, clock, mar=0.40, duration=0.3)
    feed_frames(detector, clock, mar=0.80, duration=1.2)   # yawn
    feed_frames(detector, clock, mar=0.40, duration=0.6)   # mouth closes > reset_duration

    passed = detector.state == YawnDetector.MOUTH_NORMAL
    print(f"  Final state: {detector.state}  (expected MOUTH_NORMAL)")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ----------------------------------------------------------------
# TEST 8 -- Second yawn after reset increments count by 1
# ----------------------------------------------------------------

def test_8_second_yawn_after_reset():
    """Two separate yawns -> yawn_count = 2."""
    print("\n[TEST 8] Two separate yawns -> yawn_count = 2")

    count, _ = feed_and_count_yawns([
        (0.40, 0.3),
        (0.80, 1.2),   # first yawn
        (0.40, 0.8),   # mouth closes (> reset_duration=0.3)
        (0.80, 1.2),   # second yawn
        (0.40, 0.6),   # closes
    ])

    passed = count == 2
    print(f"  yawn_count: {count}  (expected 2)")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ----------------------------------------------------------------
# TEST 9 -- Talking simulation (brief crossings, no yawn)
# ----------------------------------------------------------------

def test_9_talking_simulation():
    """Simulate talking: mouth crosses threshold briefly many times -> NO YAWN.

    Each 'syllable' raises MAR briefly (<= 0.2 s) then drops back.
    No single crossing stays above threshold for >= 1.0 s.
    """
    print("\n[TEST 9] Talking simulation (brief MAR spikes) -> NO YAWN")

    talking_pattern = [
        # (mar, duration_seconds)
        (0.45, 0.10), (0.62, 0.15), (0.50, 0.08),  # "hel-lo"
        (0.43, 0.12), (0.65, 0.12), (0.55, 0.10),  # "how"
        (0.48, 0.08), (0.60, 0.18), (0.47, 0.08),  # "are"
        (0.52, 0.10), (0.63, 0.20), (0.45, 0.10),  # "you"
        (0.42, 0.20),                                # pause
        (0.46, 0.10), (0.64, 0.15), (0.48, 0.10),  # "fine"
        (0.44, 0.10), (0.58, 0.12), (0.50, 0.08),  # "thanks"
        (0.43, 0.30),                                # longer pause
        (0.55, 0.15), (0.61, 0.18), (0.50, 0.10),  # "driv-ing"
        (0.40, 0.20),                                # rest
    ]

    count, final_state = feed_and_count_yawns(talking_pattern)

    passed = count == 0
    print(f"  yawn_count after talking: {count}  (expected 0)")
    print(f"  Final detector state: {final_state}  (expected MOUTH_NORMAL)")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


# ----------------------------------------------------------------
# TEST 10 -- Existing drowsiness classifier still correct
# ----------------------------------------------------------------

def test_10_drowsiness_classifier_unchanged():
    """Verify drowsiness classifier works correctly (yawning = supporting only)."""
    print("\n[TEST 10] Drowsiness classifier unaffected by yawn improvements")

    from src.classifiers.drowsiness_classifier import classify_drowsiness

    cases = [
        (False, 0.0, 5.0,  False, "NORMAL"),
        (True,  2.0, 10.0, False, "DROWSY"),
        (True,  4.0, 15.0, False, "MICROSLEEP"),
        (True,  0.5, 5.0,  False, "NORMAL"),
        (False, 0.0, 5.0,  True,  "NORMAL"),  # yawning alone -> still NORMAL
    ]

    all_pass = True
    for eye_closed, duration, perclos, yawning, expected in cases:
        result = classify_drowsiness(eye_closed, duration, perclos, yawning)
        ok = result["state"] == expected
        all_pass = all_pass and ok
        print(f"  eye={eye_closed} dur={duration} yawn={yawning} -> "
              f"{result['state']} (expected {expected}) [{'PASS' if ok else 'FAIL'}]")

    return all_pass


# ----------------------------------------------------------------
# Runner
# ----------------------------------------------------------------

def run_all_tests():
    print("=" * 60)
    print("SmartDrive Guardian -- Yawn Detection Tests")
    print("YawnDetector: temporal state machine (simulated clock)")
    print("=" * 60)

    test_fns = [
        test_1_mar_below_threshold,
        test_2_short_opening_02s,
        test_3_short_opening_05s,
        test_4_long_opening_1s,
        test_5_yawn_count_is_1,
        test_6_mouth_open_3s_count_is_1,
        test_7_state_resets_after_yawn,
        test_8_second_yawn_after_reset,
        test_9_talking_simulation,
        test_10_drowsiness_classifier_unchanged,
    ]

    results = []
    for fn in test_fns:
        try:
            passed = fn()
        except Exception as e:
            import traceback
            print(f"  EXCEPTION: {e}")
            traceback.print_exc()
            passed = False
        results.append((fn.__name__, passed))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    print(f"\n  {passed_count}/{total} tests passed")

    if passed_count == total:
        print("\n  ALL YAWN DETECTION TESTS PASSED")
    else:
        print("\n  SOME TESTS FAILED -- check output above")

    return passed_count == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
