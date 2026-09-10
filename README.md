# SmartDrive Guardian — Driver Alertness Monitoring System

SmartDrive Guardian is a real-time driver drowsiness monitoring system that utilizes computer vision to track Eye Aspect Ratio (EAR), Mouth Aspect Ratio (MAR), and Percentage of Eye Closure (PERCLOS) to detect drowsiness and microsleep events, process them through a backend Risk Engine, and stream live alerts, metrics, and safety events to both the Driver Dashboard and the Owner Dashboard.

---

## 🏛️ System Architecture

```text
[Laptop 1: AI Service]
  Webcam → MediaPipe FaceLandmarker → EAR / MAR / PERCLOS
  → Drowsiness Classifier (NORMAL / DROWSY / MICROSLEEP)
  → AI WebSocket Server (ws://0.0.0.0:8001/ws/ai)
           │
           ▼  (WebSocket LAN Stream)
[Laptop 2: Application Computer]
  FastAPI Backend (AI Client)
  → Risk Engine (SafetyStateMachine: NORMAL→LOW, DROWSY→MEDIUM, MICROSLEEP→HIGH)
  → Safety Events Persistence (State-transition logging to SQLite)
  → Backend WebSocket Gateway:
      ├─ ws://0.0.0.0:8000/ws/drowsiness  →  Driver Dashboard (Port 5173)
      └─ ws://0.0.0.0:8000/ws/owner/default → Owner Dashboard (Port 5174)
```

---

## 🔌 Network Ports & Endpoints

| Component | Port | Endpoint / URL | Purpose |
|---|---|---|---|
| **AI Service** (Laptop 1) | `8001` | `ws://<laptop1-ip>:8001/ws/ai` | Streams detection telemetry |
| **Backend API** (Laptop 2) | `8000` | `ws://<laptop2-ip>:8000/ws/drowsiness` | Driver WebSocket Gateway |
| **Backend API** (Laptop 2) | `8000` | `ws://<laptop2-ip>:8000/ws/owner/{id}` | Owner WebSocket Gateway |
| **Backend REST API** | `8000` | `http://<laptop2-ip>:8000/api/v1/safety/events` | Safety events query API |
| **Driver Dashboard** | `5173` | `http://localhost:5173` | Real-time Driver UI |
| **Owner Dashboard** | `5174` | `http://localhost:5174` | Executive / Fleet Safety UI |

---

## 🧠 Risk Engine & State Transitions

The Risk Engine (`SafetyStateMachine`) interprets the AI states and manages state transitions:

| AI State | Risk Level | Alert Message | Action / DB Event |
|---|---|---|---|
| `NORMAL` | `LOW` | *Driver Alert* | Normal monitoring; no alarm |
| `DROWSY` | `MEDIUM` | *Driver Attention Required* | Logs 1 `DROWSY` SafetyEvent; warning audio beep |
| `MICROSLEEP` | `HIGH` | *IMMEDIATE ATTENTION REQUIRED* | Logs 1 `MICROSLEEP` SafetyEvent; critical audio alarm |

> **Duplicate Prevention**: Events are only recorded upon state transitions (e.g. `NORMAL -> DROWSY`), preventing database and frontend alert spam during sustained states.

---

## 📦 Enriched Telemetry JSON Format

```json
{
  "type": "drowsiness_update",
  "timestamp": "2026-09-10T22:30:00.123456+00:00",
  "state": "DROWSY",
  "risk_level": "MEDIUM",
  "alert_message": "Driver Attention Required",
  "state_changed": true,
  "ear": 0.172,
  "eye_closed": true,
  "closed_duration": 1.82,
  "perclos": 14.5,
  "mar": 0.420,
  "yawning": false,
  "recent_events": [
    {
      "id": "a1b2c3d4",
      "timestamp": "2026-09-10T22:30:00.123456+00:00",
      "state": "DROWSY",
      "risk_level": "MEDIUM",
      "description": "Driver Attention Required"
    }
  ]
}
```

---

## 🚀 Installation & Prerequisites

### Required Environment
- **Python**: 3.10 to 3.13
- **Node.js**: v18+ & npm

### 1. Install AI Service Requirements
```powershell
cd ai-service
pip install -r requirements.txt
```

### 2. Install Backend Requirements
```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Install Frontend Dependencies
```powershell
# Driver Dashboard
cd frontend/driver-dashboard
npm install

# Owner Dashboard
cd ../owner-dashboard
npm install
```

---

## 🏃 How to Run

### Option A: Single Laptop (Development Mode)

#### Terminal 1 — Backend
```powershell
cd backend
.\venv\Scripts\activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### Terminal 2 — AI Service
```powershell
cd ai-service
python -m src.main
```

#### Terminal 3 — React Driver Dashboard (Port 5173)
```powershell
cd frontend/driver-dashboard
npm run dev
```

#### Terminal 4 — React Owner Dashboard (Port 5174)
```powershell
cd frontend/owner-dashboard
npm run dev
```

- **Driver Dashboard**: `http://localhost:5173`
- **Owner Dashboard**: `http://localhost:5174`

---

### Option B: Two Laptops (LAN Setup)

1. **Laptop 1 (AI Computer with Webcam)**:
   - Find LAN IP: `ipconfig` (e.g. `192.168.1.105`).
   - Run: `python -m src.main` in `ai-service/`.
2. **Laptop 2 (Application Computer)**:
   - Configure `backend/.env`:
     ```env
     AI_SERVER_HOST=192.168.1.105
     AI_SERVER_PORT=8001
     ```
   - Start backend: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
   - Start driver dashboard on port 5173: `npm run dev` in `frontend/driver-dashboard/`
   - Start owner dashboard on port 5174: `npm run dev` in `frontend/owner-dashboard/`
   - Access UI at `http://localhost:5173` and `http://localhost:5174`.

---

## 🧪 Automated Testing

### 1. Run Phase 2 Module Tests
```powershell
cd ai-service
python -m tests.test_phase2_modules
```

### 2. Run Phase 3 Networking Tests
```powershell
cd backend
.\venv\Scripts\python tests/test_phase3_networking.py
```

### 3. Run Phase 4 Risk Engine Tests
```powershell
cd backend
.\venv\Scripts\python tests/test_phase4_risk_engine.py
```

---

## 🖥️ Expected Dashboard Verification Flow

1. **Normal Driving**:
   - Eyes open → Card shows **NORMAL** (Green, Risk: **LOW**).
   - Driver metrics: EAR ~0.25–0.32, Eye Status: **OPEN**, Closed Duration: `0.00 s`.
   - Owner dashboard: Driver Status **NORMAL**, Risk **LOW**, Vehicle **ONLINE**.
2. **Drowsiness Trigger (~1.5s eyes closed or yawning)**:
   - Card transitions to **DROWSY** (Amber, Risk: **MEDIUM**).
   - "Recent Drowsiness Events" logs `DROWSY` with timestamp on both dashboards.
   - Audio beep sounds locally on Laptop 1.
3. **Microsleep Trigger (>3.0s eyes closed)**:
   - Card flashes **MICROSLEEP** (Red, Risk: **HIGH**).
   - "Recent Drowsiness Events" logs `MICROSLEEP` with timestamp on both dashboards.
   - Critical alarm sounds on Laptop 1.
4. **Recovery**:
   - Eyes opened → Instantly returns to **NORMAL** (Green, Risk: **LOW**).
   - Event logged for transition to `NORMAL`.