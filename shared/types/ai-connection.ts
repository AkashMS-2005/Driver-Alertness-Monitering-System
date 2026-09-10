/** AI connection status types. */

export type AIConnectionStatus = 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING';

export interface AIConnection {
  status: AIConnectionStatus;
  lastDetectionAt: string | null;
  secondsSinceLastDetection: number | null;
  aiServerHost: string;
  aiServerPort: number;
  reconnectAttempts: number;
  errorMessage: string | null;
}
