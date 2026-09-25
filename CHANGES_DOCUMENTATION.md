# SmartDrive Guardian — Final Fix Documentation & Change Log

**Project**: Driver Alertness Monitoring System (DAMS)  
**Date**: September 25, 2026  
**Version**: 2.0 Final Fix  
**Scope**: Multimodal Driver Monitoring + Head Pose Stability + Automatic 2-Microsleep Emergency + Toll Response Message Delivery + Persistent History

---

## 1. Executive Summary

This document provides a comprehensive record of all changes, refactorings, and bug fixes applied to the SmartDrive Guardian project. All changes were made strictly within the existing codebase architecture (FastAPI backend, MediaPipe AI service, SQLite database, and React frontends) without removing any internal AI calculations or replacing core components.

### Key Objectives Delivered:
1. **Head Pose Stability**: Eliminated false "DISTRACTED" alerts caused by small natural head movements or brief mirror glances using dead-zones, moving average temporal smoothing, neutral driving baseline calibration, and hysteresis.
2. **Owner Dashboard UI Cleanup**: Hidden research/debug metrics (**Alertness Score** and **Drowsiness %**) from the owner website while keeping all internal AI calculations active.
3. **Automatic 2-Microsleep Emergency**: Implemented strict edge-triggered counting (`microsleep_count = 2` triggers an automatic emergency; consecutive frames are ignored; no manual button click required).
4. **Highway/Toll Response Message**: `POST /api/v1/emergency/{emergency_id}/respond` stores the response in the SQLite database, keeps the status as `ASSISTANCE_RESPONDED`, and broadcasts the message via WebSocket to both the **Owner Dashboard** and the **Vehicle/Driver UI**.
5. **Persistent Emergency History**: History displays responded emergencies with Emergency ID, Status (`ASSISTANCE RESPONDED`), Microsleep Events (`>= 2`), Location, Coordinates, Nearest Assistance, Distance, Triggered time, and the Toll Response text box. All history records survive page refresh.

---

## 2. Summary of Modified Files

| # | Component | File Path | Type | Purpose |
|---|---|---|---|---|
| 1 | **AI Service** | `ai-service/src/config/thresholds.yaml` | Config | Added head pose deadzones, hysteresis limits, smoothing window, and durations. |
| 2 | **AI Service** | `ai-service/src/perception/head_pose.py` | Python | Refactored `HeadPoseTracker` with smoothing, baseline calibration, deadzone filtering, and hysteresis. |
| 3 | **AI Service** | `ai-service/src/main.py` | Python | Loaded new thresholds into `HeadPoseTracker` and updated WebSocket output. |
| 4 | **AI Service** | `ai-service/src/fusion/multimodal_fusion.py` | Python | Bounded head pose risk contribution so glances never trigger false drowsiness. |
| 5 | **Backend** | `backend/app/risk_engine/emergency_engine.py` | Python | Added edge-triggered microsleep counting, `TRIGGERING` re-entry guard, and state reset on response. |
| 6 | **Backend** | `backend/app/services/emergency_service.py` | Python | Added fallback vehicle/trip queries, `broadcast_to_all`, and removed auto-resolve to keep `ASSISTANCE_RESPONDED`. |
| 7 | **Backend** | `backend/app/risk_engine/state_machine.py` | Python | Resolved active DB vehicle and trip IDs instead of hard-coded `"vehicle-1"`. |
| 8 | **Backend** | `backend/app/api/v1/emergency_routes.py` | Python | Added `GET /api/v1/emergency/history` and `/history/all` endpoints; added `await db.commit()` in respond endpoint. |
| 9 | **Backend** | `backend/smartdrive.db` | SQLite | Resolved stale rows from prior debug sessions that were blocking new auto emergencies. |
| 10 | **Owner Dashboard** | `frontend/owner-dashboard/src/App.tsx` | React / TSX | Hid Alertness Score & Drowsiness %; simplified Head Pose to Normal/Distracted; updated Emergency History to Part 13 card format; auto-refreshes on response. |
| 11 | **Owner Dashboard** | `frontend/owner-dashboard/src/App.css` | CSS | Added styles for `.emergency-history-list`, `.emergency-history-card`, `.emg-hist-grid`, and `.emg-hist-response-box`. |
| 12 | **Driver Dashboard** | `frontend/driver-dashboard/src/App.tsx` | React / TSX | Added WebSocket listener for `ASSISTANCE_RESPONSE` and rendered highway assistance response banner. |

---

## 3. Detailed File-by-File Changes

### 3.1 `ai-service/src/config/thresholds.yaml`
**Added configurable stability thresholds for head pose tracking:**
```yaml
# Head Pose Distraction & Stability Thresholds
head_pose:
  # Dead-zone tolerances around neutral position (degrees)
  yaw_deadzone: 12.0
  pitch_deadzone: 10.0
  roll_deadzone: 10.0

  # Hysteresis Thresholds (enter > exit prevents flickering)
  enter_yaw_threshold: 30.0
  exit_yaw_threshold: 18.0
  enter_pitch_threshold: 22.0
  exit_pitch_threshold: 14.0
  enter_roll_threshold: 22.0
  exit_roll_threshold: 14.0

  # Temporal Durations (seconds)
  deviation_min_duration: 2.0    # Deviation must persist >= 2.0s to enter DISTRACTED
  exit_duration: 0.8             # Must stay in normal range >= 0.8s to exit DISTRACTED

  # Temporal Smoothing & Calibration
  smoothing_window_frames: 8     # Moving average window across consecutive frames
  calibration_frames: 30         # Neutral driving posture baseline calibration
```

---

### 3.2 `ai-service/src/perception/head_pose.py`
**Refactored `HeadPoseTracker` implementation:**
- **Temporal Smoothing**: Maintained rolling buffers (`_pitch_buf`, `_yaw_buf`, `_roll_buf`) over `smoothing_window_frames` (8 frames).
- **Baseline Neutral Pose Calibration**: First 30 frames calculate neutral pitch, yaw, and roll; gradual adaptive update prevents drift while preserving individual driver posture.
- **Dead-Zone Filtering**: Angular deviations within `±12°` yaw, `±10°` pitch, and `±10°` roll relative to neutral are clamped to `0.0`.
- **Hysteresis State Machine**:
  - Exceeding enter threshold (`> 30°` yaw, `> 22°` pitch/roll) starts the `_deviation_start` timer. Distraction is only triggered if deviation persists for `deviation_min_duration` (2.0s).
  - Returning below exit threshold (`<= 18°` yaw, `<= 14°` pitch/roll) for `exit_duration` (0.8s) transitions back to `NORMAL`.
- **Mirror Glances**: Normal glances (< 2.0s) remain classified as `NORMAL`.
- **Consistent Binary State**: Output `head_state` is strictly `"NORMAL"` or `"DISTRACTED"` (no flickering `DEVIATING` status shown on UI).

---

### 3.3 `ai-service/src/main.py`
- In `load_config()`, extracted all deadzone and hysteresis keys.
- Passed parameters to `HeadPoseTracker` instantiation.
- Streamed `head_state` in the real-time WebSocket JSON payload to backend and dashboards.

---

### 3.4 `ai-service/src/fusion/multimodal_fusion.py`
- In `_compute_head_risk()`, ensured normal head pose returns `0.0` risk, and bounded distracted risk to max `0.35–0.50`.
- In `_recommended_state()`, ensured head distraction alone **never** changes driver state to `DROWSY` or `MICROSLEEP`. Drowsiness detection strictly prioritizes EAR, eye closure, and PERCLOS.

---

### 3.5 `backend/app/risk_engine/emergency_engine.py`
- **Edge-Triggered Microsleep Counting**:
  ```python
  if state == "MICROSLEEP" and self._previous_state != "MICROSLEEP":
      self._microsleep_count += 1
  ```
  Continuous frames of `MICROSLEEP` do not increment the counter.
- **Race Condition Prevention**: Added `self._active_emergency_status = "TRIGGERING"` to immediately block consecutive high-FPS frames from firing duplicate emergency creation tasks.
- **Emergency Responded Handler**: Implemented `on_emergency_responded(emergency_id)` which clears `_active_emergency_id = None` so that the resolved/responded emergency moves to history.

---

### 3.6 `backend/app/services/emergency_service.py`
- **Dynamic Vehicle & Trip Fallback**: If `vehicle_id` or `trip_id` are fallback strings (`"vehicle-1"`, `"trip-1"`), query the database for the active registered vehicle and trip UUID to guarantee foreign key integrity.
- **Full WebSocket Broadcast**: Switched WebSocket broadcasts from `broadcast_to_all_owners` to `manager.broadcast_to_all` so that both the owner dashboard (`/ws/owner/{id}`) and the vehicle driver dashboard (`/ws/drowsiness`) receive `EMERGENCY_TRIGGERED` and `ASSISTANCE_RESPONSE`.
- **Preserved `ASSISTANCE_RESPONDED` Status**: Removed `_auto_resolve` from `respond_to_emergency()`. The emergency remains in `ASSISTANCE_RESPONDED` state in SQLite and in history.
- **Default Place Name**: Configured fallback location name `"Ashokanagar, Bengaluru"` if reverse geocoding is unavailable.

---

### 3.7 `backend/app/risk_engine/state_machine.py`
- Added `_resolve_vehicle_trip_ids()` helper to load real active vehicle and trip IDs from SQLite before creating safety events.

---

### 3.8 `backend/app/api/v1/emergency_routes.py`
- Added endpoints:
  - `GET /api/v1/emergency/history`
  - `GET /api/v1/emergency/history/all`
  Returns all emergencies ordered by `detected_at desc`, enriched with linked `HighwayAssistance` data (`assistance_name`, `assistance_distance_km`), `response_message`, and `microsleep_count`.
- Added `await db.commit()` in `POST /api/v1/emergency/{emergency_id}/respond` to ensure immediate database persistence.

---

### 3.9 `frontend/owner-dashboard/src/App.tsx`
- **UI Metric Cleanup (Part 2 & 18)**:
  - Removed Alertness Score (`77/100`) and Drowsiness % (`0%`) from `DriverSafetyCard`.
  - Removed Drowsiness % from `EmergencyAlertCard`.
  - Simplified Head Pose display to `✓ Normal` (green) or `⚠ DISTRACTED` (red).
- **Manual Emergency Button (Part 17)**:
  - Updated label to `🚨 REQUEST HIGHWAY ASSISTANCE (MANUAL DEMO)`.
- **Automatic History Refresh (Part 12 & 15)**:
  - Added `window.dispatchEvent(new Event('emergency_updated'))` upon receiving `ASSISTANCE_RESPONSE` or `EMERGENCY_TRIGGERED`.
  - `EmergencyAssistancePage` listens to this event and calls `loadHistory()` immediately.
- **Part 13 Emergency History Cards**:
  - Replaced the simple table with structured cards showing:
    - `Emergency #ID`
    - `Status: ASSISTANCE RESPONDED`
    - `Microsleep Events: 2` (or actual count >= 2)
    - `Location: Ashokanagar, Bengaluru`
    - `Coordinates: 12.971600, 77.594600`
    - `Nearest Assistance: Kengeri Toll Plaza`
    - `Distance: 14.0 km`
    - `Triggered: Time`
    - `Toll Response: "Emergency request received. Highway assistance team is responding to your location."`
    - `Responded: Time`

---

### 3.10 `frontend/owner-dashboard/src/App.css`
- Added styles for:
  - `.emergency-history-list`
  - `.emergency-history-card`
  - `.emg-hist-header`
  - `.emg-hist-grid`
  - `.emg-hist-response-box`
  - `.emg-hist-response-msg`

---

### 3.11 `frontend/driver-dashboard/src/App.tsx`
- Added `AssistanceResponseData` interface and state.
- In `ws.onmessage`, added handler for `ASSISTANCE_RESPONSE`.
- Rendered high-visibility banner above the main driver card:
  - Badge: `ASSISTANCE RESPONDED`
  - Title: `HIGHWAY ASSISTANCE RESPONSE`
  - Body: `"{message}"`
  - Timestamp of receipt.

---

## 4. Verification and Test Results

### 1. Backend 2-Microsleep & Toll Response Verification
Executed end-to-end integration test against `smartdrive.db`:
```text
=== TEST START: 2-Microsleep Auto-Emergency & Response Verification ===
[TEST] 1st microsleep start: count=1
[TEST] Consecutive frames: count=1 (no duplicate count)
[TEST] Driver recovered: count=1
[TEST] Triggering 2nd separate microsleep event...
[TEST] 2nd microsleep start: count=2
WARNING:smartdrive.emergency_service:AUTO EMERGENCY TRIGGERED — id=de201992-... vehicle=1d604a34-... microsleeps=2 drowsiness=88.0% nearest_toll=Kengeri Toll Plaza (NICE Road) (14.0km)
[TEST] Latest DB emergency: id=de201992-..., status=ACTIVE, microsleeps=2
[TEST] After toll response: id=de201992-..., status=ASSISTANCE_RESPONDED, response=Emergency request received. Highway assistance team is responding...
[TEST] Top history item: id=de201992-..., status=ASSISTANCE_RESPONDED, microsleeps=2
[TEST] Toll response in history: Emergency request received...
[TEST] Assistance name: Kengeri Toll Plaza (NICE Road), Distance: 13.96 km
=== ALL TEST ASSERTIONS PASSED SUCCESSFULLY! ===
```

### 2. Head Pose Stability & Deadzone Verification
Executed unit tests for angular tolerances, smoothing, and hysteresis:
```text
=== TEST START: Head Pose Stability & Dead-zone Verification ===
[TEST] Baseline calibrated: pitch=-1.00, yaw=1.00, roll=0.50
[TEST 1 PASSED] Small movements (yaw=5°, pitch=4°) remain NORMAL (deadzone works).
[TEST 2 PASSED] Quick left mirror glance remains NORMAL (< 2.0s).
[TEST 3 PASSED] Sustained deviation (> 2.0s) successfully triggered DISTRACTED.
[TEST 4 PASSED] Returned to NORMAL after driver faces forward (hysteresis works).
=== ALL HEAD POSE TESTS PASSED SUCCESSFULLY! ===
```

### 3. Frontend Typecheck
- Executed `npx tsc --noEmit` in `frontend/owner-dashboard`: **0 errors, clean build**.

---

## 5. Startup Commands

### Terminal 1: Backend Service (FastAPI)
```powershell
cd "A:\Major DAMS\Driver-Alertness-Monitering-System\backend"
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2: AI Perception Service
```powershell
cd "A:\Major DAMS\Driver-Alertness-Monitering-System\ai-service"
.\venv\Scripts\Activate.ps1
python -m src.main
```

### Terminal 3: Owner Dashboard (Active Frontend)
```powershell
cd "A:\Major DAMS\Driver-Alertness-Monitering-System\frontend\owner-dashboard"
npm run dev
```

---

## 6. Demonstration Steps

1. **Verify Head Pose Stability**:
   - Tilt head slightly left/right or up/down: UI shows `HEAD POSE: ✓ Normal`.
   - Glance at mirrors briefly (< 2 seconds): remains `✓ Normal`.
   - Turn head sideways and hold for > 2 seconds: transitions to `⚠ DISTRACTED`. Return head forward: smoothly returns to `✓ Normal`.
2. **Verify Clean Dashboard**:
   - Confirm Alertness Score and Drowsiness % are hidden from the dashboard.
   - Only Driver Status (`AWAKE` / `DROWSY` / `SLEEPING`), Head Pose, and Vehicle info are displayed.
3. **Trigger 1st Microsleep**:
   - Close eyes for 1.5–2s until state becomes `MICROSLEEP`.
   - Banner displays `Microsleep Events: 1`. No emergency is created.
4. **Recover**:
   - Open eyes. Driver state returns to `AWAKE`.
5. **Trigger 2nd Microsleep**:
   - Close eyes again for 1.5–2s.
   - Counter increments to `2`.
   - Red **EMERGENCY ACTIVE** card automatically appears with `Microsleep Events: 2`, `Status: SLEEPING`, and `Nearest Assistance: Kengeri Toll Plaza (14.0 km)`.
6. **Simulate Toll Response**:
   - Click `⚡ SIMULATE TOLL RESPONSE`.
   - Active emergency card disappears from the active section.
   - Connected driver client displays the highway assistance response banner.
7. **Verify Persistent History**:
   - Click the **Emergency** navigation tab.
   - Under **EMERGENCY HISTORY**, view the emergency record showing status `ASSISTANCE RESPONDED`, `Microsleep Events: 2`, and the full toll response message.
   - Refresh the browser (`F5`): the record persists from the SQLite database.
