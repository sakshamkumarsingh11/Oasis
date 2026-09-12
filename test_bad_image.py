import httpx
import asyncio

async def main():
    async with httpx.AsyncClient() as c:
        r = await c.post(
            'http://127.0.0.1:8000/api/v1/analyze',
            data={'approx_lat': 15, 'approx_lon': 65, 'wind_speed_ms': 7, 'wind_dir_from': 220, 'current_speed_ms': 0.35, 'current_dir_to': 45},
            files={'file': ('fake.txt', b'this is not an image', 'image/tiff')}
        )
        print(r.status_code)
        print(r.text)

asyncio.run(main())
