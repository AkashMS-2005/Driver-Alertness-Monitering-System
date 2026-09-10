import { useState, useEffect, useRef } from 'react';
import './App.css';

export type DrowsinessState = 'NORMAL' | 'DROWSY' | 'MICROSLEEP';
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export interface DrowsinessEvent {
  id: string;
  timestamp: string;
  state: DrowsinessState;
  risk_level: RiskLevel;
  description: string;
}

export interface DrowsinessData {
  type: string;
  timestamp: string;
  state: DrowsinessState;
  risk_level: RiskLevel;
  alert_message?: string | null;
  state_changed?: boolean;
  ear: number;
  eye_closed: boolean;
  closed_duration: number;
  perclos: number;
  mar: number;
  yawning: boolean;
  recent_events?: DrowsinessEvent[];
}

const DEFAULT_DATA: DrowsinessData = {
  type: 'drowsiness_update',
  timestamp: new Date().toISOString(),
  state: 'NORMAL',
  risk_level: 'LOW',
  alert_message: 'Driver Alert',
  state_changed: false,
  ear: 0.28,
  eye_closed: false,
  closed_duration: 0.0,
  perclos: 0.0,
  mar: 0.25,
  yawning: false,
  recent_events: [],
};

function getWsUrl(): string {
  if (import.meta.env.VITE_BACKEND_WS_URL) {
    return import.meta.env.VITE_BACKEND_WS_URL;
  }
  const host = window.location.hostname || 'localhost';
  return `ws://${host}:8000/ws/drowsiness`;
}

export function App() {
  const [data, setData] = useState<DrowsinessData>(DEFAULT_DATA);
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [aiCameraStatus, setAiCameraStatus] = useState<string>('DISCONNECTED');
  const [recentEvents, setRecentEvents] = useState<DrowsinessEvent[]>([]);
  const [simMode, setSimMode] = useState<boolean>(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const pingIntervalRef = useRef<number | null>(null);
  const lastStateRef = useRef<DrowsinessState>('NORMAL');

  const wsUrl = getWsUrl();

  // Helper to add event on state change
  const addEventIfChanged = (newState: DrowsinessState, risk: RiskLevel, desc: string, timeStr?: string) => {
    if (newState !== lastStateRef.current) {
      lastStateRef.current = newState;
      const newEvent: DrowsinessEvent = {
        id: Math.random().toString(36).substring(2, 9),
        timestamp: timeStr || new Date().toISOString(),
        state: newState,
        risk_level: risk,
        description: desc,
      };
      setRecentEvents((prev) => [newEvent, ...prev].slice(0, 10));
    }
  };

  useEffect(() => {
    let isMounted = true;

    function connect() {
      if (simMode) return;

      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMounted) return;
          setWsConnected(true);
          // Keepalive ping every 15s
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
              const alertMsg = msg.alert_message || (state === 'MICROSLEEP' ? 'Immediate attention required' : state === 'DROWSY' ? 'Driver Attention Required' : 'Driver Alert');

              setData({
                ...msg,
                state,
                risk_level: risk,
                alert_message: alertMsg,
              });

              setAiCameraStatus('CONNECTED');

              // Sync recent events from backend if available, or track locally on transition
              if (msg.recent_events && Array.isArray(msg.recent_events) && msg.recent_events.length > 0) {
                setRecentEvents(msg.recent_events.slice(0, 10));
                lastStateRef.current = state;
              } else {
                addEventIfChanged(state, risk, alertMsg, msg.timestamp);
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
            if (isMounted && !simMode) {
              connect();
            }
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
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [wsUrl, simMode]);

  // Simulation test triggers
  const triggerSimulation = (presetState: DrowsinessState) => {
    setSimMode(true);
    let risk: RiskLevel = 'LOW';
    let desc = 'Driver Alert';
    let payload: DrowsinessData;

    if (presetState === 'NORMAL') {
      risk = 'LOW';
      desc = 'Driver Alert';
      payload = {
        type: 'drowsiness_update',
        timestamp: new Date().toISOString(),
        state: 'NORMAL',
        risk_level: 'LOW',
        alert_message: desc,
        ear: 0.285,
        eye_closed: false,
        closed_duration: 0.0,
        perclos: 2.1,
        mar: 0.28,
        yawning: false,
      };
    } else if (presetState === 'DROWSY') {
      risk = 'MEDIUM';
      desc = 'Driver Attention Required';
      payload = {
        type: 'drowsiness_update',
        timestamp: new Date().toISOString(),
        state: 'DROWSY',
        risk_level: 'MEDIUM',
        alert_message: desc,
        ear: 0.172,
        eye_closed: true,
        closed_duration: 1.82,
        perclos: 14.5,
        mar: 0.42,
        yawning: false,
      };
    } else {
      risk = 'HIGH';
      desc = 'IMMEDIATE ATTENTION REQUIRED';
      payload = {
        type: 'drowsiness_update',
        timestamp: new Date().toISOString(),
        state: 'MICROSLEEP',
        risk_level: 'HIGH',
        alert_message: desc,
        ear: 0.115,
        eye_closed: true,
        closed_duration: 3.45,
        perclos: 32.0,
        mar: 0.31,
        yawning: false,
      };
    }

    setData(payload);
    addEventIfChanged(presetState, risk, desc);
  };

  const resumeLiveStream = () => {
    setSimMode(false);
  };

  // State visuals mapping
  const getStateClass = () => {
    switch (data.state) {
      case 'MICROSLEEP':
        return 'state-microsleep';
      case 'DROWSY':
        return 'state-drowsy';
      default:
        return 'state-normal';
    }
  };

  const getRiskBadgeClass = () => {
    switch (data.risk_level) {
      case 'HIGH':
        return 'risk-badge-high';
      case 'MEDIUM':
        return 'risk-badge-medium';
      default:
        return 'risk-badge-low';
    }
  };

  const formatEventTime = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return isoString;
    }
  };

  // Percentage calculations
  const earPercent = Math.min(Math.max((data.ear / 0.4) * 100, 0), 100);
  const marPercent = Math.min(Math.max((data.mar / 1.0) * 100, 0), 100);
  const perclosPercent = Math.min(Math.max(data.perclos, 0), 100);

  return (
    <div className="dashboard-container">
      {/* Header */}
      <header className="dashboard-header">
        <div className="brand-section">
          <div className="brand-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.5 2.8C2.1 10.7 2 10.9 2 11.1V16c0 .6.4 1 1 1h2"></path>
              <circle cx="7" cy="17" r="2"></circle>
              <circle cx="17" cy="17" r="2"></circle>
            </svg>
          </div>
          <div>
            <h1 className="brand-title">SMARTDRIVE GUARDIAN</h1>
            <div className="brand-subtitle">Driver Drowsiness Monitoring</div>
          </div>
        </div>

        <div className="status-badges">
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

      {/* Main Drowsiness Status Card */}
      <section className={`hero-state-card ${getStateClass()}`}>
        <div className="hero-top-row">
          <div className={`hero-pill pill-${data.state.toLowerCase()}`}>
            Driver Status
          </div>
          <div className={`risk-badge ${getRiskBadgeClass()}`}>
            Risk: {data.risk_level}
          </div>
        </div>

        <h2 className="hero-state-title">{data.state}</h2>
        <p className="hero-state-subtitle">
          {data.alert_message || (data.state === 'MICROSLEEP' ? 'IMMEDIATE ATTENTION REQUIRED' : data.state === 'DROWSY' ? 'Driver Attention Required' : 'Driver Alert')}
        </p>
      </section>

      {/* Live Metrics Grid */}
      <section className="metrics-grid">
        {/* EAR Card */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">EAR</span>
            <span className="metric-tag">Threshold: 0.20</span>
          </div>
          <div className="metric-value-row">
            <span className="metric-value">{data.ear.toFixed(3)}</span>
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${earPercent}%`,
                backgroundColor: data.ear < 0.2 ? 'var(--color-microsleep)' : 'var(--color-normal)',
              }}
            />
          </div>
        </div>

        {/* Eye Status Card */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">Eye Status</span>
            <span className="metric-tag">State</span>
          </div>
          <div className="metric-value-row">
            <span className={`status-badge-lg ${data.eye_closed ? 'badge-closed' : 'badge-open'}`}>
              {data.eye_closed ? 'CLOSED' : 'OPEN'}
            </span>
          </div>
          <div className="metric-tag">
            {data.eye_closed ? 'Eyes are closed' : 'Eyes are open & alert'}
          </div>
        </div>

        {/* Closed Eye Duration Card */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">Closed Duration</span>
            <span className="metric-tag">1.5s / 3.0s</span>
          </div>
          <div className="metric-value-row">
            <span className="metric-value">
              {data.closed_duration.toFixed(2)}
              <span className="metric-unit">s</span>
            </span>
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${Math.min((data.closed_duration / 3.5) * 100, 100)}%`,
                backgroundColor:
                  data.closed_duration >= 3.0
                    ? 'var(--color-microsleep)'
                    : data.closed_duration >= 1.5
                    ? 'var(--color-drowsy)'
                    : 'var(--color-normal)',
              }}
            />
          </div>
        </div>

        {/* PERCLOS Card */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">PERCLOS</span>
            <span className="metric-tag">60s Window</span>
          </div>
          <div className="metric-value-row">
            <span className="metric-value">
              {data.perclos.toFixed(1)}
              <span className="metric-unit">%</span>
            </span>
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${perclosPercent}%`,
                backgroundColor: data.perclos >= 15 ? 'var(--color-drowsy)' : 'var(--color-normal)',
              }}
            />
          </div>
        </div>

        {/* MAR Card */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">MAR</span>
            <span className="metric-tag">Threshold: 0.60</span>
          </div>
          <div className="metric-value-row">
            <span className="metric-value">{data.mar.toFixed(3)}</span>
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${marPercent}%`,
                backgroundColor: data.yawning ? 'var(--color-drowsy)' : '#3b82f6',
              }}
            />
          </div>
        </div>

        {/* Yawning Card */}
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-title">Yawning</span>
            <span className="metric-tag">MAR ≥ 0.60</span>
          </div>
          <div className="metric-value-row">
            <span className={`status-badge-lg ${data.yawning ? 'badge-yawn-yes' : 'badge-yawn-no'}`}>
              {data.yawning ? 'YES' : 'NO'}
            </span>
          </div>
          <div className="metric-tag">
            {data.yawning ? 'Yawn event detected' : 'Mouth posture normal'}
          </div>
        </div>
      </section>

      {/* Recent Drowsiness Events Section */}
      <section className="events-section">
        <div className="events-header">
          <h3 className="events-title">Recent Drowsiness Events</h3>
          <span className="events-counter">{recentEvents.length} recorded</span>
        </div>

        {recentEvents.length === 0 ? (
          <div className="empty-events">
            No drowsiness events recorded yet. Continuous monitoring active.
          </div>
        ) : (
          <div className="events-list">
            {recentEvents.map((evt) => (
              <div key={evt.id} className="event-item">
                <span className="event-time">{formatEventTime(evt.timestamp)}</span>
                <span className={`event-state-badge badge-${evt.state.toLowerCase()}`}>
                  {evt.state}
                </span>
                <span className={`event-risk-badge risk-${evt.risk_level.toLowerCase()}`}>
                  {evt.risk_level} Risk
                </span>
                <span className="event-desc">{evt.description}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Controls & Simulator Bar */}
      <footer className="controls-bar">
        <div className="controls-info">
          <span>WebSocket Gateway:</span>
          <span className="endpoint-chip">{wsUrl}</span>
        </div>

        <div className="sim-buttons">
          <span className="sim-label">Test Visual States:</span>
          <button
            type="button"
            className="btn btn-normal"
            onClick={() => triggerSimulation('NORMAL')}
          >
            NORMAL
          </button>
          <button
            type="button"
            className="btn btn-drowsy"
            onClick={() => triggerSimulation('DROWSY')}
          >
            DROWSY
          </button>
          <button
            type="button"
            className="btn btn-microsleep"
            onClick={() => triggerSimulation('MICROSLEEP')}
          >
            MICROSLEEP
          </button>
          {simMode && (
            <button
              type="button"
              className="btn btn-active"
              onClick={resumeLiveStream}
            >
              Resume Live Stream
            </button>
          )}
        </div>
      </footer>
    </div>
  );
}

export default App;
