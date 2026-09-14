from datetime import datetime, timezone, timedelta
from app.schemas import (
    SpillAnalysisResponse, SpillGeometry, GeoPoint, SpillDrift, ProbableOrigin, DriftPoint,
    AISCoverageStatus, CandidateVessel, ConfidenceLevel, EvidenceBreakdown, TrackPoint
)

def get_scenario(scenario_id: str) -> SpillAnalysisResponse:
    now = datetime.now(timezone.utc)
    
    if scenario_id == "mumbai_high":
        return SpillAnalysisResponse(
            spill_id="SPILL_MH_001",
            detection_timestamp=now,
            segmentation_confidence=0.94,
            geometry=SpillGeometry(
                centroid=GeoPoint(lat=19.41, lon=71.32),
                area_km2=14.72,
                perimeter_km=18.4,
                bbox=[19.38, 71.29, 19.44, 71.35],
                orientation_degrees=42.5
            ),
            drift=SpillDrift(
                hindcast_origin=ProbableOrigin(
                    centroid=GeoPoint(lat=19.42, lon=71.31),
                    time_window_start=now - timedelta(hours=7),
                    time_window_end=now - timedelta(hours=5),
                    uncertainty_radius_km=3.5
                ),
                forecast_trajectory=[
                    DriftPoint(timestamp=now + timedelta(hours=3), location=GeoPoint(lat=19.40, lon=71.33)),
                    DriftPoint(timestamp=now + timedelta(hours=6), location=GeoPoint(lat=19.39, lon=71.34)),
                    DriftPoint(timestamp=now + timedelta(hours=9), location=GeoPoint(lat=19.38, lon=71.35)),
                    DriftPoint(timestamp=now + timedelta(hours=12), location=GeoPoint(lat=19.37, lon=71.36))
                ]
            ),
            ais_status=AISCoverageStatus.AVAILABLE,
            ranked_vessels=[
                CandidateVessel(
                    mmsi="419000123",
                    vessel_name="SWARNA MALA",
                    vessel_type="Crude Oil Tanker",
                    attribution_score=0.96,
                    confidence=ConfidenceLevel.HIGH,
                    evidence=EvidenceBreakdown(
                        cpa_distance_km=0.6,
                        time_discrepancy_min=4.2,
                        trajectory_match="STRONG",
                        speed_anomaly_detected=True
                    ),
                    track_history=[
                        TrackPoint(location=GeoPoint(lat=19.43, lon=71.30), timestamp=now - timedelta(hours=7), sog_knots=11.2, cog_degrees=135.0),
                        TrackPoint(location=GeoPoint(lat=19.42, lon=71.31), timestamp=now - timedelta(hours=6), sog_knots=4.2, cog_degrees=135.0),
                        TrackPoint(location=GeoPoint(lat=19.41, lon=71.32), timestamp=now - timedelta(hours=5), sog_knots=12.1, cog_degrees=135.0)
                    ]
                )
            ],
            status_message="Analysis completed with high attribution confidence for SWARNA MALA."
        )

    elif scenario_id == "kutch_dark_vessel":
        return SpillAnalysisResponse(
            spill_id="SPILL_KD_002",
            detection_timestamp=now,
            segmentation_confidence=0.88,
            geometry=SpillGeometry(
                centroid=GeoPoint(lat=22.61, lon=69.25),
                area_km2=8.3,
                perimeter_km=9.1,
                bbox=[22.59, 69.23, 22.63, 69.27],
                orientation_degrees=115.0
            ),
            drift=SpillDrift(
                hindcast_origin=ProbableOrigin(
                    centroid=GeoPoint(lat=22.62, lon=69.24),
                    time_window_start=now - timedelta(hours=6),
                    time_window_end=now - timedelta(hours=4),
                    uncertainty_radius_km=4.2
                ),
                forecast_trajectory=[
                    DriftPoint(timestamp=now + timedelta(hours=3), location=GeoPoint(lat=22.60, lon=69.26)),
                    DriftPoint(timestamp=now + timedelta(hours=6), location=GeoPoint(lat=22.59, lon=69.27)),
                    DriftPoint(timestamp=now + timedelta(hours=9), location=GeoPoint(lat=22.58, lon=69.28)),
                    DriftPoint(timestamp=now + timedelta(hours=12), location=GeoPoint(lat=22.57, lon=69.29))
                ]
            ),
            ais_status=AISCoverageStatus.UNAVAILABLE,
            ranked_vessels=[],
            status_message="AIS unavailable. Triggering tactical ICG Dornier-228 aerial search coordinates."
        )

    elif scenario_id == "bengal_lookalike":
        return SpillAnalysisResponse(
            spill_id="SPILL_BL_003",
            detection_timestamp=now,
            segmentation_confidence=0.45,
            geometry=SpillGeometry(
                centroid=GeoPoint(lat=14.25, lon=83.51),
                area_km2=2.1,
                perimeter_km=4.5,
                bbox=[14.24, 83.50, 14.26, 83.52],
                orientation_degrees=0.0
            ),
            drift=SpillDrift(
                hindcast_origin=ProbableOrigin(
                    centroid=GeoPoint(lat=14.25, lon=83.51),
                    time_window_start=now - timedelta(hours=2),
                    time_window_end=now - timedelta(hours=1),
                    uncertainty_radius_km=1.0
                ),
                forecast_trajectory=[]
            ),
            ais_status=AISCoverageStatus.AVAILABLE,
            ranked_vessels=[],
            status_message="Model 2 confirms low contrast (< 1.2 dB). Flagged as PROBABLE_LOOKALIKE (calm sea)."
        )

    raise ValueError("Scenario not found")
