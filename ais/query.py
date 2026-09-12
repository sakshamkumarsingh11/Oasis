"""
SIH26143 — AIS Pipeline: Sequential Query Pipeline

Implements the 6-step candidate vessel extraction from DuckDB:
    1. Time filter
    2. Bounding-box prefilter
    3. Exact Haversine radius filter
    4. Candidate MMSI extraction
    5. Wider trajectory retrieval
    6. CandidateVessel object construction

Also includes:
    - Dark AIS detection (vessels whose AIS gap crosses the spill origin)
    - Dynamic search expansion (retry with larger radius/time on zero candidates)

Reference:
    Pipeline §17–22 (sequential queries), §3 (required dates).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import duckdb

from .schemas import (
    AISRecord,
    CandidateVessel,
    Origin,
    VesselTrack,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility: date partitions
# ---------------------------------------------------------------------------

def required_dates(start_time: datetime, end_time: datetime) -> List[str]:
    """
    Determine which daily date partitions are needed for the time range.

    Pipeline §3: handles midnight/year-boundary cases automatically.

    Returns:
        List of date strings, e.g. ['2025-12-31', '2026-01-01']
    """
    dates = []
    current = start_time.date()
    while current <= end_time.date():
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


# ---------------------------------------------------------------------------
# Utility: bounding-box calculation
# ---------------------------------------------------------------------------

def _bbox_from_radius(lat: float, lon: float, radius_km: float) -> Tuple[float, float, float, float]:
    """
    Calculate a generous bounding box around a point for a given radius.

    Pipeline §19: cheap prefilter before exact Haversine distance.

    Returns:
        (lat_min, lat_max, lon_min, lon_max)
    """
    # 1 degree of latitude ≈ 111 km
    lat_delta = radius_km / 111.0
    # 1 degree of longitude varies with latitude
    lon_delta = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))

    return (
        lat - lat_delta,
        lat + lat_delta,
        lon - lon_delta,
        lon + lon_delta,
    )


# ---------------------------------------------------------------------------
# Core query: find candidate vessels
# ---------------------------------------------------------------------------

def find_candidate_vessels(
    con: duckdb.DuckDBPyConnection,
    origin: Origin,
    search_radius_km: float = 25.0,
    time_window_minutes: float = 60.0,
    view_name: str = "ais_data",
    enable_dark_ais: bool = True,
    enable_expansion: bool = True,
    max_expansion_steps: int = 3,
    expansion_radius_step_km: float = 10.0,
    expansion_time_step_minutes: float = 30.0,
) -> Tuple[List[CandidateVessel], dict]:
    """
    Run the full sequential query pipeline to find candidate vessels.

    Pipeline §17–22.

    Args:
        con: DuckDB connection with ais_data view registered.
        origin: Probable spill origin (lat, lon, timestamp).
        search_radius_km: Initial search radius.
        time_window_minutes: Initial time window (±minutes from origin).
        view_name: Name of the DuckDB view.
        enable_dark_ais: If True, also search for vessels with AIS gaps
                         crossing the origin (Dark AIS detection).
        enable_expansion: If True, retry with expanded search parameters
                          if zero candidates are found.
        max_expansion_steps: Maximum number of expansion retries.
        expansion_radius_step_km: How much to increase radius each retry.
        expansion_time_step_minutes: How much to increase time window each retry.

    Returns:
        Tuple of (list of CandidateVessel, audit_metadata dict).
    """
    current_radius = search_radius_km
    current_window = time_window_minutes
    expansion_step = 0

    while True:
        # Execute the core pipeline
        candidates, audit = _run_candidate_pipeline(
            con=con,
            origin=origin,
            search_radius_km=current_radius,
            time_window_minutes=current_window,
            view_name=view_name,
        )

        # If we found candidates, optionally add Dark AIS suspects
        if enable_dark_ais:
            dark_candidates = _detect_dark_ais_vessels(
                con=con,
                origin=origin,
                search_radius_km=current_radius,
                time_window_minutes=current_window,
                existing_mmsis={c.mmsi for c in candidates},
                view_name=view_name,
            )
            if dark_candidates:
                logger.info(
                    "Dark AIS detection found %d additional suspect(s).",
                    len(dark_candidates),
                )
                candidates.extend(dark_candidates)
                audit["dark_ais_candidates"] = len(dark_candidates)

        # If we found candidates or expansion is disabled, return
        if candidates or not enable_expansion:
            audit["final_radius_km"] = current_radius
            audit["final_time_window_min"] = current_window
            audit["expansion_steps"] = expansion_step
            return candidates, audit

        # Dynamic expansion — Pipeline §39 fallback
        expansion_step += 1
        if expansion_step > max_expansion_steps:
            logger.warning(
                "Dynamic expansion exhausted after %d steps. "
                "No candidates found.",
                max_expansion_steps,
            )
            audit["final_radius_km"] = current_radius
            audit["final_time_window_min"] = current_window
            audit["expansion_steps"] = expansion_step
            return [], audit

        current_radius += expansion_radius_step_km
        current_window += expansion_time_step_minutes
        logger.info(
            "Zero candidates found. Expanding search: "
            "radius=%.1fkm, window=±%.0fmin (step %d/%d)",
            current_radius,
            current_window,
            expansion_step,
            max_expansion_steps,
        )


def _run_candidate_pipeline(
    con: duckdb.DuckDBPyConnection,
    origin: Origin,
    search_radius_km: float,
    time_window_minutes: float,
    view_name: str,
) -> Tuple[List[CandidateVessel], dict]:
    """
    Execute Steps 1–6 of the sequential pipeline.

    Returns:
        Tuple of (CandidateVessel list, audit metadata dict).
    """
    audit = {
        "origin_lat": origin.latitude,
        "origin_lon": origin.longitude,
        "origin_time": origin.timestamp.isoformat(),
        "search_radius_km": search_radius_km,
        "time_window_minutes": time_window_minutes,
    }

    # --- Step 1 & 2: Time + Bounding Box filter (Pipeline §18–19) ---
    time_start = origin.timestamp - timedelta(minutes=time_window_minutes)
    time_end = origin.timestamp + timedelta(minutes=time_window_minutes)

    lat_min, lat_max, lon_min, lon_max = _bbox_from_radius(
        origin.latitude, origin.longitude, search_radius_km
    )

    audit["time_start"] = time_start.isoformat()
    audit["time_end"] = time_end.isoformat()
    audit["required_dates"] = required_dates(time_start, time_end)

    # Combined time + bbox SQL query
    nearby_df = con.execute(f"""
        SELECT
            mmsi,
            base_date_time,
            latitude,
            longitude,
            sog,
            cog,
            heading,
            vessel_name,
            imo,
            call_sign,
            vessel_type,
            status,
            length,
            width,
            draft,
            cargo,
            transceiver
        FROM {view_name}
        WHERE base_date_time BETWEEN TIMESTAMP '{time_start}' AND TIMESTAMP '{time_end}'
          AND latitude  BETWEEN {lat_min} AND {lat_max}
          AND longitude BETWEEN {lon_min} AND {lon_max}
          AND mmsi IS NOT NULL
          AND latitude IS NOT NULL
          AND longitude IS NOT NULL
    """).fetchdf()

    logger.info(
        "Time+BBox filter: %d rows (radius=%.1fkm, window=±%.0fmin)",
        len(nearby_df), search_radius_km, time_window_minutes,
    )

    if nearby_df.empty:
        audit["bbox_row_count"] = 0
        audit["candidate_mmsi_count"] = 0
        return [], audit

    audit["bbox_row_count"] = len(nearby_df)

    # --- Step 3: Exact Haversine radius filter (Pipeline §20) ---
    nearby_df["distance_km"] = nearby_df.apply(
        lambda row: _haversine(
            row["latitude"], row["longitude"],
            origin.latitude, origin.longitude,
        ),
        axis=1,
    )
    nearby_df = nearby_df[nearby_df["distance_km"] <= search_radius_km]

    logger.info(
        "Exact radius filter: %d rows within %.1f km.",
        len(nearby_df), search_radius_km,
    )

    if nearby_df.empty:
        audit["radius_row_count"] = 0
        audit["candidate_mmsi_count"] = 0
        return [], audit

    audit["radius_row_count"] = len(nearby_df)

    # --- Step 4: Extract candidate MMSIs (Pipeline §21) ---
    candidate_mmsis = nearby_df["mmsi"].dropna().unique().tolist()
    audit["candidate_mmsi_count"] = len(candidate_mmsis)
    audit["candidate_mmsis"] = [str(m) for m in candidate_mmsis]

    logger.info("Candidate MMSIs: %d unique vessels.", len(candidate_mmsis))

    # --- Step 5: Retrieve wider trajectories (Pipeline §22) ---
    # Fetch ±3x the time window for trajectory context
    context_hours = (time_window_minutes / 60.0) * 3.0
    wider_start = origin.timestamp - timedelta(hours=context_hours)
    wider_end = origin.timestamp + timedelta(hours=context_hours)

    mmsi_list_sql = ", ".join(str(int(m)) for m in candidate_mmsis)

    wider_df = con.execute(f"""
        SELECT
            mmsi,
            base_date_time,
            latitude,
            longitude,
            sog,
            cog,
            heading,
            vessel_name,
            imo,
            call_sign,
            vessel_type,
            status,
            length,
            width,
            draft,
            cargo,
            transceiver
        FROM {view_name}
        WHERE mmsi IN ({mmsi_list_sql})
          AND base_date_time BETWEEN TIMESTAMP '{wider_start}' AND TIMESTAMP '{wider_end}'
        ORDER BY mmsi, base_date_time
    """).fetchdf()

    logger.info(
        "Wider trajectory fetch: %d rows for %d MMSIs (±%.1f hours).",
        len(wider_df), len(candidate_mmsis), context_hours,
    )

    audit["wider_track_row_count"] = len(wider_df)

    # --- Step 6: Build CandidateVessel objects (Pipeline §23–24) ---
    candidates = _build_candidate_vessels_from_df(wider_df)

    return candidates, audit


# ---------------------------------------------------------------------------
# Dark AIS Detection
# ---------------------------------------------------------------------------

def _detect_dark_ais_vessels(
    con: duckdb.DuckDBPyConnection,
    origin: Origin,
    search_radius_km: float,
    time_window_minutes: float,
    existing_mmsis: set,
    view_name: str = "ais_data",
) -> List[CandidateVessel]:
    """
    Detect vessels that may have turned off AIS while passing through
    the spill origin area.

    Logic: Find vessels that have a ping BEFORE the origin time (outside
    the radius) and a ping AFTER the origin time (outside the radius),
    where the straight-line path between those two pings would cross
    within the search radius of the origin.

    These are "Dark AIS" suspects — vessels that conveniently lost their
    signal right as they passed the spill zone.
    """
    time_start = origin.timestamp - timedelta(minutes=time_window_minutes * 2)
    time_end = origin.timestamp + timedelta(minutes=time_window_minutes * 2)

    # Wider bbox to catch vessels that were outside the radius but could
    # have transited through it
    outer_radius = search_radius_km * 3.0
    lat_min, lat_max, lon_min, lon_max = _bbox_from_radius(
        origin.latitude, origin.longitude, outer_radius
    )

    # Exclude already-found MMSIs
    exclude_clause = ""
    if existing_mmsis:
        exclude_list = ", ".join(str(int(m)) for m in existing_mmsis)
        exclude_clause = f"AND mmsi NOT IN ({exclude_list})"

    # Get last-before and first-after pings for each MMSI
    dark_sql = f"""
        WITH vessel_pings AS (
            SELECT
                mmsi,
                base_date_time,
                latitude,
                longitude,
                sog, cog, heading,
                vessel_name, imo, call_sign, vessel_type,
                status, length, width, draft, cargo, transceiver
            FROM {view_name}
            WHERE base_date_time BETWEEN TIMESTAMP '{time_start}' AND TIMESTAMP '{time_end}'
              AND latitude  BETWEEN {lat_min} AND {lat_max}
              AND longitude BETWEEN {lon_min} AND {lon_max}
              AND mmsi IS NOT NULL
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
              {exclude_clause}
        ),
        before_pings AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY mmsi ORDER BY base_date_time DESC) AS rn
            FROM vessel_pings
            WHERE base_date_time < TIMESTAMP '{origin.timestamp}'
        ),
        after_pings AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY mmsi ORDER BY base_date_time ASC) AS rn
            FROM vessel_pings
            WHERE base_date_time > TIMESTAMP '{origin.timestamp}'
        )
        SELECT
            b.mmsi,
            b.latitude AS lat_before, b.longitude AS lon_before,
            b.base_date_time AS time_before,
            a.latitude AS lat_after, a.longitude AS lon_after,
            a.base_date_time AS time_after
        FROM before_pings b
        JOIN after_pings a ON b.mmsi = a.mmsi
        WHERE b.rn = 1 AND a.rn = 1
    """

    try:
        gap_df = con.execute(dark_sql).fetchdf()
    except Exception as e:
        logger.warning("Dark AIS query failed: %s", e)
        return []

    if gap_df.empty:
        return []

    # Check if the straight-line path between before/after pings
    # crosses within the search radius of the origin
    dark_mmsis = []
    for _, row in gap_df.iterrows():
        closest_dist = _closest_approach_distance(
            row["lat_before"], row["lon_before"],
            row["lat_after"], row["lon_after"],
            origin.latitude, origin.longitude,
        )
        if closest_dist <= search_radius_km:
            dark_mmsis.append(int(row["mmsi"]))

    if not dark_mmsis:
        return []

    logger.info(
        "Dark AIS: %d vessels with gap-crossing trajectories.",
        len(dark_mmsis),
    )

    # Fetch wider tracks for the dark AIS suspects
    context_hours = (time_window_minutes / 60.0) * 3.0
    wider_start = origin.timestamp - timedelta(hours=context_hours)
    wider_end = origin.timestamp + timedelta(hours=context_hours)
    mmsi_list_sql = ", ".join(str(m) for m in dark_mmsis)

    dark_df = con.execute(f"""
        SELECT
            mmsi, base_date_time, latitude, longitude,
            sog, cog, heading, vessel_name, imo, call_sign,
            vessel_type, status, length, width, draft, cargo, transceiver
        FROM {view_name}
        WHERE mmsi IN ({mmsi_list_sql})
          AND base_date_time BETWEEN TIMESTAMP '{wider_start}' AND TIMESTAMP '{wider_end}'
        ORDER BY mmsi, base_date_time
    """).fetchdf()

    return _build_candidate_vessels_from_df(dark_df)


# ---------------------------------------------------------------------------
# DataFrame → CandidateVessel conversion
# ---------------------------------------------------------------------------

def _build_candidate_vessels_from_df(df) -> List[CandidateVessel]:
    """
    Convert a pandas DataFrame of AIS rows into CandidateVessel objects.

    Pipeline §23–24: sort by MMSI + time, group, build trajectories.
    """
    import pandas as pd

    if df.empty:
        return []

    candidates = []
    grouped = df.sort_values(["mmsi", "base_date_time"]).groupby("mmsi")

    for mmsi, group in grouped:
        mmsi_str = str(int(mmsi))

        records = []
        for _, row in group.iterrows():
            records.append(AISRecord(
                mmsi=mmsi_str,
                base_date_time=pd.Timestamp(row["base_date_time"]).to_pydatetime(),
                latitude=_safe_float(row.get("latitude")),
                longitude=_safe_float(row.get("longitude")),
                sog=_safe_float(row.get("sog")),
                cog=_safe_float(row.get("cog")),
                heading=_safe_float(row.get("heading")),
                vessel_name=_safe_str(row.get("vessel_name")),
                imo=_safe_str(row.get("imo")),
                call_sign=_safe_str(row.get("call_sign")),
                vessel_type=_safe_int(row.get("vessel_type")),
                status=_safe_int(row.get("status")),
                length=_safe_float(row.get("length")),
                width=_safe_float(row.get("width")),
                draft=_safe_float(row.get("draft")),
                cargo=_safe_int(row.get("cargo")),
                transceiver=_safe_str(row.get("transceiver")),
            ))

        track = VesselTrack(mmsi=mmsi_str, records=records)

        # Extract vessel metadata from first record with data
        vessel_name = None
        vessel_type = None
        imo = None
        call_sign = None
        for r in records:
            if vessel_name is None and r.vessel_name:
                vessel_name = r.vessel_name
            if vessel_type is None and r.vessel_type is not None:
                vessel_type = r.vessel_type
            if imo is None and r.imo:
                imo = r.imo
            if call_sign is None and r.call_sign:
                call_sign = r.call_sign

        candidates.append(CandidateVessel(
            mmsi=mmsi_str,
            track=track,
            vessel_name=vessel_name,
            vessel_type=vessel_type,
            imo=imo,
            call_sign=call_sign,
        ))

    return candidates


# ---------------------------------------------------------------------------
# Geodesic utilities (local copies to avoid circular imports)
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
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


def _closest_approach_distance(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    point_lat: float, point_lon: float,
) -> float:
    """
    Approximate the closest distance (km) from a point to the
    straight-line segment between two other points.

    Uses a flat-Earth projection — acceptable for distances under ~100km.
    """
    # Convert to simple x, y (km from point)
    cos_lat = math.cos(math.radians(point_lat))
    x1 = (lon1 - point_lon) * 111.0 * cos_lat
    y1 = (lat1 - point_lat) * 111.0
    x2 = (lon2 - point_lon) * 111.0 * cos_lat
    y2 = (lat2 - point_lat) * 111.0

    # Point is at origin (0, 0) in this projection
    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq == 0:
        # Degenerate segment — both pings at same location
        return math.sqrt(x1 * x1 + y1 * y1)

    # Project origin onto the line segment
    t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / seg_len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy

    return math.sqrt(proj_x * proj_x + proj_y * proj_y)


# ---------------------------------------------------------------------------
# Safe type conversions (handle NaN/None from pandas)
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    """Convert a value to float, returning None for NaN/None."""
    import pandas as pd
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    if isinstance(val, pd.Timestamp):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> Optional[int]:
    """Convert a value to int, returning None for NaN/None."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_str(val) -> Optional[str]:
    """Convert a value to str, returning None for NaN/None/empty."""
    import pandas as pd
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    return s if s and s.lower() != "nan" else None
