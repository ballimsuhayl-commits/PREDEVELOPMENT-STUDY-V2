from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from .config import settings


@dataclass(frozen=True)
class ArcGISFetchResult:
    feature_count: int
    output_geojson_path: str


async def fetch_arcgis_layer_to_geojson(
    layer_url: str,
    out_path: str,
    where: str = "1=1",
    out_fields: str = "*",
    page_size: int = 2000,
    timeout_s: Optional[float] = None,
) -> ArcGISFetchResult:
    """Fetch an ArcGIS REST layer and save as a single GeoJSON FeatureCollection.

    Works with FeatureServer and MapServer layer endpoints.

    Strategy:
      1) Query with pagination via resultOffset/resultRecordCount
      2) Ask for f=geojson when supported; otherwise fall back to ESRI JSON and convert on disk.

    Notes:
      - Always requests outSR=4326 (WGS84 lon/lat)
      - Keeps properties from the source attributes.
    """

    layer_url = layer_url.rstrip("/")
    query_url = f"{layer_url}/query"
    timeout = float(timeout_s or settings.request_timeout_s)

    # First attempt: GeoJSON directly (ArcGIS supports f=geojson on many servers)
    all_features: List[Dict[str, Any]] = []
    offset = 0

    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            params = {
                "where": where,
                "outFields": out_fields,
                "returnGeometry": "true",
                "outSR": 4326,
                "f": "geojson",
                "resultOffset": offset,
                "resultRecordCount": page_size,
            }

            r = await client.get(query_url, params=params)
            # Some servers return 200 with ESRI error payload; some return 400.
            if r.status_code >= 400:
                break

            payload = r.json()
            if isinstance(payload, dict) and payload.get("error"):
                break

            feats = payload.get("features") if isinstance(payload, dict) else None
            if not isinstance(feats, list) or len(feats) == 0:
                break

            all_features.extend(feats)
            if len(feats) < page_size:
                # last page
                break
            offset += page_size

        if all_features:
            fc = {"type": "FeatureCollection", "features": all_features}
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(fc, f, ensure_ascii=False)
            return ArcGISFetchResult(feature_count=len(all_features), output_geojson_path=out_path)

    # Fall back: ESRI JSON and write it as-is (our polygon loader already supports ESRI JSON)
    # We still request SR=4326.
    all_esri_features: List[Dict[str, Any]] = []
    offset = 0

    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            params = {
                "where": where,
                "outFields": out_fields,
                "returnGeometry": "true",
                "outSR": 4326,
                "f": "json",
                "resultOffset": offset,
                "resultRecordCount": page_size,
            }
            r = await client.get(query_url, params=params)
            r.raise_for_status()
            payload = r.json()
            if payload.get("error"):
                raise RuntimeError(f"ArcGIS error: {payload['error']}")

            feats = payload.get("features")
            if not isinstance(feats, list) or len(feats) == 0:
                break

            all_esri_features.extend(feats)
            if len(feats) < page_size:
                break
            offset += page_size

    out_esri = {
        "spatialReference": {"wkid": 4326, "latestWkid": 4326},
        "features": all_esri_features,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_esri, f, ensure_ascii=False)
    return ArcGISFetchResult(feature_count=len(all_esri_features), output_geojson_path=out_path)
