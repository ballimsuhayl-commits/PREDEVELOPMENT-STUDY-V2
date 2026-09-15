"""Live municipal GIS + end-to-end integration smoke test.

Small metadata/sample queries only; no citywide downloads. The municipal GIS host is
queried with certificate verification disabled because its current chain is not trusted by
clean GitHub Linux runners. External ArcGIS Online sources remain certificate-verified.

After schema checks, the smoke test selects a real live parcel returned by the municipality,
uses a representative point from that parcel, runs the full analysis pipeline, and generates
its PDF. This catches integration regressions that isolated geometry tests cannot.
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
    real_parcels = None

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

        # Select a reasonably sized real parcel for an end-to-end run. Querying 25 records
        # is still tiny compared with the citywide layer and avoids dependence on a hard-coded
        # test address that may change or geocode ambiguously.
        parcel_url = f"{ps.CADASTRAL_BASE}/{ps.LAYER_PARCELS}/query"
        real_parcels = await get_json(municipal_client, parcel_url, {
            "f": "json", "where": "1=1", "outFields": "*", "returnGeometry": "true",
            "resultRecordCount": 25, "outSR": 4326,
        })

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True, verify=True) as verified_client:
        for url in (ps.BUILDING_FOOTPRINTS_URL, ps.SUBURB_OVERVIEW_URL):
            meta = await get_json(verified_client, url, {"f": "json"})
            assert meta.get("fields"), f"No schema fields at {url}"

    candidates = []
    for feat in (real_parcels or {}).get("features", []):
        g = ps.esri_geometry_to_shape(feat.get("geometry"))
        if g is None or g.is_empty:
            continue
        try:
            area = ps.to_metric(g).area
        except Exception:
            continue
        if area > 25:
            candidates.append((area, g))
    assert candidates, "No usable live parcel geometry returned for end-to-end smoke test"
    _, selected = max(candidates, key=lambda x: x[0])
    point = selected.representative_point()

    request = ps.AnalysisRequest(
        lat=float(point.y), lon=float(point.x),
        controls=ps.SetbackControls(
            front_m=1.0, side_m=1.0, rear_m=1.0,
            building_height_m=9.0, frontage_threshold_m=18.0,
        ),
    )
    report = await ps.analyze_property(request)
    assert report.get("success") is True
    assert report.get("parcel", {}).get("area_m2", 0) > 25
    assert "frontages" in report and "edge_features" in report["frontages"]
    assert report.get("setbacks", {}).get("basis") == "measured inward from cadastral site boundary by classified boundary segment"
    assert "beacons" in report and "items" in report["beacons"]
    assert "contours" in report
    assert "servitudes" in report
    pdf = ps.generate_pdf(report)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000

    print(f"LIVE_GIS_E2E_OK parcel_area_m2={report['parcel']['area_m2']} frontages={report['frontages']['count']}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"LIVE_GIS_SMOKE_FAILED: {exc}", file=sys.stderr)
        raise
