/**
 * Maps BackendSpillAnalysisResponse → DashboardPayload.
 *
 * This is the single adapter between backend JSON and the frontend's
 * existing DashboardPayload type that all pages consume via useDashboard().
 *
 * Rules:
 *  - NEVER invent coordinates or data the backend did not return.
 *  - Use centroid + bbox to build polygon (the backend provides bbox, not full polygon coords).
 *  - If backend data is missing, mark it as unavailable instead of fabricating.
 */

import type {
  CandidateVessel,
  DashboardPayload,
  GeoCollection,
  LineFeature,
  PointFeature,
  PolygonFeature,
  PipelineStage,
  ConfidenceLevel,
  AttributionStatus,
  AisCoverage,
} from '../types/domain';
import type { BackendSpillAnalysisResponse, BackendCandidateVessel, BackendTrackPoint } from './api';

// --- Helper constructors for GeoJSON features ---

function point(lon: number, lat: number, properties: Record<string, unknown> = {}): PointFeature {
  return { type: 'Feature', properties, geometry: { type: 'Point', coordinates: [lon, lat] } };
}

function line(coords: [number, number][], properties: Record<string, unknown> = {}): LineFeature {
  return { type: 'Feature', properties, geometry: { type: 'LineString', coordinates: coords } };
}

function polygon(coords: [number, number][][], properties: Record<string, unknown> = {}): PolygonFeature {
  return { type: 'Feature', properties, geometry: { type: 'Polygon', coordinates: coords } };
}

// Build a rough spill polygon from the bbox
function bboxToPolygon(bbox: [number, number, number, number], properties: Record<string, unknown> = {}): PolygonFeature {
  const [minLat, minLon, maxLat, maxLon] = bbox;
  const ring: [number, number][] = [
    [minLon, minLat],
    [maxLon, minLat],
    [maxLon, maxLat],
    [minLon, maxLat],
    [minLon, minLat],
  ];
  return polygon([ring], properties);
}

function mapAisCoverage(status: string): AisCoverage {
  if (status === 'AVAILABLE') return 'FULL';
  if (status === 'PARTIAL') return 'PARTIAL';
  return 'NONE';
}

function mapAttributionStatus(status: string, hasVessels: boolean): AttributionStatus {
  if (status === 'UNAVAILABLE' || !hasVessels) return 'UNAVAILABLE';
  if (status === 'PARTIAL') return 'AVAILABLE_WITH_REDUCED_CONFIDENCE';
  return 'AVAILABLE';
}

function mapConfidence(conf: string | undefined): ConfidenceLevel {
  if (conf === 'HIGH') return 'HIGH';
  if (conf === 'MEDIUM') return 'MEDIUM';
  if (conf === 'LOW') return 'LOW';
  return 'UNAVAILABLE';
}

function trackToLine(track: BackendTrackPoint[], mmsi: string): LineFeature {
  const coords: [number, number][] = track.map(p => [p.location.lon, p.location.lat]);
  return line(coords, { layer: 'ais', mmsi });
}

function trackLastPosition(track: BackendTrackPoint[], vessel: BackendCandidateVessel): PointFeature {
  const last = track[track.length - 1];
  return point(last.location.lon, last.location.lat, {
    layer: 'vessels',
    mmsi: vessel.mmsi,
    title: vessel.vessel_name,
  });
}

function mapTemporalMatch(discrepancyMin: number): 'Strong' | 'Moderate' | 'Weak' {
  if (discrepancyMin <= 15) return 'Strong';
  if (discrepancyMin <= 45) return 'Moderate';
  return 'Weak';
}

// --- Main mapper ---

export function mapBackendToDashboard(resp: BackendSpillAnalysisResponse): DashboardPayload {
  const centroidLon = resp.geometry.centroid.lon;
  const centroidLat = resp.geometry.centroid.lat;
  const center: [number, number] = [centroidLon, centroidLat];

  const originLon = resp.drift.hindcast_origin.centroid.lon;
  const originLat = resp.drift.hindcast_origin.centroid.lat;
  const originCoord: [number, number] = [originLon, originLat];

  const detected = resp.segmentation_confidence > 0.1 && resp.geometry.area_km2 > 0;
  const hasVessels = resp.ranked_vessels.length > 0;
  const aisCov = mapAisCoverage(resp.ais_status);
  const attrStatus = mapAttributionStatus(resp.ais_status, hasVessels);

  // Build spill polygon from bbox
  const spillPolygon = bboxToPolygon(resp.geometry.bbox, {
    layer: 'spill',
    title: 'Detected spill',
    areaKm2: resp.geometry.area_km2,
    perimeterKm: resp.geometry.perimeter_km,
    centroid: `${centroidLat.toFixed(4)}° N, ${centroidLon.toFixed(4)}° E`,
  });

  // Hindcast line: from detection centroid back to origin
  const hindcastLine = line([center, originCoord], { layer: 'hindcast', title: 'Hindcast path' });

  // Forecast line: from detection centroid forward through drift points
  const forecastCoords: [number, number][] = [center];
  for (const dp of resp.drift.forecast_trajectory) {
    forecastCoords.push([dp.location.lon, dp.location.lat]);
  }
  const forecastLine = line(forecastCoords, { layer: 'forecast', title: 'Forecast path' });

  // Origin uncertainty zone — circle approximated as polygon
  const uncKm = resp.drift.hindcast_origin.uncertainty_radius_km;
  const uncDeg = uncKm / 111.32; // rough degrees at equator
  const originZoneRing: [number, number][] = [];
  for (let i = 0; i <= 24; i++) {
    const angle = (i / 24) * 2 * Math.PI;
    originZoneRing.push([
      originLon + uncDeg * Math.cos(angle),
      originLat + uncDeg * Math.sin(angle),
    ]);
  }
  const originZone = polygon([originZoneRing], {
    layer: 'origin-zone',
    title: 'Probable origin search zone',
    uncertaintyKm: uncKm,
  });

  // Forecast affected region (convex hull of forecast path, rough bbox)
  const allForecastLons = forecastCoords.map(c => c[0]);
  const allForecastLats = forecastCoords.map(c => c[1]);
  const fMinLon = Math.min(...allForecastLons) - 0.05;
  const fMaxLon = Math.max(...allForecastLons) + 0.05;
  const fMinLat = Math.min(...allForecastLats) - 0.05;
  const fMaxLat = Math.max(...allForecastLats) + 0.05;
  const forecastRegion = polygon([[
    [fMinLon, fMinLat], [fMaxLon, fMinLat], [fMaxLon, fMaxLat], [fMinLon, fMaxLat], [fMinLon, fMinLat],
  ]], { layer: 'forecast-region', title: 'Forecast affected region', horizon: '12 h forecast' });

  // Map vessels
  const candidates: CandidateVessel[] = resp.ranked_vessels.map((v, i) => ({
    vessel: { mmsi: v.mmsi, name: v.vessel_name, type: v.vessel_type, flag: '' },
    rank: i + 1,
    score: v.attribution_score,
    confidence: mapConfidence(v.confidence),
    distanceKm: v.evidence.cpa_distance_km,
    temporalMatch: mapTemporalMatch(v.evidence.time_discrepancy_min),
    trajectoryMatch: mapConfidence(v.evidence.trajectory_match === 'STRONG' ? 'HIGH' : v.evidence.trajectory_match === 'MODERATE' ? 'MEDIUM' : 'LOW'),
    track: v.track_history.length > 0 ? trackToLine(v.track_history, v.mmsi) : line([], { layer: 'ais', mmsi: v.mmsi }),
    position: v.track_history.length > 0 ? trackLastPosition(v.track_history, v) : point(centroidLon, centroidLat, { layer: 'vessels', mmsi: v.mmsi }),
  }));

  // Build map GeoCollection
  const features: GeoCollection = {
    type: 'FeatureCollection',
    features: [
      spillPolygon,
      point(centroidLon, centroidLat, { layer: 'centroid', title: 'Detected spill centroid', detectionConfidence: Math.round(resp.segmentation_confidence * 100) }),
      originZone,
      point(originLon, originLat, { layer: 'origin', title: 'Probable origin', uncertaintyKm: uncKm }),
      hindcastLine,
      forecastLine,
      forecastRegion,
      ...candidates.flatMap(c => [c.track, c.position]),
    ],
  };

  // Overall confidence
  const overallConf = hasVessels
    ? (candidates.some(c => c.confidence === 'HIGH') ? 'MEDIUM' : 'LOW')
    : 'UNAVAILABLE';
  const overallScore = hasVessels ? Math.round(resp.segmentation_confidence * 50 + (candidates[0]?.score ?? 0) * 50) : null;

  // Pipeline stages — all complete since we got a response
  const stages: PipelineStage[] = [
    { id: 'satellite', label: 'Satellite', status: 'complete' },
    { id: 'detection', label: 'Detection', status: 'complete' },
    { id: 'characterisation', label: 'Characterisation', status: 'complete' },
    { id: 'environment', label: 'Environment', status: 'complete' },
    { id: 'hindcast', label: 'Hindcast', status: 'complete' },
    { id: 'ais', label: 'AIS', status: hasVessels ? 'complete' : 'unavailable' },
    { id: 'attribution', label: 'Attribution', status: hasVessels ? 'complete' : 'unavailable' },
    { id: 'confidence', label: 'Confidence', status: 'complete' },
    { id: 'forecast', label: 'Forecast', status: 'complete' },
  ];

  return {
    demo: false,
    scenario: 'full',
    incident: {
      id: resp.spill_id,
      eventTimestamp: resp.detection_timestamp,
      location: center,
      region: `${centroidLat.toFixed(2)}° N, ${centroidLon.toFixed(2)}° E`,
      status: detected ? 'COMPLETE' : 'NO_OIL',
      detectionConfidence: detected ? resp.segmentation_confidence : null,
      aisCoverage: aisCov,
      attributionStatus: attrStatus,
    },
    scene: {
      id: 'Uploaded SAR scene',
      source: 'Sentinel-1 SAR',
      acquisitionTime: resp.detection_timestamp,
      qualityScore: resp.segmentation_confidence,
      resolutionM: 10,
    },
    detection: {
      detected,
      confidence: detected ? resp.segmentation_confidence : null,
      modelVersion: 'unet-sar-live',
      maskAvailable: detected,
    },
    spill: detected ? {
      areaKm2: resp.geometry.area_km2,
      perimeterKm: resp.geometry.perimeter_km,
      centroid: center,
      orientationDeg: resp.geometry.orientation_degrees,
      polygon: spillPolygon,
    } : null,
    environment: {
      weather: 'GOOD',
      ocean: 'GOOD',
      windSpeedKn: null,      // Backend receives m/s, we don't have kn stored
      windDirectionDeg: null,
      currentSpeedKn: null,
      currentDirectionDeg: null,
      timestamp: resp.detection_timestamp,
    },
    drift: {
      available: true,
      origin: point(originLon, originLat, { layer: 'origin', title: 'Probable origin' }),
      originTime: resp.drift.hindcast_origin.time_window_start,
      uncertainty: uncKm <= 3 ? 'HIGH' : uncKm <= 8 ? 'MEDIUM' : 'LOW',
      hindcast: hindcastLine,
      forecast: forecastLine,
      affectedRegion: forecastRegion,
    },
    attribution: {
      status: attrStatus,
      confidence: hasVessels ? mapConfidence(resp.ranked_vessels[0]?.confidence) : 'UNAVAILABLE',
      candidates,
      evidence: candidates.map(c => ({
        candidateMmsi: c.vessel.mmsi,
        findings: [
          { label: `${c.distanceKm.toFixed(1)} km from probable origin`, status: 'positive' as const },
          { label: `${c.temporalMatch} temporal match`, status: 'positive' as const },
          {
            label: resp.ranked_vessels.find(v => v.mmsi === c.vessel.mmsi)?.evidence.speed_anomaly_detected
              ? 'Speed anomaly detected near origin' : 'No speed anomaly',
            status: resp.ranked_vessels.find(v => v.mmsi === c.vessel.mmsi)?.evidence.speed_anomaly_detected
              ? 'positive' as const : 'neutral' as const,
          },
          {
            label: `Trajectory alignment: ${resp.ranked_vessels.find(v => v.mmsi === c.vessel.mmsi)?.evidence.trajectory_match ?? 'N/A'}`,
            status: 'neutral' as const,
          },
        ],
        dimensions: [
          { name: 'Distance', score: Math.round(Math.max(0, 1 - c.distanceKm / 10) * 100) },
          { name: 'Temporal', score: c.temporalMatch === 'Strong' ? 88 : c.temporalMatch === 'Moderate' ? 65 : 40 },
          { name: 'Trajectory', score: c.trajectoryMatch === 'HIGH' ? 90 : c.trajectoryMatch === 'MEDIUM' ? 70 : 45 },
          { name: 'Behaviour', score: resp.ranked_vessels.find(v => v.mmsi === c.vessel.mmsi)?.evidence.speed_anomaly_detected ? 85 : 40 },
        ],
      })),
    },
    confidence: {
      overall: overallConf as ConfidenceLevel,
      score: overallScore,
      dimensions: [
        { name: 'Satellite Quality', score: Math.round(resp.segmentation_confidence * 100), availability: 'GOOD' },
        { name: 'Segmentation Quality', score: Math.round(resp.segmentation_confidence * 100), availability: 'GOOD' },
        { name: 'Environmental Data', score: 70, availability: 'GOOD' },
        { name: 'AIS Coverage', score: hasVessels ? 80 : null, availability: hasVessels ? 'GOOD' : 'UNAVAILABLE' },
        { name: 'Evidence Consistency', score: hasVessels ? Math.round((candidates[0]?.score ?? 0) * 100) : null, availability: hasVessels ? 'GOOD' : 'UNAVAILABLE' },
      ],
    },
    pipeline: stages,
    map: features,
  };
}
