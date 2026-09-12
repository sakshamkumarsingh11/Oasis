import httpx
import asyncio
import numpy as np
import cv2

async def main():
    # create a dummy image (e.g. 512x512 with a black blob)
    img = np.ones((512, 512), dtype=np.uint8) * 150
    cv2.ellipse(img, (256, 256), (100, 50), 30, 0, 360, 20, -1) # Dark spot like oil
    
    cv2.imwrite("dummy_test_img.png", img)
    
    print("Testing backend endpoint...")
    async with httpx.AsyncClient(timeout=120) as client:
        with open("dummy_test_img.png", "rb") as f:
            files = {"file": ("dummy_test_img.png", f, "image/png")}
            data = {
                "approx_lat": 15.0,
                "approx_lon": 65.0,
                "wind_speed_ms": 7.5,
                "wind_dir_from": 220,
                "current_speed_ms": 0.35,
                "current_dir_to": 45,
            }
            resp = await client.post("http://127.0.0.1:8000/api/v1/analyze", data=data, files=files)
            
            if resp.status_code == 200:
                print("SUCCESS!")
                import json
                print(json.dumps(resp.json(), indent=2))
            else:
                print("FAILED!")
                print(resp.status_code)
                print(resp.text)

if __name__ == "__main__":
    asyncio.run(main())
