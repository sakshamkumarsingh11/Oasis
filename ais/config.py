"""
SIH26143 — Attribution Engine: Configuration

All tunable parameters for the attribution engine live here.
Weights, thresholds, and search windows are configuration values,
not hard-coded throughout the application.

Reference:
    Architecture §29 (configuration).
    Pipeline §34 (weighted evidence score — example weights).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class AttributionWeights:
    """
    Weights for the evidence scoring formula.

    Architecture §14.3:
        Total Score = w1*distance + w2*time + w3*trajectory + w4*heading
                    + w5*speed + w6*path_proximity + w7*behaviour
                    + w8*vessel_type

    These are *prototype/example* numbers, not validated scientific
    weights (Pipeline §34).  They must sum to 1.0.
    """
    distance: float = 0.25
    time: float = 0.20
    trajectory: float = 0.15
    heading: float = 0.10
    speed: float = 0.10
    path_proximity: float = 0.05
    behaviour: float = 0.05
    vessel_type: float = 0.10

    def as_dict(self) -> Dict[str, float]:
        return {
            "distance": self.distance,
            "time": self.time,
            "trajectory": self.trajectory,
            "heading": self.heading,
            "speed": self.speed,
            "path_proximity": self.path_proximity,
            "behaviour": self.behaviour,
            "vessel_type": self.vessel_type,
        }

    def total(self) -> float:
        return sum(self.as_dict().values())


@dataclass
class ScoreNormalisationConfig:
    """
    Parameters that control how raw measurements are normalised into
    [0, 1] feature scores.

    These are implementation recommendations — adjust based on the
    operational domain (e.g. coastal vs open-ocean).
    """
    # Distance score: score = max(0, 1 - distance_km / max_distance_km)
    max_distance_km: float = 50.0

    # Time score: score = max(0, 1 - abs(delta_min) / max_time_delta_minutes)
    max_time_delta_minutes: float = 120.0

    # Heading score: score = max(0, 1 - abs(heading_diff_deg) / max_heading_diff)
    max_heading_diff_deg: float = 180.0

    # Speed anomaly detection thresholds
    speed_change_threshold_knots: float = 3.0   # sudden change per interval
    speed_anomaly_window: int = 5               # number of consecutive records

    # Course anomaly detection thresholds
    course_change_threshold_deg: float = 30.0   # sudden change per interval
    course_anomaly_window: int = 5


@dataclass
class InterpolationConfig:
    """
    Controls when trajectory interpolation is permitted.

    Pipeline §25, §47: do not interpolate across large gaps.
    """
    # Maximum time gap (in minutes) between two AIS records
    # for interpolation to be allowed.
    max_gap_minutes: float = 15.0

    # Minimum number of valid records required for a usable trajectory.
    min_records_for_trajectory: int = 3


@dataclass
class ConfidenceConfig:
    """
    Thresholds for mapping scores/coverage into confidence bands.

    Architecture §15, Pipeline §36.
    """
    # Minimum feature coverage (fraction 0–1) for FULL AIS state
    full_coverage_threshold: float = 0.8

    # Below this → INSUFFICIENT
    insufficient_coverage_threshold: float = 0.3

    # Score thresholds for confidence bands
    high_confidence_min_score: float = 0.7
    medium_confidence_min_score: float = 0.4

    # Minimum number of candidates required for attribution
    min_candidates_for_attribution: int = 1

    # Minimum feature coverage for a single candidate to be rankable
    min_feature_coverage: float = 0.25


@dataclass
class VesselTypeRelevance:
    """
    Contextual relevance scores for AIS vessel type codes.

    Pipeline §33: vessel_type_score is contextual; do not let it dominate.

    PLACEHOLDER: This is a starter mapping. Replace with a properly
    researched mapping of AIS vessel type codes once the domain experts
    provide guidance.

    Common AIS vessel type ranges (ITU-R M.1371-5):
        30      = fishing
        60–69   = passenger
        70–79   = cargo
        80–89   = tanker
        (other codes exist; see full ITU spec)
    """
    # Map from vessel_type integer code to relevance score [0, 1].
    # Higher = more relevant to oil-spill causation.
    # These are PLACEHOLDER values — not validated.
    relevance_map: Dict[int, float] = field(default_factory=lambda: {
        # Tankers — most relevant
        80: 0.9, 81: 0.9, 82: 0.9, 83: 0.9, 84: 0.9,
        85: 0.9, 86: 0.9, 87: 0.9, 88: 0.9, 89: 0.9,
        # Cargo — moderately relevant
        70: 0.6, 71: 0.6, 72: 0.6, 73: 0.6, 74: 0.6,
        75: 0.6, 76: 0.6, 77: 0.6, 78: 0.6, 79: 0.6,
        # Fishing — lower relevance
        30: 0.3,
        # Passenger — low relevance
        60: 0.2, 61: 0.2, 62: 0.2, 63: 0.2, 64: 0.2,
        65: 0.2, 66: 0.2, 67: 0.2, 68: 0.2, 69: 0.2,
    })

    # Default score for vessel types not in the map
    default_relevance: float = 0.4

    def get_relevance(self, vessel_type_code: int | None) -> float | None:
        """
        Return relevance score for a vessel type code.
        Returns None if vessel_type_code is None (missing data).
        """
        if vessel_type_code is None:
            return None
        return self.relevance_map.get(vessel_type_code, self.default_relevance)


@dataclass
class AttributionConfig:
    """
    Top-level configuration container.

    Architecture §29.
    """
    weights: AttributionWeights = field(default_factory=AttributionWeights)
    normalisation: ScoreNormalisationConfig = field(
        default_factory=ScoreNormalisationConfig)
    interpolation: InterpolationConfig = field(
        default_factory=InterpolationConfig)
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    vessel_type_relevance: VesselTypeRelevance = field(
        default_factory=VesselTypeRelevance)

    # --- AIS search parameters (also in architecture §29) ---
    # These are used by the query layer, but stored here for reference.
    spatial_radius_km: float = 25.0
    temporal_window_hours: float = 12.0

    # Trajectory context multiplier: fetch this multiple of the search
    # window for wider context (Pipeline §22).
    trajectory_context_multiplier: float = 3.0


def load_config() -> AttributionConfig:
    """
    Load attribution configuration.

    PLACEHOLDER: In production, load from a YAML file (configs/default.yaml)
    as recommended by Architecture §29.  For now, returns defaults.
    """
    # TODO: implement YAML loading from configs/default.yaml
    return AttributionConfig()


def validate_config(config: AttributionConfig) -> bool:
    """
    Validate that configuration values are self-consistent.

    Returns True if valid, raises ValueError otherwise.
    """
    weight_sum = config.weights.total()
    if abs(weight_sum - 1.0) > 0.01:
        raise ValueError(
            f"Attribution weights must sum to 1.0, got {weight_sum:.4f}. "
            f"Weights: {config.weights.as_dict()}"
        )

    if config.normalisation.max_distance_km <= 0:
        raise ValueError("max_distance_km must be positive.")

    if config.normalisation.max_time_delta_minutes <= 0:
        raise ValueError("max_time_delta_minutes must be positive.")

    if config.interpolation.max_gap_minutes <= 0:
        raise ValueError("max_gap_minutes must be positive.")

    if not (0.0 <= config.confidence.full_coverage_threshold <= 1.0):
        raise ValueError("full_coverage_threshold must be in [0, 1].")

    if not (0.0 <= config.confidence.insufficient_coverage_threshold <= 1.0):
        raise ValueError("insufficient_coverage_threshold must be in [0, 1].")

    return True
