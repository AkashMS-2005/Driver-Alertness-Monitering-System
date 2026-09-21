# SMARTDRIVE GUARDIAN — PROJECT & WORK DOCUMENTATION

**Project Name:** SmartDrive Guardian (Driver Alertness Monitoring System — DAMS)  
**Date:** September 21, 2026  
**Repository:** `D:\DAMS\Driver-Alertness-Monitering-System`  

---

## 1. Executive Summary

Today's primary objective was to **restore the complete, unified SmartDrive Guardian web application** and **fix the oversized camera feed layout** while strictly preserving the backend architecture, AI pipeline, WebSockets, database models, and authentication system.

### Key Milestones Achieved:
1. **Camera Feed Sizing Fixed**: Eliminated fullscreen stretching and constrained the live camera inside a dedicated 16:9 card (~650–750px desktop width, `aspect-ratio: 16 / 9`, `object-fit: cover`, `border-radius: 12px`).
2. **Unified Navigation & Header**: Built a fixed top navigation bar with brand logo, quick tabs (**Dashboard**, **Trip Summary**, **Drowsiness History**, **Emergency**), logged-in owner details, vehicle plate number, and logout.
3. **Four Complete Dedicated Application Views**:
   - **Dashboard (Default)**: Controlled live camera, driver alertness status (`AWAKE`, `DROWSY`, `SLEEPING`), drowsiness percentage progress bar, active vehicle card, current trip summary, and live location mini-map.
   - **Trip Summary**: Complete trip telemetry (status, start time, elapsed duration, distance traveled, start/current coordinates) and a full interactive **Leaflet + OpenStreetMap** view with route polyline history.
   - **Drowsiness History**: Aggregate fatigue metrics (Total Events, Drowsy Warnings, Microsleep Alerts, Awake Recoveries) and an event log table displaying timestamp, status, description, and risk severity (`LOW`, `MEDIUM`, `HIGH`).
   - **Emergency Assistance**: Integrated `[ 🚨 REQUEST HIGHWAY ASSISTANCE ]` trigger calling the backend API, displaying reverse-geocoded place names, GPS coordinates, nearest toll plaza assistance with distance in km (labeled as static reference data), and owner WebSocket notification status.
4. **Zero Backend / AI Disruption**: Retained all existing FastAPI routes (`:8000`), AI perception pipeline (`:8001`), database schemas, and WebSocket channels (`/ws/drowsiness`).

---

## 2. End-to-End System Architecture

```
                    ┌──────────────────────────────┐
                    │   Driver Camera / Webcam     │
                    └──────────────┬───────────────┘
                                   │ Video Frames
                                   ▼
                    ┌──────────────────────────────┐
                    │      AI Service (:8001)      │
                    │  - MediaPipe Face Mesh       │
                    │  - Eye Aspect Ratio (EAR)    │
                    │  - Mouth Aspect Ratio (MAR)  │
                    │  - PERCLOS (60s window)      │
                    │  - State: NORMAL/DROWSY/     │
                    │           MICROSLEEP         │
                    └──────────────┬───────────────┘
                                   │ WebSocket (ws://127.0.0.1:8001/ws/ai)
                                   ▼
                    ┌──────────────────────────────┐
                    │     FastAPI Backend (:8000)  │
                    │  - State Machine / Risk Engine│
                    │  - SQLite Database (Async)   │
                    │  - Aggregation (/api/v1/...) │
                    │  - Emergency Dispatch API    │
                    │  - WebSocket Gateway         │
                    └──────────────┬───────────────┘
                                   │ WebSocket (/ws/drowsiness) & REST APIs
                                   ▼
                    ┌──────────────────────────────┐
                    │  Unified React Website (:5174│
                    │  - Dashboard                 │
                    │  - Trip Summary (Leaflet)    │
                    │  - Drowsiness History        │
                    │  - Emergency Assistance      │
                    └──────────────────────────────┘
```

---

## 3. Work Completed Today (Component Breakdown)

### 3.1 Live Camera Layout & Sizing Fix
- **Previous Issue**: The camera frame stretched across the screen, breaking the layout and pushing all dashboard metrics off the screen.
- **Solution Implemented**:
  - Encapsulated the camera inside a `.camera-card` with `aspect-ratio: 16 / 9`, `object-fit: cover`, and max-width bounded to `760px`.
  - Structured desktop layout in a two-column grid: Camera occupies ~60–65% row width, and Driver Safety card occupies ~35–40%.
  - Added live status indicators: `● LIVE` (green badge during active frame stream) and fallback indicator `○ DISCONNECTED`.

### 3.2 Top Unified Header & Navigation
- **Location**: `frontend/owner-dashboard/src/App.tsx` & `App.css`
- **Features**:
  - **Left**: Shield icon (`🛡️`), Application Name (*SmartDrive Guardian*), Subtitle (*Driver Alertness Monitoring System*).
  - **Center Navigation Tabs**:
    - `🏠 Dashboard`
    - `🗺️ Trip Summary`
    - `📋 Drowsiness History`
    - `🚨 Emergency`
  - **Right**: Authenticated Owner Name (`Akash MS`), Vehicle Number (`MH-01-AB-1234`), and `Logout` button.
  - **Mobile Menu**: Responsive hamburger toggle for mobile devices.

### 3.3 Dashboard Page (Default View)
- **Driver Status Card**: Real-time display mapping backend AI states:
  - `NORMAL` ➔ **AWAKE** (green)
  - `DROWSY` ➔ **DROWSY** (amber)
  - `MICROSLEEP` ➔ **SLEEPING** (pulsing red warning)
- **Drowsiness Percentage**: Clean numeric percentage with animated multi-colored progress bar based on PERCLOS.
- **Vehicle Information**: Dynamically populated plate number, make, model, and year.
- **Current Trip Card**: Displays trip status (`ACTIVE`), start time, elapsed duration, distance traveled in km, and destination.
- **Current Location Card**: Mini interactive Leaflet map displaying vehicle coordinates, speed in km/h, and GPS status (`Live GPS` / `Demo Location`).

### 3.4 Dedicated Trip Summary Page
- **Telemetry Metric Cards**: Trip Status, Start Time, Elapsed Driving Duration, Total Distance Traveled (km).
- **Full Interactive Map**:
  - Powered by Leaflet and OpenStreetMap tiles.
  - Renders Start Location marker, Current Position marker, and historical route polyline loaded from `/api/v1/locations/trip/{trip_id}`.
- **Waypoints & Telemetry**: Start and current coordinates, real-time speed, and GPS ping interval.

### 3.5 Dedicated Drowsiness History Page
- **Statistical Overview Cards**:
  - Total Safety Events
  - Drowsy Warnings
  - Microsleep Alerts
  - Awake Recoveries
- **Event Log Table**:
  - Displays actual `SafetyEvent` records fetched from the backend.
  - Columns: Timestamp (mono format), Status badge, Description / Duration, Severity Risk Tag (`LOW`, `MEDIUM`, `HIGH`).
  - Graceful empty state when no fatigue events are recorded.

### 3.6 Dedicated Emergency Assistance Page
- **Hero Action Card**: Prominent `[ 🚨 REQUEST HIGHWAY ASSISTANCE ]` button.
- **Workflow & API Integration**:
  - Dispatches `POST /api/v1/emergency/trigger`.
  - **Vehicle Location Card**: Displays reverse-geocoded place name (via OpenStreetMap Nominatim), latitude/longitude coordinates, and GPS source status.
  - **Nearest Assistance Card**: Calculates nearest toll plaza (e.g. *Kengeri Toll Plaza*, NICE Road, 13.9 km away) with static development reference data notice.
  - **Owner Notification Card**: Confirms WebSocket alert dispatch and indicates SMS service configuration state.

---

## 4. Source Files Modified

| File Path | Description of Changes |
|---|---|
| [`frontend/owner-dashboard/src/App.tsx`](file:///d:/DAMS/Driver-Alertness-Monitering-System/frontend/owner-dashboard/src/App.tsx) | Complete multi-view architecture: Top header, view switching, 16:9 camera feed, driver safety cards, full Leaflet map, drowsiness event table, emergency trigger flow, and JWT session handling. |
| [`frontend/owner-dashboard/src/App.css`](file:///d:/DAMS/Driver-Alertness-Monitering-System/frontend/owner-dashboard/src/App.css) | Dark automotive design system: 16:9 camera constraints, responsive grid layouts, status color tokens, progress bars, tables, and alert badges. |

---

## 5. API & WebSocket Reference

### Key Endpoints Used by Frontend:
- `POST /api/v1/owners/login` — Owner authentication and JWT generation.
- `POST /api/v1/owners/register` — Owner registration and account creation.
- `GET /api/v1/dashboard/state` — Aggregated snapshot of driver state, vehicle info, active trip, latest location, and recent safety events.
- `GET /api/v1/locations/trip/{trip_id}` — Historical GPS coordinates for route polyline mapping.
- `GET /api/v1/safety/events` — Recent drowsiness and safety event log.
- `POST /api/v1/emergency/trigger` — Trigger emergency workflow, find nearest toll plaza, and notify owner.
- `WS /ws/drowsiness` — Real-time stream of camera frames (`frame_b64`), PERCLOS, and alertness state.

---

## 6. How to Run All Services

### 1. Backend Server (FastAPI)
```powershell
cd "D:\DAMS\Driver-Alertness-Monitering-System\backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- **URL**: `http://localhost:8000`
- **Swagger Docs**: `http://localhost:8000/docs`

### 2. AI Perception Service (Python / MediaPipe)
```powershell
cd "D:\DAMS\Driver-Alertness-Monitering-System\ai-service"
python -m src.main
```
- **WebSocket Feed**: `ws://127.0.0.1:8001/ws/ai`

### 3. Unified Frontend (React + Vite)
```powershell
cd "D:\DAMS\Driver-Alertness-Monitering-System\frontend\owner-dashboard"
npm run dev
```
- **Website URL**: `http://localhost:5174`

---

## 7. Verification Summary

- **TypeScript / Vite Build**: Passed with `0` errors (`npm run build` executed in 547ms).
- **Backend Health Check**: Verified `GET /api/v1/dashboard/state` returning live vehicle and drowsiness data.
- **Emergency Trigger Test**: Tested `POST /api/v1/emergency/trigger`, successfully returning nearest toll assistance and WebSocket notification confirmation.
- **Frontend Server**: Actively running and serving assets at `http://localhost:5174`.
