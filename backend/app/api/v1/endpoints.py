from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone
from typing import Optional
import numpy as np
import cv2
import logging

from app.schemas import SpillAnalysisResponse
from app.core.segmentation import run_segmentation
from app.core.geometry import extract_geometry
from app.core.drift_engine import compute_drift, MetoceanCondition
from app.core.ais_service import search_nearby_vessels
from app.core.attribution import rank_vessels
from app.core.metocean_service import fetch_live_metocean
from app.core.scenarios import get_scenario
from app.utils.report_generator import generate_forensic_pdf

logger = logging.getLogger("endpoints")

router = APIRouter()


def get_default_utc_now() -> datetime:
    """Returns timezone-aware UTC datetime (Python 3.12+ compliant)."""
    return datetime.now(timezone.utc)


def _try_lookalike_verification(seg_result: dict, spill_mask: np.ndarray):
    """
    Attempt to run Model 2 (EfficientNet-B0 lookalike verifier) on the
    segmentation output. Falls back gracefully if unavailable.

    Returns (verified_mask, forensic_result_or_None).
    """
    raw_sar = seg_result.get("raw_sar_gray")
    if raw_sar is None:
        logger.info("Lookalike verifier skipped: no raw SAR image available from segmentation.")
        return spill_mask, None

    try:
        from app.core.lookalike_verifier import verify_spill, Model2Config, load_model
        from pathlib import Path

        config = Model2Config()

        # Try to load the EfficientNet-B0 checkpoint
        model = None
        search_paths = [
            Path(__file__).resolve().parents[2] / "best_lookalike_model.pt",
            Path(__file__).resolve().parents[3] / "best_lookalike_model.pt",
            Path("best_lookalike_model.pt"),
        ]
        for p in search_paths:
            if p.exists():
                try:
                    model = load_model(str(p), config)
                    logger.info("Lookalike model loaded from %s", p)
                except Exception as e:
                    logger.warning("Failed to load lookalike model from %s: %s", p, e)
                break

        # Run verification (works in physics-only mode even without CNN model)
        forensic = verify_spill(raw_sar, spill_mask, model=model, config=config)

        verified_mask = forensic.get("clean_mask", spill_mask)
        logger.info(
            "Lookalike verification: status=%s, proceed=%s, oil_prob=%.3f",
            forensic.get("forensic_status"),
            forensic.get("proceed_with_attribution"),
            forensic.get("mineral_oil_probability", 0),
        )
        return verified_mask, forensic

    except Exception as e:
        logger.warning("Lookalike verifier failed (%s) — using raw segmentation mask.", e)
        return spill_mask, None


@router.get("/metocean")
async def get_metocean(lat: float, lon: float):
    return await fetch_live_metocean(lat, lon)


@router.post("/analyze", response_model=SpillAnalysisResponse, summary="Analyze SAR image and attribute spill")
async def analyze_spill(
    file: UploadFile = File(..., description="Sentinel-1 SAR image (GeoTIFF/PNG)"),
    approx_lat: float = Form(15.2105, description="Observation Latitude"),
    approx_lon: float = Form(65.4210, description="Observation Longitude"),
    observation_time: datetime = Form(default_factory=get_default_utc_now),
    wind_speed_ms: Optional[float] = Form(None, description="Local wind speed in m/s"),
    wind_dir_from: Optional[float] = Form(None, description="Wind direction from in degrees (0-360)"),
    current_speed_ms: Optional[float] = Form(None, description="Surface current speed in m/s"),
    current_dir_to: Optional[float] = Form(None, description="Surface current direction to in degrees (0-360)")
):
    image_bytes = await file.read()

    try:
        # 1. Task 1: U-Net Segmentation (real model inference)
        seg_result = run_segmentation(image_bytes)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))

    # Pass the real mask from the model
    spill_mask = seg_result.get("mask", np.zeros((256, 256), dtype=np.uint8))

    # 1b. Task 1b: Lookalike Verification (Model 2)
    verified_mask, forensic_result = _try_lookalike_verification(seg_result, spill_mask)

    # Use verified mask for downstream if available
    final_mask = verified_mask if verified_mask is not None else spill_mask

    # Adjust confidence using forensic result if available
    seg_confidence = seg_result["confidence"]
    if forensic_result and "mineral_oil_probability" in forensic_result:
        # Blend segmentation confidence with lookalike verification probability
        seg_confidence = round(
            0.6 * seg_result["confidence"] + 0.4 * forensic_result["mineral_oil_probability"],
            4
        )

    # 2. Task 2: Real Metric Geometry Extraction
    geom = extract_geometry(
        mask=final_mask,
        center_lat=approx_lat,
        center_lon=approx_lon,
        pixel_resolution_m=10.0
    )

    # 3. Task 3: Physics Leeway Drift Engine (Hindcast & Forecast)
    if None in (wind_speed_ms, wind_dir_from, current_speed_ms, current_dir_to):
        metocean = await fetch_live_metocean(approx_lat, approx_lon)
    else:
        metocean = MetoceanCondition(
            wind_speed_ms=wind_speed_ms,
            wind_dir_from_deg=wind_dir_from,
            current_speed_ms=current_speed_ms,
            current_dir_to_deg=current_dir_to
        )
    drift = compute_drift(
        centroid=geom.centroid,
        detection_time=observation_time,
        hindcast_hours=6.0,
        forecast_hours=12.0,
        metocean=metocean
    )

    # 4. Task 4: AIS Spatiotemporal Query
    ais_status, candidates_raw = search_nearby_vessels(drift.hindcast_origin)

    # 5. Task 5: Attribution Ranking (with slick orientation from Task 2)
    ranked_vessels = rank_vessels(
        candidates_raw=candidates_raw,
        origin_point=drift.hindcast_origin.centroid,
        slick_orientation=geom.orientation_degrees
    )

    return SpillAnalysisResponse(
        spill_id="SPILL_2026_001",
        detection_timestamp=observation_time,
        segmentation_confidence=seg_confidence,
        geometry=geom,
        drift=drift,
        ais_status=ais_status,
        ranked_vessels=ranked_vessels,
        status_message="Analysis completed with physical hindcast, trajectory alignment, and AIS attribution."
    )

@router.get("/scenarios")
async def list_scenarios():
    return [
        {"id": "mumbai_high", "title": "Mumbai High: Offshore Tanker Discharge"},
        {"id": "kutch_dark_vessel", "title": "Kutch: Dark Vessel (AIS Unavailable)"},
        {"id": "bengal_lookalike", "title": "Bay of Bengal: Calm Sea Look-Alike"}
    ]

@router.get("/scenarios/{scenario_id}", response_model=SpillAnalysisResponse)
async def get_scenario_data(scenario_id: str):
    try:
        return get_scenario(scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/report/generate")
async def generate_report(analysis: SpillAnalysisResponse):
    pdf_buffer = generate_forensic_pdf(analysis)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=OASIS_Forensic_{analysis.spill_id}.pdf"}
    )

@router.get("/report/scenario/{scenario_id}")
async def generate_scenario_report(scenario_id: str):
    try:
        analysis = get_scenario(scenario_id)
        pdf_buffer = generate_forensic_pdf(analysis)
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=OASIS_Forensic_{analysis.spill_id}.pdf"}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))