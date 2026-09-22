# SmartDrive Guardian — Automatic Emergency Escalation & Assistance System
## Technical Architecture & Operational Documentation

---

## 1. System Overview

**SmartDrive Guardian** is an edge-to-cloud driver alertness monitoring and safety response platform. It monitors driver alertness in real time via computer vision, assesses fatigue risk through a centralized backend state machine, automatically escalates emergencies to highway assistance and fleet owners upon critical fatigue detection, and allows driver recovery and cancellation.

### End-to-End Pipeline Architecture

```
┌─────────────────────────┐
│     Driver Camera       │
│  (Webcam / In-Cabin)    │
└────────────┬────────────┘
             │ Frames (~30 FPS)
             ▼
┌────────────────────────────────────────────────────────┐
│             AI Service (Port 8001)                     │
│  • MediaPipe Face Mesh (468 landmarks)                 │
│  • Eye Aspect Ratio (EAR) & PERCLOS Calculation        │
│  • Classification: NORMAL / DROWSY / MICROSLEEP        │
└────────────┬───────────────────────────────────────────┘
             │ WebSocket Stream (/ws/ai)
             ▼
┌────────────────────────────────────────────────────────┐
│            Backend Server (Port 8000)                  │
│  • Risk Engine & State Machine                         │
│  • EmergencyEngine (Microsleep Transition Tracker)     │
│  • Haversine Toll Plaza Distance Calculation           │
│  • SQLite Database (EmergencyEvent & HighwayAssistance)│
│  • Broadcast Manager (/ws/owner/{id} & /ws/drowsiness) │
└────────────┬───────────────────────────────────────────┘
             │ WebSocket & REST API
             ▼
┌────────────────────────────────────────────────────────┐
│         Frontend Owner Dashboard (Port 5174)           │
│  • Real-time Face & EAR Telemetry                      │
│  • Live Interactive EmergencyAlertCard (3 states)      │
│  • 1-Click "Simulate Toll Response" Control            │
│  • Driver Recovery & Cancellation Modal                │
└────────────────────────────────────────────────────────┘
```

---

## 2. Emergency Escalation Logic

The emergency escalation logic is executed strictly on the **Backend** inside [`EmergencyEngine`](file:///d:/Akash%20M%20S%20project/Driver-Alertness-Monitering-System/backend/app/risk_engine/emergency_engine.py). The frontend never makes emergency trigger decisions.

### A. Automatic Trigger Conditions

An emergency is automatically triggered when **both** conditions are met:
1. **`microsleep_count >= 2`**: The driver has entered a microsleep event at least twice during the active trip.
2. **`drowsiness_percentage > 50%`**: PERCLOS drowsiness percentage is strictly greater than 50.0% (not `>=`).

### B. Event-Based State Transition Counting

To avoid duplicate triggers from consecutive video frames:
- The system only increments `microsleep_count` when there is an active state transition:
  $$\text{NORMAL / DROWSY} \longrightarrow \text{MICROSLEEP}$$
- Sustained frames in `MICROSLEEP` remain a single event.
- A new event requires the driver to exit `MICROSLEEP` and enter it again.

### C. Cooldown & Duplicate Prevention

- Only **one active emergency** can exist at any given time.
- After an emergency is resolved or cancelled, an `EMERGENCY_COOLDOWN_SECONDS = 60` period is enforced before any new emergency can be triggered.

---

## 3. State Machine & Recovery Workflow

```
   ┌──────────────────────────────────────────────────────────┐
   │                   NO_ACTIVE_EMERGENCY                    │
   └────────────────────────────┬─────────────────────────────┘
                                │ [microsleep >= 2 & PERCLOS > 50%]
                                ▼
   ┌──────────────────────────────────────────────────────────┐
   │                     EMERGENCY: ACTIVE                    │
   │  • Red alert on owner dashboard                          │
   │  • Highway assistance notified (nearest toll plaza)      │
   │  • Owner alerted via WebSocket                           │
   └─────────────┬──────────────────────────────┬─────────────┘
                 │                              │
 [Driver NORMAL  │                              │ [Assistance
  & PERCLOS ≤ 50%│                              │  responds]
  for 10s]       ▼                              ▼
   ┌───────────────────────────┐  ┌───────────────────────────┐
   │     DRIVER_RECOVERED      │  │   ASSISTANCE_RESPONDED    │
   │ • Amber alert on card     │  │ • Green alert on card     │
   │ • Cancel button unlocked  │  │ • Shows patrol ETA & msg  │
   │ • Assistance can still    │  │ • Driver cancel LOCKED    │
   │   respond                 │  └─────────────┬─────────────┘
   └──────┬─────────────┬──────┘                │
          │             │                       │
[Driver   │             │ [Assistance responds] │
 cancels] │             └───────────────────────┤
          ▼                                     ▼
   ┌───────────────┐                    ┌───────────────┐
   │   CANCELLED   │                    │   RESOLVED    │
   └──────┬────────┘                    └───────┬───────┘
          │                                     │
          └───────────────┬─────────────────────┘
                          │ [60-second cooldown expires]
                          ▼
   ┌──────────────────────────────────────────────────────────┐
   │                   NO_ACTIVE_EMERGENCY                    │
   └──────────────────────────────────────────────────────────┘
```

### A. Driver Recovery Criteria
- Driver state must be `NORMAL`.
- `drowsiness_percentage <= 50.0%`.
- Must remain continuously in this state for `RECOVERY_CONFIRMATION_SECONDS = 10`.
- If the driver lapses into `DROWSY` or `MICROSLEEP` during the 10-second window, the timer immediately resets to zero.

### B. Cancellation Rules
- Driver can only cancel if status is `DRIVER_RECOVERED`.
- If Highway Assistance has already responded (`ASSISTANCE_RESPONDED`), cancellation is **strictly locked** (returns HTTP 400 with message `"Cannot cancel emergency after highway assistance has responded"`).

---

## 4. Highway Assistance & Toll Plaza Dispatch

### A. Geographic Reference Data
The system stores authentic coordinates of major Indian National Highway toll plazas:

| Toll Plaza Name | Highway | Latitude | Longitude |
|---|---|---|---|
| **Kengeri Toll Plaza** | NICE Road | 12.9092 | 77.4820 |
| **Nelamangala Toll Plaza** | NH-48 (Bengaluru - Tumakuru) | 13.0995 | 77.3811 |
| **Attibele Toll Plaza** | NH-44 (Bengaluru - Hosur) | 12.7783 | 77.7711 |
| **Devanahalli Toll Plaza** | NH-44 (Airport Expressway) | 13.2450 | 77.7120 |
| **Sadahalli Toll Plaza** | NH-44 (Bengaluru - Hyderabad) | 13.2012 | 77.6745 |

### B. Nearest Unit Selection (Haversine Formula)

$$d = 2R \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta \phi}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\Delta \lambda}{2}\right)}\right)$$

Where $R = 6371\text{ km}$. The system evaluates the vehicle's last known GPS coordinates against the database to find the minimum distance.

---

## 5. REST API Reference

### 1. Get Dashboard State
- **URL**: `GET /api/v1/dashboard/state`
- **Response**:
```json
{
  "vehicle": { "id": "1d604a34-...", "plate_number": "MH-01-AB-1234" },
  "owner": { "id": "894fce4a-...", "name": "SmartDrive Owner" },
  "trip": { "id": "3ca10b5e-...", "status": "ACTIVE" },
  "location": { "latitude": 12.9716, "longitude": 77.5946, "gps_available": true }
}
```

### 2. Get Active Emergency
- **URL**: `GET /api/v1/emergency/active/{vehicle_id}`
- **Response (when active)**:
```json
{
  "active": true,
  "emergency": {
    "emergency_id": "bde4fc4b-...",
    "status": "ACTIVE",
    "microsleep_count": 2,
    "drowsiness_percentage": 68.5,
    "latitude": 12.9716,
    "longitude": 77.5946,
    "assistance_name": "Kengeri Toll Plaza (NICE Road)",
    "assistance_distance_km": 14.0,
    "triggered_at": "2026-09-22T10:30:53.127637Z"
  }
}
```

### 3. Simulate Toll / Assistance Response
- **URL**: `POST /api/v1/emergency/{emergency_id}/respond`
- **Request Body**:
```json
{
  "message": "Highway patrol unit dispatched from Kengeri Toll Plaza. ETA 8 mins."
}
```
- **Response**:
```json
{
  "success": true,
  "emergency_id": "bde4fc4b-...",
  "status": "ASSISTANCE_RESPONDED",
  "message": "Highway patrol unit dispatched from Kengeri Toll Plaza. ETA 8 mins.",
  "responded_at": "2026-09-22T10:32:00.000000Z"
}
```

### 4. Cancel Emergency
- **URL**: `POST /api/v1/emergency/{emergency_id}/cancel`
- **Request Body**:
```json
{
  "reason": "Driver recovered, rested, and cancelled emergency."
}
```
- **Response**:
```json
{
  "success": true,
  "status": "CANCELLED",
  "cancelled_at": "2026-09-22T10:35:00.000000Z"
}
```

---

## 6. Real-Time WebSocket Events

### Channel: `/ws/owner/{owner_id}`

| Event Type | Payload Fields | Purpose |
|---|---|---|
| `EMERGENCY_TRIGGERED` | `emergency_id`, `status`, `microsleep_count`, `drowsiness_percentage`, `assistance_name`, `assistance_distance_km`, `latitude`, `longitude` | Displays red EmergencyAlertCard on owner screen |
| `DRIVER_RECOVERED` | `emergency_id`, `status: "DRIVER_RECOVERED"`, `drowsiness_percentage`, `timestamp` | Switches card to amber, enables Cancel button |
| `ASSISTANCE_RESPONSE` | `emergency_id`, `status: "ASSISTANCE_RESPONDED"`, `message`, `responded_at` | Switches card to green, displays dispatch message |
| `EMERGENCY_CANCELLED` | `emergency_id`, `status: "CANCELLED"`, `reason`, `cancelled_at` | Closes card after 3 seconds |
| `EMERGENCY_RESOLVED` | `emergency_id`, `status: "RESOLVED"`, `timestamp` | Closes card after 5 seconds |

---

## 7. Database Models

### A. `EmergencyEvent` (`emergency_events`)

```python
class EmergencyEvent(Base):
    __tablename__ = "emergency_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("trips.id"))
    vehicle_id: Mapped[str] = mapped_column(String(36), ForeignKey("vehicles.id"))
    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("owners.id"), nullable=True)
    emergency_type: Mapped[str] = mapped_column(String(50))   # "AUTO_DROWSINESS" | "DRIVER_EMERGENCY"
    status: Mapped[str] = mapped_column(String(30))           # ACTIVE, DRIVER_RECOVERED, etc.
    trigger_source: Mapped[str] = mapped_column(String(20))   # "AUTO_DROWSINESS" | "MANUAL"
    description: Mapped[str | None] = mapped_column(Text)

    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    place_name: Mapped[str | None] = mapped_column(String(200))

    microsleep_count: Mapped[int | None] = mapped_column(Integer, default=0)
    drowsiness_percentage: Mapped[float | None] = mapped_column(Float, default=0.0)

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_message: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

### B. `HighwayAssistance` (`highway_assistances`)

```python
class HighwayAssistance(Base):
    __tablename__ = "highway_assistances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("trips.id"))
    vehicle_id: Mapped[str] = mapped_column(String(36), ForeignKey("vehicles.id"))
    emergency_id: Mapped[str | None] = mapped_column(String(36))
    assistance_type: Mapped[str] = mapped_column(String(30))
    assistance_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30))
    distance_km: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

---

## 8. How to Run the Complete Stack

### Terminal 1 — Backend (FastAPI + Uvicorn)
```powershell
cd "D:\Akash M S project\Driver-Alertness-Monitering-System\backend"
.\venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2 — AI Vision Pipeline
```powershell
cd "D:\Akash M S project\Driver-Alertness-Monitering-System\ai-service"
.\venv\Scripts\python -m src.main
```

### Terminal 3 — Owner Dashboard
```powershell
cd "D:\Akash M S project\Driver-Alertness-Monitering-System\frontend\owner-dashboard"
npm run dev
```
Open **`http://localhost:5174`** in your browser.

---

## 9. Automated Test Suites

All tests can be executed using the backend virtual environment:

```powershell
cd "D:\Akash M S project\Driver-Alertness-Monitering-System\backend"

# Run 16 dedicated EmergencyEngine unit tests
.\venv\Scripts\python -m pytest tests/test_emergency_engine.py -v

# Run Phase 4 Risk Engine & State Machine integration tests
.\venv\Scripts\python tests/test_phase4_risk_engine.py

# Run Phase 3 AI-to-Backend networking tests
.\venv\Scripts\python tests/test_phase3_networking.py
```
