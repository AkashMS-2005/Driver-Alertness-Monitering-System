# SmartDrive Guardian — Driver Alertness Monitoring System

SmartDrive Guardian is a real-time driver drowsiness monitoring system that utilizes computer vision to track eye aspect ratio (EAR), mouth aspect ratio (MAR), and percentage of eye closure (PERCLOS) to detect drowsiness and microsleep events in real time.

---

## 🏛️ Phase 3 Architecture Overview

The system streams detection telemetry over a dual WebSocket pipeline across two machines (or on a single machine for development):

```
Laptop 1 (AI Computer)
  Webcam → MediaPipe FaceLandmarker → EAR / MAR / PERCLOS
  → Drowsiness Classifier (NORMAL / DROWSY / MICROSLEEP)
  → AI WebSocket Server (ws://0.0.0.0:8001/ws/ai)
           │
           ▼  (WebSocket LAN JSON Stream)
Laptop 2 (Application Computer)
  FastAPI Backend (AI Client + Connection Manager)
  → Backend WebSocket Gateway (ws://0.0.0.0:8000/ws/drowsiness)
           │
           ▼  (WebSocket Forwarding)
  React Driver Dashboard (http://localhost:5173)
```

---

## 🔌 Network Ports & Endpoints

| Component | Host / Port | WebSocket Endpoint | Description |
|---|---|---|---|
| **AI Service** (Laptop 1) | `0.0.0.0:8001` | `ws://<laptop1-ip>:8001/ws/ai` | Streams live drowsiness telemetry frames |
| **Backend API** (Laptop 2) | `0.0.0.0:8000` | `ws://<laptop2-ip>:8000/ws/drowsiness` | Ingests AI stream & broadcasts to clients |
| **Driver Dashboard** | `localhost:5173` | `http://localhost:5173` | Real-time React driver UI |

---

## 📦 Telemetry JSON Format

Each frame transmits the following JSON payload:

```json
{
  "type": "drowsiness",
  "timestamp": "2026-09-10T22:30:00.123456+00:00",
  "state": "NORMAL",
  "ear": 0.285,
  "eye_closed": false,
  "closed_duration": 0.0,
  "perclos": 2.1,
  "mar": 0.280,
  "yawning": false,
  "alert_message": null
}
```

### Possible States
- `NORMAL` — Eyes open and driver alert (Green status)
- `DROWSY` — Eyes closed > 1.5s or yawning (Orange/Yellow warning)
- `MICROSLEEP` — Eyes closed > 3.0s (Strong Red alert + audible alarm)

---

## 🚀 How to Run

### Option A: Single Laptop (Development Mode)

All 3 components run on the same computer using `localhost` / `127.0.0.1`.

#### Step 1: Start the Backend (Terminal 1)
```bash
cd backend
.\venv\Scripts\activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
> Backend runs at `http://localhost:8000`.

#### Step 2: Start the AI Service (Terminal 2)
```bash
cd ai-service
python src/main.py
```
> Opens webcam, runs MediaPipe, and starts WebSocket server at `ws://0.0.0.0:8001/ws/ai`.

#### Step 3: Start the React Driver Dashboard (Terminal 3)
```bash
cd frontend/driver-dashboard
npm run dev
```
> Open browser at: **`http://localhost:5173`**

---

### Option B: Two Laptops (LAN Setup)

#### Step 1: Find Laptop 1's IP address
On Laptop 1, open command prompt and run:
```bash
ipconfig
```
> Example: `192.168.1.105`

#### Step 2: Configure Laptop 2 Backend
On Laptop 2, open `backend/.env` and set `AI_SERVER_HOST`:
```env
AI_SERVER_HOST=192.168.1.105
AI_SERVER_PORT=8001
```

#### Step 3: Start Services
- **Laptop 1**: Run `python src/main.py` in `ai-service/`
- **Laptop 2**: Run FastAPI backend on port 8000 and React Dashboard on port 5173.
- Open `http://<laptop2-ip>:5173` or `http://localhost:5173` on Laptop 2.

---

## 🧪 Automated Testing

### Run Phase 2 AI Module Tests
```bash
cd ai-service
python tests/test_phase2_modules.py
```
*Validates MediaPipe loading, EAR/MAR calculation, temporal closure durations, PERCLOS calculation, and drowsiness classifier.*

### Run Phase 3 Networking Tests
```bash
cd backend
.\venv\Scripts\python tests/test_phase3_networking.py
```
*Validates AI WS Server startup, Backend AI Client connection, message schema validation, telemetry transmission across state transitions (NORMAL -> DROWSY -> MICROSLEEP -> NORMAL), and clean disconnects.*

---

## 🖥️ Expected Dashboard Behavior

1. **Normal Alert State**:
   - Hero banner displays **NORMAL** with a sleek green border and emerald glow.
   - EAR displays ~0.25–0.32, Eye Status shows **OPEN** (Green badge).
   - Closed duration remains `0.00 s`.

2. **Drowsy State (Eyes closed ~1.5s or yawning)**:
   - Hero banner changes to **DROWSY** with amber warning glow and alert subtitle.
   - Eye Status shows **CLOSED** (Red badge), duration displays `~1.50 s+`.
   - Audio beep triggers on Laptop 1.

3. **Microsleep State (Eyes closed > 3.0s)**:
   - Hero banner flashes **MICROSLEEP** with a strong red alert and critical instruction.
   - High-pitch emergency alarm sounds continuously.

4. **Return to Alert State (Eyes opened)**:
   - Immediately reverts to **NORMAL** with zero lag.