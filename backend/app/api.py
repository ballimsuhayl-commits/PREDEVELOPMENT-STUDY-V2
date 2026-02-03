from __future__ import annotations

from typing import List, Optional, Dict, Any

from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlmodel import Session, select

from .config import settings
from .db import get_session
from .geocode import geocode_address
from .geo_layers import BoundaryLayer
from .models import CheckLog, CheckRequest, CheckResult
from .util import normalize_address
from .arcgis_fetch import fetch_arcgis_layer_to_geojson

router = APIRouter(prefix="/api")

# Layer config: we make name_keys inclusive so it works with many exports.
MUNICIPALITIES = BoundaryLayer(
    folder=settings.municipalities_dir,
    name_keys=["MUNICNAME", "municname", "MUNICNAME", "municipality", "name", "NAME"],
    extras_keys=["PROVINCE", "provname", "province", "PROVNAME"],
)

# NSC (North/South/Central) often comes from the Zoning layer (MapServer/28).
# That layer uses SCHEMENAME and REGION as described in the ArcGIS layer docs.
NSC = BoundaryLayer(
    folder=settings.nsc_regions_dir,
    name_keys=[
        "SCHEMENAME",
        "SCHEME",
        "REGION",
        "REGION_NAME",
        "REGIONDESC",
        "REGION_DESC",
        "REGION_FULL",
        "REGIONFULL",
        "REGIONTEXT",
        "REGION_TEXT",
        "NAME",
        "name",
        "REGIONLABEL",
        "REGION_LABEL",
    ],
    extras_keys=[],
)

# MPR (Municipal Planning Regions) commonly uses a name field like FUNC_DISTR.
MPR = BoundaryLayer(
    folder=settings.mpr_regions_dir,
    name_keys=["REGION", "REGION_NAME", "NAME", "name", "FUNC_DISTR", "FUNC_DIST", "PLANNING_R", "PLANNING_REGION"],
    extras_keys=[],
)

CUSTOM = BoundaryLayer(
    folder=settings.custom_regions_dir,
    name_keys=["REGION", "REGION_NAME", "NAME", "name", "LABEL", "label"],
    extras_keys=[],
)


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/check", response_model=CheckResult)
async def check_address(payload: CheckRequest, session: Session = Depends(get_session)):
    addr = normalize_address(payload.address)
    if not addr:
        raise HTTPException(status_code=400, detail="Address is required")

    lat: Optional[float] = payload.lat
    lon: Optional[float] = payload.lon

    normalized: Optional[str] = None
    confidence: float = 0.0
    reason: Optional[str] = None

    # If caller didn't provide coordinates, we attempt geocoding (optional).
    if lat is None or lon is None:
        hit = await geocode_address(addr, payload.country)
        if not hit:
            res = CheckResult(
                ok=False,
                input_address=addr,
                normalized_address=None,
                lat=None,
                lon=None,
                municipality=None,
                province=None,
                nsc_region=None,
                mpr_region=None,
                custom_region=None,
                confidence=0.0,
                reason="Could not geocode address. Provide lat/lon or enable geocoder.",
            )
            session.add(
                CheckLog(
                    address=addr,
                    normalized_address=None,
                    lat=None,
                    lon=None,
                    municipality=None,
                    province=None,
                    nsc_region=None,
                    mpr_region=None,
                    custom_region=None,
                    confidence=0.0,
                    ok=False,
                    reason=res.reason,
                )
            )
            session.commit()
            return res

        normalized = hit.display_name
        lat, lon = hit.lat, hit.lon
        # Nominatim importance is 0..1-ish, but not a strict probability.
        confidence = max(0.35, min(0.95, float(hit.importance)))

    lat_f = float(lat)
    lon_f = float(lon)

    mun_hit = MUNICIPALITIES.query(lat_f, lon_f)
    nsc_hit = NSC.query(lat_f, lon_f)
    mpr_hit = MPR.query(lat_f, lon_f)
    custom_hit = CUSTOM.query(lat_f, lon_f)

    municipality = mun_hit.name if mun_hit else None
    province = None
    if mun_hit:
        province = mun_hit.extras.get("PROVINCE") or mun_hit.extras.get("provname") or mun_hit.extras.get("province")
        if province is not None:
            province = str(province).strip() or None

    nsc_region = nsc_hit.name if nsc_hit else None
    mpr_region = mpr_hit.name if mpr_hit else None
    custom_region = custom_hit.name if custom_hit else None

    ok = municipality is not None

    missing = []
    if not mun_hit:
        missing.append("municipality")
    if not nsc_hit:
        missing.append("NSC")
    if not mpr_hit:
        missing.append("MPR")
    if not custom_hit:
        missing.append("custom")
    if missing:
        reason = "No match for: " + ", ".join(missing) + ". If this is unexpected, refresh/download datasets."

    res = CheckResult(
        ok=ok,
        input_address=addr,
        normalized_address=normalized,
        lat=lat_f,
        lon=lon_f,
        municipality=municipality,
        province=province,
        nsc_region=nsc_region,
        mpr_region=mpr_region,
        custom_region=custom_region,
        confidence=float(confidence if ok else max(0.1, confidence)),
        reason=reason,
    )

    session.add(
        CheckLog(
            address=addr,
            normalized_address=normalized,
            lat=lat_f,
            lon=lon_f,
            municipality=municipality,
            province=province,
            nsc_region=nsc_region,
            mpr_region=mpr_region,
            custom_region=custom_region,
            confidence=res.confidence,
            ok=res.ok,
            reason=res.reason,
        )
    )
    session.commit()
    return res


@router.get("/history", response_model=List[CheckLog])
def history(limit: int = 50, session: Session = Depends(get_session)):
    limit = max(1, min(500, int(limit)))
    stmt = select(CheckLog).order_by(CheckLog.created_at.desc()).limit(limit)
    return list(session.exec(stmt).all())


@router.post("/admin/refresh-datasets")
async def admin_refresh(
    which: str = "all",
    x_admin_token: Optional[str] = Header(default=None),
):
    """Refresh cached datasets by downloading from official ArcGIS endpoints.

    Security:
      - Provide header X-Admin-Token matching MAC_ADMIN_TOKEN (env) / settings.admin_token.

    which: all|municipality|nsc|mpr
    """

    if not (settings.admin_token or "").strip():
        raise HTTPException(status_code=404, detail="Admin refresh is disabled")

    if (x_admin_token or "") != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")

    which_l = (which or "all").lower().strip()

    out: Dict[str, Any] = {}
    # Ensure directories exist
    Path(settings.municipalities_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.nsc_regions_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.mpr_regions_dir).mkdir(parents=True, exist_ok=True)

    async def _refresh_municipality():
        url = (settings.ethekwini_municipal_layer_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="Missing MAC_ETHEKWINI_MUNICIPAL_LAYER_URL")
        out_path = str(Path(settings.municipalities_dir) / "ethekwini_municipality.json")
        res = await fetch_arcgis_layer_to_geojson(url, out_path)
        out["municipality"] = {"features": res.feature_count, "file": res.output_geojson_path}

    async def _refresh_nsc():
        url = (settings.ethekwini_nsc_layer_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="Missing MAC_ETHEKWINI_NSC_LAYER_URL")
        out_path = str(Path(settings.nsc_regions_dir) / "ethekwini_nsc.json")
        res = await fetch_arcgis_layer_to_geojson(url, out_path)
        out["nsc"] = {"features": res.feature_count, "file": res.output_geojson_path}

    async def _refresh_mpr():
        url = (settings.ethekwini_mpr_layer_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="Missing MAC_ETHEKWINI_MPR_LAYER_URL")
        out_path = str(Path(settings.mpr_regions_dir) / "ethekwini_mpr.json")
        res = await fetch_arcgis_layer_to_geojson(url, out_path)
        out["mpr"] = {"features": res.feature_count, "file": res.output_geojson_path}

    if which_l == "all":
        await _refresh_municipality()
        await _refresh_nsc()
        await _refresh_mpr()
    elif which_l in ("municipality", "mun", "muni"):
        await _refresh_municipality()
    elif which_l in ("nsc", "northsouthcentral"):
        await _refresh_nsc()
    elif which_l in ("mpr", "planning", "planningregions"):
        await _refresh_mpr()
    else:
        raise HTTPException(status_code=400, detail="Invalid 'which'. Use all|municipality|nsc|mpr")

    return {"ok": True, "which": which_l, "result": out}
