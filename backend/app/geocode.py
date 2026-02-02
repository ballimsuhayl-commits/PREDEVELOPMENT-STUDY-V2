from __future__ import annotations

from typing import Optional, Tuple

import httpx


class GeocodeError(RuntimeError):
    pass


def _format_query(address: str, country: Optional[str]) -> str:
    addr = address.strip()
    if country:
        # Nominatim tends to do better if the country is included
        addr = f"{addr}, {country.strip()}"
    return addr


def geocode_nominatim(address: str, country: Optional[str] = None) -> Tuple[float, float, str]:
    """Geocode using OSM Nominatim.

    Returns: (lat, lon, display_name)

    Note: Nominatim usage policies apply. Use responsibly.
    """

    q = _format_query(address, country)
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": q, "format": "json", "limit": 1}
    headers = {"User-Agent": "municipality-address-check/1.0"}

    with httpx.Client(timeout=20.0, headers=headers) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    if not data:
        raise GeocodeError("No results from geocoder")

    item = data[0]
    lat = float(item["lat"])
    lon = float(item["lon"])
    name = str(item.get("display_name") or "")
    return lat, lon, name
