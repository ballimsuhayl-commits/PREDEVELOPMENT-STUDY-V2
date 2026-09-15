"""Live municipal GIS integration smoke test.

Small metadata/sample queries only; no citywide downloads. The municipal GIS host is
queried with certificate verification disabled because its current chain is not trusted by
clean GitHub Linux runners. External ArcGIS Online sources remain certificate-verified.
"""
from __future__ import annotations

import asyncio
import sys

import httpx

import main as ps


async def get_json(client: httpx.AsyncClient, url: str, params=None):
    last = None
    for attempt in range(3):
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("error"):
                raise RuntimeError(data["error"])
            return data
        except Exception as exc:
            last = exc
            if attempt < 2:
                await asyncio.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"GET failed: {url}: {last}")


async def main():
    headers = {"User-Agent": ps.USER_AGENT, "Accept": "application/json"}
    timeout = httpx.Timeout(25.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True, verify=False) as municipal_client:
        checks = {
            ps.LAYER_ROADS: ("esriGeometryPolyline", {"ROAD_TYPE"}),
            ps.LAYER_CONTOURS: ("esriGeometryPolyline", {"ELEVATION"}),
            ps.LAYER_BEACONS: (None, set()),
            ps.LAYER_SERVITUDES: (None, set()),
            ps.LAYER_PARCELS: ("esriGeometryPolygon", set()),
            ps.LAYER_SUBURBS: ("esriGeometryPolygon", set()),
            ps.LAYER_ZONING: ("esriGeometryPolygon", {"ZONING", "SCHEMENAME"}),
            ps.LAYER_SDF: ("esriGeometryPolygon", set()),
        }
        for layer_id, (geom_type, required_fields) in checks.items():
            url = f"{ps.CADASTRAL_BASE}/{layer_id}"
            meta = await get_json(municipal_client, url, {"f": "json"})
            assert meta.get("name"), f"Layer {layer_id} missing name"
            if geom_type:
                assert meta.get("geometryType") == geom_type, (layer_id, meta.get("name"), meta.get("geometryType"))
            fields = {f.get("name") for f in meta.get("fields", [])}
            missing = required_fields - fields
            assert not missing, f"Layer {layer_id} missing fields: {sorted(missing)}"
            sample = await get_json(municipal_client, url + "/query", {
                "f": "json", "where": "1=1", "outFields": "*",
                "returnGeometry": "true", "resultRecordCount": 1, "outSR": 4326,
            })
            assert sample.get("features"), f"Layer {layer_id} returned no sample feature"

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True, verify=True) as verified_client:
        for url in (ps.BUILDING_FOOTPRINTS_URL, ps.SUBURB_OVERVIEW_URL):
            meta = await get_json(verified_client, url, {"f": "json"})
            assert meta.get("fields"), f"No schema fields at {url}"

    print("LIVE_GIS_SMOKE_OK")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"LIVE_GIS_SMOKE_FAILED: {exc}", file=sys.stderr)
        raise
