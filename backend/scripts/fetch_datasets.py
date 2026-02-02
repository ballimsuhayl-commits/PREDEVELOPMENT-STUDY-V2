"""Fetch public ArcGIS REST datasets and save them into backend/data.

Run:
  cd backend
  python -m scripts.fetch_datasets

This is optional. The app works with any boundary datasets you provide manually.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx


HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
DATA = BACKEND / "data"


def _ensure_dirs() -> None:
    for d in [DATA / "municipalities", DATA / "nsc_regions", DATA / "mpr_regions", DATA / "custom_regions"]:
        d.mkdir(parents=True, exist_ok=True)


def arcgis_query_to_geojson(layer_url: str, out_path: Path, where: str = "1=1", out_fields: str = "*") -> None:
    base = layer_url.rstrip("/") + "/query"
    params = {"where": where, "outFields": out_fields, "f": "geojson", "resultRecordCount": 2000, "resultOffset": 0}
    features = []
    with httpx.Client(timeout=60.0, headers={"User-Agent": "municipality-address-check/1.0"}) as client:
        while True:
            r = client.get(base, params=params)
            r.raise_for_status()
            gj = r.json()
            batch = gj.get("features") or []
            features.extend(batch)
            if len(batch) < int(params["resultRecordCount"]):
                out = {"type": "FeatureCollection", "features": features}
                out_path.write_text(json.dumps(out), encoding="utf-8")
                return
            params["resultOffset"] = int(params["resultOffset"]) + int(params["resultRecordCount"])


def main() -> None:
    _ensure_dirs()

    ETHEKWINI_MUNIC_BOUNDARY_LAYER = (
        "https://services3.arcgis.com/HO0zfySJshlD6Twu/arcgis/rest/services/"
        "eThekwini_Municipal_Boundary/FeatureServer/0"
    )

    # If you have NSC/MPR boundary layers, paste the layer URLs here.
    NSC_LAYER: Optional[str] = None
    MPR_LAYER: Optional[str] = None

    print("Downloading eThekwini municipal boundary…")
    out_mun = DATA / "municipalities" / "eThekwini_Municipal_Boundary.geojson"
    arcgis_query_to_geojson(ETHEKWINI_MUNIC_BOUNDARY_LAYER, out_mun)
    print(f"Saved: {out_mun}")

    if NSC_LAYER:
        out_nsc = DATA / "nsc_regions" / "NSC.geojson"
        arcgis_query_to_geojson(NSC_LAYER, out_nsc)
        print(f"Saved: {out_nsc}")
    if MPR_LAYER:
        out_mpr = DATA / "mpr_regions" / "MPR.geojson"
        arcgis_query_to_geojson(MPR_LAYER, out_mpr)
        print(f"Saved: {out_mpr}")

    print("Done.")


if __name__ == "__main__":
    main()
