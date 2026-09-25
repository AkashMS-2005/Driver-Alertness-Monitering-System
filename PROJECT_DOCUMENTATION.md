# SMARTDRIVE GUARDIAN — COMPLETE PROJECT DOCUMENTATION

**Project Title:** A Real-Time Vision-Based Driver Drowsiness Monitoring and Emergency Assistance System
**Version:** 2.1.0  
**Last Updated:** September 2026  
**Repository Architecture:** Multi-tier distributed edge-and-cloud architecture (AI Perception Engine + Backend Risk Engine & API Gateway + React Dashboards)

---

## 1. Executive Summary & Vision

**SmartDrive Guardian** is a real-time, safety-critical Driver Alertness Monitoring System (DAMS) designed to prevent road accidents caused by driver fatigue, drowsiness, and distraction.

The system combines:
1. **Edge AI Computer Vision Perception**: High-frequency video stream processing using facial landmark tracking (MediaPipe Face Mesh) to monitor Eye Aspect Ratio (EAR), Mouth Aspect Ratio (MAR), head pose deviation, and 60-second temporal PERCLOS (Percentage of Eye Closure).
2. **Backend Risk & Automatic Emergency Engine**: A deterministic state machine and Risk Engine that detects discrete microsleep events, automatically triggers high-severity emergency states upon repeated fatigue events (≥ 2 microsleep events), resolves nearest highway/toll assistance via spatial distance calculations, and manages safety lifecycle transitions (`ACTIVE`, `DRIVER_RECOVERED`, `ASSISTANCE_RESPONDED`, `CANCELLED`, `RESOLVED`).
3. **Real-Time Two-Way Highway Assistance SMS Gateway**: An integrated Twilio SMS communication layer replacing manual simulations. When an emergency is created, the system dispatches an SMS alert to a configured highway assistance contact containing vehicle registration, GPS coordinates, fatigue telemetry, and dispatch commands. Inbound SMS replies (`ACCEPT <ID>` or `REJECT <ID>`) are verified via webhook, update the database, and reflect instantly on the Owner Dashboard via WebSockets without browser refreshes.
4. **Unified React Web Applications**:
   - **Owner Dashboard**: Fleet/owner monitoring interface featuring live camera feeds, trip telemetry, interactive Leaflet route maps, drowsiness history tables, emergency alert cards, and persistent emergency history logs.
  

---

## 2. Complete End-to-End System Architecture

```
                          ┌─────────────────────────────────────┐
                          │         Driver In-Cab Camera        │
                          └──────────────────┬──────────────────┘
                                             │ Video frames (Webcam / Stream)
                                             ▼
                          ┌─────────────────────────────────────┐
                          │          AI PERCEPTION SERVICE      │
                          │             (Port 8001)             │
                          │  • MediaPipe 468-point Face Mesh    │
                          │  • Eye Aspect Ratio (EAR)           │
                          │  • Mouth Aspect Ratio (MAR)         │
                          │  • Head Pose (Yaw, Pitch, Roll)     │
                          │  • PERCLOS (60s Sliding Window)     │
                          │  • Multimodal Fusion Classifier     │
                          └──────────────────┬──────────────────┘
                                             │ WebSocket (ws://127.0.0.1:8001/ws/ai)
                                             ▼
                          ┌─────────────────────────────────────┐
                          │            FASTAPI BACKEND          │
                          │             (Port 8000)             │
                          │  • Risk Engine & State Machine      │
                          │  • Microsleep Edge Event Counter    │
                          │  • Auto Emergency Trigger (>= 2)    │
                          │  • Nearest Toll Assistance Resolver │
                          │  • WebSocket Gateway Broadcast      │
                          │  • Async Database (SQLite / Postgres)│
                          └──────┬───────────────────────┬──────┘
                                 │                       │
      Outbound SMS Alert (Twilio)│                       │ WebSocket (/ws/drowsiness)
                                 ▼                       ▼
      ┌───────────────────────────────────┐    ┌───────────────────────────────────┐
      │   Highway Assistance / Toll Plaza │    │      OWNER DASHBOARD (Port 5174)  │
      │   Configured Mobile Contact       │    │  • 16:9 Live Camera Feed Card     │
      └──────────────────┬────────────────┘    │  • Real-time Driver State (AWAKE, │
                         │                      │    DROWSY, SLEEPING)              │
        Inbound SMS Reply│ (ACCEPT / REJECT)   │  • Leaflet Interactive GPS Maps   │
                         ▼                     │  • Read-Only Assistance Status    │
      ┌───────────────────────────────────┐    │  • Persistent Emergency History   │
      │   Twilio Inbound Webhook          │    └───────────────────────────────────┘
      │   POST /api/v1/webhooks/twilio/sms│                       ▲
      └──────────────────┬────────────────┘                       │
                         │ Webhook update                         │ Live sync
                         └────────────────────────────────────────┘
```

---

## 3. Work Completed in This Project

### 3.1 AI Perception Service (`ai-service`)
- **Facial Landmark Tracking**: Uses Google MediaPipe Face Mesh to extract 468 3D facial landmarks at 30 FPS.
- **Ocular Analysis (EAR)**: Computes the 6-point Euclidean distance ratio for both left and right eyes to detect blinks, eyelid drooping, and prolonged eye closures.
- **Yawn Detection (MAR)**: Analyzes vertical-to-horizontal inner lip aspect ratio to flag fatigue-induced yawning episodes.
- **Head Pose & Distraction Tracking**: Solves the Perspective-n-Point (PnP) problem using facial feature points and a 3D generic head model to track head yaw, pitch, and roll, detecting driver gaze deviation or drooping.
- **Temporal PERCLOS Window**: Implemented a 60-second sliding window calculating the percentage of time eyes remain ≥ 80% closed.
- **Multimodal Classification**: Merges ocular, oral, and head pose data into fused driver alertness states:
  - `NORMAL` (Alert / Awake)
  - `DROWSY` (Fatigued / Inattentive)
  - `MICROSLEEP` (Eyes closed ≥ 1.5s / High risk)
- **High-Performance Streaming**: Streams AI metrics and base64 video frames over WebSocket (`/ws/ai`) to the backend.

---

### 3.2 Backend Core & Risk Engine (`backend`)
- **Asynchronous FastAPI Architecture**: High-throughput REST API and WebSocket gateway powered by Starlette, Uvicorn, and Python 3.13.
- **Database Layer**: Full async SQLAlchemy 2.0 ORM supporting SQLite (`aiosqlite`) for frictionless local development and PostgreSQL (`asyncpg`) for production. Features dynamic column migration helpers (`_migrate_sqlite_columns`) to prevent schema breaking changes.
- **Data Models**:
  - `Owner`: User account, credentials, and contact details.
  - `Vehicle`: Vehicle registration plate, make, model, year, and owner linkage.
  - `Trip`: Active driving session, start/end coordinates, distance, and duration.
  - `Location`: Real-time GPS coordinate history.
  - `SafetyEvent`: Granular timeline log of drowsiness, distraction, and microsleep occurrences.
  - `Alert`: Driver/owner notification records.
  - `HighwayAssistance`: Nearest highway assistance dispatch record, location coordinates, distance in km, and response state.
  - `EmergencyEvent`: Safety emergency event tracking microsleep count, location, timestamps, driver status, cancellation reason, and resolution details.
  - `EmergencySmsLog`: Complete audit trail of outbound emergency SMS notifications, Twilio message SIDs, carrier delivery statuses, responder phone numbers, and response statuses (`ACCEPTED` / `REJECTED`).

---

### 3.3 Automatic Emergency Escalation System
- **Dual Microsleep Condition**: Designed and implemented an edge-triggered counter. When a driver experiences a second separate microsleep episode, an automatic emergency is immediately created without requiring human intervention.
- **Nearest Toll / Highway Assistance Discovery**: Evaluates the vehicle's real-time GPS coordinates against an Indian National Highway toll plaza database using the Haversine spatial distance algorithm, resolving the closest assistance point and route distance.
- **Driver Recovery Protocol**: Monitored confirmation window (10 continuous seconds of `NORMAL` state with low drowsiness) shifts the emergency state to `DRIVER_RECOVERED`.
- **Cancellation Protection**: Driver cancellation is permitted only if the driver has verified recovery and the toll authority has not yet responded.
- **Orphan Cleanup & Cooldown**: Automated cooldown timer prevents duplicate emergency spamming while preserving complete historical records.

---

### 3.4 Real-Time Two-Way Highway Assistance SMS Gateway
- **Automatic Alert Dispatch**: Immediately upon emergency creation, the backend dispatches a structured SMS to the configured toll assistance number (`TOLL_ASSISTANCE_PHONE_NUMBER`):
  ```text
  SMARTDRIVE GUARDIAN EMERGENCY ALERT

  Emergency ID: #C99A3DCE
  Vehicle: MH-01-AB-1234
  2 separate microsleep events detected.
  Driver recovery status: UNRESPONSIVE / CRITICAL
  Location: 12.971600, 77.594600
  Nearest assistance: Kengeri Toll Plaza (NICE Road)
  Distance: 14.0 km

  Highway assistance is requested.

  Reply:
  ACCEPT C99A3DCE
  or
  REJECT C99A3DCE

  SmartDrive Guardian
  ```
- **Inbound Webhook Endpoint (`POST /api/v1/webhooks/twilio/sms`)**:
  - Validates Twilio cryptographic signature (`X-Twilio-Signature`) when enabled.
  - Validates that the sender phone matches the authorized assistance contact number.
  - Parses commands (`ACCEPT <ID>` or `REJECT <ID>`) case-insensitively.
  - Updates emergency status to `ASSISTANCE_RESPONDED` and highway assistance status to `ACCEPTED` or `REJECTED`.
  - Records response message, responder phone, and timestamp in database.
  - Returns a compliant TwiML XML confirmation to the assistance responder's mobile device.
- **Real-Time WebSocket Integration**: Broadcasts `ASSISTANCE_RESPONSE` and `SMS_STATUS_UPDATE` through the existing WebSocket gateway, instantly updating connected dashboards.
- **Carrier Delivery Status Tracking (`POST /api/v1/webhooks/twilio/status`)**: Tracks delivery states (`SMS_PENDING`, `SMS_SENT`, `SMS_DELIVERED`, `SMS_FAILED`). If SMS sending fails, the system safely records `SMS_FAILED` while keeping the automatic emergency fully operational.

---

### 3.5 Owner Dashboard Frontend (`frontend/owner-dashboard`)
- **Technology Stack**: React 19, TypeScript, Vite, Vanilla CSS design tokens.
- **Four Dedicated Application Views**:
  1. **Dashboard View**:
     - 16:9 constrained live camera card (`aspect-ratio: 16/9`, `object-fit: cover`, max-width 760px).
     - Driver Alertness card showing real-time status (`AWAKE`, `DROWSY`, `SLEEPING`) with dynamic color indicators.
     - Drowsiness percentage progress bar derived from PERCLOS.
     - Vehicle metadata card and live trip telemetry.
     - Mini interactive location map.
  2. **Trip Summary View**:
     - Key metrics: Trip status, start time, elapsed duration, distance traveled.
     - Full interactive OpenStreetMap powered by Leaflet, displaying start marker, current position, and historical route polyline loaded from `/api/v1/locations/trip/{trip_id}`.
  3. **Drowsiness History View**:
     - Aggregate metrics: Total Events, Drowsy Warnings, Microsleep Alerts, Awake Recoveries.
     - Filterable, timestamped safety events table with risk badges (`LOW`, `MEDIUM`, `HIGH`).
  4. **Emergency Assistance View**:
     - Manual emergency trigger button for testing.
     - OpenStreetMap Nominatim reverse geocoding displaying exact location names.
     - Nearest toll assistance details.
- **Real-Time Emergency Alert Card**:
  - Replaced manual `⚡ SIMULATE TOLL RESPONSE` button with an automated, live read-only status box:
    - `📱 SMS SENT` — Waiting for highway assistance response...
    - `✓ REQUEST ACCEPTED` — Displays accepted confirmation and exact response time.
    - `✕ REQUEST REJECTED` — Displays rejection notice and response time.
    - `⚠ SMS DELIVERY FAILED` — Informs owner if SMS dispatch encountered carrier failure while keeping emergency active.
  - `✓ ACKNOWLEDGE & CLOSE` button allowing owner to dismiss answered emergencies.
- **Persistent Emergency History Log**:
  - Displays all past emergencies across server restarts.
  - Details include Microsleep count, Location coordinates, Nearest Assistance, SMS delivery status (`DELIVERED`/`SENT`/`FAILED`), Assistance Response status (`ACCEPTED`/`REJECTED`), responder phone number, and response timestamp.

---

### 3.6 Driver Dashboard Frontend (`frontend/driver-dashboard`)
- Lightweight in-cab display tailored for drivers.
- Receives immediate audio/visual alert notifications upon drowsiness or microsleep onset.
- Receives real-time highway assistance notifications (`ASSISTANCE_RESPONSE`) informing the driver that help is en route.

---

## 4. Repository Directory Structure

```
Driver-Alertness-Monitering-System/
├── ai-service/                        # Edge AI Perception Pipeline (Python 3.10+)
│   ├── src/
│   │   ├── camera/                    # Video capture and frame streaming
│   │   ├── config/                    # Detection thresholds (thresholds.yaml)
│   │   ├── detectors/                 # EAR, MAR, FaceMesh, HeadPose detectors
│   │   ├── fusion/                    # Multimodal fusion classifier
│   │   ├── temporal/                  # 60s sliding window & PERCLOS calculator
│   │   └── websocket/                 # WebSocket server for backend bridge
│   ├── main.py                        # Entrypoint (Port 8001)
│   └── requirements.txt
│
├── backend/                           # FastAPI Core, Risk Engine & SMS Gateway
│   ├── app/
│   │   ├── api/v1/                    # REST route modules
│   │   │   ├── emergency_routes.py    # Emergency trigger & history endpoints
│   │   │   ├── twilio_routes.py       # Inbound SMS & delivery status webhooks
│   │   │   └── router.py              # Root API v1 router
│   │   ├── core/                      # Configuration, settings & security
│   │   ├── db/                        # Database engine, session, & migrations
│   │   ├── models/                    # SQLAlchemy database models
│   │   │   ├── emergency_event.py     # EmergencyEvent model
│   │   │   ├── emergency_sms_log.py   # EmergencySmsLog model (NEW)
│   │   │   ├── highway_assistance.py  # HighwayAssistance model
│   │   │   └── ...                    # Owner, Vehicle, Trip, Alert, Location
│   │   ├── risk_engine/               # EmergencyEngine & drowsiness state machine
│   │   ├── services/                  # Business logic services
│   │   │   ├── emergency_service.py   # Emergency persistence & WebSocket broadcast
│   │   │   ├── sms_service.py         # Twilio SMS dispatch & inbound processing (NEW)
│   │   │   └── ...                    # Trip, Safety, Notification services
│   │   └── websocket/                 # WebSocket connection manager (Driver & Owner)
│   ├── tests/                         # Automated test suite
│   │   ├── test_emergency_engine.py   # 16 Unit tests for Risk Engine state machine
│   │   └── ...
│   ├── .env.example                   # Environment configuration template
│   ├── main.py                        # FastAPI application entrypoint (Port 8000)
│   ├── requirements.txt               # Backend dependencies (FastAPI, Twilio, SQLAlchemy)
│   ├── test_automatic_emergency_flow.py # 10-stage end-to-end verification script
│   └── test_sms_integration.py        # Automated test for SMS dispatch & reply parsing
│
├── frontend/
│   ├── owner-dashboard/               # Unified Fleet Owner Web Application
│   │   ├── src/
│   │   │   ├── App.tsx                # Main application, 4 views, WebSocket listener
│   │   │   ├── App.css                # Premium responsive styling & design tokens
│   │   │   └── main.tsx
│   │   ├── package.json               # React 19, TypeScript, Leaflet, Vite
│   │   └── vite.config.ts
│   │
│   └── driver-dashboard/              # In-Cab Driver HUD Application
│       ├── src/
│       └── package.json
│
├── CHANGES_DOCUMENTATION.md           # Granular changelog
├── EMERGENCY_SYSTEM_DOCUMENTATION.md  # Detailed emergency engine specification
├── PROJECT_DOCUMENTATION.md           # Master project documentation (this file)
└── README.md                          # Quickstart guide
```

---

## 5. API and Webhook Specifications

### 5.1 Twilio Inbound SMS Webhook
- **URL**: `POST /api/v1/webhooks/twilio/sms`
- **Content-Type**: `application/x-www-form-urlencoded`
- **Request Parameters**:
  - `From`: Sender mobile number (e.g. `+919876543210`)
  - `Body`: Message text (e.g. `ACCEPT C99A3DCE` or `REJECT C99A3DCE`)
  - `MessageSid`: Unique Twilio SMS identifier
- **Security**: Validates `X-Twilio-Signature` when enabled and verifies that `From` matches `TOLL_ASSISTANCE_PHONE_NUMBER`.
- **Response**: `application/xml` (TwiML)
  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <Response>
      <Message>SmartDrive Guardian: Emergency #C99A3DCE has been ACCEPTED. Dispatch details recorded.</Message>
  </Response>
  ```

### 5.2 Twilio Delivery Status Webhook
- **URL**: `POST /api/v1/webhooks/twilio/status`
- **Request Parameters**: `MessageSid`, `MessageStatus` (`queued`, `sent`, `delivered`, `undelivered`, `failed`)
- **Action**: Updates `EmergencySmsLog` and broadcasts status update over WebSocket.

### 5.3 Active Emergency Endpoint
- **URL**: `GET /api/v1/emergency/active/{vehicle_id}`
- **Response**:
  ```json
  {
    "active": true,
    "emergency": {
      "emergency_id": "c99a3dce-...",
      "status": "ACTIVE",
      "microsleep_count": 2,
      "drowsiness_percentage": 88.5,
      "latitude": 12.9716,
      "longitude": 77.5946,
      "place_name": "Bengaluru",
      "assistance_name": "Kengeri Toll Plaza (NICE Road)",
      "assistance_distance_km": 14.0,
      "sms_status": "SMS_SENT",
      "assistance_response_status": null
    }
  }
  ```

### 5.4 Emergency History Endpoint
- **URL**: `GET /api/v1/emergency/history/all`
- **Response**: List of all emergency records enriched with linked highway assistance and SMS communication logs.

---

## 6. How to Run and Test the System

### 6.1 Prerequisites
- Python 3.10+ (Recommended Python 3.13)
- Node.js 18+ and npm
- ngrok (for public webhook tunneling during SMS testing)
- Active Twilio account with an SMS-capable phone number

### 6.2 Environment Setup
Create [`backend/.env`](file:///a:/Major%20DAMS/Driver-Alertness-Monitering-System/backend/.env) from [`.env.example`](file:///a:/Major%20DAMS/Driver-Alertness-Monitering-System/backend/.env.example):
```env
DATABASE_URL=sqlite+aiosqlite:///./smartdrive.db
DATABASE_URL_SYNC=sqlite:///./smartdrive.db

AI_SERVER_HOST=127.0.0.1
AI_SERVER_PORT=8001

BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
SECRET_KEY=smartdrive-dev-secret-key
CORS_ORIGINS=http://localhost:5173,http://localhost:5174

# Twilio SMS Configuration
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_PHONE_NUMBER=your_twilio_phone_number
TOLL_ASSISTANCE_PHONE_NUMBER=+91XXXXXXXXXX
TWILIO_STATUS_CALLBACK_URL=https://your-ngrok-domain.ngrok-free.app/api/v1/webhooks/twilio/status
TWILIO_WEBHOOK_VALIDATE_SIGNATURE=false
```

### 6.3 Starting the Services

1. **AI Perception Service** (Terminal 1):
   ```powershell
   cd "a:\Major DAMS\Driver-Alertness-Monitering-System\ai-service"
   python main.py
   # Runs on ws://127.0.0.1:8001
   ```

2. **Backend API & Risk Engine** (Terminal 2):
   ```powershell
   cd "a:\Major DAMS\Driver-Alertness-Monitering-System\backend"
   .\venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   # Runs on http://localhost:8000
   ```

3. **Owner Dashboard Frontend** (Terminal 3):
   ```powershell
   cd "a:\Major DAMS\Driver-Alertness-Monitering-System\frontend\owner-dashboard"
   npm run dev -- --port 5174
   # Runs on http://localhost:5174
   ```

4. **Public ngrok Tunnel for SMS Webhook** (Terminal 4):
   ```powershell
   ngrok http 8000
   ```
   Configure the webhook URL in Twilio Console under **Phone Numbers** ➔ **Manage** ➔ **Active numbers** ➔ **Messaging**:
   `https://<your-ngrok-subdomain>.ngrok-free.app/api/v1/webhooks/twilio/sms` (HTTP POST).

---

## 7. Automated Test Suite

The project includes automated test coverage validating every critical pipeline:

```powershell
cd "a:\Major DAMS\Driver-Alertness-Monitering-System\backend"

# 1. Run Emergency Engine Unit Tests (16 tests)
.\venv\Scripts\python -m pytest tests/test_emergency_engine.py

# 2. Run Automatic Emergency System Flow Tests (10 stages)
.\venv\Scripts\python test_automatic_emergency_flow.py

# 3. Run SMS Integration Tests (Alert dispatch, reply parsing, DB state)
.\venv\Scripts\python test_sms_integration.py
```

All suites execute cleanly with zero errors.

---

## 8. Summary of Milestones Achieved

| Feature Area | Implementation Summary | Status |
| :--- | :--- | :--- |
| **AI Computer Vision** | MediaPipe Face Mesh, EAR, MAR, Head Pose, 60s PERCLOS window | Complete |
| **Risk Engine** | Fatigue classification, state machine, edge-triggered microsleep counter | Complete |
| **Automatic Emergency** | Automatic emergency created at 2 microsleeps, nearest toll resolved | Complete |
| **Recovery & Cancel** | 10s recovery window, conditional driver cancel, orphan cleanup | Complete |
| **Two-Way SMS Gateway** | Outbound Twilio emergency alert, inbound ACCEPT/REJECT webhook | Complete |
| **Live UI Sync** | Real-time WebSocket bridge, simulation button removed, read-only status box | Complete |
| **Emergency History** | Persistent SQLite/Postgres logs with SMS status and responder details | Complete |
| **Frontend UI** | 16:9 camera card, Leaflet GPS maps, Drowsiness table, Responsive layout | Complete |
| **Test Verification** | 16 unit tests, 10-stage flow verification, end-to-end SMS test | Complete |
