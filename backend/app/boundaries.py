from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from shapely.geometry import shape, Polygon, MultiPolygon, Point
from shapely.prepared import prep


def _safe_get(d: Dict[str, Any], keys: List[str]) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _esri_rings_to_polygon(rings: List[List[List[float]]]) -> Polygon | MultiPolygon:
    """Convert ArcGIS JSON 'rings' to shapely polygon.

    ArcGIS rings: list of rings; first is outer; subsequent may be holes or separate parts.
    This is a best-effort conversion.
    """

    if not rings:
        raise ValueError("No rings")

    # Many ESRI JSON exports store a single polygon with holes as multiple rings.
    # We treat first ring as shell and any ring fully inside as holes.
    shell = rings[0]
    holes = rings[1:] if len(rings) > 1 else []

    try:
        poly = Polygon(shell, holes=holes)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly
    except Exception:
        # Fallback: treat as MultiPolygon of separate parts
        parts = []
        for r in rings:
            p = Polygon(r)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty:
                parts.append(p)
        if not parts:
            raise
        return MultiPolygon(parts)


def _load_any_feature_collection(path: Path) -> List[Tuple[Dict[str, Any], Polygon | MultiPolygon]]:
    """Load GeoJSON FeatureCollection OR ESRI JSON {features:[{attributes,geometry:{rings}}]}.

    Returns list of (properties, geometry).
    """

    raw = json.loads(path.read_text(encoding="utf-8"))

    out: List[Tuple[Dict[str, Any], Polygon | MultiPolygon]] = []

    # GeoJSON
    if raw.get("type") in {"FeatureCollection", "Feature"}:
        features = raw.get("features") if raw.get("type") == "FeatureCollection" else [raw]
        for f in features or []:
            props = dict(f.get("properties") or {})
            geom = f.get("geometry")
            if not geom:
                continue
            g = shape(geom)
            if g.is_empty:
                continue
            if g.geom_type == "Polygon":
                out.append((props, g))
            elif g.geom_type == "MultiPolygon":
                out.append((props, g))
        return out

    # ESRI JSON
    if isinstance(raw.get("features"), list):
        for f in raw["features"]:
            props = dict(f.get("attributes") or {})
            geom = f.get("geometry") or {}
            rings = geom.get("rings")
            if not rings:
                continue
            g = _esri_rings_to_polygon(rings)
            if not g.is_empty:
                out.append((props, g))
        return out

    raise ValueError(f"Unsupported boundary format in {path.name}")


@dataclass
class PreparedFeature:
    name: str
    props: Dict[str, Any]
    geom: Polygon | MultiPolygon
    prepared: Any


class PolygonIndex:
    """Simple in-memory polygon index (linear scan, prepared geometries)."""

    def __init__(self, label_keys: List[str]):
        self.label_keys = label_keys
        self.features: List[PreparedFeature] = []

    def add(self, props: Dict[str, Any], geom: Polygon | MultiPolygon) -> None:
        name = _safe_get(props, self.label_keys) or "(unnamed)"
        self.features.append(PreparedFeature(name=name, props=props, geom=geom, prepared=prep(geom)))

    def query(self, lon: float, lat: float) -> Optional[str]:
        p = Point(lon, lat)
        for f in self.features:
            if f.prepared.contains(p) or f.prepared.intersects(p):
                return f.name
        return None


def load_layer(folder: Path, label_keys: List[str]) -> PolygonIndex:
    idx = PolygonIndex(label_keys=label_keys)
    if not folder.exists():
        return idx

    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".json", ".geojson"}]
    for p in sorted(files):
        try:
            items = _load_any_feature_collection(p)
        except Exception:
            continue
        for props, geom in items:
            idx.add(props, geom)
    return idx
