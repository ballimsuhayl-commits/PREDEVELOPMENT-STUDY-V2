from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from app.arcgis_fetch import fetch_arcgis_layer_to_geojson
from app.config import settings


def _require(v: str, name: str) -> str:
    v = (v or "").strip()
    if not v:
        raise ValueError(
            f"Missing {name}. Set env var MAC_{name} (see README) or update backend/app/config.py."
        )
    return v


async def main() -> int:
    """Fetch official layers and freeze them into backend/data/*.

    This writes files into:
      - data/municipalities/ethekwini_municipality.(geo)json
      - data/nsc_regions/ethekwini_nsc.(geo)json
      - data/mpr_regions/ethekwini_mpr.(geo)json
    """

    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"

    municipalities_dir = Path(settings.municipalities_dir)
    nsc_dir = Path(settings.nsc_regions_dir)
    mpr_dir = Path(settings.mpr_regions_dir)

    municipalities_dir.mkdir(parents=True, exist_ok=True)
    nsc_dir.mkdir(parents=True, exist_ok=True)
    mpr_dir.mkdir(parents=True, exist_ok=True)

    mun_url = _require(settings.ethekwini_municipal_layer_url, "ETHEKWINI_MUNICIPAL_LAYER_URL")
    nsc_url = _require(settings.ethekwini_nsc_layer_url, "ETHEKWINI_NSC_LAYER_URL")
    mpr_url = _require(settings.ethekwini_mpr_layer_url, "ETHEKWINI_MPR_LAYER_URL")

    print("Fetching municipality layer…")
    mun_out = str(municipalities_dir / "ethekwini_municipality.json")
    mun_res = await fetch_arcgis_layer_to_geojson(mun_url, mun_out)
    print(f"  ✓ {mun_res.feature_count} features -> {mun_res.output_geojson_path}")

    print("Fetching NSC layer…")
    nsc_out = str(nsc_dir / "ethekwini_nsc.json")
    nsc_res = await fetch_arcgis_layer_to_geojson(nsc_url, nsc_out)
    print(f"  ✓ {nsc_res.feature_count} features -> {nsc_res.output_geojson_path}")

    print("Fetching MPR layer…")
    mpr_out = str(mpr_dir / "ethekwini_mpr.json")
    mpr_res = await fetch_arcgis_layer_to_geojson(mpr_url, mpr_out)
    print(f"  ✓ {mpr_res.feature_count} features -> {mpr_res.output_geojson_path}")

    print("Done. The app now runs fully offline using the cached files.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
