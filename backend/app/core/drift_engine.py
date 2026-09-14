import math
from datetime import datetime, timedelta
from typing import List, Optional
from app.schemas import SpillDrift, ProbableOrigin, DriftPoint, GeoPoint


class MetoceanCondition:
    """
    Environmental parameters at the slick location.
    Conventions:
        wind_speed_ms: Wind velocity in meters/sec
        wind_dir_from_deg: Direction wind is blowing FROM (0° = North, 90° = East)
        current_speed_ms: Ocean surface current velocity in meters/sec
        current_dir_to_deg: Direction current is flowing TOWARDS (0° = North, 90° = East)
    """
    def __init__(
        self,
        wind_speed_ms: float = 7.5,
        wind_dir_from_deg: float = 220.0,
        current_speed_ms: float = 0.35,
        current_dir_to_deg: float = 45.0
    ):
        self.wind_speed_ms = wind_speed_ms
        self.wind_dir_from_deg = wind_dir_from_deg
        self.current_speed_ms = current_speed_ms
        self.current_dir_to_deg = current_dir_to_deg


def calculate_drift_velocity(
    metocean: MetoceanCondition,
    latitude: float,
    leeway_factor: float = 0.03
) -> tuple[float, float]:
    """
    Computes resultant slick velocity vector (u_slick, v_slick) in m/s.
    Standard Formulation: V_slick = V_current + (leeway_factor * V_wind)
    Includes Coriolis deflection angle (+15° to right in Northern Hemisphere).
    """
    # 1. Surface current components (flows towards current_dir_to_deg)
    curr_rad = math.radians(metocean.current_dir_to_deg)
    u_curr = metocean.current_speed_ms * math.sin(curr_rad)
    v_curr = metocean.current_speed_ms * math.cos(curr_rad)

    # 2. Wind leeway components (blows towards wind_dir_from_deg + 180°)
    downwind_deg = (metocean.wind_dir_from_deg + 180.0) % 360.0
    
    # Coriolis deflection: +15 deg in North, -15 deg in South
    deflection = 15.0 if latitude >= 0 else -15.0
    leeway_deg = (downwind_deg + deflection) % 360.0
    leeway_rad = math.radians(leeway_deg)

    leeway_speed = metocean.wind_speed_ms * leeway_factor
    u_wind = leeway_speed * math.sin(leeway_rad)
    v_wind = leeway_speed * math.cos(leeway_rad)

    # 3. Resultant velocity vector (m/s)
    u_slick = u_curr + u_wind
    v_slick = v_curr + v_wind

    return u_slick, v_slick


def step_geopoint(
    pt: GeoPoint,
    u_ms: float,
    v_ms: float,
    delta_seconds: float
) -> GeoPoint:
    """Displaces a coordinate along velocity vector (u, v) over delta_seconds."""
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 40075000.0 * math.cos(math.radians(pt.lat)) / 360.0

    delta_lat = (v_ms * delta_seconds) / meters_per_deg_lat
    delta_lon = (u_ms * delta_seconds) / meters_per_deg_lon

    return GeoPoint(
        lat=round(pt.lat + delta_lat, 5),
        lon=round(pt.lon + delta_lon, 5)
    )


def compute_drift(
    centroid: GeoPoint,
    detection_time: datetime,
    hindcast_hours: float = 6.0,
    forecast_hours: float = 12.0,
    metocean: Optional[MetoceanCondition] = None
) -> SpillDrift:
    """
    Task 3: Physics-Based Hindcasting and Forecasting Engine.
    
    - Hindcasts backward in time to project the slick's probable origin.
    - Forecasts forward in time to project future drift path.
    - Expands spatial uncertainty radius proportional to elapsed time.
    """
    if metocean is None:
        metocean = MetoceanCondition()  # Default operational conditions if live stream is unattached

    # Slick drift velocity vector in m/s
    u_slick, v_slick = calculate_drift_velocity(metocean, centroid.lat)

    # ------------------ 1. HINDCASTING (BACKWARD) ------------------
    # Step backward: negate velocity
    hindcast_seconds = hindcast_hours * 3600.0
    origin_geo = step_geopoint(centroid, -u_slick, -v_slick, hindcast_seconds)

    # Uncertainty radius expands with time: R(t) = R_base + sigma * sqrt(hours)
    # Using 1.2 km/sqrt(hr) diffusion/uncertainty growth factor
    uncertainty_radius_km = round(1.0 + 1.2 * math.sqrt(hindcast_hours), 2)

    origin = ProbableOrigin(
        centroid=origin_geo,
        time_window_start=detection_time - timedelta(hours=hindcast_hours + 1.0),
        time_window_end=detection_time - timedelta(hours=max(hindcast_hours - 1.0, 0.5)),
        uncertainty_radius_km=uncertainty_radius_km
    )

    # ------------------ 2. FORECASTING (FORWARD) ------------------
    forecast_trajectory: List[DriftPoint] = []
    current_pt = centroid
    step_hours = 3.0
    total_steps = int(forecast_hours / step_hours)

    for step in range(1, total_steps + 1):
        step_dt_seconds = step_hours * 3600.0
        current_pt = step_geopoint(current_pt, u_slick, v_slick, step_dt_seconds)
        step_time = detection_time + timedelta(hours=step * step_hours)
        forecast_trajectory.append(
            DriftPoint(timestamp=step_time, location=current_pt)
        )

    return SpillDrift(
        hindcast_origin=origin,
        forecast_trajectory=forecast_trajectory
    )