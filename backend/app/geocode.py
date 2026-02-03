from dataclasses import dataclass
from typing import Optional

import httpx

from .config import settings


@dataclass(frozen=True)
class GeocodeHit:
    display_name: str
    lat: float
    lon: float
    importance: float


async def geocode_address(address: str, country: Optional[str] = None) -> Optional[GeocodeHit]:
    if not settings.allow_nominatim:
        return None

    q = address if not country else f"{address}, {country}"
    params = {"q": q, "format": "jsonv2", "limit": 1, "addressdetails": 1}
    headers = {"User-Agent": settings.nominatim_user_agent}

    async with httpx.AsyncClient(timeout=settings.request_timeout_s, headers=headers) as client:
        r = await client.get(f"{settings.nominatim_base_url}/search", params=params)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        hit = data[0]
        return GeocodeHit(
            display_name=str(hit.get("display_name", "")),
            lat=float(hit["lat"]),
            lon=float(hit["lon"]),
            importance=float(hit.get("importance", 0.0)),
        )
