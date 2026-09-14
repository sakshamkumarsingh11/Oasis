import math
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Dict, Any
from app.schemas import ProbableOrigin, AISCoverageStatus, TrackPoint, GeoPoint


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes the great-circle distance between two coordinates in kilometers."""
    R = 6371.0  # Earth's mean radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0)**2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return R * c


def generate_synthetic_ais_feed(origin: ProbableOrigin) -> List[Dict[str, Any]]:
    """
    Generates realistic maritime traffic tracks around the incident area
    for demonstration and evaluation when a live commercial AIS feed is unattached.
    """
    mid_time = origin.time_window_start + (origin.time_window_end - origin.time_window_start) / 2
    c_lat, c_lon = origin.centroid.lat, origin.centroid.lon

    return [
        {
            "mmsi": "413219000",
            "vessel_name": "PACIFIC EXPLORER",
            "vessel_type": "Crude Oil Tanker",
            "track": [
                TrackPoint(
                    location=GeoPoint(lat=round(c_lat - 0.012, 5), lon=round(c_lon - 0.010, 5)),
                    timestamp=mid_time - timedelta(minutes=40),
                    sog_knots=13.8,
                    cog_degrees=42.0
                ),
                # Suspicious speed drop near the probable origin
                TrackPoint(
                    location=GeoPoint(lat=round(c_lat + 0.003, 5), lon=round(c_lon + 0.002, 5)),
                    timestamp=mid_time - timedelta(minutes=10),
                    sog_knots=4.5,
                    cog_degrees=40.0
                ),
                TrackPoint(
                    location=GeoPoint(lat=round(c_lat + 0.018, 5), lon=round(c_lon + 0.014, 5)),
                    timestamp=mid_time + timedelta(minutes=25),
                    sog_knots=13.2,
                    cog_degrees=45.0
                )
            ]
        },
        {
            "mmsi": "352001450",
            "vessel_name": "NORDIC STAR",
            "vessel_type": "Container Ship",
            "track": [
                TrackPoint(
                    location=GeoPoint(lat=round(c_lat + 0.05, 5), lon=round(c_lon - 0.03, 5)),
                    timestamp=mid_time - timedelta(minutes=30),
                    sog_knots=18.5,
                    cog_degrees=110.0
                ),
                TrackPoint(
                    location=GeoPoint(lat=round(c_lat + 0.04, 5), lon=round(c_lon + 0.02, 5)),
                    timestamp=mid_time + timedelta(minutes=15),
                    sog_knots=18.2,
                    cog_degrees=112.0
                )
            ]
        },
        {
            "mmsi": "211456000",
            "vessel_name": "ALBATROSS II",
            "vessel_type": "Fishing Vessel",
            "track": [
                TrackPoint(
                    location=GeoPoint(lat=round(c_lat - 0.08, 5), lon=round(c_lon - 0.07, 5)),
                    timestamp=mid_time - timedelta(hours=2),
                    sog_knots=6.0,
                    cog_degrees=270.0
                )
            ]
        }
    ]


def search_nearby_vessels(
    origin: ProbableOrigin,
    external_ais_data: List[Dict[str, Any]] = None
) -> Tuple[AISCoverageStatus, List[Dict[str, Any]]]:
    """
    Task 4: AIS Spatiotemporal Correlator.
    Filters vessels intersecting the origin spatio-temporal envelope using DuckDB.
    """
    import duckdb
    import os
    import pandas as pd
    
    # We define the bounding box of the origin envelope (+ 5km buffer)
    search_radius_km = origin.uncertainty_radius_km + 5.0
    lat_deg_km = 111.0
    lon_deg_km = 111.0 * math.cos(math.radians(origin.centroid.lat))
    if lon_deg_km == 0: lon_deg_km = 111.0
    
    min_lat = origin.centroid.lat - (search_radius_km / lat_deg_km)
    max_lat = origin.centroid.lat + (search_radius_km / lat_deg_km)
    min_lon = origin.centroid.lon - (search_radius_km / lon_deg_km)
    max_lon = origin.centroid.lon + (search_radius_km / lon_deg_km)
    
    t_start = origin.time_window_start - timedelta(hours=1)
    t_end = origin.time_window_end + timedelta(hours=1)
    
    start_str = t_start.strftime("%Y-%m-%d %H:%M:%S")
    end_str = t_end.strftime("%Y-%m-%d %H:%M:%S")
    
    # Path to AIS dataset
    csv_pattern = os.path.join(os.path.dirname(__file__), "..", "..", "..", "ais dataset", "*.csv")
    csv_pattern = os.path.abspath(csv_pattern).replace('\\', '/')
    
    query = f"""
    SELECT mmsi, vessel_name, vessel_type, base_date_time, latitude, longitude, sog, cog
    FROM read_csv_auto('{csv_pattern}')
    WHERE latitude BETWEEN {min_lat} AND {max_lat}
      AND longitude BETWEEN {min_lon} AND {max_lon}
      AND base_date_time >= '{start_str}'
      AND base_date_time <= '{end_str}'
    ORDER BY mmsi, base_date_time
    """
    
    try:
        con = duckdb.connect()
        df = con.execute(query).df()
    except Exception as e:
        print("DuckDB query failed:", e)
        return AISCoverageStatus.UNAVAILABLE, []
        
    if df.empty:
        return AISCoverageStatus.UNAVAILABLE, []
        
    candidates = []
    # Group by MMSI to build tracks
    for mmsi, group in df.groupby('mmsi'):
        vessel_name = str(group['vessel_name'].iloc[0])
        vessel_type = str(group['vessel_type'].iloc[0])
        
        # Determine human readable type
        v_type_str = "Unknown"
        try:
            v_code = int(float(vessel_type))
            if 70 <= v_code < 80: v_type_str = "Cargo Ship"
            elif 80 <= v_code < 90: v_type_str = "Tanker"
            elif v_code == 30: v_type_str = "Fishing Vessel"
            elif 50 <= v_code < 60: v_type_str = "Tug/Special"
            elif v_code == 37: v_type_str = "Pleasure Craft"
            else: v_type_str = f"Type {v_code}"
        except:
            v_type_str = vessel_type
            
        track = []
        for _, row in group.iterrows():
            ts_str = str(row['base_date_time'])
            try:
                # pandas datetime to python datetime
                ts = row['base_date_time'].to_pydatetime()
            except:
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except:
                    ts = t_start
                    
            # Ensure naive for compatibility
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
                
            track.append(
                TrackPoint(
                    location=GeoPoint(lat=float(row['latitude']), lon=float(row['longitude'])),
                    timestamp=ts.replace(tzinfo=timezone.utc),
                    sog_knots=float(row['sog']) if not pd.isna(row['sog']) else 0.0,
                    cog_degrees=float(row['cog']) if not pd.isna(row['cog']) else 0.0
                )
            )
            
        candidates.append({
            "mmsi": str(mmsi),
            "vessel_name": vessel_name if vessel_name and vessel_name != "nan" else f"MMSI {mmsi}",
            "vessel_type": v_type_str,
            "track": track
        })
        
    status = AISCoverageStatus.AVAILABLE if len(candidates) > 0 else AISCoverageStatus.PARTIAL
    return status, candidates