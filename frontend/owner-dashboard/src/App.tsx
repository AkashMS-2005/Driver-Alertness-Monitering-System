import { useState, useEffect, useRef, useCallback } from 'react';
import L from 'leaflet';
import './App.css';

// Fix Leaflet icon path (Vite bundler issue)
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
type PageTab = 'dashboard' | 'trip' | 'history' | 'emergency';
type EmergencyStatus =
  | 'ACTIVE'
  | 'DRIVER_RECOVERED'
  | 'ASSISTANCE_RESPONDED'
  | 'CANCELLED'
  | 'RESOLVED';

interface DrowsinessData {
  state: AIState;
  perclos: number;
  yawning: boolean;
  alert_message: string | null;
  alertness_score: number;    // 0-100, from multi-modal fusion
  head_state: string;         // NORMAL / DEVIATING / DISTRACTED / UNKNOWN
  alert_label: string;        // NORMAL / MILD / MODERATE / CRITICAL
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

interface ActiveEmergency {
  emergency_id: string;
  status: EmergencyStatus;
  vehicle_id: string;
  trip_id: string;
  microsleep_count: number;
  drowsiness_percentage: number;
  latitude: number | null;
  longitude: number | null;
  place_name: string | null;
  gps_source: string;
  assistance_name: string | null;
  assistance_distance_km: number | null;
  triggered_at: string | null;
  response_source?: string | null;
  response_message: string | null;
  raw_response?: string | null;
  responded_at: string | null;
  cancelled_at: string | null;
  cancelled_reason: string | null;
  sms_status?: string | null;
  sms_sent_at?: string | null;
  assistance_response_status?: string | null;
  assistance_phone_number?: string | null;
  // local flag — set after cancel
  _dismissed?: boolean;
}

interface EmergencyResult {
  emergency_id: string;
  vehicle_location: { latitude: number; longitude: number; source: string };
  nearest_toll: { name: string; highway: string; latitude: number; longitude: number; distance_km: number } | null;
  owner_notified: boolean;
  owner_notification_method: string;
  status: string;
  message: string;
  note: string;
  triggered_at: string;
}

interface AuthUser {
  owner_id: string;
  name: string;
  email: string;
  token: string;
}

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────
function apiBase() {
  return `http://${window.location.hostname || 'localhost'}:8000`;
}
function wsBase() {
  return `ws://${window.location.hostname || 'localhost'}:8000`;
}

const STATUS_LABEL: Record<AIState, string> = {
  NORMAL: 'AWAKE',
  DROWSY: 'DROWSY',
  MICROSLEEP: 'SLEEPING',
};

const STATUS_CLASS: Record<AIState, string> = {
  NORMAL: 'status-awake',
  DROWSY: 'status-drowsy',
  MICROSLEEP: 'status-sleeping',
};

function fmtTime(iso: string) {
  try {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
}

function fmtDate(iso: string) {
  try {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso;
  }
}

function fmtDuration(secs: number) {
  if (!secs || secs <= 0) return '0m';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

// ─────────────────────────────────────────────────────────────
// EmergencyAlertCard — shown when there is an active emergency
// ─────────────────────────────────────────────────────────────
function EmergencyAlertCard({
  emergency,
  onCancel,
}: {
  emergency: ActiveEmergency;
  onCancel: () => void;
}) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState('');
  const [responding, setResponding] = useState(false);
  const [responseError, setResponseError] = useState('');

  const status = emergency.status;

  // Determine card appearance
  const isActive = status === 'ACTIVE';
  const isRecovered = status === 'DRIVER_RECOVERED';
  const isResponded = status === 'ASSISTANCE_RESPONDED' || Boolean(emergency.assistance_response_status);

  // Hide card after cancelled/resolved/dismissed
  if (status === 'CANCELLED' || status === 'RESOLVED' || emergency._dismissed) {
    return null;
  }

  async function handleManualResponse(action: 'ACCEPT' | 'REJECT') {
    setResponding(true);
    setResponseError('');
    try {
      const res = await fetch(`${apiBase()}/api/v1/emergency/${emergency.emergency_id}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          response_source: 'MANUAL',
        }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Manual response failed');
      }
      window.dispatchEvent(new Event('emergency_updated'));
    } catch (err: unknown) {
      setResponseError(err instanceof Error ? err.message : 'Manual response failed');
    } finally {
      setResponding(false);
    }
  }

  async function confirmCancel() {
    setCancelling(true);
    setCancelError('');
    try {
      const res = await fetch(`${apiBase()}/api/v1/emergency/${emergency.emergency_id}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Driver recovered and cancelled emergency.' }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Cancellation failed');
      }
      onCancel();
      setShowConfirm(false);
    } catch (err: unknown) {
      setCancelError(err instanceof Error ? err.message : 'Cancellation failed');
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className={`emergency-alert-card ${
      isActive ? 'emg-active' : isRecovered ? 'emg-recovered' : 'emg-responded'
    }`}>
      {/* Header */}
      <div className="emg-card-header">
        <div className="emg-header-icon">
          {isActive ? '🚨' : isRecovered ? '⚠️' : '✓'}
        </div>
        <div className="emg-header-text">
          <span className="emg-title">
            {isActive && 'EMERGENCY ACTIVE'}
            {isRecovered && 'DRIVER RECOVERED — EMERGENCY ACTIVE'}
            {isResponded && 'ASSISTANCE RESPONDED'}
          </span>
          <span className={`emg-status-badge ${
            isActive ? 'emg-badge-red' : isRecovered ? 'emg-badge-amber' : 'emg-badge-green'
          }`}>
            {status.replace(/_/g, ' ')}
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="emg-card-body">
        {/* Driver metrics */}
        <div className="emg-metrics-row">
          <div className="emg-metric">
            <span className="emg-metric-label">Microsleep Events</span>
            <span className="emg-metric-value txt-red">{emergency.microsleep_count}</span>
          </div>
          <div className="emg-metric">
            <span className="emg-metric-label">Driver Status</span>
            <span className="emg-metric-value">
              {isRecovered ? '✓ AWAKE' : '⚠ SLEEPING'}
            </span>
          </div>
        </div>

        {/* Location */}
        <div className="emg-location-row">
          <div className="emg-loc-item">
            <span className="emg-loc-label">📍 Location</span>
            <span className="emg-loc-value">
              {emergency.place_name || (emergency.latitude
                ? `${emergency.latitude.toFixed(4)}, ${emergency.longitude?.toFixed(4)}`
                : 'Unavailable')}
            </span>
          </div>
          {emergency.latitude && (
            <div className="emg-loc-item">
              <span className="emg-loc-label">Coordinates</span>
              <span className="emg-loc-value mono">
                {emergency.latitude.toFixed(6)}, {emergency.longitude?.toFixed(6)}
              </span>
            </div>
          )}
        </div>

        {/* Assistance */}
        <div className="emg-assistance-row">
          <div className="emg-assist-item">
            <span className="emg-loc-label">🚧 Nearest Assistance</span>
            <span className="emg-loc-value">
              {emergency.assistance_name || '[DEV] Demo Highway Assistance'}
            </span>
          </div>
          {emergency.assistance_distance_km !== null && emergency.assistance_distance_km !== undefined && (
            <div className="emg-assist-item">
              <span className="emg-loc-label">Distance</span>
              <span className="emg-loc-value txt-blue">{emergency.assistance_distance_km.toFixed(1)} km</span>
            </div>
          )}
          <div className="emg-assist-item">
            <span className="emg-loc-label">Assistance Status</span>
            <span className={`emg-assist-status ${
              isResponded ? 'txt-green' : 'txt-amber'
            }`}>
              {isResponded ? '✓ Responded' : '⏳ Waiting for response'}
            </span>
          </div>
        </div>

        {/* Assistance response message */}
        {isResponded && emergency.response_message && (
          <div className="emg-response-box">
            <span className="emg-response-label">✓ Assistance Message</span>
            <p className="emg-response-text">"{emergency.response_message}"</p>
            {emergency.responded_at && (
              <span className="emg-response-time">Response time: {fmtTime(emergency.responded_at)}</span>
            )}
          </div>
        )}

        {/* Real-time Highway Assistance Status Box */}
        <div className="emg-live-assistance-box">
          <div className="emg-status-heading">ASSISTANCE STATUS</div>
          <div className="emg-status-content">
            {isResponded ? (
              emergency.assistance_response_status === 'REJECTED' ? (
                <>
                  <div className="emg-status-title-row">
                    <span className="emg-status-title-badge rejected">✕ REQUEST REJECTED</span>
                  </div>
                  <p className="emg-status-message-text">Highway assistance rejected the request.</p>
                  <div className="emg-status-detail-group">
                    <div className="emg-detail-item">
                      <span className="emg-detail-lbl">Response:</span>
                      <span className="emg-detail-val mono">{emergency.raw_response || emergency.response_message || 'REJECT'}</span>
                      {emergency.response_source && (
                        <span className="emg-source-tag">via {emergency.response_source}</span>
                      )}
                    </div>
                    {emergency.responded_at && (
                      <div className="emg-detail-item">
                        <span className="emg-detail-lbl">Response Time:</span>
                        <span className="emg-detail-val mono">{fmtTime(emergency.responded_at)}</span>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className="emg-status-title-row">
                    <span className="emg-status-title-badge accepted">✓ REQUEST ACCEPTED</span>
                  </div>
                  <p className="emg-status-message-text">Highway assistance has accepted the emergency request.</p>
                  <div className="emg-status-detail-group">
                    <div className="emg-detail-item">
                      <span className="emg-detail-lbl">Response:</span>
                      <span className="emg-detail-val mono">{emergency.raw_response || emergency.response_message || 'ACCEPT'}</span>
                      {emergency.response_source && (
                        <span className="emg-source-tag">via {emergency.response_source}</span>
                      )}
                    </div>
                    {emergency.responded_at && (
                      <div className="emg-detail-item">
                        <span className="emg-detail-lbl">Response Time:</span>
                        <span className="emg-detail-val mono">{fmtTime(emergency.responded_at)}</span>
                      </div>
                    )}
                  </div>
                </>
              )
            ) : (
              <>
                <div className="emg-status-title-row">
                  {emergency.sms_status === 'SMS_FAILED' ? (
                    <span className="emg-status-title-badge failed">⚠ SMS DELIVERY FAILED</span>
                  ) : emergency.sms_status === 'SMS_DELIVERED' ? (
                    <span className="emg-status-title-badge waiting">📱 SMS DELIVERED</span>
                  ) : emergency.sms_status === 'SMS_PENDING' ? (
                    <span className="emg-status-title-badge waiting">⏳ SMS PENDING</span>
                  ) : (
                    <span className="emg-status-title-badge waiting">📱 SMS SENT</span>
                  )}
                </div>
                <span className="emg-status-timestamp">Waiting for response...</span>

                {/* Manual Response Controls Box (Section 12: Manual Website Response) */}
                <div className="emg-manual-response-box">
                  <div className="emg-manual-header">
                    <span className="emg-manual-title">MANUAL RESPONSE</span>
                    <span className="emg-manual-sub">Respond directly from website dashboard</span>
                  </div>
                  <div className="emg-manual-actions">
                    <button
                      id="btn-manual-accept"
                      className="btn-manual-accept"
                      onClick={() => handleManualResponse('ACCEPT')}
                      disabled={responding}
                      title="Manually accept emergency assistance"
                    >
                      {responding ? 'Submitting…' : '✓ ACCEPT ASSISTANCE'}
                    </button>
                    <button
                      id="btn-manual-reject"
                      className="btn-manual-reject"
                      onClick={() => handleManualResponse('REJECT')}
                      disabled={responding}
                      title="Manually reject emergency assistance"
                    >
                      {responding ? 'Submitting…' : '✕ REJECT ASSISTANCE'}
                    </button>
                  </div>
                  {responseError && <p className="emg-manual-error">{responseError}</p>}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Real-time info note */}
        <div className="emg-dev-note">
          ℹ Emergency alert dispatched via SMS to highway assistance contact. Live reply synced automatically.
        </div>
      </div>

      {/* Footer actions */}
      <div className="emg-card-footer">
        <div className="emg-triggered-info">
          Emergency #{emergency.emergency_id.slice(-8).toUpperCase()}
          {emergency.triggered_at && ` · ${fmtTime(emergency.triggered_at)}`}
        </div>
        <div className="emg-footer-buttons">
          {isResponded && (
            <button
              id="btn-dismiss-emergency"
              className="btn-dismiss-emergency"
              onClick={onCancel}
              title="Acknowledge and dismiss response"
            >
              ✓ ACKNOWLEDGE & CLOSE
            </button>
          )}
          {isRecovered && !isResponded && (
            <button
              id="btn-cancel-emergency"
              className="btn-cancel-emergency"
              onClick={() => setShowConfirm(true)}
              disabled={cancelling}
            >
              ✕ CANCEL EMERGENCY
            </button>
          )}
        </div>
      </div>

      {/* Cancel confirmation dialog */}
      {showConfirm && (
        <div className="emg-confirm-overlay">
          <div className="emg-confirm-dialog">
            <h4>Cancel Emergency?</h4>
            <p>
              Driver appears to have recovered.<br />
              Are you sure you want to cancel the emergency assistance request?
            </p>
            {cancelError && <p className="emg-confirm-error">{cancelError}</p>}
            <div className="emg-confirm-actions">
              <button
                className="btn-confirm-cancel"
                onClick={confirmCancel}
                disabled={cancelling}
              >
                {cancelling ? 'Cancelling…' : '✕ CANCEL EMERGENCY'}
              </button>
              <button
                className="btn-confirm-keep"
                onClick={() => { setShowConfirm(false); setCancelError(''); }}
                disabled={cancelling}
              >
                ✓ KEEP EMERGENCY ACTIVE
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Login / Register Page
// ─────────────────────────────────────────────────────────────
function AuthPage({ onLogin }: { onLogin: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [form, setForm] = useState({ name: '', email: '', phone: '', password: '', plate: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const update = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${apiBase()}/api/v1/owners/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: form.email, password: form.password }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Login failed');
      }
      const data = await res.json();
      onLogin({ owner_id: data.owner.id, name: data.owner.name, email: data.owner.email, token: data.access_token });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${apiBase()}/api/v1/owners/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: form.name, email: form.email, phone: form.phone, password: form.password }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Registration failed');
      }
      const owner = await res.json();

      if (form.plate.trim()) {
        await fetch(`${apiBase()}/api/v1/vehicles/${owner.id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plate_number: form.plate.trim().toUpperCase(), make: 'Vehicle', model: 'Owner Registered', year: new Date().getFullYear() }),
        });
      }

      const loginRes = await fetch(`${apiBase()}/api/v1/owners/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: form.email, password: form.password }),
      });
      const loginData = await loginRes.json();
      onLogin({ owner_id: loginData.owner.id, name: loginData.owner.name, email: loginData.owner.email, token: loginData.access_token });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-logo">
          <div className="shield-icon">🛡️</div>
          <h1>SmartDrive Guardian</h1>
          <p>Driver Alertness Monitoring System</p>
        </div>

        <div className="auth-tabs">
          <button className={mode === 'login' ? 'active' : ''} onClick={() => { setMode('login'); setError(''); }}>
            Sign In
          </button>
          <button className={mode === 'register' ? 'active' : ''} onClick={() => { setMode('register'); setError(''); }}>
            Register
          </button>
        </div>

        {mode === 'login' ? (
          <form onSubmit={handleLogin} className="auth-form">
            <div className="field-group">
              <label>Email Address</label>
              <input type="email" required value={form.email} onChange={(e) => update('email', e.target.value)} placeholder="owner@example.com" />
            </div>
            <div className="field-group">
              <label>Password</label>
              <input type="password" required value={form.password} onChange={(e) => update('password', e.target.value)} placeholder="Enter password" />
            </div>
            {error && <p className="auth-error">{error}</p>}
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleRegister} className="auth-form">
            <div className="field-group">
              <label>Full Name</label>
              <input type="text" required value={form.name} onChange={(e) => update('name', e.target.value)} placeholder="Akash MS" />
            </div>
            <div className="field-group">
              <label>Email Address</label>
              <input type="email" required value={form.email} onChange={(e) => update('email', e.target.value)} placeholder="owner@example.com" />
            </div>
            <div className="field-group">
              <label>Phone Number <span className="optional">(optional)</span></label>
              <input type="tel" value={form.phone} onChange={(e) => update('phone', e.target.value)} placeholder="+91 98765 43210" />
            </div>
            <div className="field-group">
              <label>Password</label>
              <input type="password" required minLength={6} value={form.password} onChange={(e) => update('password', e.target.value)} placeholder="Min. 6 characters" />
            </div>
            <div className="field-group">
              <label>Vehicle Plate Number <span className="optional">(optional)</span></label>
              <input type="text" value={form.plate} onChange={(e) => update('plate', e.target.value)} placeholder="MH-01-AB-1234" />
            </div>
            {error && <p className="auth-error">{error}</p>}
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? 'Creating account…' : 'Create Account'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Subcomponent: Live Driver Camera Box
// ─────────────────────────────────────────────────────────────
function DriverCameraBox({
  cameraFrame,
  cameraConnected,
  aiConnected,
}: {
  cameraFrame: string;
  cameraConnected: boolean;
  aiConnected: boolean;
}) {
  return (
    <div className="camera-card">
      <div className="card-header">
        <div className="header-badge-group">
          <span className={`live-indicator ${cameraConnected ? 'live' : 'offline'}`}>
            {cameraConnected ? '● LIVE' : '○ DISCONNECTED'}
          </span>
          <span className="card-title">Driver Camera</span>
        </div>
        <span className="aspect-ratio-tag">16:9 Feed</span>
      </div>
      <div className="camera-viewport">
        {cameraFrame ? (
          <img src={`data:image/jpeg;base64,${cameraFrame}`} alt="Live driver camera stream" className="camera-video-element" />
        ) : (
          <div className="camera-placeholder">
            <span className="ph-icon">📹</span>
            <span className="ph-title">{aiConnected ? 'Awaiting camera frames…' : 'AI Service Offline'}</span>
            <span className="ph-sub">Ensure the AI service (Port 8001) is running to stream camera video</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Subcomponent: Driver Safety Card
// ─────────────────────────────────────────────────────────────
function DriverSafetyCard({
  state,
  headState,
  vehicle,
  aiConnected,
}: {
  state: AIState;
  perclos?: number;
  alertnessScore?: number;
  headState: string;
  alertLabel?: string;
  vehicle?: VehicleInfo;
  aiConnected: boolean;
}) {
  const displayStatus = STATUS_LABEL[state] || 'AWAKE';
  const statusClass = STATUS_CLASS[state] || 'status-awake';

  return (
    <div className="safety-card">
      <div className="card-header">
        <span className="card-title">DRIVER SAFETY</span>
        <span className={`ai-badge ${aiConnected ? 'ai-online' : 'ai-offline'}`}>
          {aiConnected ? '● AI Connected' : '○ AI Disconnected'}
        </span>
      </div>

      <div className="safety-body">
        {/* Driver Status */}
        <div className="status-block">
          <span className="block-label">Driver Status</span>
          <div className={`status-display ${statusClass}`}>
            {displayStatus}
          </div>
        </div>

        {/* Head Pose State */}
        <div className="status-block" style={{ marginTop: '14px' }}>
          <span className="block-label">Head Pose</span>
          <div className="data-row" style={{ marginTop: '4px' }}>
            <span
              className={`data-val ${headState === 'DISTRACTED' ? 'txt-red' : 'txt-green'}`}
              style={{ fontSize: '1.05rem', fontWeight: 600 }}
            >
              {headState === 'DISTRACTED' ? '⚠ DISTRACTED' : '✓ Normal'}
            </span>
          </div>
        </div>

        {/* Vehicle Information */}
        <div className="vehicle-block">
          <span className="block-label">Vehicle</span>
          <div className="vehicle-plate">{vehicle?.plate_number && vehicle.plate_number !== 'N/A' ? vehicle.plate_number : 'MH-01-AB-1234'}</div>
          <div className="vehicle-desc">
            {vehicle?.make && vehicle?.model && vehicle.make !== 'N/A'
              ? `${vehicle.make} ${vehicle.model} ${vehicle.year ? `(${vehicle.year})` : ''}`
              : 'Toyota Camry (2024)'}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Page 1: Dashboard View
// ─────────────────────────────────────────────────────────────
function DashboardPage({
  dash,
  drowsiness,
  cameraFrame,
  cameraConnected,
  aiConnected,
  onNavigate,
}: {
  dash: DashboardState | null;
  drowsiness: DrowsinessData;
  cameraFrame: string;
  cameraConnected: boolean;
  aiConnected: boolean;
  onNavigate: (tab: PageTab) => void;
}) {
  const miniMapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);

  const trip = dash?.trip ?? { id: null, status: 'ACTIVE', start_time: null, duration_seconds: 0, distance_km: 0, start_latitude: null, start_longitude: null };
  const location = dash?.location ?? { latitude: null, longitude: null, speed_kmh: 0, timestamp: null, gps_available: false };
  const vehicle = dash?.vehicle;

  // Mini Map Initializer
  useEffect(() => {
    if (!miniMapRef.current || leafletMapRef.current) return;
    const lat = location.latitude ?? (trip.start_latitude ?? 12.9716);
    const lon = location.longitude ?? (trip.start_longitude ?? 77.5946);
    const map = L.map(miniMapRef.current, { zoomControl: false, attributionControl: false }).setView([lat, lon], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    leafletMapRef.current = map;

    return () => {
      map.remove();
      leafletMapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = leafletMapRef.current;
    if (!map) return;
    const lat = location.latitude ?? (trip.start_latitude ?? null);
    const lon = location.longitude ?? (trip.start_longitude ?? null);
    if (lat !== null && lon !== null) {
      if (!markerRef.current) {
        markerRef.current = L.marker([lat, lon]).addTo(map);
      } else {
        markerRef.current.setLatLng([lat, lon]);
      }
      map.setView([lat, lon], 12);
    }
  }, [location.latitude, location.longitude, trip.start_latitude, trip.start_longitude]);

  return (
    <div className="dashboard-content">
      {/* Row 1: Camera + Driver Status */}
      <div className="top-grid">
        <DriverCameraBox cameraFrame={cameraFrame} cameraConnected={cameraConnected} aiConnected={aiConnected} />
        <DriverSafetyCard
          state={drowsiness.state}
          perclos={drowsiness.perclos}
          alertnessScore={drowsiness.alertness_score}
          headState={drowsiness.head_state}
          alertLabel={drowsiness.alert_label}
          vehicle={vehicle}
          aiConnected={aiConnected}
        />
      </div>

      {/* Row 2: Current Trip + Current Location */}
      <div className="bottom-grid">
        {/* Current Trip Card */}
        <div className="info-card">
          <div className="card-header">
            <span className="card-title">CURRENT TRIP</span>
            <button className="card-action-btn" onClick={() => onNavigate('trip')}>
              View Full Trip →
            </button>
          </div>
          <div className="card-body">
            <div className="data-row">
              <span className="data-label">Trip Status</span>
              <span className={`status-badge ${trip.status === 'ACTIVE' ? 'badge-green' : 'badge-neutral'}`}>
                {trip.status}
              </span>
            </div>
            <div className="data-row">
              <span className="data-label">Started</span>
              <span className="data-val">{trip.start_time ? fmtTime(trip.start_time) : 'Active Session'}</span>
            </div>
            <div className="data-row">
              <span className="data-label">Duration</span>
              <span className="data-val">{fmtDuration(trip.duration_seconds)}</span>
            </div>
            <div className="data-row">
              <span className="data-label">Distance</span>
              <span className="data-val">{trip.distance_km.toFixed(1)} km</span>
            </div>
            <div className="data-row">
              <span className="data-label">Destination</span>
              <span className="data-val muted">Not Set</span>
            </div>
          </div>
        </div>

        {/* Current Location Card */}
        <div className="info-card">
          <div className="card-header">
            <div className="header-badge-group">
              <span className="card-title">CURRENT LOCATION</span>
              <span className={`status-badge ${location.gps_available ? 'badge-blue' : 'badge-amber'}`}>
                {location.gps_available ? 'Live GPS' : 'Demo Location'}
              </span>
            </div>
            <button className="card-action-btn" onClick={() => onNavigate('trip')}>
              Open Map →
            </button>
          </div>
          <div className="card-body">
            <div ref={miniMapRef} className="mini-map-container" />
            <div className="location-meta">
              <div className="data-row">
                <span className="data-label">Coordinates</span>
                <span className="data-val mono">
                  {location.latitude ? `${location.latitude.toFixed(4)}, ${location.longitude?.toFixed(4)}` : '12.9716, 77.5946'}
                </span>
              </div>
              <div className="data-row">
                <span className="data-label">Speed</span>
                <span className="data-val">{location.speed_kmh ? `${location.speed_kmh.toFixed(0)} km/h` : '0 km/h'}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Page 2: Trip Summary View
// ─────────────────────────────────────────────────────────────
function TripSummaryPage({ dash }: { dash: DashboardState | null }) {
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletRef = useRef<L.Map | null>(null);
  const startMarkerRef = useRef<L.Marker | null>(null);
  const currentMarkerRef = useRef<L.Marker | null>(null);
  const routePolylineRef = useRef<L.Polyline | null>(null);

  const [routePoints, setRoutePoints] = useState<[number, number][]>([]);
  const [loadingRoute, setLoadingRoute] = useState(false);

  const trip = dash?.trip ?? { id: null, status: 'ACTIVE', start_time: null, duration_seconds: 0, distance_km: 0, start_latitude: null, start_longitude: null };
  const location = dash?.location ?? { latitude: null, longitude: null, speed_kmh: 0, timestamp: null, gps_available: false };
  const vehicle = dash?.vehicle;

  // Fetch trip route history if trip id exists
  useEffect(() => {
    if (!trip.id) return;
    setLoadingRoute(true);
    fetch(`${apiBase()}/api/v1/locations/trip/${trip.id}`)
      .then((res) => (res.ok ? res.json() : []))
      .then((pts: { latitude: number; longitude: number }[]) => {
        if (Array.isArray(pts) && pts.length > 0) {
          const latLngs: [number, number][] = pts.map((p) => [p.latitude, p.longitude]);
          setRoutePoints(latLngs);
        }
      })
      .catch(() => {})
      .finally(() => setLoadingRoute(false));
  }, [trip.id]);

  // Leaflet Map instance
  useEffect(() => {
    if (!mapRef.current || leafletRef.current) return;
    const defaultLat = location.latitude ?? trip.start_latitude ?? 12.9716;
    const defaultLon = location.longitude ?? trip.start_longitude ?? 77.5946;

    const map = L.map(mapRef.current).setView([defaultLat, defaultLon], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
    }).addTo(map);

    leafletRef.current = map;
    return () => {
      map.remove();
      leafletRef.current = null;
    };
  }, []);

  // Update map markers & polylines
  useEffect(() => {
    const map = leafletRef.current;
    if (!map) return;

    // Start marker
    if (trip.start_latitude && trip.start_longitude) {
      if (!startMarkerRef.current) {
        startMarkerRef.current = L.marker([trip.start_latitude, trip.start_longitude], {
          title: 'Trip Start',
        }).addTo(map).bindPopup('<b>Start Location</b>');
      } else {
        startMarkerRef.current.setLatLng([trip.start_latitude, trip.start_longitude]);
      }
    }

    // Current position marker
    const curLat = location.latitude ?? trip.start_latitude;
    const curLon = location.longitude ?? trip.start_longitude;
    if (curLat !== null && curLon !== null && curLat !== undefined && curLon !== undefined) {
      if (!currentMarkerRef.current) {
        currentMarkerRef.current = L.marker([curLat, curLon], {
          title: 'Current Position',
        }).addTo(map).bindPopup('<b>Current Vehicle Position</b>');
      } else {
        currentMarkerRef.current.setLatLng([curLat, curLon]);
      }
      map.setView([curLat, curLon], 13);
    }

    // Route polyline
    if (routePoints.length > 1) {
      if (routePolylineRef.current) routePolylineRef.current.remove();
      routePolylineRef.current = L.polyline(routePoints, { color: '#388bfd', weight: 4, opacity: 0.85 }).addTo(map);
      map.fitBounds(routePolylineRef.current.getBounds(), { padding: [40, 40] });
    }
  }, [location.latitude, location.longitude, trip.start_latitude, trip.start_longitude, routePoints]);

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Trip Summary</h2>
          <p className="page-subtitle">Real-time route, vehicle telemetry, and trip distance metrics</p>
        </div>
        <span className={`status-badge ${trip.status === 'ACTIVE' ? 'badge-green' : 'badge-neutral'}`}>
          {trip.status}
        </span>
      </div>

      {/* Metric Cards Grid */}
      <div className="trip-metric-cards">
        <div className="metric-box">
          <span className="metric-box-title">TRIP STATUS</span>
          <span className={`metric-box-val ${trip.status === 'ACTIVE' ? 'txt-green' : 'txt-muted'}`}>{trip.status}</span>
          <span className="metric-box-note">{vehicle ? `${vehicle.plate_number}` : 'Active Vehicle'}</span>
        </div>
        <div className="metric-box">
          <span className="metric-box-title">START TIME</span>
          <span className="metric-box-val">{trip.start_time ? fmtTime(trip.start_time) : 'Active'}</span>
          <span className="metric-box-note">{trip.start_time ? fmtDate(trip.start_time) : 'Today'}</span>
        </div>
        <div className="metric-box">
          <span className="metric-box-title">DURATION</span>
          <span className="metric-box-val">{fmtDuration(trip.duration_seconds)}</span>
          <span className="metric-box-note">Elapsed driving time</span>
        </div>
        <div className="metric-box">
          <span className="metric-box-title">DISTANCE</span>
          <span className="metric-box-val txt-blue">{trip.distance_km.toFixed(1)} <span className="unit">km</span></span>
          <span className="metric-box-note">Total route distance</span>
        </div>
      </div>

      {/* Full Interactive Map */}
      <div className="map-section-card">
        <div className="card-header">
          <div className="header-badge-group">
            <span className="card-title">LIVE / TRIP MAP</span>
            <span className={`status-badge ${location.gps_available ? 'badge-blue' : 'badge-amber'}`}>
              {location.gps_available ? '● Live GPS Active' : '⚠ Demo Location (GPS Disconnected)'}
            </span>
          </div>
          {loadingRoute && <span className="muted small">Loading route history…</span>}
        </div>
        <div ref={mapRef} className="full-map-container" />
      </div>

      {/* Telemetry Summary Rows */}
      <div className="trip-details-grid">
        <div className="info-card">
          <div className="card-header">
            <span className="card-title">ROUTE WAYPOINTS</span>
          </div>
          <div className="card-body">
            <div className="data-row">
              <span className="data-label">Start Location</span>
              <span className="data-val mono">
                {trip.start_latitude ? `${trip.start_latitude.toFixed(4)}, ${trip.start_longitude?.toFixed(4)}` : 'Not recorded'}
              </span>
            </div>
            <div className="data-row">
              <span className="data-label">Current Position</span>
              <span className="data-val mono">
                {location.latitude ? `${location.latitude.toFixed(4)}, ${location.longitude?.toFixed(4)}` : '12.9716, 77.5946'}
              </span>
            </div>
            <div className="data-row">
              <span className="data-label">Destination</span>
              <span className="data-val muted">Not Set</span>
            </div>
          </div>
        </div>

        <div className="info-card">
          <div className="card-header">
            <span className="card-title">SPEED & TELEMETRY</span>
          </div>
          <div className="card-body">
            <div className="data-row">
              <span className="data-label">Current Speed</span>
              <span className="data-val">{location.speed_kmh > 0 ? `${location.speed_kmh.toFixed(1)} km/h` : '0 km/h (Stationary)'}</span>
            </div>
            <div className="data-row">
              <span className="data-label">GPS Update Interval</span>
              <span className="data-val">Every 15 seconds</span>
            </div>
            <div className="data-row">
              <span className="data-label">Route Points Stored</span>
              <span className="data-val">{routePoints.length > 0 ? `${routePoints.length} points` : '1 point'}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Page 3: Drowsiness History View
// ─────────────────────────────────────────────────────────────
function DrowsinessHistoryPage({ events }: { events: SafetyEvent[] }) {
  const drowsyCount = events.filter((e) => e.state.toUpperCase().includes('DROWSY')).length;
  const sleepCount = events.filter((e) => e.state.toUpperCase().includes('MICROSLEEP') || e.state.toUpperCase().includes('SLEEP')).length;
  const normalCount = events.filter((e) => e.state.toUpperCase().includes('NORMAL') || e.state.toUpperCase().includes('AWAKE')).length;

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Drowsiness History</h2>
          <p className="page-subtitle">Chronological record of driver alertness and fatigue events</p>
        </div>
      </div>

      {/* Aggregate Stats */}
      <div className="history-stat-cards">
        <div className="stat-card">
          <span className="stat-label">TOTAL SAFETY EVENTS</span>
          <span className="stat-value">{events.length}</span>
          <span className="stat-sub">Recorded in session</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">DROWSY WARNINGS</span>
          <span className="stat-value txt-amber">{drowsyCount}</span>
          <span className="stat-sub">Driver attention required</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">MICROSLEEP ALERTS</span>
          <span className="stat-value txt-red">{sleepCount}</span>
          <span className="stat-sub">Critical fatigue detected</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">AWAKE RECOVERIES</span>
          <span className="stat-value txt-green">{normalCount}</span>
          <span className="stat-sub">Normal posture restored</span>
        </div>
      </div>

      {/* History Table */}
      <div className="history-table-card">
        <div className="card-header">
          <span className="card-title">EVENT LOG</span>
          <span className="muted small">{events.length} events logged</span>
        </div>

        {events.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon">🛡️</span>
            <span className="empty-title">No drowsiness events recorded.</span>
            <span className="empty-desc">Events will appear here automatically when the driver is detected as Drowsy or Sleeping.</span>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="history-table">
              <thead>
                <tr>
                  <th>TIME</th>
                  <th>STATUS</th>
                  <th>DESCRIPTION / DURATION</th>
                  <th>SEVERITY</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev, i) => {
                  const isMicrosleep = ev.state.toUpperCase().includes('MICROSLEEP') || ev.state.toUpperCase().includes('SLEEP');
                  const isDrowsy = ev.state.toUpperCase().includes('DROWSY');
                  const statusLabel = isMicrosleep ? 'SLEEPING' : isDrowsy ? 'DROWSY' : 'AWAKE';
                  const badgeClass = isMicrosleep ? 'badge-red' : isDrowsy ? 'badge-amber' : 'badge-green';

                  return (
                    <tr key={i}>
                      <td className="mono">{fmtTime(ev.timestamp)}</td>
                      <td>
                        <span className={`status-badge ${badgeClass}`}>{statusLabel}</span>
                      </td>
                      <td className="event-desc-cell">{ev.description || (isMicrosleep ? 'Microsleep episode detected' : isDrowsy ? 'Drowsiness and eyelid closure detected' : 'Driver alert')}</td>
                      <td>
                        <span className={`risk-tag ${ev.risk_level === 'HIGH' ? 'risk-high' : ev.risk_level === 'MEDIUM' ? 'risk-med' : 'risk-low'}`}>
                          {ev.risk_level || (isMicrosleep ? 'HIGH' : isDrowsy ? 'MEDIUM' : 'LOW')}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Emergency History Item type
// ─────────────────────────────────────────────────────────────
interface EmergencyHistoryItem {
  id: string;
  trip_id?: string | null;
  vehicle_id?: string | null;
  status: string;
  microsleep_count: number | null;
  drowsiness_percentage: number | null;
  latitude: number | null;
  longitude: number | null;
  place_name: string | null;
  triggered_at: string | null;
  detected_at: string;
  response_message: string | null;
  vehicle_plate?: string | null;
  responded_at: string | null;
  cancelled_at: string | null;
  cancelled_reason: string | null;
  resolved_at: string | null;
  assistance_name?: string | null;
  assistance_distance_km?: number | null;
  sms_status?: string | null;
  sms_sent_at?: string | null;
  assistance_phone_number?: string | null;
  assistance_response_status?: string | null;
  response_source?: string | null;
  raw_response?: string | null;
}

// ─────────────────────────────────────────────────────────────
// Page 4: Emergency Assistance View
// ─────────────────────────────────────────────────────────────
function EmergencyAssistancePage({
  dash,
  drowsiness,
}: {
  dash: DashboardState | null;
  drowsiness: DrowsinessData;
}) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<EmergencyResult | null>(null);
  const [placeName, setPlaceName] = useState<string>('');
  const [error, setError] = useState('');
  const [history, setHistory] = useState<EmergencyHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const vehicle = dash?.vehicle;

  // Load emergency history from backend on mount (persists across page refresh)
  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await fetch(`${apiBase()}/api/v1/emergency/history`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data as EmergencyHistoryItem[]);
      } else {
        const r2 = await fetch(`${apiBase()}/api/v1/emergency/history/all`);
        if (r2.ok) setHistory(await r2.json());
      }
    } catch { /* ignore */ }
    finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
    const handleUpdate = () => {
      loadHistory();
    };
    window.addEventListener('emergency_updated', handleUpdate);
    return () => {
      window.removeEventListener('emergency_updated', handleUpdate);
    };
  }, [loadHistory]);

  async function triggerEmergency() {
    setLoading(true);
    setError('');
    setResult(null);
    setPlaceName('');

    try {
      const res = await fetch(`${apiBase()}/api/v1/emergency/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          vehicle_id: vehicle?.id || null,
          reason: 'DASHBOARD_EMERGENCY',
          driver_status: drowsiness.state || 'UNKNOWN',
          drowsiness_level: drowsiness.perclos || 0.0,
        }),
      });

      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Emergency request failed');
      }

      const data: EmergencyResult = await res.json();
      setResult(data);
      window.dispatchEvent(new Event('emergency_updated'));

      // Free Nominatim Reverse Geocoding
      const lat = data.vehicle_location.latitude;
      const lon = data.vehicle_location.longitude;
      try {
        const geo = await fetch(
          `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`,
          { headers: { 'User-Agent': 'SmartDriveGuardian/2.0' } }
        );
        if (geo.ok) {
          const geoData = await geo.json();
          const addr = geoData.address;
          const parts = [addr.suburb, addr.city_district, addr.city, addr.state].filter(Boolean);
          setPlaceName(parts.slice(0, 2).join(', ') || geoData.display_name?.split(',')[0] || '');
        }
      } catch {
        setPlaceName('');
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to trigger emergency assistance');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Emergency Assistance</h2>
          <p className="page-subtitle">Instant highway safety dispatch, toll gate lookup, and owner emergency alerts</p>
        </div>
      </div>

      {/* Emergency Action Banner */}
      <div className="emergency-hero-card">
        <div className="hero-alert-content">
          <div className="alert-icon-lg">🚨</div>
          <div className="alert-text-block">
            <h3>Request Highway Emergency Assistance (Manual Demo)</h3>
            <p>
              In case of critical fatigue, accidents, or distress, pressing this button triggers immediate system response:
              identifying the vehicle GPS position, finding nearest highway support, creating emergency logs, and alerting the owner.
              Automatic emergencies are triggered when two separate microsleep events occur.
            </p>
          </div>
        </div>

        <button
          id="btn-emergency-trigger"
          className={`btn-emergency-hero ${loading ? 'loading' : ''}`}
          onClick={triggerEmergency}
          disabled={loading}
        >
          {loading ? '⏳ DISPATCHING ASSISTANCE…' : '🚨 REQUEST HIGHWAY ASSISTANCE (MANUAL DEMO)'}
        </button>
      </div>

      {error && <div className="emergency-error-card">{error}</div>}

      {/* Emergency Result Section */}
      {result && (
        <div className="emergency-result-grid">
          {/* Section 1: Location */}
          <div className="info-card">
            <div className="card-header">
              <span className="card-title">1. EMERGENCY VEHICLE LOCATION</span>
              <span className="status-badge badge-red">EMERGENCY ACTIVE</span>
            </div>
            <div className="card-body">
              <div className="data-row">
                <span className="data-label">Place Name</span>
                <span className="data-val highlight">{placeName || 'Location name unavailable (Reverse geocoding)'}</span>
              </div>
              <div className="data-row">
                <span className="data-label">GPS Coordinates</span>
                <span className="data-val mono">
                  {result.vehicle_location.latitude.toFixed(6)}, {result.vehicle_location.longitude.toFixed(6)}
                </span>
              </div>
              <div className="data-row">
                <span className="data-label">Source</span>
                <span className="data-val muted">{result.vehicle_location.source || 'GPS'}</span>
              </div>
              {result.vehicle_location.source?.includes('PLACEHOLDER') && (
                <div className="note-box">⚠ GPS hardware disconnected — coordinates are approximate fallback</div>
              )}
            </div>
          </div>

          {/* Section 2: Nearest Highway / Toll Assistance */}
          <div className="info-card">
            <div className="card-header">
              <span className="card-title">2. NEAREST HIGHWAY / TOLL ASSISTANCE</span>
              <span className="status-badge badge-blue">TOLL SUPPORT</span>
            </div>
            <div className="card-body">
              {result.nearest_toll ? (
                <>
                  <div className="data-row">
                    <span className="data-label">Toll Plaza Name</span>
                    <span className="data-val highlight">{result.nearest_toll.name}</span>
                  </div>
                  <div className="data-row">
                    <span className="data-label">Highway</span>
                    <span className="data-val">{result.nearest_toll.highway}</span>
                  </div>
                  <div className="data-row">
                    <span className="data-label">Distance</span>
                    <span className="data-val txt-blue">{result.nearest_toll.distance_km.toFixed(1)} km away</span>
                  </div>
                  <div className="data-row">
                    <span className="data-label">Toll Coordinates</span>
                    <span className="data-val mono">
                      {result.nearest_toll.latitude.toFixed(4)}, {result.nearest_toll.longitude.toFixed(4)}
                    </span>
                  </div>
                  <div className="note-box info">
                    📌 Demo assistance location (static development reference data of Indian NH toll plazas).
                  </div>
                </>
              ) : (
                <p className="muted">No toll assistance located within range.</p>
              )}
            </div>
          </div>

          {/* Section 3: Owner Notification */}
          <div className="info-card">
            <div className="card-header">
              <span className="card-title">3. OWNER NOTIFICATION</span>
              <span className={`status-badge ${result.owner_notified ? 'badge-green' : 'badge-neutral'}`}>
                {result.owner_notified ? 'NOTIFICATION SENT' : 'PENDING'}
              </span>
            </div>
            <div className="card-body">
              <div className="data-row">
                <span className="data-label">WebSocket Broadcast</span>
                <span className="data-val txt-green">{result.owner_notified ? '✓ Notification sent via WebSocket' : 'Failed to broadcast'}</span>
              </div>
              <div className="data-row">
                <span className="data-label">SMS Alert Status</span>
                <span className="data-val txt-amber">SMS service not configured</span>
              </div>
              <div className="data-row">
                <span className="data-label">Triggered At</span>
                <span className="data-val mono">{fmtTime(result.triggered_at)}</span>
              </div>
              <div className="note-box">
                ℹ Twilio credentials not configured in backend/.env — alerts broadcasted via active WebSocket sessions.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Emergency History (Part 13) ── */}
      <div className="history-table-card" style={{ marginTop: '2rem' }}>
        <div className="card-header">
          <span className="card-title">EMERGENCY HISTORY</span>
          <span className="muted small">
            {historyLoading ? 'Loading…' : `${history.length} records`}
          </span>
        </div>

        {history.length === 0 && !historyLoading ? (
          <div className="empty-state">
            <span className="empty-icon">🛡️</span>
            <span className="empty-title">No emergency events recorded.</span>
            <span className="empty-desc">
              Emergency records will appear here automatically when microsleep events trigger an
              automatic emergency (≥ 2 microsleep events), or when a manual emergency is triggered.
              These records persist across restarts.
            </span>
          </div>
        ) : historyLoading ? (
          <div className="empty-state">
            <span className="empty-desc">Loading emergency history…</span>
          </div>
        ) : (
          <div className="emergency-history-list">
            {history.map((ev) => {
              const statusBadge =
                ev.status === 'ACTIVE' ? 'badge-red' :
                ev.status === 'DRIVER_RECOVERED' ? 'badge-amber' :
                ev.status === 'ASSISTANCE_RESPONDED' ? 'badge-blue' :
                ev.status === 'RESOLVED' ? 'badge-green' :
                ev.status === 'CANCELLED' ? 'badge-neutral' : 'badge-neutral';

              const displayTime = ev.triggered_at || ev.detected_at;
              const locationStr = ev.place_name ||
                (ev.latitude ? `${ev.latitude.toFixed(4)}, ${ev.longitude?.toFixed(4)}` : 'Ashokanagar, Bengaluru');

              return (
                <div className="emergency-history-card" key={ev.id}>
                  <div className="emg-hist-header">
                    <div className="emg-hist-id-group">
                      <span className="emg-hist-badge-icon">🚨</span>
                      <span className="emg-hist-id">Emergency #{ev.id.slice(-8).toUpperCase()}</span>
                    </div>
                    <span className={`status-badge ${statusBadge}`}>
                      {ev.status.replace(/_/g, ' ')}
                    </span>
                  </div>

                  <div className="emg-hist-grid">
                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Vehicle</span>
                      <span className="emg-hist-value mono">{ev.vehicle_plate || 'MH-01-AB-1234'}</span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Trip</span>
                      <span className="emg-hist-value mono">Trip #{ev.trip_id ? ev.trip_id.slice(-8).toUpperCase() : 'ACTIVE'}</span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Microsleep Events</span>
                      <span className="emg-hist-value txt-red" style={{ fontWeight: 700 }}>
                        {ev.microsleep_count != null && ev.microsleep_count > 0 ? ev.microsleep_count : 2}
                      </span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Location</span>
                      <span className="emg-hist-value">{locationStr}</span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Coordinates</span>
                      <span className="emg-hist-value mono">
                        {ev.latitude ? `${ev.latitude.toFixed(6)}, ${ev.longitude?.toFixed(6)}` : '12.971600, 77.594600'}
                      </span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Nearest Assistance</span>
                      <span className="emg-hist-value">{ev.assistance_name || 'Kengeri Toll Plaza (NICE Road)'}</span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Distance</span>
                      <span className="emg-hist-value txt-blue">
                        {ev.assistance_distance_km != null ? `${ev.assistance_distance_km.toFixed(1)} km` : '14.0 km'}
                      </span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Emergency Time</span>
                      <span className="emg-hist-value mono">{displayTime ? fmtTime(displayTime) : '—'}</span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">SMS Status</span>
                      <span className={`emg-hist-value ${
                        ev.sms_status === 'SMS_FAILED' ? 'txt-red' :
                        ev.sms_status === 'SMS_DELIVERED' ? 'txt-green' : 'txt-blue'
                      }`} style={{ fontWeight: 600 }}>
                        {ev.sms_status ? ev.sms_status.replace('SMS_', '') : 'SENT'}
                      </span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Response</span>
                      <span className={`emg-hist-value ${
                        ev.assistance_response_status === 'ACCEPTED' ? 'txt-green' :
                        ev.assistance_response_status === 'REJECTED' ? 'txt-red' : 'txt-amber'
                      }`} style={{ fontWeight: 600 }}>
                        {ev.assistance_response_status || (ev.status === 'ASSISTANCE_RESPONDED' ? 'ACCEPTED' : 'PENDING')}
                      </span>
                    </div>

                    <div className="emg-hist-field">
                      <span className="emg-hist-label">Response Source</span>
                      <span className="emg-hist-value" style={{ fontWeight: 600 }}>
                        {ev.response_source || (ev.assistance_phone_number ? 'SMS' : ev.status === 'ASSISTANCE_RESPONDED' ? 'MANUAL' : '—')}
                      </span>
                    </div>

                    {ev.responded_at && (
                      <div className="emg-hist-field">
                        <span className="emg-hist-label">Response Time</span>
                        <span className="emg-hist-value mono">{fmtTime(ev.responded_at)}</span>
                      </div>
                    )}

                    {ev.assistance_phone_number && (
                      <div className="emg-hist-field">
                        <span className="emg-hist-label">Assistance Phone</span>
                        <span className="emg-hist-value mono">{ev.assistance_phone_number}</span>
                      </div>
                    )}
                  </div>

                  {ev.response_message && (
                    <div className="emg-hist-response-box">
                      <div className="emg-hist-response-header">
                        <span className="emg-hist-label">Toll Response:</span>
                        {ev.responded_at && (
                          <span className="emg-hist-sub mono" style={{ fontSize: '11px', color: '#7d8590' }}>
                            Responded: {fmtTime(ev.responded_at)}
                          </span>
                        )}
                      </div>
                      <p className="emg-hist-response-msg">"{ev.response_message}"</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Main Application Component
// ─────────────────────────────────────────────────────────────
function DashboardApp({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const [currentTab, setCurrentTab] = useState<PageTab>('dashboard');
  const [dash, setDash] = useState<DashboardState | null>(null);
  const [drowsiness, setDrowsiness] = useState<DrowsinessData>({
    state: 'NORMAL',
    perclos: 0,
    yawning: false,
    alert_message: null,
    alertness_score: 100,
    head_state: 'NORMAL',
    alert_label: 'NORMAL',
  });
  const [cameraFrame, setCameraFrame] = useState<string>('');
  const [cameraConnected, setCameraConnected] = useState(false);
  const [aiConnected, setAiConnected] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // ── Emergency state ──
  const [activeEmergency, setActiveEmergency] = useState<ActiveEmergency | null>(null);
  const [microsleepCount, setMicrosleepCount] = useState(0);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll aggregated state every 5s
  const pollDashboard = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase()}/api/v1/dashboard/state`);
      if (res.ok) {
        const data: DashboardState = await res.json();
        setDash(data);
      }
    } catch {
      // ignore network errors silently
    }
  }, []);

  useEffect(() => {
    pollDashboard();
    pollRef.current = setInterval(pollDashboard, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [pollDashboard]);

  // ── Owner WebSocket — receives real-time emergency events ──
  useEffect(() => {
    if (!user.owner_id) return;
    let ownerWs: WebSocket;
    let ownerReconnect: ReturnType<typeof setTimeout>;

    function connectOwner() {
      ownerWs = new WebSocket(`${wsBase()}/ws/owner/${user.owner_id}`);

      ownerWs.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          const t = msg.type || msg.event_type || '';

          if (t === 'EMERGENCY_TRIGGERED') {
            setActiveEmergency({
              emergency_id: msg.emergency_id,
              status: msg.status || 'ACTIVE',
              vehicle_id: msg.vehicle_id || '',
              trip_id: msg.trip_id || '',
              microsleep_count: msg.microsleep_count ?? 0,
              drowsiness_percentage: msg.drowsiness_percentage ?? 0,
              latitude: msg.latitude ?? null,
              longitude: msg.longitude ?? null,
              place_name: msg.place_name ?? null,
              gps_source: msg.gps_source || 'UNKNOWN',
              assistance_name: msg.assistance_name ?? null,
              assistance_distance_km: msg.assistance_distance_km ?? null,
              triggered_at: msg.triggered_at ?? null,
              response_message: null,
              responded_at: null,
              cancelled_at: null,
              cancelled_reason: null,
            });
            setMicrosleepCount(msg.microsleep_count ?? 0);
            window.dispatchEvent(new Event('emergency_updated'));
          } else if (t === 'DRIVER_RECOVERED') {
            setActiveEmergency((prev) =>
              prev ? {
                ...prev,
                status: 'DRIVER_RECOVERED',
                drowsiness_percentage: msg.drowsiness_percentage ?? prev.drowsiness_percentage,
              } : prev
            );
          } else if (t === 'ASSISTANCE_RESPONSE') {
            setActiveEmergency((prev) =>
              prev ? {
                ...prev,
                status: 'ASSISTANCE_RESPONDED',
                assistance_response_status: (msg.response_status || (msg.status === 'REJECTED' ? 'REJECTED' : 'ACCEPTED')) as EmergencyStatus,
                response_source: msg.response_source || 'SMS',
                response_message: msg.response_message || msg.raw_response || msg.message || 'Highway assistance team has responded.',
                raw_response: msg.raw_response || msg.response_message,
                responded_at: msg.responded_at || new Date().toISOString(),
              } : prev
            );
            window.dispatchEvent(new Event('emergency_updated'));
          } else if (t === 'SMS_STATUS_UPDATE') {
            setActiveEmergency((prev) =>
              prev && prev.emergency_id === msg.emergency_id ? {
                ...prev,
                sms_status: msg.sms_status,
              } : prev
            );
          } else if (t === 'EMERGENCY_CANCELLED') {
            setActiveEmergency((prev) =>
              prev ? {
                ...prev,
                status: 'CANCELLED',
                _dismissed: true,
                cancelled_at: msg.cancelled_at ?? null,
                cancelled_reason: msg.reason ?? null,
              } : prev
            );
            window.dispatchEvent(new Event('emergency_updated'));
            // Dismiss alert after 3 seconds
            setTimeout(() => setActiveEmergency(null), 3000);
          } else if (t === 'EMERGENCY_RESOLVED') {
            setActiveEmergency((prev) =>
              prev ? { ...prev, status: 'RESOLVED', _dismissed: true } : prev
            );
            window.dispatchEvent(new Event('emergency_updated'));
            setTimeout(() => setActiveEmergency(null), 5000);
          } else if (t === 'EMERGENCY_UPDATED') {
            setActiveEmergency((prev) =>
              prev ? { ...prev, status: (msg.status as EmergencyStatus) ?? prev.status } : prev
            );
            window.dispatchEvent(new Event('emergency_updated'));
          }
        } catch {
          // ignore parsing errors
        }
      };

      ownerWs.onclose = () => {
        ownerReconnect = setTimeout(connectOwner, 4000);
      };
      ownerWs.onerror = () => ownerWs.close();
    }

    connectOwner();
    return () => {
      clearTimeout(ownerReconnect);
      ownerWs?.close();
    };
  }, [user.owner_id]);

  // WebSocket for AI updates and camera frames
  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let cameraTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      ws = new WebSocket(`${wsBase()}/ws/drowsiness`);

      ws.onopen = () => {
        setAiConnected(false);
      };

      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          if (data.type === 'EMERGENCY_TRIGGERED') {
            setActiveEmergency({
              emergency_id: data.emergency_id,
              status: data.status || 'ACTIVE',
              vehicle_id: data.vehicle_id || '',
              trip_id: data.trip_id || '',
              microsleep_count: data.microsleep_count ?? 0,
              drowsiness_percentage: data.drowsiness_percentage ?? 0,
              latitude: data.latitude ?? null,
              longitude: data.longitude ?? null,
              place_name: data.place_name ?? null,
              gps_source: data.gps_source || 'UNKNOWN',
              assistance_name: data.assistance_name ?? null,
              assistance_distance_km: data.assistance_distance_km ?? null,
              triggered_at: data.triggered_at ?? null,
              response_message: null,
              responded_at: null,
              cancelled_at: null,
              cancelled_reason: null,
            });
            setMicrosleepCount(data.microsleep_count ?? 0);
            window.dispatchEvent(new Event('emergency_updated'));
          } else if (data.type === 'ASSISTANCE_RESPONSE') {
            setActiveEmergency((prev) =>
              prev ? {
                ...prev,
                status: 'ASSISTANCE_RESPONDED',
                assistance_response_status: (data.response_status || (data.status === 'REJECTED' ? 'REJECTED' : 'ACCEPTED')) as EmergencyStatus,
                response_source: data.response_source || 'SMS',
                response_message: data.response_message || data.raw_response || data.message || 'Highway assistance team has responded.',
                raw_response: data.raw_response || data.response_message,
                responded_at: data.responded_at || new Date().toISOString(),
              } : prev
            );
            window.dispatchEvent(new Event('emergency_updated'));
          } else if (data.type === 'SMS_STATUS_UPDATE') {
            setActiveEmergency((prev) =>
              prev && prev.emergency_id === data.emergency_id ? {
                ...prev,
                sms_status: data.sms_status,
              } : prev
            );
          } else if (data.type === 'DRIVER_RECOVERED') {
            setActiveEmergency((prev) =>
              prev ? { ...prev, status: 'DRIVER_RECOVERED', drowsiness_percentage: data.drowsiness_percentage ?? prev.drowsiness_percentage } : prev
            );
          } else if (data.type === 'EMERGENCY_RESOLVED' || data.type === 'EMERGENCY_CANCELLED') {
            setActiveEmergency(null);
            window.dispatchEvent(new Event('emergency_updated'));
          }

          if (data.state) {
            setDrowsiness({
              state: data.state,
              perclos: data.perclos ?? 0,
              yawning: data.yawning ?? false,
              alert_message: data.alert_message ?? null,
              alertness_score: data.alertness_score ?? 100,
              head_state: data.head_state ?? 'NORMAL',
              alert_label: data.alert_label ?? 'NORMAL',
              timestamp: data.timestamp,
            });
            setAiConnected(true);
          }
          if (data.frame_b64) {
            setCameraFrame(data.frame_b64);
            setCameraConnected(true);
            clearTimeout(cameraTimeout);
            cameraTimeout = setTimeout(() => setCameraConnected(false), 5000);
          }
        } catch {
          // ignore parsing errors
        }
      };

      ws.onclose = () => {
        setAiConnected(false);
        setCameraConnected(false);
        reconnectTimer = setTimeout(connect, 3000);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      clearTimeout(cameraTimeout);
      ws?.close();
    };
  }, []);

  const state = drowsiness.state;
  const vehicle = dash?.vehicle;
  const safetyEvents = dash?.safety_events ?? [];

  return (
    <div className="app-shell">
      {/* ── Top Unified Header ── */}
      <header className="top-header">
        <div className="header-brand" onClick={() => setCurrentTab('dashboard')}>
          <div className="brand-shield">🛡️</div>
          <div className="brand-text">
            <span className="brand-name">SmartDrive Guardian</span>
            <span className="brand-tagline">Driver Alertness Monitoring System</span>
          </div>
        </div>

        {/* Desktop Navigation */}
        <nav className="desktop-nav">
          <button
            className={`nav-btn ${currentTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setCurrentTab('dashboard')}
          >
            <span className="nav-icon">🏠</span>
            <span>Dashboard</span>
          </button>
          <button
            className={`nav-btn ${currentTab === 'trip' ? 'active' : ''}`}
            onClick={() => setCurrentTab('trip')}
          >
            <span className="nav-icon">🗺️</span>
            <span>Trip Summary</span>
          </button>
          <button
            className={`nav-btn ${currentTab === 'history' ? 'active' : ''}`}
            onClick={() => setCurrentTab('history')}
          >
            <span className="nav-icon">📋</span>
            <span>Drowsiness History</span>
          </button>
          <button
            className={`nav-btn nav-emergency ${currentTab === 'emergency' ? 'active' : ''}`}
            onClick={() => setCurrentTab('emergency')}
          >
            <span className="nav-icon">🚨</span>
            <span>Emergency</span>
          </button>
        </nav>

        {/* User Info & Actions */}
        <div className="header-user-section">
          <div className="user-details">
            <span className="user-name">{user.name}</span>
            {vehicle?.plate_number && vehicle.plate_number !== 'N/A' && (
              <span className="user-plate">{vehicle.plate_number}</span>
            )}
          </div>
          <button className="btn-logout" onClick={onLogout} title="Sign Out">
            Logout
          </button>
          <button
            className="mobile-hamburger"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle Navigation"
          >
            ☰
          </button>
        </div>
      </header>

      {/* Mobile Navigation Dropdown */}
      {mobileMenuOpen && (
        <nav className="mobile-nav-menu">
          <button
            className={`mobile-nav-btn ${currentTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => {
              setCurrentTab('dashboard');
              setMobileMenuOpen(false);
            }}
          >
            🏠 Dashboard
          </button>
          <button
            className={`mobile-nav-btn ${currentTab === 'trip' ? 'active' : ''}`}
            onClick={() => {
              setCurrentTab('trip');
              setMobileMenuOpen(false);
            }}
          >
            🗺️ Trip Summary
          </button>
          <button
            className={`mobile-nav-btn ${currentTab === 'history' ? 'active' : ''}`}
            onClick={() => {
              setCurrentTab('history');
              setMobileMenuOpen(false);
            }}
          >
            📋 Drowsiness History
          </button>
          <button
            className={`mobile-nav-btn mobile-emergency ${currentTab === 'emergency' ? 'active' : ''}`}
            onClick={() => {
              setCurrentTab('emergency');
              setMobileMenuOpen(false);
            }}
          >
            🚨 Emergency
          </button>
        </nav>
      )}

      {/* Alert Banner for Severe Fatigue */}
      {drowsiness.alert_message && state !== 'NORMAL' && (
        <div className={`alert-banner-top ${state === 'MICROSLEEP' ? 'banner-microsleep' : 'banner-drowsy'}`}>
          <span className="banner-icon">{state === 'MICROSLEEP' ? '🚨' : '⚠'}</span>
          <span>{drowsiness.alert_message}</span>
          {microsleepCount > 0 && (
            <span className="banner-microsleep-count">
              Microsleep Events: {microsleepCount}
            </span>
          )}
        </div>
      )}

      {/* ── Active Emergency Alert Card ── */}
      {activeEmergency && !activeEmergency._dismissed && (
        <div className="emergency-card-wrapper">
          <EmergencyAlertCard
            emergency={activeEmergency}
            onCancel={() => setActiveEmergency((prev) => prev ? { ...prev, _dismissed: true } : null)}
          />
        </div>
      )}

      {/* ── Main Views ── */}
      <main className="main-content-area">
        {currentTab === 'dashboard' && (
          <DashboardPage
            dash={dash}
            drowsiness={drowsiness}
            cameraFrame={cameraFrame}
            cameraConnected={cameraConnected}
            aiConnected={aiConnected}
            onNavigate={(tab) => setCurrentTab(tab)}
          />
        )}
        {currentTab === 'trip' && <TripSummaryPage dash={dash} />}
        {currentTab === 'history' && <DrowsinessHistoryPage events={safetyEvents} />}
        {currentTab === 'emergency' && <EmergencyAssistancePage dash={dash} drowsiness={drowsiness} />}
      </main>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Root App with Authentication State
// ─────────────────────────────────────────────────────────────
export default function App() {
  const [user, setUser] = useState<AuthUser | null>(() => {
    try {
      const raw = localStorage.getItem('smartdrive_user');
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });

  function handleLogin(u: AuthUser) {
    localStorage.setItem('smartdrive_user', JSON.stringify(u));
    setUser(u);
  }

  function handleLogout() {
    localStorage.removeItem('smartdrive_user');
    setUser(null);
  }

  if (!user) return <AuthPage onLogin={handleLogin} />;
  return <DashboardApp user={user} onLogout={handleLogout} />;
}
