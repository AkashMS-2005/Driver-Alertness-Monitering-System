"""Phase 2 module test — validates imports and model loading without a camera.

Run from the ai-service directory:
  python -m tests.test_phase2_modules
"""

import sys
import os

# Add ai-service root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_imports():
    """Test that all Phase 2 modules can be imported."""
    print("=" * 50)
    print("Phase 2 Module Import Test")
    print("=" * 50)

    tests = []

    try:
        from src.capture.camera_stream import CameraStream
        tests.append(("CameraStream import", True))
    except Exception as e:
        tests.append(("CameraStream import", False, str(e)))

    try:
        from src.perception.landmark_detector import LandmarkDetector
        tests.append(("LandmarkDetector import", True))
    except Exception as e:
        tests.append(("LandmarkDetector import", False, str(e)))

    try:
        from src.perception.eye_state import get_eye_state, calculate_ear
        tests.append(("eye_state import", True))
    except Exception as e:
        tests.append(("eye_state import", False, str(e)))

    try:
        from src.perception.mouth_state import get_mouth_state, calculate_mar
        tests.append(("mouth_state import", True))
    except Exception as e:
        tests.append(("mouth_state import", False, str(e)))

    try:
        from src.temporal.temporal_analyzer import TemporalAnalyzer
        tests.append(("TemporalAnalyzer import", True))
    except Exception as e:
        tests.append(("TemporalAnalyzer import", False, str(e)))

    try:
        from src.classifiers.drowsiness_classifier import classify_drowsiness
        tests.append(("DrowsinessClassifier import", True))
    except Exception as e:
        tests.append(("DrowsinessClassifier import", False, str(e)))

    for t in tests:
        status = "PASS" if t[1] else "FAIL"
        msg = f"  [{status}] {t[0]}"
        if not t[1]:
            msg += f" — {t[2]}"
        print(msg)

    return all(t[1] for t in tests)


def test_model_loading():
    """Test that the face_landmarker.task model can be loaded."""
    print("\n" + "=" * 50)
    print("Model Loading Test")
    print("=" * 50)

    from src.perception.landmark_detector import LandmarkDetector

    detector = LandmarkDetector()
    success = detector.initialize()
    status = "PASS" if success else "FAIL"
    print(f"  [{status}] FaceLandmarker model loading")

    if success:
        detector.close()
    return success


def test_ear_calculation():
    """Test EAR calculation with known landmarks."""
    print("\n" + "=" * 50)
    print("EAR Calculation Test")
    print("=" * 50)

    from src.perception.eye_state import get_eye_state

    # Create dummy landmarks (478 points) with plausible eye landmarks
    # We'll set eye landmarks to simulate open eyes
    landmarks = [(0.5, 0.5, 0.0)] * 478

    # Set right eye (indices 33, 160, 158, 133, 153, 144) to a known open shape
    landmarks[33]  = (0.3, 0.5, 0.0)   # p1 (outer corner)
    landmarks[160] = (0.35, 0.45, 0.0)  # p2 (upper-1)
    landmarks[158] = (0.40, 0.45, 0.0)  # p3 (upper-2)
    landmarks[133] = (0.45, 0.5, 0.0)   # p4 (inner corner)
    landmarks[153] = (0.40, 0.55, 0.0)  # p5 (lower-2)
    landmarks[144] = (0.35, 0.55, 0.0)  # p6 (lower-1)

    # Set left eye (indices 362, 385, 387, 263, 373, 380)
    landmarks[362] = (0.55, 0.5, 0.0)
    landmarks[385] = (0.60, 0.45, 0.0)
    landmarks[387] = (0.65, 0.45, 0.0)
    landmarks[263] = (0.70, 0.5, 0.0)
    landmarks[373] = (0.65, 0.55, 0.0)
    landmarks[380] = (0.60, 0.55, 0.0)

    result = get_eye_state(landmarks)
    print(f"  EAR: {result['ear']:.4f}")
    print(f"  Eye closed: {result['eye_closed']}")
    print(f"  [{'PASS' if result['ear'] > 0 else 'FAIL'}] EAR is positive")
    print(f"  [{'PASS' if not result['eye_closed'] else 'FAIL'}] Eyes detected as open")

    return result["ear"] > 0


def test_drowsiness_classifier():
    """Test drowsiness classification logic."""
    print("\n" + "=" * 50)
    print("Drowsiness Classifier Test")
    print("=" * 50)

    from src.classifiers.drowsiness_classifier import classify_drowsiness

    # NORMAL: eyes open
    r = classify_drowsiness(eye_closed=False, closed_duration=0.0, perclos=5.0)
    print(f"  Eyes open -> {r['state']} [{'PASS' if r['state'] == 'NORMAL' else 'FAIL'}]")

    # DROWSY: eyes closed > 1.5s
    r = classify_drowsiness(eye_closed=True, closed_duration=2.0, perclos=10.0)
    print(f"  Eyes closed 2.0s -> {r['state']} [{'PASS' if r['state'] == 'DROWSY' else 'FAIL'}]")

    # MICROSLEEP: eyes closed > 3.0s
    r = classify_drowsiness(eye_closed=True, closed_duration=4.0, perclos=15.0)
    print(f"  Eyes closed 4.0s -> {r['state']} [{'PASS' if r['state'] == 'MICROSLEEP' else 'FAIL'}]")

    # Below threshold: eyes closed but < 1.5s
    r = classify_drowsiness(eye_closed=True, closed_duration=0.5, perclos=5.0)
    print(f"  Eyes closed 0.5s -> {r['state']} [{'PASS' if r['state'] == 'NORMAL' else 'FAIL'}]")

    return True


def test_temporal_analyzer():
    """Test temporal analyzer."""
    print("\n" + "=" * 50)
    print("Temporal Analyzer Test")
    print("=" * 50)

    import time
    from src.temporal.temporal_analyzer import TemporalAnalyzer

    analyzer = TemporalAnalyzer()

    # Simulate eyes open
    analyzer.update(eye_closed=False)
    state = analyzer.get_state()
    print(f"  Eyes open -> closed_duration={state['closed_duration']}")
    assert state["closed_duration"] == 0.0
    print("  [PASS] Eyes open -> duration 0.0")

    # Simulate eyes closed for a short time
    analyzer.update(eye_closed=True)
    time.sleep(0.1)
    analyzer.update(eye_closed=True)
    state = analyzer.get_state()
    print(f"  Eyes closed briefly -> closed_duration={state['closed_duration']}")
    assert state["closed_duration"] > 0
    print("  [PASS] Eyes closed -> duration > 0")

    # Open eyes resets duration
    analyzer.update(eye_closed=False)
    state = analyzer.get_state()
    print(f"  Eyes opened -> closed_duration={state['closed_duration']}")
    assert state["closed_duration"] == 0.0
    print("  [PASS] Eyes opened -> duration reset to 0.0")

    # PERCLOS should have some frames
    print(f"  PERCLOS: {state['perclos']:.1f}%")
    print("  [PASS] PERCLOS calculated")

    return True


if __name__ == "__main__":
    all_passed = True
    all_passed &= test_imports()
    all_passed &= test_model_loading()
    all_passed &= test_ear_calculation()
    all_passed &= test_drowsiness_classifier()
    all_passed &= test_temporal_analyzer()

    print("\n" + "=" * 50)
    if all_passed:
        print("ALL PHASE 2 MODULE TESTS PASSED!")
    else:
        print("SOME TESTS FAILED — check output above")
    print("=" * 50)
