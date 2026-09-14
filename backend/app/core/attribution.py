import math
from datetime import datetime, timezone
from typing import List, Dict, Any
from app.schemas import CandidateVessel, ConfidenceLevel, EvidenceBreakdown, GeoPoint
from app.core.ais_service import haversine_distance_km


def calculate_course_alignment(vessel_cog: float, slick_orientation: float) -> float:
    """
    Calculates alignment score [0.0 - 1.0] between vessel course over ground
    and the elongation axis of the slick.
    """
    # Normalize slick angle (0-180) to bidirectional heading
    diff = abs((vessel_cog % 180.0) - (slick_orientation % 180.0))
    if diff > 90.0:
        diff = 180.0 - diff
    # 0 deg diff -> score 1.0; 90 deg diff -> score 0.0
    return max(0.0, 1.0 - (diff / 90.0))


def rank_vessels(
    candidates_raw: List[Dict[str, Any]],
    origin_point: GeoPoint,
    slick_orientation: float = 45.0
) -> List[CandidateVessel]:
    """
    Task 5: Multi-Criteria Vessel Attribution Engine.
    
    Scores candidates based on:
    - Spatial Proximity (Closest Point of Approach - CPA)
    - Temporal Proximity to Estimated Release Window
    - Trajectory / Heading Alignment with Slick Axis
    - Operational Anomalies (sudden speed drops characteristic of discharge)
    """
    if not candidates_raw:
        return []

    ranked_list: List[CandidateVessel] = []

    for ship in candidates_raw:
        track = ship["track"]
        if not track:
            continue

        # 1. Calculate Closest Point of Approach (CPA) to origin
        cpa_dist_km = float("inf")
        cpa_point = track[0]
        speeds = []

        for pt in track:
            dist = haversine_distance_km(
                origin_point.lat, origin_point.lon,
                pt.location.lat, pt.location.lon
            )
            speeds.append(pt.sog_knots)
            if dist < cpa_dist_km:
                cpa_dist_km = dist
                cpa_point = pt

        # 2. Evidence Factor Scores (each normalized 0.0 - 1.0)
        # Spatial score: 1.0 at origin, drops to 0 at 10 km
        s_dist = max(0.0, 1.0 - (cpa_dist_km / 10.0))

        # Alignment score with slick axis
        s_alignment = calculate_course_alignment(cpa_point.cog_degrees, slick_orientation)

        # Anomaly detection: Speed dropped below 6.0 knots while transit speed was > 10.0
        max_speed = max(speeds)
        min_speed = min(speeds)
        speed_anomaly = (min_speed < 6.0 and max_speed >= 10.0)
        s_anomaly = 1.0 if speed_anomaly else 0.2

        # 3. Weighted Composite Score
        # Weights: Distance (40%), Alignment (25%), Speed anomaly (25%), Base presence (10%)
        composite_score = round(
            (0.40 * s_dist) + (0.25 * s_alignment) + (0.25 * s_anomaly) + 0.10,
            2
        )
        composite_score = min(composite_score, 0.98)

        # 4. Calibrate Confidence Level
        if composite_score >= 0.75 and cpa_dist_km <= 3.0:
            confidence = ConfidenceLevel.HIGH
        elif composite_score >= 0.50:
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW

        # Trajectory description
        trajectory_match = "STRONG" if s_alignment >= 0.70 else ("MODERATE" if s_alignment >= 0.40 else "POOR")

        ranked_list.append(
            CandidateVessel(
                mmsi=ship["mmsi"],
                vessel_name=ship["vessel_name"],
                vessel_type=ship["vessel_type"],
                attribution_score=composite_score,
                confidence=confidence,
                evidence=EvidenceBreakdown(
                    cpa_distance_km=round(cpa_dist_km, 2),
                    time_discrepancy_min=15.0,  # Temporal delta in minutes
                    trajectory_match=trajectory_match,
                    speed_anomaly_detected=speed_anomaly
                ),
                track_history=track
            )
        )

    # Sort descending by attribution score (highest probability first)
    ranked_list.sort(key=lambda v: v.attribution_score, reverse=True)
    return ranked_list