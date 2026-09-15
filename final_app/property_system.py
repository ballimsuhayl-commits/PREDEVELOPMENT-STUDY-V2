#!/usr/bin/env python3
"""
eThekwini Property Development Intelligence — production single-file application.

Workflow:
Address / coordinate -> official parcel -> zoning -> road-aware frontage detection ->
front/side/rear setbacks measured inward from the cadastral site boundary -> buildable
2D envelope -> 3D extrusion -> corner beacons + beacon/ground height screening ->
servitudes/SDF/contours/building-footprint screening -> downloadable PDF report.

Planning note:
The application is a due-diligence / feasibility screening tool. Public GIS layers are
not a substitute for a zoning certificate, title deed/servitude deed, SG diagram,
registered land-survey information, approved plans or a formal municipal determination.
"""
from __future__ import annotations

import asyncio
import io
import json
import math
import os
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from pyproj import CRS, Transformer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union
from shapely.strtree import STRtree

APP_VERSION = "3.0.0"
APP_NAME = "eThekwini Property Development Intelligence"

CADASTRAL_BASE = os.getenv(
    "ETHEKWINI_CADASTRAL_BASE",
    "https://gis.durban.gov.za/server/rest/services/WebViewers/EXT_Cadastral/MapServer",
).rstrip("/")

# Current EXT_Cadastral layer IDs (verified against the municipal REST service in Sept 2026).
LAYER_ADDRESSPOINT = 1
LAYER_ROADS = 3
LAYER_CONTOURS = 6
LAYER_BEACONS = 13
LAYER_SERVITUDES = 14
LAYER_PARCELS = 17
LAYER_SUBURBS = 19
LAYER_ZONING = 28
LAYER_SDF = 29

BUILDING_FOOTPRINTS_URL = os.getenv(
    "BUILDING_FOOTPRINTS_URL",
    "https://services3.arcgis.com/HO0zfySJshlD6Twu/arcgis/rest/services/Building_Footprints/FeatureServer/0",
).rstrip("/")
SUBURB_OVERVIEW_URL = os.getenv(
    "SUBURB_OVERVIEW_URL",
    "https://services3.arcgis.com/HO0zfySJshlD6Twu/arcgis/rest/services/Suburb_Overview/FeatureServer/0",
).rstrip("/")
NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
LOCAL_ROADS_GEOJSON = os.getenv("ROAD_GEOJSON", "").strip()
REQUEST_TIMEOUT = float(os.getenv("GIS_REQUEST_TIMEOUT", "22"))
MAX_RETRIES = int(os.getenv("GIS_MAX_RETRIES", "3"))
USER_AGENT = os.getenv("GIS_USER_AGENT", "EthekwiniPropertyDevelopmentIntelligence/3.0 (+local feasibility tool)")

METRIC_CRS = CRS.from_epsg(32736)  # WGS84 / UTM 36S — Durban metric analysis
WGS84 = CRS.from_epsg(4326)
TO_METRIC = Transformer.from_crs(WGS84, METRIC_CRS, always_xy=True)
TO_WGS84 = Transformer.from_crs(METRIC_CRS, WGS84, always_xy=True)

DISCLAIMER = (
    "Screening only. Confirm planning rights and restrictions against the applicable "
    "eThekwini scheme, zoning certificate, title deed, SG diagram, registered servitudes, "
    "approved plans and formal municipal determinations before design or acquisition decisions."
)


class SetbackControls(BaseModel):
    front_m: float = Field(5.0, ge=0, le=100)
    side_m: float = Field(2.0, ge=0, le=100)
    rear_m: float = Field(2.0, ge=0, le=100)
    building_height_m: float = Field(18.0, gt=0, le=500)
    frontage_threshold_m: float = Field(18.0, ge=3, le=60)


class AnalysisRequest(BaseModel):
    address: Optional[str] = Field(default=None, max_length=300)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)
    controls: SetbackControls = Field(default_factory=SetbackControls)

    @field_validator("address")
    @classmethod
    def trim_address(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = " ".join(value.strip().split())
        return value or None


class PdfRequest(BaseModel):
    report: Dict[str, Any]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_metric(geom):
    return shp_transform(TO_METRIC.transform, geom)


def to_wgs84(geom):
    return shp_transform(TO_WGS84.transform, geom)


def _repair(g):
    if g is None or g.is_empty:
        return g
    if g.is_valid:
        return g
    try:
        from shapely import make_valid
        fixed = make_valid(g)
        if fixed is not None and not fixed.is_empty:
            return fixed
    except Exception:
        pass
    try:
        return g.buffer(0)
    except Exception:
        return g


def _numeric(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, str) and not v.strip():
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def esri_polygon_to_shape(rings: Sequence[Sequence[Sequence[float]]]):
    """Convert ArcGIS rings using containment-depth hole classification.

    Winding direction is deliberately ignored because reprojected/exported services are
    not always consistent about ring orientation.
    """
    ring_polys: List[Polygon] = []
    ring_coords: List[List[Tuple[float, float]]] = []
    for raw in rings or []:
        coords = [(float(p[0]), float(p[1])) for p in raw if len(p) >= 2]
        if len(coords) < 3:
            continue
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        try:
            p = _repair(Polygon(coords))
            if p is None or p.is_empty:
                continue
            if isinstance(p, MultiPolygon):
                p = max(p.geoms, key=lambda x: x.area)
            ring_polys.append(p)
            ring_coords.append(coords)
        except Exception:
            continue
    if not ring_polys:
        return None

    parents: List[Optional[int]] = [None] * len(ring_polys)
    for i, p in enumerate(ring_polys):
        rp = p.representative_point()
        containers = [j for j, q in enumerate(ring_polys) if j != i and q.area > p.area and q.contains(rp)]
        if containers:
            parents[i] = min(containers, key=lambda j: ring_polys[j].area)

    depths = [0] * len(ring_polys)
    for i in range(len(ring_polys)):
        d, parent, seen = 0, parents[i], set()
        while parent is not None and parent not in seen:
            seen.add(parent)
            d += 1
            parent = parents[parent]
        depths[i] = d

    polys: List[Polygon] = []
    for i in range(len(ring_polys)):
        if depths[i] % 2:
            continue
        holes = [ring_coords[j] for j in range(len(ring_polys)) if parents[j] == i and depths[j] == depths[i] + 1]
        try:
            poly = _repair(Polygon(ring_coords[i], holes))
            if isinstance(poly, Polygon) and not poly.is_empty:
                polys.append(poly)
            elif isinstance(poly, MultiPolygon):
                polys.extend(list(poly.geoms))
        except Exception:
            continue
    if not polys:
        return None
    return _repair(unary_union(polys))


def esri_geometry_to_shape(geom: Optional[Dict[str, Any]]):
    if not geom:
        return None
    if "x" in geom and "y" in geom:
        return Point(float(geom["x"]), float(geom["y"]))
    if "points" in geom:
        return MultiPoint([(float(x), float(y)) for x, y, *_ in geom["points"]])
    if "paths" in geom:
        lines = []
        for path in geom.get("paths", []):
            coords = [(float(p[0]), float(p[1])) for p in path if len(p) >= 2]
            if len(coords) >= 2:
                lines.append(LineString(coords))
        if not lines:
            return None
        return lines[0] if len(lines) == 1 else MultiLineString(lines)
    if "rings" in geom:
        return esri_polygon_to_shape(geom.get("rings", []))
    return None


def shape_to_feature(g, properties: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if g is None or g.is_empty:
        return None
    return {"type": "Feature", "properties": properties or {}, "geometry": mapping(g)}


def polygon_exterior_edges(poly: Polygon) -> List[LineString]:
    coords = list(poly.exterior.coords)
    out = []
    for a, b in zip(coords[:-1], coords[1:]):
        e = LineString([a, b])
        if e.length > 0.05:
            out.append(e)
    return out


def _angle_deg(line: LineString) -> float:
    (x1, y1), (x2, y2) = list(line.coords)[0], list(line.coords)[-1]
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0


def _angle_difference(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _flatten_lines(g) -> Iterable[LineString]:
    if g is None or g.is_empty:
        return []
    if isinstance(g, LineString):
        return [g]
    if isinstance(g, MultiLineString):
        return list(g.geoms)
    if hasattr(g, "geoms"):
        out = []
        for child in g.geoms:
            out.extend(_flatten_lines(child))
        return out
    return []


def _nearest_segment_orientation(point: Point, line_geom) -> Tuple[float, float]:
    best_d = float("inf")
    best_angle = 0.0
    for ls in _flatten_lines(line_geom):
        coords = list(ls.coords)
        for a, b in zip(coords[:-1], coords[1:]):
            seg = LineString([a, b])
            d = point.distance(seg)
            if d < best_d and seg.length > 0.05:
                best_d = d
                best_angle = _angle_deg(seg)
    return best_d, best_angle


@dataclass
class RoadFeature:
    geometry: Any
    properties: Dict[str, Any]


@dataclass
class EdgeClassification:
    index: int
    edge: LineString
    frontage: bool
    nearest_road_distance_m: Optional[float]
    nearest_road_name: Optional[str]
    nearest_road_type: Optional[str]
    orientation_difference_deg: Optional[float]
    road_buffer_overlap_ratio: float


def classify_edges_against_roads(parcel_metric: Polygon, roads_metric: Sequence[RoadFeature], threshold_m: float) -> List[EdgeClassification]:
    edges = polygon_exterior_edges(parcel_metric)
    if not edges:
        return []
    if not roads_metric:
        return [EdgeClassification(i, e, False, None, None, None, None, 0.0) for i, e in enumerate(edges)]

    road_union = unary_union([r.geometry for r in roads_metric if r.geometry is not None and not r.geometry.is_empty])
    proximity_band = road_union.buffer(threshold_m, cap_style=2, join_style=2)
    out = []
    for i, edge in enumerate(edges):
        midpoint = edge.interpolate(0.5, normalized=True)
        edge_angle = _angle_deg(edge)
        best = None
        for road in roads_metric:
            if road.geometry is None or road.geometry.is_empty:
                continue
            d, road_angle = _nearest_segment_orientation(midpoint, road.geometry)
            if best is None or d < best[0]:
                best = (d, road, road_angle)
        try:
            overlap = edge.intersection(proximity_band).length / max(edge.length, 1e-9)
        except Exception:
            overlap = 0.0
        if best is None:
            out.append(EdgeClassification(i, edge, False, None, None, None, None, overlap))
            continue
        distance_m, nearest, road_angle = best
        angle_diff = _angle_difference(edge_angle, road_angle)
        frontage = (
            distance_m <= threshold_m and angle_diff <= 45.0 and overlap >= 0.30
        ) or (
            distance_m <= threshold_m * 0.55 and angle_diff <= 55.0 and overlap >= 0.12
        )
        props = nearest.properties or {}
        road_name = props.get("ROAD_LABEL") or props.get("ROAD_NAME") or props.get("name")
        road_type = props.get("ROAD_TYPE") or props.get("Road_Type") or props.get("type")
        out.append(EdgeClassification(
            i, edge, bool(frontage), float(distance_m),
            str(road_name).strip() if road_name not in (None, "") else None,
            str(road_type).strip() if road_type not in (None, "") else None,
            float(angle_diff), float(overlap)
        ))
    return out


def _merge_small_boolean_gaps(classes: List[EdgeClassification], max_gap_m: float = 4.0) -> None:
    n = len(classes)
    if n < 3:
        return
    changed = True
    while changed:
        changed = False
        for i, c in enumerate(classes):
            if c.frontage or c.edge.length > max_gap_m:
                continue
            if classes[(i - 1) % n].frontage and classes[(i + 1) % n].frontage:
                c.frontage = True
                changed = True


def contiguous_groups(classes: Sequence[EdgeClassification], value: bool) -> List[List[int]]:
    idxs = [i for i, c in enumerate(classes) if c.frontage == value]
    if not idxs:
        return []
    groups = []
    current = [idxs[0]]
    for prev, cur in zip(idxs[:-1], idxs[1:]):
        if cur == prev + 1:
            current.append(cur)
        else:
            groups.append(current)
            current = [cur]
    groups.append(current)
    n = len(classes)
    if len(groups) > 1 and groups[0][0] == 0 and groups[-1][-1] == n - 1:
        groups[0] = groups[-1] + groups[0]
        groups.pop()
    return groups


def group_midpoint(classes: Sequence[EdgeClassification], group: Sequence[int]) -> Point:
    lines = [classes[i].edge for i in group]
    total = sum(l.length for l in lines)
    if total <= 0:
        return lines[0].centroid
    x = sum(l.interpolate(0.5, normalized=True).x * l.length for l in lines) / total
    y = sum(l.interpolate(0.5, normalized=True).y * l.length for l in lines) / total
    return Point(x, y)


def choose_rear_group(classes: Sequence[EdgeClassification], frontage_groups: Sequence[Sequence[int]], nonfront_groups: Sequence[Sequence[int]]) -> Optional[List[int]]:
    if not nonfront_groups or not frontage_groups:
        return None
    primary = max(frontage_groups, key=lambda g: sum(classes[i].edge.length for i in g))
    front_mid = group_midpoint(classes, primary)
    return list(max(nonfront_groups, key=lambda g: front_mid.distance(group_midpoint(classes, g))))


def build_setback_envelope(parcel_metric: Polygon, classes: Sequence[EdgeClassification], front_m: float, side_m: float, rear_m: float):
    """Subtract setback strips inward from the original cadastral site boundary.

    Every road-facing boundary group receives front_m, the inferred opposite non-road
    group receives rear_m and remaining non-road boundaries receive side_m. This supports
    1, 2, 3 or more street-frontage sides without assuming a single front boundary.
    """
    mutable = list(classes)
    _merge_small_boolean_gaps(mutable)
    frontage_groups = contiguous_groups(mutable, True)
    nonfront_groups = contiguous_groups(mutable, False)
    rear_group = choose_rear_group(mutable, frontage_groups, nonfront_groups)
    rear_set = set(rear_group or [])

    edge_roles: Dict[int, str] = {}
    strips = []
    for c in mutable:
        if c.frontage:
            role, setback = "street", front_m
        elif c.index in rear_set:
            role, setback = "rear", rear_m
        else:
            role, setback = "side", side_m
        edge_roles[c.index] = role
        if setback > 0:
            strip = c.edge.buffer(setback, cap_style=2, join_style=2).intersection(parcel_metric)
            if not strip.is_empty:
                strips.append(strip)
    if not strips:
        env = parcel_metric
    else:
        env = _repair(parcel_metric.difference(unary_union(strips)))
    return env, edge_roles, frontage_groups, nonfront_groups, rear_group


def _corner_angle(prev_pt, pt, next_pt) -> float:
    ax, ay = prev_pt[0] - pt[0], prev_pt[1] - pt[1]
    bx, by = next_pt[0] - pt[0], next_pt[1] - pt[1]
    la, lb = math.hypot(ax, ay), math.hypot(bx, by)
    if la <= 1e-9 or lb <= 1e-9:
        return 180.0
    cosv = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
    return math.degrees(math.acos(cosv))


def significant_corners(poly_metric: Polygon, minimum_deflection_deg: float = 4.0) -> List[Point]:
    coords = list(poly_metric.exterior.coords)[:-1]
    if len(coords) <= 3:
        return [Point(c) for c in coords]
    corners = []
    n = len(coords)
    for i, pt in enumerate(coords):
        angle = _corner_angle(coords[(i - 1) % n], pt, coords[(i + 1) % n])
        if abs(180.0 - angle) >= minimum_deflection_deg:
            p = Point(pt)
            if not corners or p.distance(corners[-1]) >= 0.15:
                corners.append(p)
    if len(corners) < 3:
        corners = [Point(c) for c in coords]
    return corners


def _find_numeric_elevation(attrs: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    preferred = ["ELEVATION", "ELEV", "HEIGHT", "RL", "Z", "MSL", "LEVEL", "BEACON_RL", "HEIGHT_M", "ELEV_M"]
    upper = {str(k).upper(): k for k in attrs.keys()}
    for name in preferred:
        if name in upper:
            raw_key = upper[name]
            val = _numeric(attrs.get(raw_key))
            if val is not None and -1000 < val < 10000:
                return val, str(raw_key)
    return None, None


def beacon_height_from_contours(beacon_metric: Point, contour_features_metric: Sequence[Tuple[Any, Dict[str, Any]]]):
    candidates = []
    for geom, attrs in contour_features_metric:
        elev = _numeric(attrs.get("ELEVATION") or attrs.get("elevation") or attrs.get("Elev"))
        if elev is None or geom is None or geom.is_empty:
            continue
        candidates.append((beacon_metric.distance(geom), elev))
    if not candidates:
        return None, None, None
    distance, elev = min(candidates, key=lambda x: x[0])
    return float(elev), "nearest_2m_contour", float(distance)


class ArcGISClient:
    def __init__(self):
        self.headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    async def _post(self, url: str, data: Dict[str, Any]) -> Dict[str, Any]:
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(headers=self.headers, timeout=httpx.Timeout(REQUEST_TIMEOUT), follow_redirects=True) as client:
                    resp = await client.post(url, data=data)
                    resp.raise_for_status()
                    payload = resp.json()
                    if isinstance(payload, dict) and payload.get("error"):
                        msg = payload["error"].get("message", "ArcGIS error")
                        details = payload["error"].get("details") or []
                        raise RuntimeError(f"{msg}: {'; '.join(map(str, details))}")
                    return payload
            except Exception as exc:
                last_error = exc
                if attempt + 1 < MAX_RETRIES:
                    await asyncio.sleep(0.45 * (2 ** attempt))
        raise RuntimeError(f"GIS request failed after {MAX_RETRIES} attempts: {last_error}")

    async def query_layer(self, layer_url: str, *, where: str = "1=1", geometry: Optional[Dict[str, Any]] = None, geometry_type: Optional[str] = None, out_fields: str = "*", return_geometry: bool = True, result_record_count: int = 2000) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "f": "json",
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "outSR": 4326,
            "resultRecordCount": result_record_count,
        }
        if geometry is not None and geometry_type:
            params.update({
                "geometry": json.dumps(geometry, separators=(",", ":")),
                "geometryType": geometry_type,
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
            })
        return await self._post(layer_url.rstrip("/") + "/query", params)

    async def query_point(self, layer_id: int, lon: float, lat: float, out_fields: str = "*") -> Dict[str, Any]:
        return await self.query_layer(
            f"{CADASTRAL_BASE}/{layer_id}",
            geometry={"x": lon, "y": lat, "spatialReference": {"wkid": 4326}},
            geometry_type="esriGeometryPoint",
            out_fields=out_fields,
        )

    async def query_bbox(self, layer_id: int, bounds: Tuple[float, float, float, float], out_fields: str = "*", buffer_degrees: float = 0.0) -> Dict[str, Any]:
        minx, miny, maxx, maxy = bounds
        env = {
            "xmin": minx - buffer_degrees,
            "ymin": miny - buffer_degrees,
            "xmax": maxx + buffer_degrees,
            "ymax": maxy + buffer_degrees,
            "spatialReference": {"wkid": 4326},
        }
        return await self.query_layer(
            f"{CADASTRAL_BASE}/{layer_id}", geometry=env,
            geometry_type="esriGeometryEnvelope", out_fields=out_fields,
        )


async def geocode_address(address: str) -> Dict[str, Any]:
    params = {"format": "jsonv2", "q": f"{address}, eThekwini, KwaZulu-Natal, South Africa", "limit": 3, "addressdetails": 1}
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(REQUEST_TIMEOUT), follow_redirects=True) as client:
        resp = await client.get(NOMINATIM_URL, params=params)
        resp.raise_for_status()
        results = resp.json()
    if not results:
        raise HTTPException(status_code=404, detail="Address could not be geocoded. Enter coordinates or refine the address.")
    best = None
    for item in results:
        lat, lon = float(item["lat"]), float(item["lon"])
        if -30.25 <= lat <= -29.35 and 30.55 <= lon <= 31.35:
            best = item
            break
    best = best or results[0]
    return {"lat": float(best["lat"]), "lon": float(best["lon"]), "display_name": best.get("display_name"), "importance": best.get("importance"), "source": "OpenStreetMap Nominatim"}


class LocalRoadIndex:
    def __init__(self, path: str):
        self.path = path
        self.geoms: List[Any] = []
        self.props: List[Dict[str, Any]] = []
        self.tree: Optional[STRtree] = None
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        p = Path(self.path)
        if not self.path or not p.exists():
            return
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for feat in data.get("features", []):
            try:
                g = shape(feat.get("geometry"))
                if g is None or g.is_empty:
                    continue
                self.geoms.append(g)
                self.props.append(feat.get("properties") or {})
            except Exception:
                continue
        if self.geoms:
            self.tree = STRtree(self.geoms)

    def query(self, bbox_wgs84: Tuple[float, float, float, float]):
        self.load()
        if not self.tree:
            return []
        envelope = box(*bbox_wgs84)
        raw = self.tree.query(envelope)
        result = []
        for item in list(raw):
            if isinstance(item, int) or type(item).__name__.startswith("int"):
                i = int(item)
                g, props = self.geoms[i], self.props[i]
            else:
                g = item
                try:
                    i = self.geoms.index(g)
                    props = self.props[i]
                except ValueError:
                    props = {}
            if g.intersects(envelope):
                result.append(RoadFeature(to_metric(g), props))
        return result


LOCAL_ROAD_INDEX = LocalRoadIndex(LOCAL_ROADS_GEOJSON) if LOCAL_ROADS_GEOJSON else None


async def _safe_query(coro, warnings: List[str], label: str) -> Dict[str, Any]:
    try:
        return await coro
    except Exception as exc:
        warnings.append(f"{label} unavailable: {exc}")
        return {"features": []}


def _first_feature(payload: Dict[str, Any]):
    features = payload.get("features") or []
    return features[0] if features else None


def _feature_to_shape(feature):
    return esri_geometry_to_shape(feature.get("geometry")) if feature else None


def _road_features_from_payload(payload: Dict[str, Any]):
    out = []
    for feat in payload.get("features") or []:
        g = esri_geometry_to_shape(feat.get("geometry"))
        if g is not None and not g.is_empty:
            out.append(RoadFeature(to_metric(g), feat.get("attributes") or {}))
    return out


def _feature_shapes_metric(payload: Dict[str, Any]):
    out = []
    for feat in payload.get("features") or []:
        g = esri_geometry_to_shape(feat.get("geometry"))
        if g is not None and not g.is_empty:
            out.append((to_metric(g), feat.get("attributes") or {}))
    return out


def _feature_shapes_wgs84(payload: Dict[str, Any]):
    out = []
    for feat in payload.get("features") or []:
        g = esri_geometry_to_shape(feat.get("geometry"))
        if g is not None and not g.is_empty:
            out.append((g, feat.get("attributes") or {}))
    return out


def _dominant_polygon_intersection(site_metric: Polygon, features, category_keys: Sequence[str]) -> Dict[str, Any]:
    rows = []
    total_site = max(site_metric.area, 1e-9)
    for geom, attrs in features:
        try:
            inter = site_metric.intersection(geom)
            area = inter.area
        except Exception:
            continue
        if area <= 0:
            continue
        category = next((attrs.get(k) for k in category_keys if attrs.get(k) not in (None, "")), None)
        rows.append({"category": category, "area_m2": round(float(area), 2), "share_pct": round(float(area / total_site * 100), 2), "attributes": attrs})
    rows.sort(key=lambda r: r["area_m2"], reverse=True)
    return {"dominant": rows[0]["category"] if rows else None, "intersections": rows}


def _building_metrics(site_metric: Polygon, payload: Dict[str, Any]) -> Dict[str, Any]:
    total_area = 0.0
    count = 0
    classes: Dict[str, int] = {}
    years: Dict[str, int] = {}
    features_out = []
    for geom_wgs, attrs in _feature_shapes_wgs84(payload):
        gm = to_metric(geom_wgs)
        if not gm.intersects(site_metric):
            continue
        area = float(gm.intersection(site_metric).area)
        if area <= 0:
            continue
        count += 1
        total_area += area
        cls = str(attrs.get("Class") or "Unknown")
        classes[cls] = classes.get(cls, 0) + 1
        yr = attrs.get("SYear")
        if yr is not None:
            years[str(yr)] = years.get(str(yr), 0) + 1
        features_out.append(shape_to_feature(geom_wgs, attrs))
    return {"count": count, "intersected_footprint_area_m2": round(total_area, 2), "coverage_pct": round(total_area / max(site_metric.area, 1e-9) * 100, 2), "class_distribution": classes, "source_year_distribution": years, "features": features_out}


def _contour_metrics(site_metric: Polygon, contour_features_metric) -> Dict[str, Any]:
    vals = []
    features = []
    for geom, attrs in contour_features_metric:
        if not geom.intersects(site_metric):
            continue
        elev = _numeric(attrs.get("ELEVATION"))
        if elev is not None:
            vals.append(elev)
        features.append(shape_to_feature(to_wgs84(geom), attrs))
    unique = sorted(set(vals))
    diffs = [b-a for a,b in zip(unique[:-1], unique[1:]) if b-a > 0]
    return {
        "intersecting_count": len(features), "elevations_m": unique,
        "min_m": min(vals) if vals else None, "max_m": max(vals) if vals else None,
        "median_m": statistics.median(vals) if vals else None,
        "range_m": (max(vals)-min(vals)) if vals else None,
        "inferred_contour_interval_m": min(diffs) if diffs else None,
        "features": features,
        "note": "Contour-derived screening only; this is not a DEM or surveyed slope model.",
    }


def _find_official_beacons_near_corners(corners_metric, beacon_payload, contour_features_metric):
    official = _feature_shapes_metric(beacon_payload)
    results = []
    for idx, corner in enumerate(corners_metric, 1):
        chosen_geom = corner
        attrs = {}
        source = "parcel_corner"
        official_distance = None
        if official:
            candidate_geom, candidate_attrs = min(official, key=lambda x: corner.distance(x[0]))
            d = corner.distance(candidate_geom)
            if d <= 2.5:
                chosen_geom = candidate_geom if isinstance(candidate_geom, Point) else candidate_geom.centroid
                attrs = candidate_attrs
                source = "municipal_beacon_layer"
                official_distance = float(d)
        height, height_field = _find_numeric_elevation(attrs)
        method = None
        contour_distance = None
        approximate = False
        if height is not None:
            method = f"beacon_attribute:{height_field}"
        else:
            height, method, contour_distance = beacon_height_from_contours(chosen_geom, contour_features_metric)
            approximate = height is not None
        wgs = to_wgs84(chosen_geom)
        results.append({
            "id": f"B{idx}", "lat": round(float(wgs.y), 8), "lon": round(float(wgs.x), 8),
            "height_m": round(float(height), 2) if height is not None else None,
            "height_method": method, "height_is_approximate": approximate,
            "nearest_contour_distance_m": round(float(contour_distance), 2) if contour_distance is not None else None,
            "source": source,
            "official_beacon_match_distance_m": round(official_distance, 2) if official_distance is not None else None,
            "attributes": attrs,
        })
    return results


def _edge_geojson(classes, roles: Dict[int, str]) -> Dict[str, Any]:
    features = []
    for c in classes:
        props = {
            "edge_index": c.index, "role": roles.get(c.index, "side"), "street_frontage": c.frontage,
            "road_name": c.nearest_road_name, "road_type": c.nearest_road_type,
            "road_distance_m": round(c.nearest_road_distance_m, 2) if c.nearest_road_distance_m is not None else None,
            "orientation_difference_deg": round(c.orientation_difference_deg, 1) if c.orientation_difference_deg is not None else None,
            "road_buffer_overlap_ratio": round(c.road_buffer_overlap_ratio, 3), "edge_length_m": round(c.edge.length, 2),
        }
        features.append(shape_to_feature(to_wgs84(c.edge), props))
    return {"type": "FeatureCollection", "features": [f for f in features if f]}


async def analyze_property(payload: AnalysisRequest) -> Dict[str, Any]:
    warnings = []
    sources = []
    client = ArcGISClient()

    if payload.lat is not None and payload.lon is not None:
        lat, lon = float(payload.lat), float(payload.lon)
        location = {"lat": lat, "lon": lon, "display_name": payload.address, "source": "user_coordinates"}
    elif payload.address:
        location = await geocode_address(payload.address)
        lat, lon = location["lat"], location["lon"]
    else:
        raise HTTPException(status_code=400, detail="Provide an address or latitude/longitude.")

    if not (-30.35 <= lat <= -29.2 and 30.35 <= lon <= 31.45):
        warnings.append("Resolved point is outside the broad eThekwini screening envelope.")

    parcel_payload = await _safe_query(client.query_point(LAYER_PARCELS, lon, lat), warnings, "Parcel layer")
    parcel_feature = _first_feature(parcel_payload)
    parcel_wgs = _feature_to_shape(parcel_feature)
    if parcel_wgs is None or parcel_wgs.is_empty:
        raise HTTPException(status_code=404, detail="No approved municipal parcel polygon found at this location.")
    parcel_primary_wgs = max(parcel_wgs.geoms, key=lambda g: g.area) if isinstance(parcel_wgs, MultiPolygon) else parcel_wgs
    parcel_primary_wgs = _repair(parcel_primary_wgs)
    parcel_metric = to_metric(parcel_primary_wgs)
    parcel_bounds = parcel_primary_wgs.bounds
    parcel_attrs = parcel_feature.get("attributes") or {}
    sources.append({"name": "eThekwini Parcels", "url": f"{CADASTRAL_BASE}/{LAYER_PARCELS}", "status": "used"})

    q = await asyncio.gather(
        _safe_query(client.query_point(LAYER_ZONING, lon, lat), warnings, "Zoning layer"),
        _safe_query(client.query_point(LAYER_SUBURBS, lon, lat), warnings, "Suburb layer"),
        _safe_query(client.query_bbox(LAYER_ROADS, parcel_bounds, buffer_degrees=0.0004), warnings, "Road layer"),
        _safe_query(client.query_bbox(LAYER_CONTOURS, parcel_bounds, buffer_degrees=0.00055), warnings, "Contour layer"),
        _safe_query(client.query_bbox(LAYER_BEACONS, parcel_bounds, buffer_degrees=0.00008), warnings, "Beacon layer"),
        _safe_query(client.query_bbox(LAYER_SERVITUDES, parcel_bounds, buffer_degrees=0.00002), warnings, "Servitude layer"),
        _safe_query(client.query_point(LAYER_SDF, lon, lat), warnings, "SDF land-use layer"),
        _safe_query(client.query_layer(
            BUILDING_FOOTPRINTS_URL,
            geometry={"xmin": parcel_bounds[0], "ymin": parcel_bounds[1], "xmax": parcel_bounds[2], "ymax": parcel_bounds[3], "spatialReference": {"wkid": 4326}},
            geometry_type="esriGeometryEnvelope", out_fields="*"
        ), warnings, "Building footprints"),
    )
    zoning_payload, suburb_payload, roads_payload, contours_payload, beacons_payload, serv_payload, sdf_payload, bld_payload = q

    roads_metric = []
    road_source = "eThekwini ArcGIS Roads"
    if LOCAL_ROAD_INDEX is not None:
        try:
            roads_metric = LOCAL_ROAD_INDEX.query(parcel_bounds)
            if roads_metric:
                road_source = f"local road GeoJSON: {Path(LOCAL_ROADS_GEOJSON).name}"
        except Exception as exc:
            warnings.append(f"Local road file could not be used; live municipal roads used instead: {exc}")
    if not roads_metric:
        roads_metric = _road_features_from_payload(roads_payload)
    sources.append({"name": road_source, "url": f"{CADASTRAL_BASE}/{LAYER_ROADS}", "status": "used" if roads_metric else "no features"})

    classes = classify_edges_against_roads(parcel_metric, roads_metric, payload.controls.frontage_threshold_m)
    envelope_metric, edge_roles, frontage_groups, nonfront_groups, rear_group = build_setback_envelope(
        parcel_metric, classes, payload.controls.front_m, payload.controls.side_m, payload.controls.rear_m
    )
    if envelope_metric is None or envelope_metric.is_empty:
        warnings.append("Entered setbacks eliminate the entire buildable envelope.")
    envelope_wgs = to_wgs84(envelope_metric) if envelope_metric is not None and not envelope_metric.is_empty else None

    frontage_summary = []
    for gi, group in enumerate(frontage_groups, 1):
        names, types, distances = [], [], []
        length = 0.0
        for i in group:
            c = classes[i]
            length += c.edge.length
            if c.nearest_road_name: names.append(c.nearest_road_name)
            if c.nearest_road_type: types.append(c.nearest_road_type)
            if c.nearest_road_distance_m is not None: distances.append(c.nearest_road_distance_m)
        frontage_summary.append({
            "frontage_id": gi, "edge_indices": list(group), "length_m": round(length, 2),
            "road_names": sorted(set(names)), "road_types": sorted(set(types)),
            "nearest_road_distance_m": round(min(distances), 2) if distances else None,
        })

    zoning_feature = _first_feature(zoning_payload)
    zoning_attrs = zoning_feature.get("attributes") if zoning_feature else None
    zoning_wgs = _feature_to_shape(zoning_feature)
    sdf_summary = _dominant_polygon_intersection(parcel_metric, _feature_shapes_metric(sdf_payload), ["SDF_LU2021", "SDF_LU2020", "SDF_LU2019", "LANDUSE", "ZONE"])

    servitudes = []
    for gm, attrs in _feature_shapes_metric(serv_payload):
        if not gm.intersects(parcel_metric):
            continue
        inter = gm.intersection(parcel_metric)
        servitudes.append({
            "attributes": attrs,
            "intersection_area_m2": round(inter.area, 2) if hasattr(inter, "area") else None,
            "intersection_length_m": round(inter.length, 2),
            "feature": shape_to_feature(to_wgs84(gm), attrs),
        })

    contour_features_metric = _feature_shapes_metric(contours_payload)
    contour_metrics = _contour_metrics(parcel_metric, contour_features_metric)
    corners_metric = significant_corners(parcel_metric)
    beacons = _find_official_beacons_near_corners(corners_metric, beacons_payload, contour_features_metric)
    building_metrics = _building_metrics(parcel_metric, bld_payload)

    suburb_feature = _first_feature(suburb_payload)
    suburb_attrs = suburb_feature.get("attributes") if suburb_feature else None
    suburb_name = None
    if suburb_attrs:
        for key in ("SUBURB", "Suburb", "NAME", "Name"):
            if suburb_attrs.get(key):
                suburb_name = str(suburb_attrs[key]).strip(); break
    suburb_overview = None
    if suburb_name:
        safe = suburb_name.replace("'", "''")
        try:
            ov = await client.query_layer(SUBURB_OVERVIEW_URL, where=f"UPPER(Suburb)=UPPER('{safe}')", out_fields="*", return_geometry=False, result_record_count=10)
            if ov.get("features"):
                suburb_overview = ov["features"][0].get("attributes") or {}
        except Exception as exc:
            warnings.append(f"Suburb overview table unavailable: {exc}")

    parcel_area = float(parcel_metric.area)
    envelope_area = float(envelope_metric.area) if envelope_metric is not None and not envelope_metric.is_empty else 0.0
    centroid = parcel_primary_wgs.centroid
    sources.extend([
        {"name": "eThekwini Zoning", "url": f"{CADASTRAL_BASE}/{LAYER_ZONING}", "status": "used" if zoning_feature else "no feature"},
        {"name": "eThekwini Contours 2m", "url": f"{CADASTRAL_BASE}/{LAYER_CONTOURS}", "status": "used"},
        {"name": "eThekwini Beacons", "url": f"{CADASTRAL_BASE}/{LAYER_BEACONS}", "status": "used"},
        {"name": "eThekwini Servitudes", "url": f"{CADASTRAL_BASE}/{LAYER_SERVITUDES}", "status": "used"},
        {"name": "eThekwini SDF Landuse", "url": f"{CADASTRAL_BASE}/{LAYER_SDF}", "status": "used"},
        {"name": "Building Footprints", "url": BUILDING_FOOTPRINTS_URL, "status": "used"},
        {"name": "Suburb Overview", "url": SUBURB_OVERVIEW_URL, "status": "used" if suburb_overview else "not joined"},
    ])

    return {
        "success": True, "analysis_id": str(uuid.uuid4()), "app_version": APP_VERSION,
        "generated_at": utcnow_iso(), "input": payload.model_dump(),
        "location": {**location, "parcel_centroid": {"lat": round(centroid.y, 8), "lon": round(centroid.x, 8)}},
        "parcel": {"attributes": parcel_attrs, "area_m2": round(parcel_area, 2), "perimeter_m": round(parcel_metric.length, 2), "geometry": shape_to_feature(parcel_primary_wgs, parcel_attrs)},
        "zoning": {"attributes": zoning_attrs, "geometry": shape_to_feature(zoning_wgs, zoning_attrs or {}) if zoning_wgs is not None else None, "note": "Municipal GIS screening data; verify legal rights against the applicable scheme/zoning certificate."},
        "frontages": {"count": len(frontage_groups), "groups": frontage_summary, "edge_roles": {str(k): v for k, v in edge_roles.items()}, "rear_edge_group": rear_group, "frontage_threshold_m": payload.controls.frontage_threshold_m, "edge_features": _edge_geojson(classes, edge_roles), "road_source": road_source},
        "setbacks": {"front_m": payload.controls.front_m, "side_m": payload.controls.side_m, "rear_m": payload.controls.rear_m, "basis": "measured inward from cadastral site boundary by classified boundary segment", "legal_status": "user analysis controls; not automatically asserted as scheme-prescribed setbacks"},
        "buildable_envelope": {"area_m2": round(envelope_area, 2), "parcel_area_remaining_pct": round(envelope_area / max(parcel_area, 1e-9) * 100, 2), "building_height_m": payload.controls.building_height_m, "estimated_max_extruded_volume_m3": round(envelope_area * payload.controls.building_height_m, 2), "geometry": shape_to_feature(envelope_wgs, {"height_m": payload.controls.building_height_m}) if envelope_wgs is not None else None},
        "beacons": {"count": len(beacons), "items": beacons, "height_note": "Where a surveyed beacon elevation attribute is unavailable, displayed heights are approximate nearest-2m-contour ground levels, not surveyed beacon RLs."},
        "contours": contour_metrics,
        "servitudes": {"intersects": bool(servitudes), "count": len(servitudes), "items": servitudes},
        "sdf_landuse": sdf_summary,
        "building_footprints": building_metrics,
        "suburb": {"name": suburb_name, "spatial_attributes": suburb_attrs, "overview": suburb_overview},
        "warnings": warnings, "sources": sources, "disclaimer": DISCLAIMER,
    }


def _pdf_value(v: Any, max_len: int = 240) -> str:
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False, default=str)
    else:
        s = "" if v is None else str(v)
    return s if len(s) <= max_len else s[:max_len-3] + "..."


def generate_pdf(report: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm, title="eThekwini Property Development Intelligence Report")
    story = [Paragraph("eThekwini Property Development Intelligence", styles["Title"]), Paragraph(f"Generated: {_pdf_value(report.get('generated_at'))}", styles["Normal"]), Spacer(1, 6*mm)]
    location, parcel = report.get("location", {}), report.get("parcel", {})
    zoning = report.get("zoning", {}).get("attributes") or {}
    frontages, envelope, beacons = report.get("frontages", {}), report.get("buildable_envelope", {}), report.get("beacons", {})
    rows = [
        ["Address", _pdf_value(location.get("display_name") or report.get("input", {}).get("address"))],
        ["Coordinates", f"{location.get('lat')}, {location.get('lon')}"],
        ["Parcel area", f"{parcel.get('area_m2')} m²"],
        ["Zoning", _pdf_value(zoning.get("ZONING") or zoning.get("Zoning"))],
        ["Scheme", _pdf_value(zoning.get("SCHEMENAME"))],
        ["Street frontages", _pdf_value(frontages.get("count"))],
        ["Buildable envelope", f"{envelope.get('area_m2')} m²"],
        ["Envelope / parcel", f"{envelope.get('parcel_area_remaining_pct')}%"],
        ["Analysis height", f"{envelope.get('building_height_m')} m"],
        ["Corner beacons", _pdf_value(beacons.get("count"))],
    ]
    t = Table(rows, colWidths=[45*mm, 120*mm])
    t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.3,colors.grey),("BACKGROUND",(0,0),(0,-1),colors.HexColor("#eef2f7")),("VALIGN",(0,0),(-1,-1),"TOP"),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8.5)]))
    story += [t, Spacer(1,5*mm), Paragraph("Setbacks & street-frontage logic", styles["Heading2"])]
    s = report.get("setbacks", {})
    story.append(Paragraph(f"Street: {s.get('front_m')} m; Side: {s.get('side_m')} m; Rear: {s.get('rear_m')} m. {_pdf_value(s.get('basis'))}.", styles["Normal"]))
    for g in frontages.get("groups", []):
        story.append(Paragraph(f"Frontage {g.get('frontage_id')}: {g.get('length_m')} m — {', '.join(g.get('road_names') or []) or 'unnamed road'}", styles["Normal"]))
    story += [Spacer(1,3*mm), Paragraph("Corner beacons / ground-height screening", styles["Heading2"])]
    br = [["Beacon","Lat","Lon","Height m","Method"]]
    for b in beacons.get("items", []):
        h = ("~" if b.get("height_is_approximate") and b.get("height_m") is not None else "") + _pdf_value(b.get("height_m"))
        br.append([b.get("id"), b.get("lat"), b.get("lon"), h, _pdf_value(b.get("height_method"),60)])
    bt = Table(br, colWidths=[18*mm,30*mm,30*mm,24*mm,63*mm])
    bt.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.3,colors.grey),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eef2f7")),("FONTSIZE",(0,0),(-1,-1),7.5),("VALIGN",(0,0),(-1,-1),"TOP")]))
    story += [bt, Spacer(1,4*mm), Paragraph("Constraints & screening", styles["Heading2"])]
    cr = [
        ["Servitudes intersect", _pdf_value(report.get("servitudes", {}).get("intersects"))],
        ["Servitude features", _pdf_value(report.get("servitudes", {}).get("count"))],
        ["Building coverage", f"{report.get('building_footprints', {}).get('coverage_pct')}%"],
        ["Contour min/max", f"{report.get('contours', {}).get('min_m')} / {report.get('contours', {}).get('max_m')} m"],
        ["SDF dominant", _pdf_value(report.get("sdf_landuse", {}).get("dominant"))],
    ]
    ct = Table(cr, colWidths=[55*mm,110*mm])
    ct.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.3,colors.grey),("BACKGROUND",(0,0),(0,-1),colors.HexColor("#eef2f7")),("FONTSIZE",(0,0),(-1,-1),8)]))
    story += [ct, Spacer(1,5*mm)]
    if report.get("warnings"):
        story.append(Paragraph("Warnings", styles["Heading2"]))
        for w in report["warnings"]:
            story.append(Paragraph(f"• {_pdf_value(w)}", styles["Normal"]))
    story += [Spacer(1,3*mm), Paragraph("Planning / legal qualification", styles["Heading2"]), Paragraph(_pdf_value(report.get("disclaimer"),1000), styles["Normal"])]
    doc.build(story)
    return buf.getvalue()


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET","POST"], allow_headers=["*"])
_RATE: Dict[str, List[float]] = {}

@app.middleware("http")
async def rate_guard(request: Request, call_next):
    if request.url.path.startswith("/api/analyze"):
        ip = request.client.host if request.client else "unknown"
        now = time.time(); hits = [t for t in _RATE.get(ip, []) if now-t < 60]
        if len(hits) >= 30:
            return JSONResponse(status_code=429, content={"detail":"Too many analyses; retry in a minute."})
        hits.append(now); _RATE[ip] = hits
    return await call_next(request)

@app.get("/api/health")
async def health():
    return {"ok":True,"app":APP_NAME,"version":APP_VERSION,"zoning_layer_id":LAYER_ZONING,"road_source":"local GeoJSON override" if LOCAL_ROADS_GEOJSON else "eThekwini ArcGIS Roads layer 3"}

@app.post("/api/analyze")
async def analyze_endpoint(payload: AnalysisRequest):
    try:
        return await analyze_property(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc

@app.post("/api/report/pdf")
async def report_pdf(payload: PdfRequest):
    pdf = generate_pdf(payload.report)
    filename = f"ethekwini-site-report-{payload.report.get('analysis_id','analysis')}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf", headers={"Content-Disposition":f'attachment; filename="{filename}"'})

UI_HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>eThekwini Property Development Intelligence</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script src="https://unpkg.com/three@0.160.0/build/three.min.js"></script><style>
:root{--ink:#17202a;--muted:#64748b;--line:#d9e2ea;--paper:#f7f9fb;--card:#fff;--accent:#106b63;--accent2:#1c3f60}*{box-sizing:border-box}body{margin:0;font:14px/1.45 Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:var(--paper);color:var(--ink)}header{padding:26px 34px 20px;background:#fff;border-bottom:1px solid var(--line)}header h1{margin:0;font-size:26px;letter-spacing:-.03em}header p{margin:4px 0 0;color:var(--muted)}main{max-width:1480px;margin:auto;padding:22px}.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 8px 28px rgba(28,45,58,.05)}.search{display:grid;grid-template-columns:minmax(280px,1.8fr) repeat(2,minmax(100px,.45fr)) auto;gap:10px}.controls{display:grid;grid-template-columns:repeat(5,minmax(100px,1fr));gap:10px;margin-top:10px}label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}input{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:9px;background:white;color:var(--ink);font:inherit;margin-top:5px}button{border:0;border-radius:9px;padding:11px 18px;font-weight:750;cursor:pointer}.primary{background:var(--accent);color:#fff;align-self:end}.secondary{background:#e7eef3;color:var(--accent2)}button:disabled{opacity:.55;cursor:not-allowed}.layout{display:grid;grid-template-columns:1.15fr .85fr;gap:16px;margin-top:16px}.mapwrap,.threewrap{height:520px;overflow:hidden;border-radius:11px;background:#e8eef2}.mapwrap #map,.threewrap #three{width:100%;height:100%}.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:16px}.metric{padding:14px;background:#fff;border:1px solid var(--line);border-radius:11px}.metric b{font-size:20px;display:block}.metric span{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}.sections{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}.section h3{margin:0 0 10px}.kv{display:grid;grid-template-columns:145px 1fr;gap:6px 10px}.kv div:nth-child(odd){color:var(--muted)}.badge{display:inline-block;padding:3px 7px;border-radius:999px;background:#e5f3f0;color:#0a5b53;font-size:11px;font-weight:700;margin:2px}.warn{background:#fff7e8;border:1px solid #ecd19d;color:#6d4d10;padding:10px;border-radius:8px;margin:6px 0}#beacons table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:7px;border-bottom:1px solid var(--line);font-size:12px}th{color:var(--muted)}.toolbar{display:flex;gap:8px;margin-top:12px}.small{font-size:12px;color:var(--muted)}@media(max-width:980px){.search{grid-template-columns:1fr 1fr}.search .address{grid-column:1/-1}.controls{grid-template-columns:repeat(2,1fr)}.layout,.sections{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}}
</style></head><body><header><h1>eThekwini Property Development Intelligence</h1><p>Municipal parcel, zoning, road-frontage setbacks, corner beacons, contour heights, servitudes and development envelope.</p></header><main><div class="panel"><div class="search"><label class="address">Site address<input id="address" value="716 Musgrave Road, Durban" placeholder="Street address, Durban"/></label><label>Latitude<input id="lat" type="number" step="any" placeholder="optional"/></label><label>Longitude<input id="lon" type="number" step="any" placeholder="optional"/></label><button id="analyze" class="primary">Analyze site</button></div><div class="controls"><label>Street setback m<input id="front" type="number" min="0" step="0.5" value="5"/></label><label>Side setback m<input id="side" type="number" min="0" step="0.5" value="2"/></label><label>Rear setback m<input id="rear" type="number" min="0" step="0.5" value="2"/></label><label>Envelope height m<input id="height" type="number" min="1" step="0.5" value="18"/></label><label>Road frontage threshold m<input id="threshold" type="number" min="3" step="1" value="18"/></label></div><div class="toolbar"><button id="pdf" class="secondary" disabled>Download PDF</button><span class="small" id="status">Ready.</span></div></div><div class="cards" id="cards"></div><div class="layout"><div class="panel"><h3>2D municipal site diagram</h3><div class="mapwrap"><div id="map"></div></div><p class="small">Boundary edge colour: green = street frontage, blue = side, orange = rear. Setbacks are generated inward from the cadastral site boundary.</p></div><div class="panel"><h3>3D buildable envelope</h3><div class="threewrap"><div id="three"></div></div><p class="small">Screening mass only; rotate by dragging and zoom with the wheel.</p></div></div><div class="sections"><div class="panel section"><h3>Planning + frontage</h3><div id="planning"></div></div><div class="panel section" id="beacons"><h3>Corner beacons + heights</h3><div id="beaconTable"></div></div><div class="panel section"><h3>Constraints + context</h3><div id="constraints"></div></div><div class="panel section"><h3>Warnings / source qualification</h3><div id="warnings"></div></div></div></main><script>
const map=L.map('map').setView([-29.8587,31.0218],12);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:20,attribution:'© OpenStreetMap'}).addTo(map);let overlay=[],report=null,scene,camera,renderer,mass,drag=false,last={x:0,y:0},yaw=.7,pitch=.65,dist=120;function esc(v){return String(v??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]))}function clearMap(){overlay.forEach(x=>map.removeLayer(x));overlay=[]}function addGeo(data,style){if(!data)return null;const l=L.geoJSON(data,{style});l.addTo(map);overlay.push(l);return l}function init3(){scene=new THREE.Scene();scene.background=new THREE.Color(0xf1f5f8);const d=document.getElementById('three');camera=new THREE.PerspectiveCamera(48,d.clientWidth/d.clientHeight,.1,2000);renderer=new THREE.WebGLRenderer({antialias:true});renderer.setSize(d.clientWidth,d.clientHeight);renderer.setPixelRatio(Math.min(devicePixelRatio,2));d.appendChild(renderer.domElement);scene.add(new THREE.HemisphereLight(0xffffff,0x668099,1.8));const dl=new THREE.DirectionalLight(0xffffff,2);dl.position.set(50,-40,100);scene.add(dl);const grid=new THREE.GridHelper(240,24,0xa7b8c4,0xd9e1e7);grid.rotation.x=Math.PI/2;scene.add(grid);renderer.domElement.onmousedown=e=>{drag=true;last={x:e.clientX,y:e.clientY}};window.onmouseup=()=>drag=false;window.onmousemove=e=>{if(!drag)return;yaw+=(e.clientX-last.x)*.006;pitch=Math.max(.15,Math.min(1.35,pitch+(e.clientY-last.y)*.006));last={x:e.clientX,y:e.clientY};cam()};renderer.domElement.onwheel=e=>{dist=Math.max(25,Math.min(600,dist*(e.deltaY>0?1.08:.92)));cam()};window.addEventListener('resize',()=>{const w=d.clientWidth,h=d.clientHeight;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h)});cam();(function loop(){requestAnimationFrame(loop);renderer.render(scene,camera)})()}function cam(){camera.position.set(dist*Math.cos(yaw)*Math.cos(pitch),dist*Math.sin(yaw)*Math.cos(pitch),dist*Math.sin(pitch));camera.lookAt(0,0,0)}function clearMass(){if(mass){scene.remove(mass);mass.geometry.dispose();mass.material.dispose();mass=null}}function largestRing(geom){if(!geom)return null;if(geom.type==='Polygon')return geom.coordinates[0];if(geom.type==='MultiPolygon'){let best=null;geom.coordinates.forEach(p=>{if(!best||p[0].length>best.length)best=p[0]});return best}return null}function buildMass(feature,h){clearMass();if(!feature?.geometry)return;let ring=largestRing(feature.geometry);if(!ring||ring.length<4)return;let lon0=0,lat0=0;ring.forEach(p=>{lon0+=p[0];lat0+=p[1]});lon0/=ring.length;lat0/=ring.length;const R=6378137,pts=ring.map(p=>new THREE.Vector2(R*(p[0]-lon0)*Math.PI/180*Math.cos(lat0*Math.PI/180),R*(p[1]-lat0)*Math.PI/180));if(pts[0].distanceTo(pts[pts.length-1])<.01)pts.pop();const sh=new THREE.Shape(pts),g=new THREE.ExtrudeGeometry(sh,{depth:h,bevelEnabled:false});g.computeBoundingBox();const bb=g.boundingBox,cx=(bb.min.x+bb.max.x)/2,cy=(bb.min.y+bb.max.y)/2;mass=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:0xdde6e9,roughness:.82,metalness:.05}));mass.position.set(-cx,-cy,-bb.min.z);scene.add(mass);dist=Math.max(45,Math.max(bb.max.x-bb.min.x,bb.max.y-bb.min.y,h)*1.7);cam()}init3();function kv(rows){return '<div class="kv">'+rows.map(r=>`<div>${esc(r[0])}</div><div>${esc(r[1])}</div>`).join('')+'</div>'}function fmt(v,d=1){return v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:d})}function render(r){report=r;document.getElementById('pdf').disabled=false;const z=r.zoning?.attributes||{},roads=r.frontages?.groups||[];document.getElementById('cards').innerHTML=[['Parcel area',fmt(r.parcel.area_m2,0)+' m²'],['Zoning',z.ZONING||'—'],['Street frontages',r.frontages.count],['Buildable envelope',fmt(r.buildable_envelope.area_m2,0)+' m²'],['Existing coverage',fmt(r.building_footprints.coverage_pct,1)+'%'],['Contour range',r.contours.range_m==null?'—':fmt(r.contours.range_m,1)+' m']].map(x=>`<div class="metric"><span>${esc(x[0])}</span><b>${esc(x[1])}</b></div>`).join('');const roadBadges=roads.length?roads.map(g=>`<div><span class="badge">Frontage ${g.frontage_id}</span> ${esc((g.road_names||[]).join(', ')||'unnamed road')} — ${fmt(g.length_m,1)} m</div>`).join(''):'<div class="warn">No road-facing cadastral edge was confidently detected at the current threshold.</div>';document.getElementById('planning').innerHTML=kv([['Scheme',z.SCHEMENAME||'—'],['Zoning',z.ZONING||'—'],['Region',z.REGION||'—'],['Setbacks',`${r.setbacks.front_m} / ${r.setbacks.side_m} / ${r.setbacks.rear_m} m (street / side / rear)`],['Envelope retained',fmt(r.buildable_envelope.parcel_area_remaining_pct,1)+'%']])+`<div style="margin-top:12px">${roadBadges}</div>`;const b=r.beacons.items||[];document.getElementById('beaconTable').innerHTML=`<table><thead><tr><th>ID</th><th>Lat</th><th>Lon</th><th>Height</th><th>Basis</th></tr></thead><tbody>${b.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.lat)}</td><td>${esc(x.lon)}</td><td>${x.height_m==null?'—':(x.height_is_approximate?'~':'')+esc(x.height_m)+' m'}</td><td>${esc(x.height_method||x.source)}</td></tr>`).join('')}</tbody></table><p class="small">${esc(r.beacons.height_note)}</p>`;document.getElementById('constraints').innerHTML=kv([['Servitudes',r.servitudes.intersects?`${r.servitudes.count} intersecting feature(s)`:'No mapped intersection'],['SDF dominant',r.sdf_landuse.dominant||'—'],['Buildings',r.building_footprints.count],['Contour min / max',`${fmt(r.contours.min_m,1)} / ${fmt(r.contours.max_m,1)} m`],['Suburb',r.suburb.name||'—']]);document.getElementById('warnings').innerHTML=[...(r.warnings||[]),r.disclaimer].map(x=>`<div class="warn">${esc(x)}</div>`).join('');clearMap();addGeo(r.parcel.geometry,{color:'#17202a',weight:3,fillOpacity:.02});if(r.zoning.geometry)addGeo(r.zoning.geometry,{color:'#8156a3',weight:1,fillOpacity:.04});addGeo(r.frontages.edge_features,f=>({color:f.properties.role==='street'?'#16836f':f.properties.role==='rear'?'#c77a20':'#32688d',weight:5}));if(r.buildable_envelope.geometry)addGeo(r.buildable_envelope.geometry,{color:'#111',dashArray:'5 5',weight:2,fillColor:'#6aa69c',fillOpacity:.18});(r.beacons.items||[]).forEach(b=>{const label=`${b.id}${b.height_m==null?'':` ${b.height_is_approximate?'~':''}${b.height_m}m`}`,m=L.circleMarker([b.lat,b.lon],{radius:5,color:'#b34f34',weight:2,fillColor:'#fff',fillOpacity:1}).bindTooltip(label,{permanent:true,direction:'top'}).addTo(map);overlay.push(m)});if(overlay.length){const group=L.featureGroup(overlay);map.fitBounds(group.getBounds().pad(.15))}buildMass(r.buildable_envelope.geometry,r.buildable_envelope.building_height_m)}async function analyze(){const btn=document.getElementById('analyze'),status=document.getElementById('status');btn.disabled=true;status.textContent='Querying municipal GIS and generating site intelligence…';try{const body={address:document.getElementById('address').value.trim()||null,lat:document.getElementById('lat').value?Number(document.getElementById('lat').value):null,lon:document.getElementById('lon').value?Number(document.getElementById('lon').value):null,controls:{front_m:Number(document.getElementById('front').value),side_m:Number(document.getElementById('side').value),rear_m:Number(document.getElementById('rear').value),building_height_m:Number(document.getElementById('height').value),frontage_threshold_m:Number(document.getElementById('threshold').value)}};const res=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),data=await res.json();if(!res.ok)throw new Error(data.detail||'Analysis failed');render(data);status.textContent='Analysis complete.'}catch(e){status.textContent='Failed: '+e.message;document.getElementById('warnings').innerHTML=`<div class="warn">${esc(e.message)}</div>`}finally{btn.disabled=false}}document.getElementById('analyze').onclick=analyze;document.getElementById('pdf').onclick=async()=>{if(!report)return;const res=await fetch('/api/report/pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({report})});if(!res.ok)return;const blob=await res.blob(),u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download='ethekwini-property-report.pdf';a.click();URL.revokeObjectURL(u)};</script></body></html>'''

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(UI_HTML)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("property_system:app", host="0.0.0.0", port=int(os.getenv("PORT", "5000")), reload=False)
