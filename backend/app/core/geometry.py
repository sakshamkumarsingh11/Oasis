import cv2
import numpy as np
import math
from typing import Optional, Tuple
from app.schemas import SpillGeometry, GeoPoint


# for processing the identified oil spill mask and extracting geometric features

def pixel_to_geo(
    px_x: float,
    px_y: float,
    img_width: int,
    img_height: int,
    center_lat: float,
    center_lon: float,
    resolution_m: float = 10.0
) -> Tuple[float, float]:
    """
    Converts pixel coordinates (x, y) into geographic (lat, lon)
    using the image center coordinate and ground sampling distance (GSD).
    """
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 40075000.0 * math.cos(math.radians(center_lat)) / 360.0

    delta_x_px = px_x - (img_width / 2.0)
    delta_y_px = (img_height / 2.0) - px_y  # Inverted Y for image coordinates

    delta_lon = (delta_x_px * resolution_m) / meters_per_deg_lon
    delta_lat = (delta_y_px * resolution_m) / meters_per_deg_lat

    return center_lat + delta_lat, center_lon + delta_lon


def extract_geometry(
    mask: np.ndarray,
    center_lat: float,
    center_lon: float,
    pixel_resolution_m: float = 10.0
) -> SpillGeometry:
    """
    Task 2: Deterministic CV & Metric Geometry Extraction.
    
    Args:
        mask: 2D binary numpy array (0 = water, 1 or 255 = oil)
        center_lat: Latitude of the image frame center
        center_lon: Longitude of the image frame center
        pixel_resolution_m: Spatial resolution per pixel in meters (Sentinel-1 default = 10m)
    """
    # Ensure binary uint8 format
    binary_mask = (mask > 0).astype(np.uint8) * 255
    height, width = binary_mask.shape[:2]

    # Find external contours of detected slicks
    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Fallback if mask is empty
    if not contours:
        return SpillGeometry(
            centroid=GeoPoint(lat=center_lat, lon=center_lon),
            area_km2=0.0,
            perimeter_km=0.0,
            bbox=[center_lat, center_lon, center_lat, center_lon],
            orientation_degrees=0.0
        )

    # Select the primary (largest) continuous slick contour
    largest_contour = max(contours, key=cv2.contourArea)

    # 1. Metric Area in km²
    pixel_area = cv2.contourArea(largest_contour)
    m2_per_pixel = pixel_resolution_m * pixel_resolution_m
    area_km2 = round((pixel_area * m2_per_pixel) / 1e6, 3)

    # 2. Metric Perimeter in km
    pixel_perimeter = cv2.arcLength(largest_contour, closed=True)
    perimeter_km = round((pixel_perimeter * pixel_resolution_m) / 1e3, 3)

    # 3. Spatial Centroid via Image Moments
    moments = cv2.moments(largest_contour)
    if moments["m00"] != 0:
        cx_px = moments["m10"] / moments["m00"]
        cy_px = moments["m01"] / moments["m00"]
    else:
        cx_px, cy_px = width / 2.0, height / 2.0

    centroid_lat, centroid_lon = pixel_to_geo(
        cx_px, cy_px, width, height, center_lat, center_lon, pixel_resolution_m
    )

    # 4. Bounding Box in Geo coordinates [min_lat, min_lon, max_lat, max_lon]
    x, y, w, h = cv2.boundingRect(largest_contour)
    bbox_min_lat, bbox_min_lon = pixel_to_geo(x, y + h, width, height, center_lat, center_lon, pixel_resolution_m)
    bbox_max_lat, bbox_max_lon = pixel_to_geo(x + w, y, width, height, center_lat, center_lon, pixel_resolution_m)
    bbox = [round(bbox_min_lat, 4), round(bbox_min_lon, 4), round(bbox_max_lat, 4), round(bbox_max_lon, 4)]

    # 5. Orientation (Elongation axis in degrees 0-180)
    if len(largest_contour) >= 5:
        ellipse = cv2.fitEllipse(largest_contour)
        orientation_deg = round(float(ellipse[2]), 1)
    else:
        orientation_deg = 0.0

    return SpillGeometry(
        centroid=GeoPoint(lat=round(centroid_lat, 5), lon=round(centroid_lon, 5)),
        area_km2=max(area_km2, 0.01),
        perimeter_km=perimeter_km,
        bbox=bbox,
        orientation_degrees=orientation_deg
    )