from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import json

from shapely.geometry import LinearRing, Point, Polygon, shape
from shapely.prepared import prep


@dataclass(frozen=True)
class LayerFeature:
    name: str
    extras: Dict[str, Any]
    prepared: Any
    bbox: Tuple[float, float, float, float]


def _guess_name_from_filename(p: Path) -> str:
    return p.stem.replace("_", " ").replace("-", " ").strip()


def _pick_first(props: Dict[str, Any], keys: List[str], fallback: Optional[str] = None) -> Optional[str]:
    for k in keys:
        if k in props and props[k] is not None:
            s = str(props[k]).strip()
            if s:
                return s
    return fallback


# --- Minimal ESRI rings -> shapely polygons ---
# Many ArcGIS JSON exports store polygons as `geometry: { rings: [[[x,y],...]] }`.
# A full ESRI ring-to-shell/holes implementation is complex; for planning boundaries (single-part) this
# simplified approach works well.

def _ring_to_linear_ring(ring: List[List[float]]) -> LinearRing:
    if ring and ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    return LinearRing([(float(x), float(y)) for x, y in ring])


def _esri_rings_to_polygons(rings: List[List[List[float]]]) -> List[Polygon]:
    polys: List[Polygon] = []
    for r in rings or []:
        lr = _ring_to_linear_ring(r)
        if lr.is_empty or not lr.is_valid:
            continue
        poly = Polygon(lr)
        if poly.is_empty or not poly.is_valid:
            continue
        polys.append(poly)
    return polys


def _load_geojson(data: dict, fallback_name: str, name_keys: List[str], extras_keys: List[str]) -> List[LayerFeature]:
    out: List[LayerFeature] = []

    def add(geom_obj: dict, props: Dict[str, Any]):
        shp = shape(geom_obj)
        if shp.is_empty:
            return
        name = _pick_first(props, name_keys, fallback_name) or fallback_name
        extras = {k: props.get(k) for k in extras_keys if props.get(k) is not None}
        out.append(LayerFeature(name=name, extras=extras, prepared=prep(shp), bbox=shp.bounds))

    t = data.get("type")
    if t == "FeatureCollection":
        for feat in data.get("features", []) or []:
            if not isinstance(feat, dict):
                continue
            props = feat.get("properties") or {}
            geom_obj = feat.get("geometry")
            if geom_obj:
                add(geom_obj, props)
        return out
    if t == "Feature":
        props = data.get("properties") or {}
        geom_obj = data.get("geometry")
        if geom_obj:
            add(geom_obj, props)
        return out
    if isinstance(data, dict) and "type" in data and "coordinates" in data:
        add(data, {})
        return out

    return out


def _load_esri_json(data: dict, fallback_name: str, name_keys: List[str], extras_keys: List[str]) -> List[LayerFeature]:
    out: List[LayerFeature] = []
    feats = data.get("features")
    if not isinstance(feats, list):
        return out

    for feat in feats:
        if not isinstance(feat, dict):
            continue
        attrs = feat.get("attributes") or {}
        geom = feat.get("geometry") or {}
        rings = geom.get("rings")
        if not isinstance(rings, list):
            continue
        name = _pick_first(attrs, name_keys, fallback_name) or fallback_name
        extras = {k: attrs.get(k) for k in extras_keys if attrs.get(k) is not None}
        for poly in _esri_rings_to_polygons(rings):
            out.append(LayerFeature(name=name, extras=extras, prepared=prep(poly), bbox=poly.bounds))

    return out


class BoundaryLayer:
    def __init__(self, folder: str, name_keys: List[str], extras_keys: List[str]):
        self.folder = folder
        self.name_keys = name_keys
        self.extras_keys = extras_keys
        self._loaded = False
        self._features: List[LayerFeature] = []

    def load(self) -> None:
        if self._loaded:
            return
        path = Path(self.folder)
        path.mkdir(parents=True, exist_ok=True)
        feats: List[LayerFeature] = []

        files = list(path.glob("*.geojson")) + list(path.glob("*.json"))
        for p in sorted(files):
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            fallback_name = _guess_name_from_filename(p)

            g = _load_geojson(data, fallback_name, self.name_keys, self.extras_keys)
            if g:
                feats.extend(g)
                continue
            e = _load_esri_json(data, fallback_name, self.name_keys, self.extras_keys)
            if e:
                feats.extend(e)
                continue

        self._features = feats
        self._loaded = True

    def query(self, lat: float, lon: float) -> Optional[LayerFeature]:
        self.load()
        if not self._features:
            return None

        pt = Point(float(lon), float(lat))
        for f in self._features:
            minx, miny, maxx, maxy = f.bbox
            if not (minx <= pt.x <= maxx and miny <= pt.y <= maxy):
                continue
            if f.prepared.contains(pt):
                return f
        return None
