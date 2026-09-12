/**
 * OASIS Frontend API Service Layer.
 *
 * Centralised client for the FastAPI backend.
 * Uses VITE_API_BASE_URL from environment (default: '' for same-origin proxy).
 */

// Backend response types (mirror of Pydantic schemas)
export interface BackendGeoPoint {
  lat: number;
  lon: number;
}

export interface BackendSpillGeometry {
  centroid: BackendGeoPoint;
  area_km2: number;
  perimeter_km: number;
  bbox: [number, number, number, number]; // [min_lat, min_lon, max_lat, max_lon]
  orientation_degrees: number;
}

export interface BackendProbableOrigin {
  centroid: BackendGeoPoint;
  time_window_start: string;
  time_window_end: string;
  uncertainty_radius_km: number;
}

export interface BackendDriftPoint {
  timestamp: string;
  location: BackendGeoPoint;
}

export interface BackendSpillDrift {
  hindcast_origin: BackendProbableOrigin;
  forecast_trajectory: BackendDriftPoint[];
}

export interface BackendEvidenceBreakdown {
  cpa_distance_km: number;
  time_discrepancy_min: number;
  trajectory_match: string;
  speed_anomaly_detected: boolean;
}

export interface BackendTrackPoint {
  location: BackendGeoPoint;
  timestamp: string;
  sog_knots: number;
  cog_degrees: number;
}

export interface BackendCandidateVessel {
  mmsi: string;
  vessel_name: string;
  vessel_type: string;
  attribution_score: number;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW';
  evidence: BackendEvidenceBreakdown;
  track_history: BackendTrackPoint[];
}

export interface BackendSpillAnalysisResponse {
  spill_id: string;
  detection_timestamp: string;
  segmentation_confidence: number;
  geometry: BackendSpillGeometry;
  drift: BackendSpillDrift;
  ais_status: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE';
  ranked_vessels: BackendCandidateVessel[];
  status_message: string;
}

export interface AnalyzeRequest {
  file: File;
  approx_lat: number;
  approx_lon: number;
  observation_time?: string;   // ISO datetime
  wind_speed_ms?: number;
  wind_dir_from?: number;
  current_speed_ms?: number;
  current_dir_to?: number;
}

export class ApiError extends Error {
  status: number;
  retryable: boolean;
  constructor(message: string, status: number, retryable = false) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.retryable = retryable;
  }
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

export async function analyzeSpill(req: AnalyzeRequest): Promise<BackendSpillAnalysisResponse> {
  const form = new FormData();
  form.append('file', req.file);
  form.append('approx_lat', String(req.approx_lat));
  form.append('approx_lon', String(req.approx_lon));

  if (req.observation_time) {
    form.append('observation_time', req.observation_time);
  }
  if (req.wind_speed_ms !== undefined) {
    form.append('wind_speed_ms', String(req.wind_speed_ms));
  }
  if (req.wind_dir_from !== undefined) {
    form.append('wind_dir_from', String(req.wind_dir_from));
  }
  if (req.current_speed_ms !== undefined) {
    form.append('current_speed_ms', String(req.current_speed_ms));
  }
  if (req.current_dir_to !== undefined) {
    form.append('current_dir_to', String(req.current_dir_to));
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000); // 2 min timeout for model inference

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/api/v1/analyze`, {
      method: 'POST',
      body: form,
      signal: controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timeout);
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError('Analysis timed out. Model inference may take longer than expected.', 408, true);
    }
    throw new ApiError(
      'Backend unavailable. Please ensure the FastAPI server is running.',
      0,
      true,
    );
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    let detail = `Server error (${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail ?? body.message ?? detail;
    } catch { /* ignore parse errors */ }
    throw new ApiError(detail, response.status, response.status >= 500);
  }

  const data: BackendSpillAnalysisResponse = await response.json();
  return data;
}

export async function healthCheck(): Promise<boolean> {
  try {
    const resp = await fetch(`${BASE_URL}/api/v1/../health`, { signal: AbortSignal.timeout(5000) });
    return resp.ok;
  } catch {
    return false;
  }
}

export interface MetoceanData {
  wind_speed_ms: number;
  wind_dir_from_deg: number;
  current_speed_ms: number;
  current_dir_to_deg: number;
}

export async function fetchLiveMetocean(lat: number, lon: number): Promise<MetoceanData> {
  const resp = await fetch(`${BASE_URL}/api/v1/metocean?lat=${lat}&lon=${lon}`, {
    signal: AbortSignal.timeout(10_000),
  });
  if (!resp.ok) {
    throw new ApiError('Failed to fetch live metocean data.', resp.status);
  }
  return resp.json();
}

export interface ScenarioListItem {
  id: string;
  title: string;
}

export async function fetchScenarios(): Promise<ScenarioListItem[]> {
  const resp = await fetch(`${BASE_URL}/api/v1/scenarios`, {
    signal: AbortSignal.timeout(5_000),
  });
  if (!resp.ok) {
    throw new ApiError('Failed to fetch scenario list.', resp.status);
  }
  return resp.json();
}

export async function fetchScenario(scenarioId: string): Promise<BackendSpillAnalysisResponse> {
  const resp = await fetch(`${BASE_URL}/api/v1/scenarios/${scenarioId}`, {
    signal: AbortSignal.timeout(5_000),
  });
  if (!resp.ok) {
    throw new ApiError('Failed to fetch scenario.', resp.status);
  }
  return resp.json();
}

export async function downloadForensicPdf(analysis: BackendSpillAnalysisResponse): Promise<Blob> {
  const resp = await fetch(`${BASE_URL}/api/v1/report/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(analysis),
    signal: AbortSignal.timeout(30_000),
  });
  if (!resp.ok) {
    throw new ApiError('Failed to generate forensic PDF.', resp.status);
  }
  return resp.blob();
}
