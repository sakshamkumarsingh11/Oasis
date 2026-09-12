import asyncio
from fastapi import UploadFile
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.api.v1.endpoints import analyze_spill
from datetime import datetime, timezone

async def test_analyze():
    image_path = r"d:\SIH 2026\SIH26143\Oasis\Test Images\IMG_01.jpeg"
    with open(image_path, "rb") as f:
        file_bytes = f.read()

    # Mock UploadFile
    class MockUploadFile:
        async def read(self):
            return file_bytes

    print("Running analyze_spill...")
    try:
        res = await analyze_spill(
            file=MockUploadFile(),
            approx_lat=15.0,
            approx_lon=65.0,
            observation_time=datetime.now(timezone.utc)
        )
        print("Analysis Response:")
        print(f"  Confidence: {res.segmentation_confidence}")
        print(f"  Area: {res.geometry.area_km2}")
        print(f"  Status: {res.status_message}")
        print(f"  Centroid: {res.geometry.centroid}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_analyze())
