/** Safety-related types — no raw CV metrics. */

export interface SafetyStatus {
  vehicleId: string;
  driverStatus: DriverStatus;
  riskLevel: RiskLevel;
  safetyState: SafetyState;
  fatigueLevel: number; // 0-100 smoothed, human-meaningful
  distractionStatus: DistractionStatus;
  alertMessage: string | null;
  speedKmh: number | null;
  timestamp: string;
}

export type DriverStatus = 'Alert' | 'Drowsy' | 'Fatigued' | 'Distracted' | 'Critical' | 'Unknown';
export type RiskLevel = 'SAFE' | 'WARNING' | 'HIGH_RISK' | 'CRITICAL';
export type SafetyState = 'SAFE' | 'WARNING' | 'HIGH_RISK' | 'HIGHWAY_ASSISTANCE' | 'CRITICAL' | 'EMERGENCY';
export type DistractionStatus = 'Normal' | 'Mild' | 'Significant' | 'Severe';

export interface SafetyEvent {
  id: string;
  tripId: string;
  vehicleId: string;
  eventType: string;
  riskLevel: RiskLevel;
  driverStatus: DriverStatus;
  distractionStatus: DistractionStatus;
  description: string | null;
  fatigueLevel: number | null;
  speedKmh: number | null;
  latitude: number | null;
  longitude: number | null;
  timestamp: string;
}
