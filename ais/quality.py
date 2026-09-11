"""
SIH26143 — Attribution Engine: Quality & Confidence Assessment

Evaluates AIS coverage, evidence quality, and determines whether
attribution is possible and at what confidence level.

Reference:
    Architecture §15 (confidence & data availability layer).
    Pipeline §36–50 (AIS coverage states, edge cases).
    Pipeline §52 (audit trail).

Edge cases handled explicitly:
    - No AIS data → UNAVAILABLE (Pipeline §37)
    - Sparse AIS → PARTIAL (Pipeline §38)
    - AIS exists but zero candidates → UNAVAILABLE (Pipeline §39)
    - Single missing field → reduce coverage, not reject (Pipeline §40)
    - Large gaps → lower coverage, disable interpolation (Pipeline §47)
    - Stationary vessel → still valid (Pipeline §48)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from .config import AttributionConfig
from .schemas import (
    AISCoverageState,
    AttributionReport,
    AttributionResult,
    AttributionStatus,
    CandidateVessel,
    ConfidenceBand,
    EvidenceVector,
    Origin,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AIS coverage assessment
# ---------------------------------------------------------------------------

def assess_ais_coverage(
    candidates: Optional[List[CandidateVessel]],
    origin: Origin,
    time_window_minutes: float,
    config: AttributionConfig,
) -> AISCoverageState:
    """
    Determine the AIS coverage state for this investigation.

    Architecture §15.1, Pipeline §36:
        FULL       → sufficient AIS records and spatial/temporal coverage
        PARTIAL    → AIS exists but has gaps or limited coverage
        INSUFFICIENT → AIS exists but too sparse for reliable attribution
        UNAVAILABLE  → no AIS data at all

    Parameters:
        candidates:          Candidate vessels from the AIS search stage.
                             None if AIS was completely unavailable.
        origin:              Probable spill origin.
        time_window_minutes: Investigation time window width.
        config:              Attribution configuration.

    Returns:
        AISCoverageState enum value.
    """
    # Case: AIS data was completely unavailable (Pipeline §37)
    if candidates is None:
        logger.info("AIS coverage: UNAVAILABLE — no AIS data provided.")
        return AISCoverageState.UNAVAILABLE

    # Case: AIS query ran but returned zero candidates (Pipeline §39)
    if len(candidates) == 0:
        logger.info(
            "AIS coverage: UNAVAILABLE — query succeeded but zero "
            "candidates found within search criteria."
        )
        return AISCoverageState.UNAVAILABLE

    # Evaluate coverage quality based on candidate tracks
    avg_coverage = _average_track_coverage(candidates, config)

    threshold_full = config.confidence.full_coverage_threshold
    threshold_insufficient = config.confidence.insufficient_coverage_threshold

    if avg_coverage >= threshold_full:
        logger.info(
            "AIS coverage: FULL (avg coverage=%.2f)", avg_coverage
        )
        return AISCoverageState.FULL
    elif avg_coverage >= threshold_insufficient:
        logger.info(
            "AIS coverage: PARTIAL (avg coverage=%.2f)", avg_coverage
        )
        return AISCoverageState.PARTIAL
    else:
        logger.info(
            "AIS coverage: INSUFFICIENT (avg coverage=%.2f)", avg_coverage
        )
        return AISCoverageState.INSUFFICIENT


def _average_track_coverage(
    candidates: List[CandidateVessel],
    config: AttributionConfig,
) -> float:
    """
    Compute average track coverage score across candidates.

    Considers:
    - Number of records per track
    - Observation gaps
    - Availability of position/time fields

    Pipeline §47: large gaps reduce coverage.
    Pipeline §40: missing individual fields reduce coverage but
                  don't invalidate the track.
    """
    if not candidates:
        return 0.0

    scores = []
    for candidate in candidates:
        track = candidate.track
        if not track.records:
            scores.append(0.0)
            continue

        # Use pre-computed coverage_score if available
        if track.coverage_score is not None:
            scores.append(track.coverage_score)
            continue

        # Otherwise compute it
        score = _compute_track_coverage(track, config)
        track.coverage_score = score
        scores.append(score)

    return sum(scores) / len(scores)


def _compute_track_coverage(
    track,
    config: AttributionConfig,
) -> float:
    """
    Compute coverage score for a single vessel track.

    Factors:
    1. Record count sufficiency
    2. Observation gap quality
    3. Field completeness

    Returns a score in [0, 1].
    """
    records = track.records
    if not records:
        return 0.0

    # Factor 1: record count
    min_records = config.interpolation.min_records_for_trajectory
    record_factor = min(1.0, len(records) / max(1, min_records * 3))

    # Factor 2: observation gaps
    gap_factor = _gap_quality_score(records, config)

    # Factor 3: field completeness — what fraction of core fields
    # are non-null across records?
    completeness = _field_completeness(records)

    # Weighted combination
    coverage = (
        0.4 * record_factor
        + 0.4 * gap_factor
        + 0.2 * completeness
    )

    return round(max(0.0, min(1.0, coverage)), 4)


def _gap_quality_score(records, config: AttributionConfig) -> float:
    """
    Assess quality based on time gaps between consecutive records.

    Pipeline §47: large gaps → lower score, interpolation disabled.
    """
    timestamps = [
        r.base_date_time for r in records
        if r.base_date_time is not None
    ]
    if len(timestamps) < 2:
        return 0.0

    timestamps.sort()

    max_gap = config.interpolation.max_gap_minutes
    gaps_minutes = []

    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60.0
        gaps_minutes.append(delta)

    if not gaps_minutes:
        return 0.0

    # Score is based on fraction of gaps that are within acceptable range
    good_gaps = sum(1 for g in gaps_minutes if g <= max_gap)
    gap_ratio = good_gaps / len(gaps_minutes)

    # Also penalise very large maximum gap
    max_observed = max(gaps_minutes)
    if max_observed > max_gap * 6:  # e.g. > 90 min gap when max is 15
        gap_ratio *= 0.5

    return gap_ratio


def _field_completeness(records) -> float:
    """
    Average completeness of core AIS fields across all records.

    Core fields for trajectory analysis: lat, lon, timestamp, sog, cog.
    Pipeline §10: each missing field is handled explicitly.
    """
    if not records:
        return 0.0

    total_fields = 0
    present_fields = 0

    for r in records:
        # Core fields
        core = [
            r.latitude,
            r.longitude,
            r.base_date_time,
            r.sog,
            r.cog,
        ]
        total_fields += len(core)
        present_fields += sum(1 for v in core if v is not None)

    if total_fields == 0:
        return 0.0

    return present_fields / total_fields


# ---------------------------------------------------------------------------
# Evidence quality assessment
# ---------------------------------------------------------------------------

def assess_evidence_quality(
    evidence_vectors: List[EvidenceVector],
) -> float:
    """
    Overall evidence quality: average feature coverage across candidates.

    Architecture §15.3: assess_evidence_quality().

    Returns:
        float in [0, 1] — average fraction of features that were
        computable across all candidates.
    """
    if not evidence_vectors:
        return 0.0

    coverages = [ev.feature_coverage() for ev in evidence_vectors]
    return round(sum(coverages) / len(coverages), 4)


# ---------------------------------------------------------------------------
# Data quality score for a single candidate
# ---------------------------------------------------------------------------

def calculate_data_quality_score(
    evidence: EvidenceVector,
) -> float:
    """
    Data quality score for a single candidate based on feature coverage.

    Architecture §14.4: calculate_data_quality_score().

    Returns:
        float in [0, 1].
    """
    return evidence.feature_coverage()


# ---------------------------------------------------------------------------
# Attribution confidence
# ---------------------------------------------------------------------------

def calculate_attribution_confidence(
    ranked_results: List[AttributionResult],
    data_quality: float,
    config: AttributionConfig,
) -> ConfidenceBand:
    """
    Determine overall confidence band for the attribution.

    Architecture §15.3: calculate_attribution_confidence().

    Considers:
    - Top candidate's evidence score
    - Overall data quality / feature coverage
    - Score separation between top candidates

    Architecture §15.4:
        FULL coverage   → High / Medium / Low
        PARTIAL coverage → reduced confidence
    """
    if not ranked_results:
        return ConfidenceBand.LOW

    top_score = ranked_results[0].score

    # Combined quality metric
    combined = (top_score * 0.6) + (data_quality * 0.4)

    if combined >= config.confidence.high_confidence_min_score:
        band = ConfidenceBand.HIGH
    elif combined >= config.confidence.medium_confidence_min_score:
        band = ConfidenceBand.MEDIUM
    else:
        band = ConfidenceBand.LOW

    logger.info(
        "Attribution confidence: %s (top_score=%.4f, "
        "data_quality=%.4f, combined=%.4f)",
        band.value, top_score, data_quality, combined,
    )

    return band


# ---------------------------------------------------------------------------
# Attribution status
# ---------------------------------------------------------------------------

def determine_attribution_status(
    ais_coverage: AISCoverageState,
    evidence_quality: float,
    config: AttributionConfig,
) -> AttributionStatus:
    """
    Whether attribution can be produced.

    Architecture §15.2 (decision flow), §15.4.
    Pipeline §36–39: explicit status determination.
    """
    # No AIS at all → unavailable (Pipeline §37)
    if ais_coverage == AISCoverageState.UNAVAILABLE:
        return AttributionStatus.UNAVAILABLE

    # AIS insufficient → unavailable (Pipeline §36)
    if ais_coverage == AISCoverageState.INSUFFICIENT:
        return AttributionStatus.UNAVAILABLE

    # AIS partial → available with reduced confidence (Pipeline §38)
    if ais_coverage == AISCoverageState.PARTIAL:
        return AttributionStatus.AVAILABLE_REDUCED_CONFIDENCE

    # FULL AIS — check evidence quality
    if evidence_quality < config.confidence.min_feature_coverage:
        return AttributionStatus.AVAILABLE_REDUCED_CONFIDENCE

    return AttributionStatus.AVAILABLE


# ---------------------------------------------------------------------------
# Confidence band for individual scores
# ---------------------------------------------------------------------------

def calculate_confidence_band(
    score: float,
    quality_score: float,
) -> ConfidenceBand:
    """
    Map a score + quality into a confidence band for a single vessel.

    Architecture §15.3: calculate_confidence_band().
    """
    combined = score * 0.7 + quality_score * 0.3

    if combined >= 0.7:
        return ConfidenceBand.HIGH
    elif combined >= 0.4:
        return ConfidenceBand.MEDIUM
    else:
        return ConfidenceBand.LOW


# ---------------------------------------------------------------------------
# Confidence explanation
# ---------------------------------------------------------------------------

def build_confidence_explanation(
    ais_coverage: AISCoverageState,
    attribution_status: AttributionStatus,
    confidence: ConfidenceBand,
    candidate_count: int,
    evidence_quality: float,
) -> str:
    """
    Build a human-readable explanation of the confidence determination.

    Architecture §15.3: build_confidence_explanation().
    Pipeline §35: explainable results.
    """
    lines = []

    lines.append(f"AIS Coverage: {ais_coverage.value}")
    lines.append(f"Attribution Status: {attribution_status.value}")
    lines.append(f"Overall Confidence: {confidence.value}")
    lines.append(f"Candidate Count: {candidate_count}")
    lines.append(f"Evidence Quality: {evidence_quality:.2f}")

    # Add contextual explanation
    if attribution_status == AttributionStatus.UNAVAILABLE:
        if ais_coverage == AISCoverageState.UNAVAILABLE:
            lines.append("")
            lines.append(
                "Attribution unavailable: no usable AIS data exists "
                "for the investigation window."
            )
        elif ais_coverage == AISCoverageState.INSUFFICIENT:
            lines.append("")
            lines.append(
                "Attribution unavailable: AIS data exists but is "
                "too sparse for reliable attribution."
            )
        elif candidate_count == 0:
            lines.append("")
            lines.append(
                "Attribution unavailable: AIS query succeeded but "
                "no vessels were found within the search criteria."
            )
    elif attribution_status == AttributionStatus.AVAILABLE_REDUCED_CONFIDENCE:
        lines.append("")
        lines.append(
            "Attribution available with reduced confidence due to "
            "partial AIS coverage or limited evidence features."
        )
    else:
        lines.append("")
        lines.append("Attribution available with full evidence coverage.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Apply confidence to individual results
# ---------------------------------------------------------------------------

def apply_confidence_to_results(
    results: List[AttributionResult],
    ais_coverage: AISCoverageState,
) -> List[AttributionResult]:
    """
    Set the confidence band on each individual vessel result.

    Adjusts confidence downward for partial/insufficient AIS coverage.
    """
    for result in results:
        quality = calculate_data_quality_score(result.evidence)
        band = calculate_confidence_band(result.score, quality)

        # Reduce confidence if AIS coverage is partial
        if ais_coverage == AISCoverageState.PARTIAL:
            if band == ConfidenceBand.HIGH:
                band = ConfidenceBand.MEDIUM

        result.confidence = band

    return results
