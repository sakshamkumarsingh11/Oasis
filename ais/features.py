"""
SIH26143 — Attribution Engine: Evidence Feature Computation

Computes the 8 evidence features for each candidate vessel, following
the architecture's explicit feature definitions and missing-data rules.

Reference:
    Architecture §12.2 (AIS functions), §14.1–14.2 (evidence features).
    Pipeline §26–33 (feature details), §10–11 (zero vs missing).

Every function checks for NULL/missing input and returns
FeatureAvailability.UNAVAILABLE rather than fabricating data.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import List, Optional, Tuple

from .config import AttributionConfig
from .schemas import (
    AISRecord,
    CandidateVessel,
    DriftResult,
    EvidenceVector,
    FeatureAvailability,
    FeatureScore,
    Origin,
    SpillGeometry,
    VesselTrack,
)


# ---------------------------------------------------------------------------
# Geodesic utilities
# ---------------------------------------------------------------------------

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on Earth (km).

    Pipeline §20: used for exact radius filtering and distance scoring.

    This is a standard Haversine formula.  For production accuracy over
    short distances, consider a Vincenty or geodesic library (e.g. geopy).
    """
    R = 6371.0  # Earth radius in km

    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return R * c


def _angle_difference(a: float, b: float) -> float:
    """Smallest unsigned difference between two angles in degrees [0, 180]."""
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


# ---------------------------------------------------------------------------
# Helper: extract valid positional records from a track
# ---------------------------------------------------------------------------

def _valid_position_records(track: VesselTrack) -> List[AISRecord]:
    """
    Return records that have valid lat, lon, and timestamp.

    Pipeline §10.3–10.5: records with missing lat OR lon cannot participate
    in spatial analysis.
    """
    return [
        r for r in track.records
        if (r.latitude is not None
            and r.longitude is not None
            and r.base_date_time is not None)
    ]


# ---------------------------------------------------------------------------
# Feature 1: Distance Score
# ---------------------------------------------------------------------------

def calculate_distance_score(
    track: VesselTrack,
    origin: Origin,
    config: AttributionConfig,
) -> FeatureScore:
    """
    How close did the vessel get to the probable origin?

    Pipeline §27: compute minimum distance, then normalise.
    Architecture §14.2: distance_score.

    Score = max(0, 1 - min_distance_km / max_distance_km)
    Higher score = closer to origin = more suspicious.
    """
    valid = _valid_position_records(track)
    if not valid:
        return FeatureScore(
            name="distance",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="No valid position records in track.",
        )

    min_dist = min(
        haversine(r.latitude, r.longitude, origin.latitude, origin.longitude)
        for r in valid
    )

    max_d = config.normalisation.max_distance_km
    score = max(0.0, 1.0 - min_dist / max_d)

    return FeatureScore(
        name="distance",
        score=round(score, 4),
        availability=FeatureAvailability.AVAILABLE,
        detail=f"Minimum distance to origin: {min_dist:.2f} km",
    )


# ---------------------------------------------------------------------------
# Feature 2: Time Score
# ---------------------------------------------------------------------------

def calculate_time_score(
    track: VesselTrack,
    origin_time: datetime,
    config: AttributionConfig,
) -> FeatureScore:
    """
    How closely does the vessel timing match the inferred origin time?

    Pipeline §28: Δt between origin time and nearest observation.
    Architecture §14.2: time_score.

    Score = max(0, 1 - |Δt_min| / max_time_delta_minutes)
    """
    timestamps = [
        r.base_date_time for r in track.records
        if r.base_date_time is not None
    ]
    if not timestamps:
        return FeatureScore(
            name="time",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="No valid timestamps in track.",
        )

    deltas_min = [
        abs((t - origin_time).total_seconds()) / 60.0
        for t in timestamps
    ]
    min_delta = min(deltas_min)

    max_t = config.normalisation.max_time_delta_minutes
    score = max(0.0, 1.0 - min_delta / max_t)

    return FeatureScore(
        name="time",
        score=round(score, 4),
        availability=FeatureAvailability.AVAILABLE,
        detail=f"Nearest observation Δt: {min_delta:.1f} minutes",
    )


# ---------------------------------------------------------------------------
# Feature 3: Trajectory Score
# ---------------------------------------------------------------------------

def calculate_trajectory_score(
    track: VesselTrack,
    drift_result: Optional[DriftResult],
    config: AttributionConfig,
) -> FeatureScore:
    """
    Consistency between the vessel route and the inferred drift corridor.

    Pipeline §29: evaluate full vessel route against probable origin,
    origin region, and drift path.
    Architecture §14.2: trajectory_score.

    PLACEHOLDER: The trajectory-vs-drift-corridor intersection requires
    the finalised drift trajectory geometry format.  Currently uses a
    simplified approach: average distance from track points to the
    nearest point on the drift trajectory.
    """
    if drift_result is None or not drift_result.trajectory:
        return FeatureScore(
            name="trajectory",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="Drift result unavailable; cannot compute trajectory match.",
        )

    valid = _valid_position_records(track)
    if not valid:
        return FeatureScore(
            name="trajectory",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="No valid position records in track.",
        )

    # PLACEHOLDER implementation:
    # For each track point, find the minimum distance to any point
    # on the drift trajectory.  Then average those minimum distances.
    # A proper implementation would use geometric intersection with
    # a drift corridor polygon or buffered LineString.

    drift_points: List[Tuple[float, float]] = []
    for point in drift_result.trajectory:
        if len(point) >= 2:
            drift_points.append((point[0], point[1]))

    if not drift_points:
        return FeatureScore(
            name="trajectory",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="Drift trajectory has no valid points.",
        )

    total_min_dist = 0.0
    for record in valid:
        min_d = min(
            haversine(record.latitude, record.longitude, dp[0], dp[1])
            for dp in drift_points
        )
        total_min_dist += min_d

    avg_dist = total_min_dist / len(valid)
    max_d = config.normalisation.max_distance_km
    score = max(0.0, 1.0 - avg_dist / max_d)

    return FeatureScore(
        name="trajectory",
        score=round(score, 4),
        availability=FeatureAvailability.AVAILABLE,
        detail=f"Average distance to drift corridor: {avg_dist:.2f} km",
    )


# ---------------------------------------------------------------------------
# Feature 4: Heading Score
# ---------------------------------------------------------------------------

def calculate_heading_score(
    track: VesselTrack,
    drift_result: Optional[DriftResult],
    config: AttributionConfig,
) -> FeatureScore:
    """
    Is the vessel heading compatible with the spill event?

    Pipeline §30: if heading missing → UNAVAILABLE. Never copy COG.
    Architecture §14.2: heading_score.

    Computes the heading difference between the vessel's heading
    (near the origin time) and the bearing from the vessel position
    to the probable origin.
    """
    if drift_result is None:
        return FeatureScore(
            name="heading",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="Drift result unavailable.",
        )

    # Find records with valid heading (NOT COG — Pipeline §30)
    records_with_heading = [
        r for r in track.records
        if (r.heading is not None
            and r.latitude is not None
            and r.longitude is not None
            and r.base_date_time is not None)
    ]

    if not records_with_heading:
        return FeatureScore(
            name="heading",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="No valid heading values in track (heading ≠ COG).",
        )

    # Use the record closest in time to the origin
    origin_time = drift_result.origin.timestamp
    closest = min(
        records_with_heading,
        key=lambda r: abs((r.base_date_time - origin_time).total_seconds()),
    )

    # Check distance from closest record to origin
    dist_to_origin = haversine(
        closest.latitude, closest.longitude,
        drift_result.origin.latitude, drift_result.origin.longitude,
    )

    if dist_to_origin < 0.15:
        score = 1.0
        detail = (
            f"Vessel passed over origin (CPA={dist_to_origin:.2f} km < 0.15 km); "
            f"heading alignment optimal (vessel heading={closest.heading:.1f}°)"
        )
    else:
        # Calculate bearing from vessel to origin
        bearing = _calculate_bearing(
            closest.latitude, closest.longitude,
            drift_result.origin.latitude, drift_result.origin.longitude,
        )
        heading_diff = _angle_difference(closest.heading, bearing)
        max_diff = config.normalisation.max_heading_diff_deg
        score = max(0.0, 1.0 - heading_diff / max_diff)
        detail = (
            f"Heading diff to origin bearing: {heading_diff:.1f}° "
            f"(vessel heading={closest.heading:.1f}°, "
            f"bearing to origin={bearing:.1f}°)"
        )

    return FeatureScore(
        name="heading",
        score=round(score, 4),
        availability=FeatureAvailability.AVAILABLE,
        detail=detail,
    )


def _calculate_bearing(lat1: float, lon1: float,
                        lat2: float, lon2: float) -> float:
    """
    Initial bearing (forward azimuth) from point 1 to point 2 in degrees.
    Returns value in [0, 360).
    """
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    d_lon_r = math.radians(lon2 - lon1)

    x = math.sin(d_lon_r) * math.cos(lat2_r)
    y = (math.cos(lat1_r) * math.sin(lat2_r)
         - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(d_lon_r))

    bearing = math.degrees(math.atan2(x, y))
    return bearing % 360.0


# ---------------------------------------------------------------------------
# Feature 5: Speed Score
# ---------------------------------------------------------------------------

def calculate_speed_score(
    track: VesselTrack,
    config: AttributionConfig,
) -> FeatureScore:
    """
    Is the vessel speed profile compatible with the event?

    Pipeline §31: if SOG missing → UNAVAILABLE. Never convert NULL→0.
    Architecture §14.2: speed_score.

    Prototype: checks whether the vessel had low/zero speed near the
    origin time (a slowing-down pattern is more suspicious).  A more
    sophisticated version would compare against expected speed profiles.

    PLACEHOLDER: refine once expected speed profile is defined by
    domain experts or the drift module.
    """
    sog_records = [
        r for r in track.records
        if (r.sog is not None and r.base_date_time is not None)
    ]

    if not sog_records:
        return FeatureScore(
            name="speed",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="No valid SOG values in track.",
        )

    # Detect if the vessel had a significant speed reduction
    sog_values = [r.sog for r in sog_records]
    min_sog = min(sog_values)
    max_sog = max(sog_values)
    avg_sog = sum(sog_values) / len(sog_values)

    # A large speed range suggests the vessel slowed down / stopped
    speed_range = max_sog - min_sog
    threshold = config.normalisation.speed_change_threshold_knots

    # Simple scoring: higher score if speed dropped significantly
    if speed_range > threshold and min_sog < 2.0:
        # Vessel showed notable deceleration to near-stop
        score = 0.8
        detail = (f"Speed dropped from {max_sog:.1f} to {min_sog:.1f} kn "
                  f"(range={speed_range:.1f} kn)")
    elif min_sog < 1.0:
        # Vessel was nearly stationary at some point
        score = 0.6
        detail = f"Vessel nearly stationary: min SOG={min_sog:.1f} kn"
    else:
        # No significant speed anomaly
        score = 0.3
        detail = f"Average SOG={avg_sog:.1f} kn, no significant slowdown"

    return FeatureScore(
        name="speed",
        score=round(score, 4),
        availability=FeatureAvailability.AVAILABLE,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Feature 6: Path Proximity Score
# ---------------------------------------------------------------------------

def calculate_path_proximity_score(
    track: VesselTrack,
    spill_geometry: Optional[SpillGeometry],
    config: AttributionConfig,
) -> FeatureScore:
    """
    How closely does the full vessel path approach the spill/origin?

    Pipeline §29: evaluate path against spill geometry.
    Architecture §14.2: path_proximity_score.

    PLACEHOLDER: uses centroid distance when polygon is not available.
    Once Shapely integration is done, compute distance from track
    LineString to spill polygon boundary.
    """
    if spill_geometry is None:
        return FeatureScore(
            name="path_proximity",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="Spill geometry unavailable.",
        )

    valid = _valid_position_records(track)
    if not valid:
        return FeatureScore(
            name="path_proximity",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="No valid position records in track.",
        )

    # PLACEHOLDER: use centroid as proxy for spill location.
    # Replace with polygon-based distance when Shapely is integrated.
    spill_lat = spill_geometry.centroid_lat
    spill_lon = spill_geometry.centroid_lon

    min_dist = min(
        haversine(r.latitude, r.longitude, spill_lat, spill_lon)
        for r in valid
    )

    max_d = config.normalisation.max_distance_km
    score = max(0.0, 1.0 - min_dist / max_d)

    return FeatureScore(
        name="path_proximity",
        score=round(score, 4),
        availability=FeatureAvailability.AVAILABLE,
        detail=f"Minimum distance to spill centroid: {min_dist:.2f} km",
    )


# ---------------------------------------------------------------------------
# Feature 7: Behaviour Score
# ---------------------------------------------------------------------------

def calculate_behaviour_score(
    track: VesselTrack,
    config: AttributionConfig,
) -> FeatureScore:
    """
    Does the vessel show unusual behaviour (sudden speed/course changes)?

    Pipeline §32: detect course and speed anomalies.
    Architecture §12.2: detect_course_anomalies, detect_speed_anomalies.

    IMPORTANT: behaviour anomaly ≠ proof of spill causation (Pipeline §32).
    It is one evidence feature among many.
    """
    valid = _valid_position_records(track)
    if len(valid) < 3:
        return FeatureScore(
            name="behaviour",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="Insufficient records for behaviour analysis (need ≥3).",
        )

    speed_anomalies = _detect_speed_anomalies(valid, config)
    course_anomalies = _detect_course_anomalies(valid, config)

    total_anomalies = speed_anomalies + course_anomalies
    total_intervals = len(valid) - 1

    if total_intervals == 0:
        return FeatureScore(
            name="behaviour",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="Not enough intervals for behaviour analysis.",
        )

    # Anomaly ratio — higher means more anomalous behaviour
    anomaly_ratio = total_anomalies / total_intervals
    score = min(1.0, anomaly_ratio)

    detail_parts = []
    if speed_anomalies > 0:
        detail_parts.append(f"{speed_anomalies} speed anomalies")
    if course_anomalies > 0:
        detail_parts.append(f"{course_anomalies} course anomalies")
    if not detail_parts:
        detail_parts.append("no anomalies detected")

    return FeatureScore(
        name="behaviour",
        score=round(score, 4),
        availability=FeatureAvailability.AVAILABLE,
        detail=f"Behaviour: {', '.join(detail_parts)} "
               f"over {total_intervals} intervals",
    )


def _detect_speed_anomalies(
    records: List[AISRecord],
    config: AttributionConfig,
) -> int:
    """
    Count intervals where SOG changed by more than the threshold.

    Architecture §12.2: detect_speed_anomalies().
    Pipeline §10.6: do not replace missing SOG with 0.
    """
    count = 0
    threshold = config.normalisation.speed_change_threshold_knots

    for i in range(1, len(records)):
        sog_prev = records[i - 1].sog
        sog_curr = records[i].sog

        # Skip intervals where SOG is missing (Pipeline §10.6)
        if sog_prev is None or sog_curr is None:
            continue

        if abs(sog_curr - sog_prev) > threshold:
            count += 1

    return count


def _detect_course_anomalies(
    records: List[AISRecord],
    config: AttributionConfig,
) -> int:
    """
    Count intervals where COG changed by more than the threshold.

    Architecture §12.2: detect_course_anomalies().
    Pipeline §10.7: do not replace missing COG with zero.
    """
    count = 0
    threshold = config.normalisation.course_change_threshold_deg

    for i in range(1, len(records)):
        cog_prev = records[i - 1].cog
        cog_curr = records[i].cog

        # Skip intervals where COG is missing (Pipeline §10.7)
        if cog_prev is None or cog_curr is None:
            continue

        if _angle_difference(cog_curr, cog_prev) > threshold:
            count += 1

    return count


# ---------------------------------------------------------------------------
# Feature 8: Vessel Type Score
# ---------------------------------------------------------------------------

def calculate_vessel_type_score(
    vessel_type: Optional[int],
    config: AttributionConfig,
) -> FeatureScore:
    """
    Contextual relevance of the vessel type.

    Pipeline §33: contextual, do not let it dominate.
    Pipeline §10.12: if vessel_type missing → UNAVAILABLE.

    Uses the VesselTypeRelevance mapping from config.
    """
    if vessel_type is None:
        return FeatureScore(
            name="vessel_type",
            availability=FeatureAvailability.UNAVAILABLE,
            detail="Vessel type unknown.",
        )

    relevance = config.vessel_type_relevance.get_relevance(vessel_type)

    return FeatureScore(
        name="vessel_type",
        score=round(relevance, 4),
        availability=FeatureAvailability.AVAILABLE,
        detail=f"Vessel type code={vessel_type}, relevance={relevance:.2f}",
    )


# ---------------------------------------------------------------------------
# Feature normalization
# ---------------------------------------------------------------------------

def normalise_attribution_features(evidence: EvidenceVector) -> EvidenceVector:
    """
    Ensure all available scores are clamped to [0, 1].

    Architecture §14.4: normalise_attribution_features().
    """
    for feat in evidence.all_features():
        if feat.is_available and feat.score is not None:
            feat.score = max(0.0, min(1.0, feat.score))
    return evidence


# ---------------------------------------------------------------------------
# Master builder: assemble all features for one candidate
# ---------------------------------------------------------------------------

def build_candidate_vessel_features(
    candidate: CandidateVessel,
    origin: Origin,
    drift_result: Optional[DriftResult],
    spill_geometry: Optional[SpillGeometry],
    config: AttributionConfig,
) -> EvidenceVector:
    """
    Compute all 8 evidence features for a single candidate vessel.

    Architecture §13.2: build_candidate_vessel_features().
    Pipeline §55 (FEATURE ENGINEERING step).

    Parameters:
        candidate:      The candidate vessel and its track.
        origin:         Probable spill origin from hindcast.
        drift_result:   Full drift/hindcast result (trajectory, uncertainty).
        spill_geometry: Characterised spill geometry (polygon, centroid).
        config:         Attribution configuration (weights, thresholds).

    Returns:
        EvidenceVector with all 8 feature scores set.
    """
    track = candidate.track

    evidence = EvidenceVector(
        distance=calculate_distance_score(track, origin, config),
        time=calculate_time_score(track, origin.timestamp, config),
        trajectory=calculate_trajectory_score(track, drift_result, config),
        heading=calculate_heading_score(track, drift_result, config),
        speed=calculate_speed_score(track, config),
        path_proximity=calculate_path_proximity_score(
            track, spill_geometry, config),
        behaviour=calculate_behaviour_score(track, config),
        vessel_type=calculate_vessel_type_score(
            candidate.vessel_type, config),
    )

    # Clamp all scores to [0, 1]
    evidence = normalise_attribution_features(evidence)

    return evidence
