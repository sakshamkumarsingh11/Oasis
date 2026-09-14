"""
SIH26143 — AIS Attribution Engine: Domain Objects & Data Contracts

Defines the stable data contracts between AIS processing, attribution,
confidence, and orchestration layers.

Reference:
    Architecture §2.2 (data contracts), §14.2 (evidence features),
    §15.1 (coverage states), §20.7–20.9 (data model),
    §40 (core domain objects).
    Pipeline §26 (evidence features), §34–35 (scoring/explainability),
    §36 (coverage states).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AISCoverageState(enum.Enum):
    """
    How much usable AIS data exists for the investigation window.

    Architecture §15.1, Pipeline §36.
    """
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    UNAVAILABLE = "UNAVAILABLE"


class AttributionStatus(enum.Enum):
    """
    Whether vessel attribution can be produced.

    Architecture §15.4.
    """
    AVAILABLE = "AVAILABLE"
    AVAILABLE_REDUCED_CONFIDENCE = "AVAILABLE_WITH_REDUCED_CONFIDENCE"
    UNAVAILABLE = "UNAVAILABLE"


class ConfidenceBand(enum.Enum):
    """
    Qualitative confidence level for the attribution result.

    Architecture §15.4.
    """
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FeatureAvailability(enum.Enum):
    """
    Whether a single evidence feature could be computed.

    Pipeline §10–11 (zero vs missing), §40 (partial fields).
    A feature is UNAVAILABLE when the required input data is NULL/missing.
    It is never silently replaced with zero or a fabricated value.
    """
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Upstream inputs  (placeholders for objects produced by other modules)
# ---------------------------------------------------------------------------

@dataclass
class Origin:
    """
    Probable spill origin estimated by the drift/hindcast layer.

    Architecture §11.3 (build_origin_result), §20.6 (DriftResult).
    """
    latitude: float
    longitude: float
    timestamp: datetime
    uncertainty_km: Optional[float] = None


@dataclass
class DriftResult:
    """
    Output of the hindcast engine.

    Architecture §11.3, §20.6.

    Attributes:
        origin: The estimated probable origin point.
        trajectory: Ordered list of (lat, lon, timestamp) tuples
                    representing the hindcast drift path.
                    # PLACEHOLDER: finalise format once drift module exists.
        uncertainty_km: Spatial uncertainty radius.
        model_version: Version identifier for the drift model used.
    """
    origin: Origin
    trajectory: List[tuple]  # [(lat, lon, datetime), ...]  — PLACEHOLDER format
    uncertainty_km: Optional[float] = None
    model_version: Optional[str] = None


@dataclass
class SpillGeometry:
    """
    Characterised spill geometry from the segmentation + geometry layer.

    Architecture §9.4, §20.4.

    Attributes:
        centroid_lat: Latitude of the spill centroid.
        centroid_lon: Longitude of the spill centroid.
        area_km2: Area of the detected spill.
        polygon: Spill boundary polygon.
                 # PLACEHOLDER: using Any; will be Shapely Polygon once
                 # the geometry service is integrated (GeoPandas is in
                 # the tech stack — Architecture §3.5).
    """
    incident_id: str
    centroid_lat: float
    centroid_lon: float
    area_km2: float
    perimeter_km: Optional[float] = None
    orientation_deg: Optional[float] = None
    bounding_box: Optional[Any] = None  # PLACEHOLDER
    polygon: Optional[Any] = None       # PLACEHOLDER: Shapely Polygon
    extent: Optional[Any] = None        # PLACEHOLDER


# ---------------------------------------------------------------------------
# AIS / Trajectory objects
# ---------------------------------------------------------------------------

@dataclass
class AISRecord:
    """
    A single AIS observation (one row from the cleaned Parquet archive).

    Pipeline §6 (schema), §7 (types).
    """
    mmsi: str
    base_date_time: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    sog: Optional[float] = None          # Speed Over Ground (knots)
    cog: Optional[float] = None          # Course Over Ground (degrees)
    heading: Optional[float] = None      # True heading (degrees)
    vessel_name: Optional[str] = None
    imo: Optional[str] = None
    call_sign: Optional[str] = None
    vessel_type: Optional[int] = None
    status: Optional[int] = None
    length: Optional[float] = None
    width: Optional[float] = None
    draft: Optional[float] = None
    cargo: Optional[int] = None
    transceiver: Optional[str] = None
    source_file: Optional[str] = None
    source_date: Optional[str] = None


@dataclass
class VesselTrack:
    """
    Chronologically sorted AIS records for a single MMSI.

    Architecture §20.8, Pipeline §23–24.
    """
    mmsi: str
    records: List[AISRecord] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    record_count: int = 0
    coverage_score: Optional[float] = None  # 0.0–1.0, set by quality module

    def __post_init__(self):
        if self.records:
            self.record_count = len(self.records)
            timestamps = [r.base_date_time for r in self.records
                          if r.base_date_time is not None]
            if timestamps:
                self.start_time = min(timestamps)
                self.end_time = max(timestamps)


@dataclass
class CandidateVessel:
    """
    A vessel that passed the spatial + temporal candidate search.

    Architecture §13.2 (find_candidate_vessels).
    """
    mmsi: str
    track: VesselTrack
    vessel_name: Optional[str] = None
    vessel_type: Optional[int] = None
    imo: Optional[str] = None
    call_sign: Optional[str] = None


# ---------------------------------------------------------------------------
# Evidence / Attribution objects
# ---------------------------------------------------------------------------

@dataclass
class FeatureScore:
    """
    A single evidence feature's score and availability.

    Pipeline §10–11 (zero vs missing).
    """
    name: str
    score: Optional[float] = None          # 0.0–1.0 when available
    availability: FeatureAvailability = FeatureAvailability.UNAVAILABLE
    detail: Optional[str] = None           # human-readable explanation

    @property
    def is_available(self) -> bool:
        return self.availability == FeatureAvailability.AVAILABLE


@dataclass
class EvidenceVector:
    """
    Complete set of evidence features for one candidate vessel.

    Architecture §14.2, Pipeline §26.
    """
    distance: FeatureScore = field(
        default_factory=lambda: FeatureScore(name="distance"))
    time: FeatureScore = field(
        default_factory=lambda: FeatureScore(name="time"))
    trajectory: FeatureScore = field(
        default_factory=lambda: FeatureScore(name="trajectory"))
    heading: FeatureScore = field(
        default_factory=lambda: FeatureScore(name="heading"))
    speed: FeatureScore = field(
        default_factory=lambda: FeatureScore(name="speed"))
    path_proximity: FeatureScore = field(
        default_factory=lambda: FeatureScore(name="path_proximity"))
    behaviour: FeatureScore = field(
        default_factory=lambda: FeatureScore(name="behaviour"))
    vessel_type: FeatureScore = field(
        default_factory=lambda: FeatureScore(name="vessel_type"))

    def all_features(self) -> List[FeatureScore]:
        """Return all features as an ordered list."""
        return [
            self.distance,
            self.time,
            self.trajectory,
            self.heading,
            self.speed,
            self.path_proximity,
            self.behaviour,
            self.vessel_type,
        ]

    def available_count(self) -> int:
        """Number of features that were successfully computed."""
        return sum(1 for f in self.all_features() if f.is_available)

    def total_count(self) -> int:
        """Total number of defined features."""
        return len(self.all_features())

    def feature_coverage(self) -> float:
        """Fraction of features that are available (0.0–1.0)."""
        total = self.total_count()
        if total == 0:
            return 0.0
        return self.available_count() / total


@dataclass
class AttributionResult:
    """
    Attribution result for a single candidate vessel.

    Architecture §20.9.
    """
    mmsi: str
    rank: int
    score: float                               # weighted evidence score
    confidence: ConfidenceBand
    evidence: EvidenceVector
    evidence_summary: str = ""                 # human-readable (§32, §35)
    vessel_name: Optional[str] = None
    imo: Optional[str] = None


@dataclass
class AttributionReport:
    """
    Complete attribution output for one incident.

    Architecture §14.4 (build_attribution_result), §41 (output contract).
    """
    incident_id: str
    status: AttributionStatus
    ais_coverage: AISCoverageState
    confidence: ConfidenceBand
    ranked_vessels: List[AttributionResult] = field(default_factory=list)
    candidate_count: int = 0
    confidence_explanation: str = ""

    # Audit trail fields (Pipeline §52)
    search_radius_km: Optional[float] = None
    time_window_minutes: Optional[float] = None
    ais_dates: Optional[List[str]] = None
