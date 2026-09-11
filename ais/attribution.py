"""
SIH26143 — Attribution Engine: Scoring, Ranking & Evidence Summaries

Computes weighted evidence scores, ranks candidate vessels, and produces
human-readable explainable evidence summaries.

Reference:
    Architecture §14.3 (weighted score), §14.4 (functions), §32 (explainability).
    Pipeline §34 (formula), §35 (no legal probability), §49 (many candidates).

CRITICAL: scores are evidence scores, NOT legal probabilities.
The output must never say "Vessel A caused the spill: 82%".
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .config import AttributionConfig, AttributionWeights
from .features import build_candidate_vessel_features
from .schemas import (
    AttributionReport,
    AttributionResult,
    AttributionStatus,
    AISCoverageState,
    CandidateVessel,
    ConfidenceBand,
    DriftResult,
    EvidenceVector,
    FeatureAvailability,
    Origin,
    SpillGeometry,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Weighted evidence score
# ---------------------------------------------------------------------------

def calculate_evidence_score(
    evidence: EvidenceVector,
    weights: AttributionWeights,
) -> float:
    """
    Compute the weighted evidence score for a candidate vessel.

    Architecture §14.3:
        Total Score = Σ (wi * feature_i)  for available features only.

    When some features are unavailable, the remaining weights are
    renormalised so the total still reflects only the available evidence.

    Pipeline §34: weights belong in configuration.

    Returns:
        float in [0, 1] — the weighted evidence score.
    """
    weight_map: Dict[str, float] = weights.as_dict()
    feature_list = evidence.all_features()

    numerator = 0.0
    weight_sum = 0.0

    for feat in feature_list:
        w = weight_map.get(feat.name, 0.0)
        if feat.is_available and feat.score is not None:
            numerator += w * feat.score
            weight_sum += w

    if weight_sum == 0.0:
        # No features available at all
        return 0.0

    # Renormalise: divide by the sum of weights that were actually used,
    # so the score stays in [0, 1] regardless of how many features
    # were computable.
    return round(numerator / weight_sum, 4)


# ---------------------------------------------------------------------------
# Build human-readable evidence summary
# ---------------------------------------------------------------------------

def build_attribution_evidence(
    candidate: CandidateVessel,
    evidence: EvidenceVector,
) -> str:
    """
    Build a human-readable evidence summary for one candidate.

    Architecture §32, Pipeline §35: explainable, checkmark-style.

    Example output:
        ✓ 2.1 km from probable origin
        ✓ strong temporal match
        ✓ trajectory compatible with drift corridor
        ✗ heading data unavailable
        ✓ moderate behavioural anomaly
    """
    lines = []

    # Header
    name = candidate.vessel_name or "Name unavailable"
    lines.append(f"MMSI: {candidate.mmsi} ({name})")
    lines.append("")

    for feat in evidence.all_features():
        if not feat.is_available:
            lines.append(f"  ✗ {feat.name}: unavailable"
                         + (f" — {feat.detail}" if feat.detail else ""))
        else:
            # Classify strength
            strength = _score_strength(feat.score)
            lines.append(
                f"  ✓ {feat.name}: {strength}"
                + (f" — {feat.detail}" if feat.detail else "")
            )

    return "\n".join(lines)


def _score_strength(score: float | None) -> str:
    """Map a [0, 1] score to a qualitative strength label."""
    if score is None:
        return "unavailable"
    if score >= 0.8:
        return "strong"
    if score >= 0.5:
        return "moderate"
    if score >= 0.2:
        return "weak"
    return "very weak"


# ---------------------------------------------------------------------------
# Rank candidate vessels
# ---------------------------------------------------------------------------

def rank_candidate_vessels(
    candidates: List[CandidateVessel],
    origin: Origin,
    drift_result: Optional[DriftResult],
    spill_geometry: Optional[SpillGeometry],
    config: AttributionConfig,
) -> List[AttributionResult]:
    """
    Score all candidates, sort descending, assign ranks.

    Architecture §14.4: rank_candidate_vessels().
    Pipeline §49: return ALL candidates passing initial search, ranked.
    Pipeline §35: do NOT present score as legal probability.

    Parameters:
        candidates:     List of candidate vessels from the AIS search stage.
        origin:         Probable spill origin.
        drift_result:   Hindcast result (may be None if unavailable).
        spill_geometry: Characterised spill (may be None).
        config:         Attribution configuration.

    Returns:
        Sorted list of AttributionResult, rank 1 = highest score.
    """
    if not candidates:
        logger.info("No candidate vessels to rank.")
        return []

    results: List[AttributionResult] = []

    for candidate in candidates:
        # Compute all evidence features
        evidence = build_candidate_vessel_features(
            candidate=candidate,
            origin=origin,
            drift_result=drift_result,
            spill_geometry=spill_geometry,
            config=config,
        )

        # Weighted score
        score = calculate_evidence_score(evidence, config.weights)

        # Evidence summary
        summary = build_attribution_evidence(candidate, evidence)

        results.append(AttributionResult(
            mmsi=candidate.mmsi,
            rank=0,  # assigned after sorting
            score=score,
            confidence=ConfidenceBand.MEDIUM,  # refined by quality module
            evidence=evidence,
            evidence_summary=summary,
            vessel_name=candidate.vessel_name,
            imo=candidate.imo,
        ))

    # Sort by score descending (Pipeline §55: RANK CANDIDATES)
    results.sort(key=lambda r: r.score, reverse=True)

    # Assign ranks (1-indexed)
    for i, result in enumerate(results, start=1):
        result.rank = i

    logger.info(
        "Ranked %d candidate vessels. Top score: %.4f (MMSI %s)",
        len(results),
        results[0].score if results else 0.0,
        results[0].mmsi if results else "N/A",
    )

    return results


# ---------------------------------------------------------------------------
# Build full attribution result
# ---------------------------------------------------------------------------

def build_attribution_result(
    incident_id: str,
    ranked_vessels: List[AttributionResult],
    ais_coverage: AISCoverageState,
    attribution_status: AttributionStatus,
    confidence: ConfidenceBand,
    confidence_explanation: str = "",
    search_radius_km: Optional[float] = None,
    time_window_minutes: Optional[float] = None,
    ais_dates: Optional[List[str]] = None,
) -> AttributionReport:
    """
    Assemble the complete attribution output for one incident.

    Architecture §14.4: build_attribution_result().
    Architecture §41: end-to-end output contract.
    Pipeline §52: audit trail fields.
    """
    return AttributionReport(
        incident_id=incident_id,
        status=attribution_status,
        ais_coverage=ais_coverage,
        confidence=confidence,
        ranked_vessels=ranked_vessels,
        candidate_count=len(ranked_vessels),
        confidence_explanation=confidence_explanation,
        search_radius_km=search_radius_km,
        time_window_minutes=time_window_minutes,
        ais_dates=ais_dates,
    )


# ---------------------------------------------------------------------------
# Validate attribution result
# ---------------------------------------------------------------------------

def validate_attribution_result(result: AttributionReport) -> bool:
    """
    Sanity-check the attribution report.

    Architecture §14.4: validate_attribution_result().

    Returns True if valid, raises ValueError otherwise.
    """
    # If status is UNAVAILABLE, there should be no ranked vessels
    if result.status == AttributionStatus.UNAVAILABLE:
        if result.ranked_vessels:
            raise ValueError(
                "Attribution status is UNAVAILABLE but ranked_vessels "
                f"is non-empty ({len(result.ranked_vessels)} vessels). "
                "This is contradictory."
            )

    # If there are ranked vessels, ranks must be sequential
    if result.ranked_vessels:
        ranks = [r.rank for r in result.ranked_vessels]
        expected = list(range(1, len(ranks) + 1))
        if ranks != expected:
            raise ValueError(
                f"Ranks are not sequential 1..N. Got: {ranks}"
            )

    # Scores must be in [0, 1]
    for vessel in result.ranked_vessels:
        if not (0.0 <= vessel.score <= 1.0):
            raise ValueError(
                f"Vessel {vessel.mmsi} has score {vessel.score} "
                "outside [0, 1] range."
            )

    # candidate_count must match
    if result.candidate_count != len(result.ranked_vessels):
        raise ValueError(
            f"candidate_count={result.candidate_count} does not match "
            f"len(ranked_vessels)={len(result.ranked_vessels)}."
        )

    return True
