/** Trip-related types. */

export type TripStatus = 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'EMERGENCY_STOPPED';

export interface Trip {
  id: string;
  vehicleId: string;
  status: TripStatus;
  startTime: string;
  endTime: string | null;
  startLatitude: number | null;
  startLongitude: number | null;
  endLatitude: number | null;
  endLongitude: number | null;
  distanceKm: number | null;
}
