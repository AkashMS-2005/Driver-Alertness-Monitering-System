/** WebSocket event types and message contracts. */

export type WebSocketEventType =
  | 'SAFETY_STATUS_UPDATE'
  | 'TRIP_UPDATE'
  | 'LOCATION_UPDATE'
  | 'ALERT_NEW'
  | 'ALERT_ACKNOWLEDGED'
  | 'ASSISTANCE_UPDATE'
  | 'EMERGENCY_UPDATE'
  | 'AI_CONNECTION_STATUS_UPDATE'
  | 'SPEED_UPDATE';

export interface WebSocketMessage {
  event_type: WebSocketEventType;
  timestamp: string;
  [key: string]: unknown;
}

export interface SafetyStatusUpdate extends WebSocketMessage {
  event_type: 'SAFETY_STATUS_UPDATE';
  vehicle_id: string;
  driver_status: string;
  risk_level: string;
  safety_state: string;
  fatigue_level: number;
  distraction_status: string;
  alert_message: string | null;
  speed_kmh: number | null;
}

export interface AIConnectionStatusUpdate extends WebSocketMessage {
  event_type: 'AI_CONNECTION_STATUS_UPDATE';
  status: 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING';
  last_detection_at: string | null;
  seconds_since_last_detection: number | null;
  message: string;
}

export interface LocationUpdate extends WebSocketMessage {
  event_type: 'LOCATION_UPDATE';
  vehicle_id: string;
  latitude: number;
  longitude: number;
  speed_kmh: number;
  heading: number | null;
}

export interface AlertEvent extends WebSocketMessage {
  event_type: 'ALERT_NEW';
  alert_id: string;
  vehicle_id: string;
  alert_type: string;
  severity: string;
  message: string;
}
