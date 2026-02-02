from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from .boundaries import load_layer
from .config import settings
from .db import init_db, get_session
from .geocode import geocode_nominatim, GeocodeError
from .models import CheckLog
from .schemas import CheckRequest, CheckResponse, LayerHit, HistoryRow


app = FastAPI(title="Municipality Address Check")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()

    data_root = Path(settings.data_dir)

    # Load layers once at startup. You can reload the server after updating files.
    app.state.layer_municipality = load_layer(
        data_root / "municipalities",
        label_keys=["MUNICNAME", "municipality", "name", "NAME"],
    )
    app.state.layer_nsc = load_layer(
        data_root / "nsc_regions",
        label_keys=["REGION", "Region", "NAME", "name"],
    )
    app.state.layer_mpr = load_layer(
        data_root / "mpr_regions",
        label_keys=["REGION", "Region", "MPR", "NAME", "name"],
    )
    app.state.layer_custom = load_layer(
        data_root / "custom_regions",
        label_keys=["REGION", "Region", "NAME", "name"],
    )


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "allow_nominatim": settings.allow_nominatim,
    }


@app.post("/api/check", response_model=CheckResponse)
def check(req: CheckRequest):
    lat = req.lat
    lon = req.lon
    normalized = None

    if lat is None or lon is None:
        if not settings.allow_nominatim:
            raise HTTPException(status_code=400, detail="lat/lon required (geocoding disabled)")
        try:
            lat, lon, normalized = geocode_nominatim(req.address, req.country)
        except GeocodeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception:
            raise HTTPException(status_code=502, detail="Geocoder failed")

    assert lat is not None and lon is not None

    municipality = app.state.layer_municipality.query(lon=lon, lat=lat)
    nsc = app.state.layer_nsc.query(lon=lon, lat=lat) if app.state.layer_nsc.features else None
    mpr = app.state.layer_mpr.query(lon=lon, lat=lat) if app.state.layer_mpr.features else None
    custom = app.state.layer_custom.query(lon=lon, lat=lat) if app.state.layer_custom.features else None

    hits = []
    hits.append(
        LayerHit(layer="municipality", match=municipality, reason=None if municipality else "No match in municipality layer")
    )
    hits.append(
        LayerHit(layer="nsc", match=nsc, reason=None if nsc else ("Layer empty" if not app.state.layer_nsc.features else "No match"))
    )
    hits.append(
        LayerHit(layer="mpr", match=mpr, reason=None if mpr else ("Layer empty" if not app.state.layer_mpr.features else "No match"))
    )
    hits.append(
        LayerHit(
            layer="custom",
            match=custom,
            reason=None if custom else ("Layer empty" if not app.state.layer_custom.features else "No match"),
        )
    )

    ok = municipality is not None
    message = "OK" if ok else "Point is not inside any municipality boundary"

    row = CheckLog(
        input_address=req.address,
        normalized_address=normalized,
        lat=lat,
        lon=lon,
        municipality=municipality,
        nsc_region=nsc,
        mpr_region=mpr,
        custom_region=custom,
        ok=ok,
        message=message,
    )

    with get_session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)

    return CheckResponse(
        ok=ok,
        input_address=req.address,
        normalized_address=normalized,
        lat=lat,
        lon=lon,
        municipality=municipality,
        nsc_region=nsc,
        mpr_region=mpr,
        custom_region=custom,
        hits=hits,
        message=message,
    )


@app.get("/api/history", response_model=list[HistoryRow])
def history(limit: int = 50):
    limit = max(1, min(int(limit), 500))
    with get_session() as s:
        rows = s.exec(select(CheckLog).order_by(CheckLog.created_at.desc()).limit(limit)).all()
    return [
        HistoryRow(
            id=r.id or 0,
            created_at=r.created_at,
            input_address=r.input_address,
            normalized_address=r.normalized_address,
            lat=r.lat,
            lon=r.lon,
            municipality=r.municipality,
            nsc_region=r.nsc_region,
            mpr_region=r.mpr_region,
            custom_region=r.custom_region,
            ok=r.ok,
            message=r.message,
        )
        for r in rows
    ]
