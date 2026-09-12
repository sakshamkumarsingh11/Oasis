"""
SIH26143 — App Orchestrator

Top-level controller that ties everything together:
    Segmentation → Hindcast → DuckDB Query → Attribution Engine → Report

This is the single entry point for the full pipeline.
In production, this will be called by the web app or scheduler.
For testing, it can be run directly with synthetic upstream inputs.

Reference:
    Pipeline §55 (complete implementation flow).
    Architecture §16 (orchestrator role).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ais import (
    run_attribution,
    AttributionReport,
    Origin,
    DriftResult,
    SpillGeometry,
)
from ais.duckdb_store import connect, register_csv_data
from ais.query import find_candidate_vessels, required_dates

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default data paths
# ---------------------------------------------------------------------------

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Path to the raw AIS CSV dataset
DEFAULT_CSV_GLOB = str(BASE_DIR / "ais dataset" / "ais-*.csv")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(
    incident_id: str,
    origin: Origin,
    drift_result: Optional[DriftResult] = None,
    spill_geometry: Optional[SpillGeometry] = None,
    search_radius_km: float = 25.0,
    time_window_minutes: float = 60.0,
    csv_glob: Optional[str] = None,
    top_n: int = 5,
    enable_dark_ais: bool = True,
    enable_expansion: bool = True,
) -> AttributionReport:
    """
    Run the complete AIS attribution pipeline for one oil spill incident.

    End-to-end flow:
        1. Connect to DuckDB and register AIS data source.
        2. Run the sequential query pipeline to find candidate vessels.
        3. Feed candidates into the Attribution Engine.
        4. Return the ranked report.

    Args:
        incident_id: Unique incident identifier.
        origin: Probable spill origin from hindcast model.
        drift_result: Full hindcast trajectory result (optional).
        spill_geometry: Spill geometry from segmentation model (optional).
        search_radius_km: Initial spatial search radius in km.
        time_window_minutes: Initial time window (±minutes from origin).
        csv_glob: Glob pattern for AIS CSV files. Uses default if None.
        top_n: Number of top suspects to highlight in the report.
        enable_dark_ais: Enable Dark AIS gap-crossing detection.
        enable_expansion: Enable dynamic search expansion on zero candidates.

    Returns:
        AttributionReport with ranked vessels, confidence, and evidence.
    """
    csv_glob = csv_glob or DEFAULT_CSV_GLOB

    logger.info("=" * 70)
    logger.info("STARTING PIPELINE for incident: %s", incident_id)
    logger.info("Origin: %.4f, %.4f @ %s", origin.latitude, origin.longitude, origin.timestamp)
    logger.info("Search: radius=%.1fkm, window=±%.0fmin", search_radius_km, time_window_minutes)
    logger.info("Data source: %s", csv_glob)
    logger.info("=" * 70)

    # --- Step 1: Connect to DuckDB ---
    logger.info("[1/4] Connecting to DuckDB...")
    con = connect()  # in-memory for speed
    register_csv_data(con, csv_glob)

    # --- Step 2: Run the Query Pipeline ---
    logger.info("[2/4] Running sequential query pipeline...")
    candidates, query_audit = find_candidate_vessels(
        con=con,
        origin=origin,
        search_radius_km=search_radius_km,
        time_window_minutes=time_window_minutes,
        enable_dark_ais=enable_dark_ais,
        enable_expansion=enable_expansion,
    )

    logger.info(
        "[2/4] Query pipeline complete: %d candidate vessels found.",
        len(candidates),
    )
    logger.info("       Query audit: %s", {
        k: v for k, v in query_audit.items()
        if k != "candidate_mmsis"  # Don't log the full MMSI list
    })

    # Determine the AIS dates that were queried
    ais_dates = query_audit.get("required_dates", [])

    # --- Step 3: Run the Attribution Engine ---
    logger.info("[3/4] Running attribution engine on %d candidates...", len(candidates))
    report = run_attribution(
        incident_id=incident_id,
        candidates=candidates if candidates else None,
        origin=origin,
        drift_result=drift_result,
        spill_geometry=spill_geometry,
        search_radius_km=query_audit.get("final_radius_km", search_radius_km),
        time_window_minutes=query_audit.get("final_time_window_min", time_window_minutes),
        ais_dates=ais_dates,
    )

    # --- Step 4: Log results ---
    logger.info("[4/4] Attribution complete!")
    logger.info("       Status: %s", report.status.value)
    logger.info("       Confidence: %s", report.confidence.value)
    logger.info("       Candidates scored: %d", report.candidate_count)

    if report.ranked_vessels:
        logger.info("       Top %d suspects:", min(top_n, len(report.ranked_vessels)))
        for rv in report.ranked_vessels[:top_n]:
            logger.info(
                "         Rank %d: MMSI=%s Name=%s Score=%.4f",
                rv.rank, rv.mmsi,
                rv.vessel_name or "N/A",
                rv.score,
            )

    # Close DuckDB connection
    con.close()

    return report


# ---------------------------------------------------------------------------
# CLI entry point for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Quick test with a synthetic origin point near Norfolk, VA.
    The AIS dataset contains 2026-01-01 through 2026-01-07.
    """
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )

    # Synthetic origin — a point near Norfolk, VA (a busy port)
    test_origin = Origin(
        latitude=36.87,
        longitude=-76.32,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        uncertainty_km=1.0,
    )

    # No hindcast or spill geometry yet — those modules aren't built
    report = run_pipeline(
        incident_id="TEST-NORFOLK-001",
        origin=test_origin,
        search_radius_km=25.0,
        time_window_minutes=60.0,
        top_n=5,
    )

    print("\n" + "=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(f"Incident:   {report.incident_id}")
    print(f"Status:     {report.status.value}")
    print(f"Confidence: {report.confidence.value}")
    print(f"Coverage:   {report.ais_coverage.value}")
    print(f"Candidates: {report.candidate_count}")
    print(f"\n{report.confidence_explanation}")

    if report.ranked_vessels:
        print(f"\nTop 5 Suspects:")
        print("-" * 60)
        for rv in report.ranked_vessels[:5]:
            print(f"  Rank {rv.rank}: MMSI={rv.mmsi}")
            print(f"    Name:  {rv.vessel_name or 'N/A'}")
            print(f"    Score: {rv.score:.4f}")
            print(f"    {rv.evidence_summary}")
            print()
    else:
        print("\nNo suspects identified.")
