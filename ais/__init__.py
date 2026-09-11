"""
SIH26143 — AIS Attribution Engine

Public API for the vessel attribution engine.

Usage by the orchestrator (Architecture §16):

    from ais import run_attribution

    report = run_attribution(
        incident_id="INC-001",
        candidates=candidate_vessels,
        origin=probable_origin,
        drift_result=hindcast_result,
        spill_geometry=spill_geo,
    )
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .schemas import (  # noqa: F401
    # Enums
    AISCoverageState,
    AttributionStatus,
    ConfidenceBand,
    FeatureAvailability,
    # Domain objects — upstream inputs
    AISRecord,
    CandidateVessel,
    DriftResult,
    Origin,
    SpillGeometry,
    VesselTrack,
    # Evidence / Attribution objects
    AttributionReport,
    AttributionResult,
    EvidenceVector,
    FeatureScore,
)

from .config import (  # noqa: F401
    AttributionConfig,
    AttributionWeights,
    load_config,
    validate_config,
)

from .features import (  # noqa: F401
    build_candidate_vessel_features,
    haversine,
)

from .attribution import (  # noqa: F401
    build_attribution_result,
    calculate_evidence_score,
    rank_candidate_vessels,
    validate_attribution_result,
)

from .quality import (  # noqa: F401
    apply_confidence_to_results,
    assess_ais_coverage,
    assess_evidence_quality,
    build_confidence_explanation,
    calculate_attribution_confidence,
    determine_attribution_status,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top-level orchestration entry point
# ---------------------------------------------------------------------------

def run_attribution(
    incident_id: str,
    candidates: Optional[List[CandidateVessel]],
    origin: Origin,
    drift_result: Optional[DriftResult] = None,
    spill_geometry: Optional[SpillGeometry] = None,
    config: Optional[AttributionConfig] = None,
    search_radius_km: Optional[float] = None,
    time_window_minutes: Optional[float] = None,
    ais_dates: Optional[List[str]] = None,
) -> AttributionReport:
    """
    Run the complete attribution pipeline for one incident.

    This is the single entry point called by the orchestrator
    (Architecture §16: run_attribution_stage).

    Flow (Pipeline §55):
        candidates → features → scoring → ranking → confidence → report

    Parameters:
        incident_id:        Unique incident identifier.
        candidates:         Candidate vessels from AIS spatial/temporal search.
                            None if AIS was completely unavailable.
        origin:             Probable spill origin from hindcast.
        drift_result:       Full hindcast result (optional).
        spill_geometry:     Characterised spill geometry (optional).
        config:             Attribution configuration (uses defaults if None).
        search_radius_km:   Search radius used (for audit trail).
        time_window_minutes: Time window used (for audit trail).
        ais_dates:          AIS date partitions queried (for audit trail).

    Returns:
        AttributionReport with ranked vessels, confidence, and status.
    """
    if config is None:
        config = load_config()
        validate_config(config)

    # --- Step 1: Assess AIS coverage (Pipeline §36–39) ---
    ais_coverage = assess_ais_coverage(
        candidates=candidates,
        origin=origin,
        time_window_minutes=time_window_minutes or (
            config.temporal_window_hours * 60),
        config=config,
    )

    logger.info(
        "incident=%s AIS_coverage=%s candidate_count=%s",
        incident_id,
        ais_coverage.value,
        len(candidates) if candidates else 0,
    )

    # --- Step 2: Early exit if attribution is impossible ---
    if candidates is None or len(candidates) == 0:
        status = determine_attribution_status(
            ais_coverage, 0.0, config)
        explanation = build_confidence_explanation(
            ais_coverage, status, ConfidenceBand.LOW,
            candidate_count=0, evidence_quality=0.0,
        )
        return build_attribution_result(
            incident_id=incident_id,
            ranked_vessels=[],
            ais_coverage=ais_coverage,
            attribution_status=status,
            confidence=ConfidenceBand.LOW,
            confidence_explanation=explanation,
            search_radius_km=search_radius_km,
            time_window_minutes=time_window_minutes,
            ais_dates=ais_dates,
        )

    # --- Step 3: Rank candidates (features → scoring → ranking) ---
    ranked = rank_candidate_vessels(
        candidates=candidates,
        origin=origin,
        drift_result=drift_result,
        spill_geometry=spill_geometry,
        config=config,
    )

    # --- Step 4: Assess evidence quality ---
    evidence_vectors = [r.evidence for r in ranked]
    evidence_quality = assess_evidence_quality(evidence_vectors)

    # --- Step 5: Determine attribution status ---
    attribution_status = determine_attribution_status(
        ais_coverage, evidence_quality, config)

    # --- Step 6: Calculate overall confidence ---
    confidence = calculate_attribution_confidence(
        ranked, evidence_quality, config)

    # --- Step 7: Apply per-vessel confidence bands ---
    ranked = apply_confidence_to_results(ranked, ais_coverage)

    # --- Step 8: Build explanation ---
    explanation = build_confidence_explanation(
        ais_coverage, attribution_status, confidence,
        candidate_count=len(ranked),
        evidence_quality=evidence_quality,
    )

    # --- Step 9: Assemble final report ---
    report = build_attribution_result(
        incident_id=incident_id,
        ranked_vessels=ranked,
        ais_coverage=ais_coverage,
        attribution_status=attribution_status,
        confidence=confidence,
        confidence_explanation=explanation,
        search_radius_km=search_radius_km,
        time_window_minutes=time_window_minutes,
        ais_dates=ais_dates,
    )

    # --- Step 10: Validate ---
    validate_attribution_result(report)

    logger.info(
        "incident=%s attribution_status=%s confidence=%s "
        "top_rank=%s top_score=%.4f",
        incident_id,
        attribution_status.value,
        confidence.value,
        ranked[0].mmsi if ranked else "N/A",
        ranked[0].score if ranked else 0.0,
    )

    return report
