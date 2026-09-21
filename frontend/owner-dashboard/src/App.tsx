import { useState, useEffect, useRef, useCallback } from 'react';
import L from 'leaflet';
import './App.css';

// Fix Leaflet default icon path (Vite bundler issue)
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────
type AIState = 'NORMAL' | 'DROWSY' | 'MICROSLEEP';
type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';

interface DrowsinessData {
  state: AIState;
  risk_level: RiskLevel;
  perclos: number;
  ear: number;
  eye_closed: boolean;
  yawning: boolean;
  alert_message: string;
  timestamp?: string;
}

interface VehicleInfo {
  id: string | null;
  plate_number: string;
  make: string;
  model: string;
  year: number | null;
}

interface OwnerInfo {
  id: string | null;
  name: string;
  email: string;
  phone: string | null;
}

interface TripInfo {
  id: string | null;
  status: string;
  start_time: string | null;
  duration_seconds: number;
  distance_km: number;
  start_latitude: number | null;
  start_longitude: number | null;
}

interface LocationInfo {
  latitude: number | null;
  longitude: number | null;
  speed_kmh: number;
  timestamp: string | null;
  gps_available: boolean;
}

interface SafetyEvent {
  timestamp: string;
  state: string;
  risk_level: string;
  description?: string | null;
}

interface DashboardState {
  drowsiness: DrowsinessData;
  vehicle: VehicleInfo;
  owner: OwnerInfo;
  trip: TripInfo;
  location: LocationInfo;
  safety_events: SafetyEvent[];
}

interface EmergencyResult {
  emergency_id: string;
  vehicle_location: { latitude: number; longitude: number; source: string };
  nearest_toll: {
    name: string;
    highway: string;
    latitude: number;
    longitude: number;
    distance_km: number;
  } | null;
  owner_notified: boolean;
  status: string;
  message: string;
  note: string;
  triggered_at: string;
}

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────
function getApiBase(): string {
  const host = window.location.hostname || 'localhost';
  return `http://${host}:8000`;
}

function getWsUrl(): string {
  if (import.meta.env.VITE_BACKEND_WS_URL) return import.meta.env.VITE_BACKEND_WS_URL as string;
  const host = window.location.hostname || 'localhost';
  return `ws://${host}:8000/ws/drowsiness`;
}

function mapStateToLabel(state: AIState): string {
  switch (state) {
    case 'NORMAL': return 'AWAKE';
    case 'DROWSY': return 'DROWSY';
    case 'MICROSLEEP': return 'SLEEPING';
    default: return 'AWAKE';
  }
}

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatTime(iso: string): string {
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
  catch { return iso; }
}

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

// ─────────────────────────────────────────────────────────────
// Map hook — vanilla Leaflet
// ─────────────────────────────────────────────────────────────
function useLeafletMap(
  containerId: string,
  lat: number,
  lon: number,
  routePoints: [number, number][],
  vehicleLabel: string,
  gpsAvailable: boolean,
) {
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const polylineRef = useRef<L.Polyline | null>(null);

  // Initialize map once
  useEffect(() => {
    const container = document.getElementById(containerId);
    if (!container || mapRef.current) return;

    const map = L.map(containerId, { zoomControl: true }).setView([lat, lon], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);

    const marker = L.marker([lat, lon]).addTo(map);
    const popup = gpsAvailable
      ? `<div style="font-family:Inter,sans-serif;min-width:140px"><strong>${vehicleLabel}</strong><br/>📍 ${lat.toFixed(5)}, ${lon.toFixed(5)}</div>`
      : `<div style="font-family:Inter,sans-serif;color:#f59e0b">⚠️ Demo location<br/>(GPS not connected)</div>`;
    marker.bindPopup(popup);

    mapRef.current = map;
    markerRef.current = marker;

    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
      polylineRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerId]);

  // Update marker position when lat/lon changes
  useEffect(() => {
    if (!mapRef.current || !markerRef.current) return;
    markerRef.current.setLatLng([lat, lon]);
    mapRef.current.setView([lat, lon], mapRef.current.getZoom(), { animate: true });
  }, [lat, lon]);

  // Update route polyline
  useEffect(() => {
    if (!mapRef.current) return;
    if (polylineRef.current) {
      polylineRef.current.remove();
      polylineRef.current = null;
    }
    if (routePoints.length > 1) {
      polylineRef.current = L.polyline(routePoints, {
        color: '#818cf8',
        weight: 3,
        opacity: 0.8,
      }).addTo(mapRef.current);
    }
  }, [routePoints]);
}

// ─────────────────────────────────────────────────────────────
// Defaults
// ─────────────────────────────────────────────────────────────
const DEFAULT_DROWSINESS: DrowsinessData = {
  state: 'NORMAL', risk_level: 'LOW', perclos: 0, ear: 0,
  eye_closed: false, yawning: false, alert_message: 'Driver Alert',
};

const DEFAULT_LAT = 12.9716;
const DEFAULT_LON = 77.5946;

// ─────────────────────────────────────────────────────────────
// Main App
// ─────────────────────────────────────────────────────────────
export function App() {
  const API = getApiBase();
  const WS_URL = getWsUrl();

  // ── State ────────────────────────────────────────────────
  const [wsConnected, setWsConnected] = useState(false);
  const [aiCameraStatus, setAiCameraStatus] = useState('DISCONNECTED');
  const [drowsiness, setDrowsiness] = useState<DrowsinessData>(DEFAULT_DROWSINESS);
  const [vehicle, setVehicle] = useState<VehicleInfo | null>(null);
  const [owner, setOwner] = useState<OwnerInfo | null>(null);
  const [trip, setTrip] = useState<TripInfo | null>(null);
  const [location, setLocation] = useState<LocationInfo>({
    latitude: null, longitude: null, speed_kmh: 0, timestamp: null, gps_available: false,
  });
  const [safetyEvents, setSafetyEvents] = useState<SafetyEvent[]>([]);
  const [tripDuration, setTripDuration] = useState(0);
  const [routePoints, setRoutePoints] = useState<[number, number][]>([]);

  // Emergency
  const [emergencyLoading, setEmergencyLoading] = useState(false);
  const [emergencyResult, setEmergencyResult] = useState<EmergencyResult | null>(null);
  const [emergencyError, setEmergencyError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const pingRef = useRef<number | null>(null);
  const tripTimerRef = useRef<number | null>(null);

  // Map values
  const mapLat = location.latitude ?? DEFAULT_LAT;
  const mapLon = location.longitude ?? DEFAULT_LON;
  const vehicleLabel = vehicle?.plate_number ?? 'Vehicle';

  // Initialize map
  useLeafletMap('leaflet-map', mapLat, mapLon, routePoints, vehicleLabel, location.gps_available);

  // ── Trip duration live counter ─────────────────────────
  useEffect(() => {
    if (trip?.start_time && trip.status === 'ACTIVE') {
      const startMs = new Date(trip.start_time).getTime();
      if (tripTimerRef.current) clearInterval(tripTimerRef.current);
      tripTimerRef.current = window.setInterval(() => {
        setTripDuration(Math.floor((Date.now() - startMs) / 1000));
      }, 1000);
    }
    return () => { if (tripTimerRef.current) clearInterval(tripTimerRef.current); };
  }, [trip?.start_time, trip?.status]);

  // ── Dashboard REST polling ─────────────────────────────
  const fetchDashboardState = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/v1/dashboard/state`);
      if (!res.ok) return;
      const data: DashboardState = await res.json();
      setDrowsiness(data.drowsiness);
      setVehicle(data.vehicle);
      setOwner(data.owner);
      setTrip(data.trip);
      setLocation(data.location);
      if (data.safety_events?.length > 0) setSafetyEvents(data.safety_events);
    } catch { /* silent */ }
  }, [API]);

  const fetchRouteHistory = useCallback(async (tripId: string) => {
    try {
      const res = await fetch(`${API}/api/v1/locations/trip/${tripId}?limit=100`);
      if (!res.ok) return;
      const locs: Array<{ latitude: number; longitude: number }> = await res.json();
      if (locs.length > 0) setRoutePoints(locs.map(l => [l.latitude, l.longitude]));
    } catch { /* silent */ }
  }, [API]);

  useEffect(() => {
    fetchDashboardState();
    const t = window.setInterval(fetchDashboardState, 5000);
    return () => clearInterval(t);
  }, [fetchDashboardState]);

  useEffect(() => {
    if (!trip?.id) return;
    fetchRouteHistory(trip.id);
    const t = window.setInterval(() => fetchRouteHistory(trip.id!), 15000);
    return () => clearInterval(t);
  }, [trip?.id, fetchRouteHistory]);

  // ── WebSocket ──────────────────────────────────────────
  useEffect(() => {
    let mounted = true;

    function connect() {
      if (!mounted) return;
      try {
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!mounted) return;
          setWsConnected(true);
          if (pingRef.current) clearInterval(pingRef.current);
          pingRef.current = window.setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
          }, 15000);
        };

        ws.onmessage = (evt) => {
          if (!mounted) return;
          try {
            const msg = JSON.parse(evt.data as string) as Record<string, unknown>;
            if (msg.type === 'drowsiness_update' || msg.type === 'drowsiness') {
              if (msg.state) {
                setDrowsiness({
                  state: msg.state as AIState,
                  risk_level: (msg.risk_level as RiskLevel) || 'LOW',
                  perclos: typeof msg.perclos === 'number' ? msg.perclos : 0,
                  ear: typeof msg.ear === 'number' ? msg.ear : 0,
                  eye_closed: Boolean(msg.eye_closed),
                  yawning: Boolean(msg.yawning),
                  alert_message: (msg.alert_message as string) || 'Driver Alert',
                  timestamp: msg.timestamp as string | undefined,
                });
                setAiCameraStatus('CONNECTED');

                const recentEvents = msg.recent_events as Array<Record<string, unknown>> | undefined;
                if (recentEvents?.length) {
                  setSafetyEvents(recentEvents.map(e => ({
                    timestamp: (e.timestamp as string) || new Date().toISOString(),
                    state: (e.state as string) || 'NORMAL',
                    risk_level: (e.risk_level as string) || 'LOW',
                    description: e.description as string | undefined,
                  })));
                }
              }
            } else if (msg.event_type === 'AI_CONNECTION_STATUS_UPDATE') {
              setAiCameraStatus((msg.status as string) || 'DISCONNECTED');
            }
          } catch { /* malformed */ }
        };

        ws.onclose = () => {
          if (!mounted) return;
          setWsConnected(false);
          if (pingRef.current) clearInterval(pingRef.current);
          reconnectRef.current = window.setTimeout(() => { if (mounted) connect(); }, 2500);
        };

        ws.onerror = () => { if (ws.readyState === WebSocket.OPEN) ws.close(); };
      } catch (err) {
        console.error('WS error:', err);
        reconnectRef.current = window.setTimeout(connect, 3000);
      }
    }

    connect();
    return () => {
      mounted = false;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (pingRef.current) clearInterval(pingRef.current);
      wsRef.current?.close();
    };
  }, [WS_URL]);

  // ── Emergency trigger ──────────────────────────────────
  const handleEmergency = async () => {
    if (emergencyLoading) return;
    setEmergencyLoading(true);
    setEmergencyResult(null);
    setEmergencyError(null);
    try {
      const res = await fetch(`${API}/api/v1/emergency/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          vehicle_id: vehicle?.id ?? null,
          reason: 'EMERGENCY_BUTTON_PRESSED',
          driver_status: drowsiness.state,
          drowsiness_level: drowsiness.perclos,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' })) as { detail?: string };
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      setEmergencyResult(await res.json() as EmergencyResult);
    } catch (e) {
      setEmergencyError(e instanceof Error ? e.message : 'Emergency request failed');
    } finally {
      setEmergencyLoading(false);
    }
  };

  // ── Derived ────────────────────────────────────────────
  const stateLabel = mapStateToLabel(drowsiness.state);
  const stateClass = drowsiness.state.toLowerCase();
  const perclosDisplay = Math.min(100, Math.round(drowsiness.perclos));

  // ─────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────
  return (
    <div className="app">
      {/* ══ HEADER ══ */}
      <header className="header">
        <div className="header-brand">
          <div className="header-logo">
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
              <circle cx="13" cy="13" r="11" stroke="currentColor" strokeWidth="2" />
              <path d="M13 7v6l4 2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <circle cx="13" cy="13" r="2" fill="currentColor" />
            </svg>
          </div>
          <div>
            <h1 className="header-title">SMARTDRIVE GUARDIAN</h1>
            <div className="header-subtitle">Vehicle Safety Dashboard</div>
          </div>
        </div>
        <div className="header-status">
          {vehicle && (
            <div className="header-badge vehicle-badge">
              <span className="badge-icon">🚗</span>
              <span>{vehicle.plate_number} · {vehicle.make} {vehicle.model}</span>
            </div>
          )}
          <div className={`header-badge ${wsConnected ? 'badge-connected' : 'badge-disconnected'}`}>
            <span className={`status-dot ${wsConnected ? 'dot-on' : 'dot-off'}`} />
            <span>Backend: {wsConnected ? 'LIVE' : 'OFFLINE'}</span>
          </div>
          <div className={`header-badge ${aiCameraStatus === 'CONNECTED' ? 'badge-connected' : 'badge-disconnected'}`}>
            <span className="badge-icon">📷</span>
            <span>AI Camera: {aiCameraStatus}</span>
          </div>
        </div>
      </header>

      <main className="main-content">

        {/* ══ ROW 1: DRIVER STATUS + DROWSINESS LEVEL ══ */}
        <div className="row-two">

          {/* Driver Status */}
          <section className={`card status-card state-${stateClass}`} id="driver-status">
            <div className="card-label">DRIVER STATUS</div>
            <div className="status-display">
              <div className="status-icon">
                {drowsiness.state === 'NORMAL' && '🟢'}
                {drowsiness.state === 'DROWSY' && '🟡'}
                {drowsiness.state === 'MICROSLEEP' && '🔴'}
              </div>
              <div className={`status-text state-${stateClass}`}>{stateLabel}</div>
            </div>
            <div className="status-detail">
              {drowsiness.state === 'NORMAL' && 'Driver is alert and responsive'}
              {drowsiness.state === 'DROWSY' && '⚠️ Driver showing signs of drowsiness'}
              {drowsiness.state === 'MICROSLEEP' && '🚨 Critical — Driver microsleeping!'}
            </div>
            {drowsiness.alert_message && (
              <div className="status-alert-msg">{drowsiness.alert_message}</div>
            )}
            {drowsiness.timestamp && (
              <div className="status-timestamp">Updated: {formatTime(drowsiness.timestamp)}</div>
            )}
          </section>

          {/* Drowsiness Level */}
          <section className="card drowsiness-card" id="drowsiness-level">
            <div className="card-label">DROWSINESS LEVEL</div>
            <div className="perclos-display">
              <div className={`perclos-value state-${stateClass}`}>
                {perclosDisplay}<span className="pct-sign">%</span>
              </div>
              <div className="perclos-label">PERCLOS — Eye closure rate (60 s window)</div>
            </div>
            <div className="perclos-bar-track">
              <div
                className={`perclos-bar-fill state-${stateClass}`}
                style={{ width: `${perclosDisplay}%` }}
              />
            </div>
            <div className="drowsiness-metrics">
              <div className="metric">
                <span className="metric-label">EAR</span>
                <span className="metric-value">{drowsiness.ear.toFixed(3)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Eyes</span>
                <span className={`metric-value ${drowsiness.eye_closed ? 'metric-warn' : 'metric-ok'}`}>
                  {drowsiness.eye_closed ? 'CLOSED' : 'OPEN'}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Yawning</span>
                <span className={`metric-value ${drowsiness.yawning ? 'metric-warn' : 'metric-ok'}`}>
                  {drowsiness.yawning ? 'YES' : 'NO'}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Risk</span>
                <span className={`metric-value risk-${drowsiness.risk_level.toLowerCase()}`}>
                  {drowsiness.risk_level}
                </span>
              </div>
            </div>
          </section>

        </div>

        {/* ══ LIVE VEHICLE LOCATION (Leaflet Map) ══ */}
        <section className="card map-card" id="live-location">
          <div className="card-header-row">
            <div className="card-label">LIVE VEHICLE LOCATION</div>
            <div className="location-info">
              {location.gps_available ? (
                <span className="location-coords">
                  📍 {location.latitude?.toFixed(4)}, {location.longitude?.toFixed(4)}
                  {location.speed_kmh > 0 && (
                    <span className="speed-badge"> · {location.speed_kmh.toFixed(0)} km/h</span>
                  )}
                  {location.timestamp && (
                    <span className="speed-badge"> · {formatTime(location.timestamp)}</span>
                  )}
                </span>
              ) : (
                <span className="location-no-gps">⚠️ GPS not connected — demo location (Bengaluru) shown</span>
              )}
            </div>
          </div>
          {/* Vanilla Leaflet map container */}
          <div id="leaflet-map" className="map-container" />
        </section>

        {/* ══ ROW 3: TRIP SUMMARY + DROWSINESS HISTORY ══ */}
        <div className="row-two">

          {/* Trip Summary */}
          <section className="card trip-card" id="trip-summary">
            <div className="card-label">TRIP SUMMARY</div>
            {trip && trip.status !== 'NO_ACTIVE_TRIP' ? (
              <>
                <div className="trip-status-row">
                  <span className={`trip-status-pill ${trip.status === 'ACTIVE' ? 'trip-active' : 'trip-ended'}`}>
                    {trip.status === 'ACTIVE' ? '● IN PROGRESS' : trip.status}
                  </span>
                </div>
                <div className="trip-grid">
                  <div className="trip-item">
                    <span className="trip-item-label">Trip Started</span>
                    <span className="trip-item-value">
                      {trip.start_time ? formatDateTime(trip.start_time) : 'N/A'}
                    </span>
                  </div>
                  <div className="trip-item">
                    <span className="trip-item-label">Duration</span>
                    <span className="trip-item-value">{formatDuration(tripDuration)}</span>
                  </div>
                  <div className="trip-item">
                    <span className="trip-item-label">Distance</span>
                    <span className="trip-item-value">{trip.distance_km.toFixed(1)} km</span>
                  </div>
                  <div className="trip-item">
                    <span className="trip-item-label">Vehicle</span>
                    <span className="trip-item-value">{vehicle?.plate_number || 'N/A'}</span>
                  </div>
                  {trip.start_latitude != null && (
                    <div className="trip-item trip-item-wide">
                      <span className="trip-item-label">Start Location</span>
                      <span className="trip-item-value">
                        {trip.start_latitude.toFixed(4)}, {trip.start_longitude?.toFixed(4)}
                      </span>
                    </div>
                  )}
                  {location.gps_available && location.latitude != null && (
                    <div className="trip-item trip-item-wide">
                      <span className="trip-item-label">Current Location</span>
                      <span className="trip-item-value">
                        {location.latitude.toFixed(4)}, {location.longitude?.toFixed(4)}
                      </span>
                    </div>
                  )}
                </div>
                {owner && (
                  <div className="owner-info">
                    <span className="owner-label">Owner:</span>
                    <span className="owner-name">{owner.name}</span>
                    {owner.phone && <span className="owner-phone">📞 {owner.phone}</span>}
                  </div>
                )}
              </>
            ) : (
              <div className="no-trip">No active trip. Trip information will appear here once a trip is started.</div>
            )}
          </section>

          {/* Drowsiness History */}
          <section className="card history-card" id="drowsiness-history">
            <div className="card-label">TRIP DROWSINESS HISTORY</div>
            {safetyEvents.length === 0 ? (
              <div className="no-events">
                No events recorded yet. History will appear as the driver's state changes during the trip.
              </div>
            ) : (
              <div className="events-list">
                {safetyEvents.map((evt, i) => (
                  <div key={`${evt.timestamp}-${i}`} className={`event-row event-${(evt.state || 'normal').toLowerCase()}`}>
                    <span className="event-time">{evt.timestamp ? formatTime(evt.timestamp) : '--:--'}</span>
                    <span className={`event-state-pill state-${(evt.state || 'normal').toLowerCase()}`}>
                      {evt.state === 'NORMAL' ? 'AWAKE'
                        : evt.state === 'DROWSY' ? 'DROWSY'
                        : evt.state === 'MICROSLEEP' ? 'SLEEPING'
                        : evt.state || 'NORMAL'}
                    </span>
                    <span className={`event-risk risk-${(evt.risk_level || 'low').toLowerCase()}`}>
                      {evt.risk_level || 'LOW'}
                    </span>
                    {evt.description && (
                      <span className="event-desc">{evt.description}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

        </div>

        {/* ══ EMERGENCY SECTION ══ */}
        <section className="card emergency-card" id="emergency-section">
          <div className="card-label">EMERGENCY ASSISTANCE</div>

          {!emergencyResult ? (
            <div className="emergency-layout">
              <div className="emergency-info">
                <p className="emergency-desc">
                  Press the emergency button to immediately request highway assistance.
                  The system will identify the nearest toll gate, create an emergency record,
                  and notify the vehicle owner in real-time.
                </p>
                <ul className="emergency-steps">
                  <li>📍 Capture current vehicle location</li>
                  <li>🏁 Find nearest toll / highway assistance point</li>
                  <li>📋 Log emergency event to database</li>
                  <li>🔔 Notify vehicle owner via WebSocket</li>
                </ul>
              </div>
              <div className="emergency-action">
                <button
                  id="emergency-button"
                  className={`emergency-btn ${emergencyLoading ? 'emergency-btn-loading' : ''}`}
                  onClick={handleEmergency}
                  disabled={emergencyLoading}
                  aria-label="Trigger emergency assistance"
                >
                  {emergencyLoading ? (
                    <>
                      <span className="spinner" />
                      <span>Requesting...</span>
                    </>
                  ) : (
                    <>
                      <span className="emergency-icon">🚨</span>
                      <span>EMERGENCY</span>
                    </>
                  )}
                </button>
                {emergencyError && (
                  <div className="emergency-error">⚠️ {emergencyError}</div>
                )}
              </div>
            </div>
          ) : (
            <div className="emergency-result" id="emergency-result">
              <div className="result-header">
                <span className="result-icon">✅</span>
                <div>
                  <div className="result-title">EMERGENCY REQUEST SENT</div>
                  <div className="result-time">{formatDateTime(emergencyResult.triggered_at)}</div>
                </div>
              </div>
              <div className="result-grid">
                {emergencyResult.nearest_toll && (
                  <div className="result-item result-item-highlight">
                    <div className="result-item-label">Nearest Toll Gate</div>
                    <div className="result-item-value">{emergencyResult.nearest_toll.name}</div>
                    <div className="result-item-sub">
                      {emergencyResult.nearest_toll.highway} · {emergencyResult.nearest_toll.distance_km.toFixed(1)} km away
                    </div>
                  </div>
                )}
                <div className="result-item">
                  <div className="result-item-label">Vehicle Location</div>
                  <div className="result-item-value">
                    {emergencyResult.vehicle_location.latitude.toFixed(4)}, {emergencyResult.vehicle_location.longitude.toFixed(4)}
                  </div>
                  <div className="result-item-sub">{emergencyResult.vehicle_location.source}</div>
                </div>
                <div className="result-item">
                  <div className="result-item-label">Owner Notified</div>
                  <div className="result-item-value">
                    {emergencyResult.owner_notified ? '✅ Yes (WebSocket)' : '❌ Could not reach'}
                  </div>
                </div>
                <div className="result-item">
                  <div className="result-item-label">Status</div>
                  <div className="result-item-value">{emergencyResult.status}</div>
                </div>
              </div>
              <div className="result-note">ℹ️ {emergencyResult.note}</div>
              <button
                className="result-reset-btn"
                onClick={() => { setEmergencyResult(null); setEmergencyError(null); }}
              >
                Close
              </button>
            </div>
          )}
        </section>

      </main>

      {/* ══ FOOTER ══ */}
      <footer className="footer">
        <div className="footer-info">
          <span>SmartDrive Guardian v2.0</span>
          <span className="footer-sep">·</span>
          <span>Backend: <code>{API}</code></span>
          <span className="footer-sep">·</span>
          <span>WebSocket: <code>{WS_URL}</code></span>
        </div>
        <div className="footer-info">
          <span>Map: OpenStreetMap (free, no API key required)</span>
          <span className="footer-sep">·</span>
          <span>AI: PERCLOS + EAR + MAR via MediaPipe FaceLandmarker</span>
        </div>
      </footer>
    </div>
  );
}

export default App;
