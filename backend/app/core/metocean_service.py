import httpx
import logging
from typing import Optional
from app.core.drift_engine import MetoceanCondition

logger = logging.getLogger(__name__)

async def fetch_live_metocean(lat: float, lon: float) -> MetoceanCondition:
    """
    Fetches live metocean data from Open-Meteo for the given coordinates.
    Falls back to default operational climatology if the APIs fail.
    """
    # Open-Meteo uses 10m wind speed (km/h -> m/s) and direction (deg)
    # Marine API uses surface ocean current speed (m/s) and direction (deg)
    
    wind_url = "https://api.open-meteo.com/v1/forecast"
    marine_url = "https://marine-api.open-meteo.com/v1/marine"
    
    wind_params = {
        "latitude": lat,
        "longitude": lon,
        "current": ["wind_speed_10m", "wind_direction_10m"],
        "wind_speed_unit": "ms"
    }
    
    marine_params = {
        "latitude": lat,
        "longitude": lon,
        "current": ["ocean_current_velocity", "ocean_current_direction"]
    }

    wind_speed = None
    wind_dir = None
    current_speed = None
    current_dir = None

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            # 1. Fetch wind
            wind_resp = await client.get(wind_url, params=wind_params)
            wind_resp.raise_for_status()
            wind_data = wind_resp.json()
            if "current" in wind_data:
                wind_speed = wind_data["current"].get("wind_speed_10m")
                wind_dir = wind_data["current"].get("wind_direction_10m")
        except Exception as e:
            logger.warning(f"Failed to fetch live wind data: {e}")

        try:
            # 2. Fetch ocean currents
            marine_resp = await client.get(marine_url, params=marine_params)
            marine_resp.raise_for_status()
            marine_data = marine_resp.json()
            if "current" in marine_data:
                current_speed = marine_data["current"].get("ocean_current_velocity")
                current_dir = marine_data["current"].get("ocean_current_direction")
        except Exception as e:
            logger.warning(f"Failed to fetch live marine data: {e}")

    # Fallbacks if values are None
    mc = MetoceanCondition()
    
    if wind_speed is not None:
        mc.wind_speed_ms = float(wind_speed)
    if wind_dir is not None:
        mc.wind_dir_from_deg = float(wind_dir)
    if current_speed is not None:
        mc.current_speed_ms = float(current_speed)
    if current_dir is not None:
        mc.current_dir_to_deg = float(current_dir)
        
    return mc
