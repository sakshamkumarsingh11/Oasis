import logging
from datetime import datetime
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Import our exact domain objects from the AIS engine
from ais import (
    run_attribution,
    Origin,
    DriftResult,
    SpillGeometry,
    CandidateVessel,
    VesselTrack,
    AISRecord,
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AIS Attribution Engine Test API",
    description="Standalone API wrapper to test the AIS Attribution Engine without modifying its core.",
    version="1.0.0"
)

# ---------------------------------------------------------------------------
# Pydantic Request Models (API Layer)
# These act as validation and deserialization wrappers for the API payload,
# and we map them instantly into the core domain dataclasses.
# ---------------------------------------------------------------------------

class AISRecordModel(BaseModel):
    mmsi: str
    base_date_time: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    sog: Optional[float] = None
    cog: Optional[float] = None
    heading: Optional[float] = None
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

class VesselTrackModel(BaseModel):
    mmsi: str
    records: List[AISRecordModel] = Field(default_factory=list)

class CandidateVesselModel(BaseModel):
    mmsi: str
    track: VesselTrackModel
    vessel_name: Optional[str] = None
    vessel_type: Optional[int] = None
    imo: Optional[str] = None
    call_sign: Optional[str] = None

class OriginModel(BaseModel):
    latitude: float
    longitude: float
    timestamp: datetime
    uncertainty_km: Optional[float] = None

class DriftResultModel(BaseModel):
    origin: OriginModel
    trajectory: List[List[Any]]  # Expecting [[lat, lon, epoch_sec_or_iso_string], ...]
    uncertainty_km: Optional[float] = None
    model_version: Optional[str] = None

class SpillGeometryModel(BaseModel):
    incident_id: str
    centroid_lat: float
    centroid_lon: float
    area_km2: float
    perimeter_km: Optional[float] = None
    orientation_deg: Optional[float] = None

class AttributionRequest(BaseModel):
    incident_id: str
    candidates: Optional[List[CandidateVesselModel]] = None
    origin: OriginModel
    drift_result: Optional[DriftResultModel] = None
    spill_geometry: Optional[SpillGeometryModel] = None
    search_radius_km: Optional[float] = 25.0
    time_window_minutes: Optional[float] = 60.0
    ais_dates: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "ais_attribution_engine"}

@app.post("/api/v1/attribution")
def trigger_attribution(req: AttributionRequest):
    """
    Trigger the attribution engine.
    This safely maps the incoming JSON payload into the domain dataclasses
    expected by `run_attribution` without altering the engine itself.
    """
    try:
        # 1. Map Origin
        domain_origin = Origin(
            latitude=req.origin.latitude,
            longitude=req.origin.longitude,
            timestamp=req.origin.timestamp,
            uncertainty_km=req.origin.uncertainty_km
        )

        # 2. Map Drift Result (if provided)
        domain_drift = None
        if req.drift_result:
            # Reconstruct trajectory tuples from the JSON-friendly format
            traj_tuples = []
            for pt in req.drift_result.trajectory:
                # We expect [lat, lon, timestamp] for the API
                # Convert the third element (string/epoch) to datetime if needed, or pass directly if parsed
                if len(pt) >= 3:
                    # In a real API, the client might pass ISO format strings for datetime
                    ts = pt[2] if isinstance(pt[2], datetime) else datetime.fromisoformat(str(pt[2]))
                    traj_tuples.append((float(pt[0]), float(pt[1]), ts))
                
            domain_drift = DriftResult(
                origin=domain_origin,
                trajectory=traj_tuples,
                uncertainty_km=req.drift_result.uncertainty_km,
                model_version=req.drift_result.model_version
            )

        # 3. Map Spill Geometry (if provided)
        domain_spill = None
        if req.spill_geometry:
            domain_spill = SpillGeometry(
                incident_id=req.spill_geometry.incident_id,
                centroid_lat=req.spill_geometry.centroid_lat,
                centroid_lon=req.spill_geometry.centroid_lon,
                area_km2=req.spill_geometry.area_km2,
                perimeter_km=req.spill_geometry.perimeter_km,
                orientation_deg=req.spill_geometry.orientation_deg
            )

        # 4. Map Candidate Vessels
        domain_candidates = None
        if req.candidates is not None:
            domain_candidates = []
            for c in req.candidates:
                # Map Records
                domain_records = []
                for r in c.track.records:
                    domain_records.append(
                        AISRecord(
                            mmsi=r.mmsi,
                            base_date_time=r.base_date_time,
                            latitude=r.latitude,
                            longitude=r.longitude,
                            sog=r.sog,
                            cog=r.cog,
                            heading=r.heading,
                            vessel_name=r.vessel_name,
                            imo=r.imo,
                            call_sign=r.call_sign,
                            vessel_type=r.vessel_type,
                            status=r.status,
                            length=r.length,
                            width=r.width,
                            draft=r.draft,
                            cargo=r.cargo,
                            transceiver=r.transceiver
                        )
                    )
                
                # Map Track
                domain_track = VesselTrack(
                    mmsi=c.track.mmsi,
                    records=domain_records
                )
                
                # Map Candidate
                domain_candidates.append(
                    CandidateVessel(
                        mmsi=c.mmsi,
                        track=domain_track,
                        vessel_name=c.vessel_name,
                        vessel_type=c.vessel_type,
                        imo=c.imo,
                        call_sign=c.call_sign
                    )
                )

        # 5. Execute the Core Engine!
        logger.info(f"Running attribution for incident {req.incident_id} with {len(domain_candidates) if domain_candidates else 0} candidates.")
        report = run_attribution(
            incident_id=req.incident_id,
            candidates=domain_candidates,
            origin=domain_origin,
            drift_result=domain_drift,
            spill_geometry=domain_spill,
            search_radius_km=req.search_radius_km,
            time_window_minutes=req.time_window_minutes,
            ais_dates=req.ais_dates
        )

        # 6. Return response (FastAPI will automatically serialize standard dataclasses)
        return report

    except Exception as e:
        logger.error(f"Error during attribution: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Test API Server on port 8000...")
    uvicorn.run("ais_api:app", host="127.0.0.1", port=8000, reload=True)
