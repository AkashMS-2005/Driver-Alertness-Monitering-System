import { useState, useEffect, useRef } from 'react';
import './App.css';

export type DrowsinessState = 'NORMAL' | 'DROWSY' | 'MICROSLEEP';
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export interface SafetyEventRecord {
  id: string;
  trip_id?: string;
  vehicle_id?: string;
  event_type: string;
  risk_level: string;
  driver_status: string;
  description?: string | null;
  timestamp: string;
}

export interface OwnerStats {
  current_state: DrowsinessState;
  current_risk: RiskLevel;
  drowsy_events_count: number;
  microsleep_events_count: number;
  total_events_count: number;
  latest_perclos: number;
}

function getWsUrl(): string {
  if (import.meta.env.VITE_BACKEND_WS_URL) {
    return import.meta.env.VITE_BACKEND_WS_URL;
  }
  const host = window.location.hostname || 'localhost';
  return `ws://${host}:8000/ws/owner/default`;
}

function getApiBaseUrl(): string {
  const host = window.location.hostname || 'localhost';
  return `http://${host}:8000`;
}

export function App() {
  const [driverState, setDriverState] = useState<DrowsinessState>('NORMAL');
  const [riskLevel, setRiskLevel] = useState<RiskLevel>('LOW');
  const [aiCameraStatus, setAiCameraStatus] = useState<string>('DISCONNECTED');
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [latestPerclos, setLatestPerclos] = useState<number>(0.0);
  const [events, setEvents] = useState<SafetyEventRecord[]>([]);
  const [stats, setStats] = useState<OwnerStats>({
    current_state: 'NORMAL',
    current_risk: 'LOW',
    drowsy_events_count: 0,
    microsleep_events_count: 0,
    total_events_count: 0,
    latest_perclos: 0.0,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const pingIntervalRef = useRef<number | null>(null);

  const wsUrl = getWsUrl();
  const apiBase = getApiBaseUrl();

  // Fetch initial REST data from backend
  const fetchSafetyData = async () => {
    try {
      const [statsRes, eventsRes] = await Promise.all([
        fetch(`${apiBase}/api/v1/safety/stats`).catch(() => null),
        fetch(`${apiBase}/api/v1/safety/events?limit=20`).catch(() => null),
      ]);

      if (statsRes && statsRes.ok) {
        const statsData = await statsRes.json();
        setStats(statsData);
        if (statsData.current_state) setDriverState(statsData.current_state);
        if (statsData.current_risk) setRiskLevel(statsData.current_risk);
        if (statsData.latest_perclos !== undefined) setLatestPerclos(statsData.latest_perclos);
      }

      if (eventsRes && eventsRes.ok) {
        const eventsData = await eventsRes.json();
        if (Array.isArray(eventsData) && eventsData.length > 0) {
          setEvents(eventsData);
        }
      }
    } catch {
      // Backend may be starting up — handled gracefully
    }
  };

  useEffect(() => {
    fetchSafetyData();
    const interval = setInterval(fetchSafetyData, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    let isMounted = true;

    function connect() {
      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMounted) return;
          setWsConnected(true);

          if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = window.setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'ping' }));
            }
          }, 15000);
        };

        ws.onmessage = (event) => {
          if (!isMounted) return;
          try {
            const msg = JSON.parse(event.data);

            if ((msg.type === 'drowsiness_update' || msg.type === 'drowsiness') && msg.state) {
              const state = msg.state as DrowsinessState;
              const risk = (msg.risk_level as RiskLevel) || (state === 'MICROSLEEP' ? 'HIGH' : state === 'DROWSY' ? 'MEDIUM' : 'LOW');
              setDriverState(state);
              setRiskLevel(risk);
              if (msg.perclos !== undefined) setLatestPerclos(msg.perclos);
              setAiCameraStatus('CONNECTED');

              // If backend sends recent events in message, update them
              if (msg.recent_events && Array.isArray(msg.recent_events) && msg.recent_events.length > 0) {
                const mappedEvents: SafetyEventRecord[] = msg.recent_events.map((e: any) => ({
                  id: e.id || Math.random().toString(36).substring(2, 8),
                  vehicle_id: 'VEHICLE-01',
                  event_type: `${e.state}_EVENT`,
                  risk_level: e.risk_level || 'LOW',
                  driver_status: e.state,
                  description: e.description || `${e.state} detected`,
                  timestamp: e.timestamp || new Date().toISOString(),
                }));
                setEvents(mappedEvents);

                // Update counts
                const drowsyCount = mappedEvents.filter((ev) => ev.driver_status === 'DROWSY').length;
                const microsleepCount = mappedEvents.filter((ev) => ev.driver_status === 'MICROSLEEP').length;
                setStats((prev) => ({
                  ...prev,
                  current_state: state,
                  current_risk: risk,
                  drowsy_events_count: Math.max(prev.drowsy_events_count, drowsyCount),
                  microsleep_events_count: Math.max(prev.microsleep_events_count, microsleepCount),
                  total_events_count: Math.max(prev.total_events_count, mappedEvents.length),
                  latest_perclos: msg.perclos !== undefined ? msg.perclos : prev.latest_perclos,
                }));
              }
            } else if (msg.event_type === 'AI_CONNECTION_STATUS_UPDATE') {
              setAiCameraStatus(msg.status || 'DISCONNECTED');
            }
          } catch (e) {
            console.error('Error parsing WS message:', e);
          }
        };

        ws.onclose = () => {
          if (!isMounted) return;
          setWsConnected(false);
          if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
          reconnectTimeoutRef.current = window.setTimeout(() => {
            if (isMounted) connect();
          }, 2500);
        };

        ws.onerror = () => {
          if (ws.readyState === WebSocket.OPEN) ws.close();
        };
      } catch (err) {
        console.error('WebSocket connection error:', err);
        reconnectTimeoutRef.current = window.setTimeout(connect, 3000);
      }
    }

    connect();

    return () => {
      isMounted = false;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [wsUrl]);

  const formatTime = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="owner-container">
      {/* Header */}
      <header className="owner-header">
        <div className="brand-section">
          <div className="brand-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7"></rect>
              <rect x="14" y="3" width="7" height="7"></rect>
              <rect x="14" y="14" width="7" height="7"></rect>
              <rect x="3" y="14" width="7" height="7"></rect>
            </svg>
          </div>
          <div>
            <h1 className="brand-title">SMARTDRIVE GUARDIAN</h1>
            <div className="brand-subtitle">Owner Safety Dashboard</div>
          </div>
        </div>

        <div className="header-right">
          <a
            href="http://localhost:5173"
            target="_blank"
            rel="noreferrer"
            className="nav-link-btn"
          >
            <span>Driver Dashboard (Port 5173) ↗</span>
          </a>

          <div className="badge">
            <span className={`status-dot ${wsConnected ? 'dot-connected' : 'dot-disconnected'}`} />
            <span>{wsConnected ? 'CONNECTED' : 'DISCONNECTED'}</span>
          </div>

          <div className="badge">
            <span className={`status-dot ${aiCameraStatus === 'CONNECTED' ? 'dot-connected' : 'dot-disconnected'}`} />
            <span>AI Camera: {aiCameraStatus}</span>
          </div>
        </div>
      </header>

      {/* Status Summary Cards */}
      <section className="status-summary-grid">
        <div className="summary-card">
          <span className="card-label">Vehicle Status</span>
          <div className="card-main-val val-online">
            <span className="status-dot dot-connected" />
            <span>ONLINE</span>
          </div>
          <span className="card-subtext">Vehicle ID: VEHICLE-01 • Highway Active</span>
        </div>

        <div className="summary-card">
          <span className="card-label">Driver Status</span>
          <div>
            <span className={`status-pill pill-${driverState.toLowerCase()}`}>
              {driverState}
            </span>
          </div>
          <span className="card-subtext">Real-time AI Attention State</span>
        </div>

        <div className="summary-card">
          <span className="card-label">Current Risk</span>
          <div>
            <span className={`risk-pill risk-${riskLevel.toLowerCase()}`}>
              {riskLevel} RISK
            </span>
          </div>
          <span className="card-subtext">Evaluated by Backend Risk Engine</span>
        </div>

        <div className="summary-card">
          <span className="card-label">Monitoring Mode</span>
          <div className="card-main-val" style={{ fontSize: '1.25rem', color: '#818cf8' }}>
            HIGHWAY ALERT
          </div>
          <span className="card-subtext">Camera + FaceLandmarker Active</span>
        </div>
      </section>

      {/* Fleet Statistics KPI Grid */}
      <section className="stats-grid">
        <div className="kpi-card">
          <span className="kpi-title">Drowsy Events</span>
          <span className="kpi-val" style={{ color: '#fbbf24' }}>
            {stats.drowsy_events_count}
          </span>
          <span className="kpi-desc">Transitions to Drowsy state</span>
        </div>

        <div className="kpi-card">
          <span className="kpi-title">Microsleep Events</span>
          <span className="kpi-val" style={{ color: '#f87171' }}>
            {stats.microsleep_events_count}
          </span>
          <span className="kpi-desc">Critical extended closures (&gt;3.0s)</span>
        </div>

        <div className="kpi-card">
          <span className="kpi-title">Average PERCLOS</span>
          <span className="kpi-val" style={{ color: '#38bdf8' }}>
            {latestPerclos.toFixed(1)}%
          </span>
          <span className="kpi-desc">Percentage of eye closure (60s window)</span>
        </div>

        <div className="kpi-card">
          <span className="kpi-title">Current Risk</span>
          <span className="kpi-val" style={{ color: riskLevel === 'HIGH' ? '#f87171' : riskLevel === 'MEDIUM' ? '#fbbf24' : '#34d399' }}>
            {riskLevel}
          </span>
          <span className="kpi-desc">Overall driver risk classification</span>
        </div>
      </section>

      {/* Recent Safety Events Table */}
      <section className="table-card">
        <div className="table-header">
          <div>
            <h3 className="table-title">Recent Safety Events</h3>
            <span className="table-subtitle">Recorded safety transitions from vehicle fleet</span>
          </div>
          <span className="badge" style={{ fontSize: '0.75rem' }}>
            {events.length} Events Logged
          </span>
        </div>

        {events.length === 0 ? (
          <div className="empty-state">
            No historical events available. Vehicle is currently operating under normal parameters.
          </div>
        ) : (
          <div className="events-table-wrapper">
            <table className="events-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Vehicle</th>
                  <th>Event Type</th>
                  <th>Risk Severity</th>
                  <th>Driver Status</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {events.map((evt) => (
                  <tr key={evt.id}>
                    <td className="time-cell">{formatTime(evt.timestamp)}</td>
                    <td>{evt.vehicle_id || 'VEHICLE-01'}</td>
                    <td>
                      <span style={{ fontWeight: 600 }}>{evt.event_type}</span>
                    </td>
                    <td>
                      <span className={`risk-pill risk-${(evt.risk_level || 'LOW').toLowerCase()}`}>
                        {evt.risk_level}
                      </span>
                    </td>
                    <td>
                      <span className={`status-pill pill-${(evt.driver_status || 'NORMAL').toLowerCase()}`}>
                        {evt.driver_status}
                      </span>
                    </td>
                    <td>{evt.description || 'State transition detected'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Footer */}
      <footer className="owner-footer">
        <div>
          <span>WebSocket Gateway: </span>
          <span className="endpoint-chip">{wsUrl}</span>
        </div>
        <div>
          <span>API Service: </span>
          <span className="endpoint-chip">{apiBase}/api/v1/safety/stats</span>
        </div>
      </footer>
    </div>
  );
}

export default App;
