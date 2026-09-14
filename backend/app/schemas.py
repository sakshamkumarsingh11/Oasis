from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum

class AISCoverageStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"

class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class GeoPoint(BaseModel):
    lat: float = Field(..., example=15.2105)
    lon: float = Field(..., example=65.4210)

class SpillGeometry(BaseModel):
    centroid: GeoPoint
    area_km2: float = Field(..., example=14.72)
    perimeter_km: float = Field(..., example=18.4)
    bbox: List[float] = Field(..., description="[min_lat, min_lon, max_lat, max_lon]", example=[15.18, 65.39, 15.24, 65.45])
    orientation_degrees: float = Field(..., example=42.5)

class ProbableOrigin(BaseModel):
    centroid: GeoPoint
    time_window_start: datetime
    time_window_end: datetime
    uncertainty_radius_km: float = Field(..., example=3.5)

class DriftPoint(BaseModel):
    timestamp: datetime
    location: GeoPoint

class SpillDrift(BaseModel):
    hindcast_origin: ProbableOrigin
    forecast_trajectory: List[DriftPoint]

class EvidenceBreakdown(BaseModel):
    cpa_distance_km: float = Field(..., description="Closest Point of Approach", example=0.8)
    time_discrepancy_min: float = Field(..., example=12.0)
    trajectory_match: str = Field(..., example="STRONG")
    speed_anomaly_detected: bool = Field(..., example=True)

class TrackPoint(BaseModel):
    location: GeoPoint
    timestamp: datetime
    sog_knots: float = Field(..., description="Speed Over Ground", example=12.4)
    cog_degrees: float = Field(..., description="Course Over Ground", example=215.0)

class CandidateVessel(BaseModel):
    mmsi: str = Field(..., example="413219000")
    vessel_name: str = Field(..., example="PACIFIC EXPLORER")
    vessel_type: str = Field(..., example="Tanker")
    attribution_score: float = Field(..., ge=0.0, le=1.0, example=0.91)
    confidence: ConfidenceLevel
    evidence: EvidenceBreakdown
    track_history: List[TrackPoint]

class SpillAnalysisResponse(BaseModel):
    spill_id: str = Field(..., example="SPILL_2026_001")
    detection_timestamp: datetime
    segmentation_confidence: float = Field(..., ge=0.0, le=1.0, example=0.94)
    geometry: SpillGeometry
    drift: SpillDrift
    ais_status: AISCoverageStatus
    ranked_vessels: List[CandidateVessel]
    status_message: str = Field(..., example="Analysis completed with high attribution confidence.")
