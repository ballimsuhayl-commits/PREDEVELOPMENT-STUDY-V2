"""Production runtime overlay for property_system.

Hardens two production concerns without deleting the mature single-file core:
1) road-facing cadastral segments are grouped into physical 1/2/3+ street-frontage sides;
2) eThekwini's municipal GIS host currently presents a TLS chain that some clean Linux
   runners cannot validate. Requests to that host alone can use the explicit
   ETHEKWINI_TLS_VERIFY switch (default false); all other HTTPS sources remain verified.
"""
from __future__ import annotations

import asyncio
import os
from typing import List, Sequence

import httpx
import property_system as core
from property_system import *  # re-export the public runtime surface

# Explicitly re-export selected internal geometry helpers used by the regression suite.
_merge_small_boolean_gaps = core._merge_small_boolean_gaps
_angle_deg = core._angle_deg
_angle_difference = core._angle_difference


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


ETHEKWINI_TLS_VERIFY = _env_bool("ETHEKWINI_TLS_VERIFY", False)


async def _municipal_aware_post(self, url, data):
    """POST with retries and host-scoped TLS policy.

    Certificate verification is disabled only for gis.durban.gov.za when the environment
    switch is false. This is an operational compatibility measure for the municipality's
    incomplete/unsupported certificate chain on some clients; other hosts stay verified.
    """
    last_error = None
    municipal = "gis.durban.gov.za" in url.lower()
    verify = ETHEKWINI_TLS_VERIFY if municipal else True
    for attempt in range(core.MAX_RETRIES):
        try:
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(core.REQUEST_TIMEOUT),
                follow_redirects=True,
                verify=verify,
            ) as client:
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
            if attempt + 1 < core.MAX_RETRIES:
                await asyncio.sleep(0.45 * (2 ** attempt))
    raise RuntimeError(f"GIS request failed after {core.MAX_RETRIES} attempts: {last_error}")


core.ArcGISClient._post = _municipal_aware_post


def _norm_road_name(value):
    return " ".join(str(value or "").upper().split())


def _same_frontage_side(a: core.EdgeClassification, b: core.EdgeClassification, max_turn_deg: float = 35.0) -> bool:
    if not a.frontage or not b.frontage:
        return False
    # A parcel corner is a new frontage side even when the same road name appears on
    # both edges (e.g. roundabout metadata duplicated across a cadastral corner).
    turn = core._angle_difference(core._angle_deg(a.edge), core._angle_deg(b.edge))
    if turn > max_turn_deg:
        return False
    an, bn = _norm_road_name(a.nearest_road_name), _norm_road_name(b.nearest_road_name)
    if an and bn and an != bn:
        return False
    return True


def frontage_side_groups(classes: Sequence[core.EdgeClassification], max_turn_deg: float = 35.0) -> List[List[int]]:
    """Group road-facing boundary segments into physical street-frontage sides.

    Plain cyclic contiguity is insufficient: two road-facing edges meeting at a corner are
    two frontages. Segmented/curved portions of one side remain grouped when their turn is
    modest and their road identity is compatible.
    """
    n = len(classes)
    if not n:
        return []
    frontage_indices = [i for i, c in enumerate(classes) if c.frontage]
    if not frontage_indices:
        return []
    groups: List[List[int]] = []
    current = [frontage_indices[0]]
    for prev, cur in zip(frontage_indices[:-1], frontage_indices[1:]):
        if cur == prev + 1 and _same_frontage_side(classes[prev], classes[cur], max_turn_deg):
            current.append(cur)
        else:
            groups.append(current)
            current = [cur]
    groups.append(current)
    if (
        len(groups) > 1
        and groups[0][0] == 0
        and groups[-1][-1] == n - 1
        and _same_frontage_side(classes[n - 1], classes[0], max_turn_deg)
    ):
        groups[0] = groups[-1] + groups[0]
        groups.pop()
    return groups


def smart_contiguous_groups(classes: Sequence[core.EdgeClassification], value: bool) -> List[List[int]]:
    if value:
        return frontage_side_groups(classes)
    idxs = [i for i, c in enumerate(classes) if c.frontage is False]
    if not idxs:
        return []
    groups: List[List[int]] = []
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


# Patch the core module global used by build_setback_envelope/analyze_property.
core.contiguous_groups = smart_contiguous_groups
contiguous_groups = smart_contiguous_groups
app = core.app
APP_VERSION = core.APP_VERSION + "+frontage-sides.3"
core.APP_VERSION = APP_VERSION


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "5000")), reload=False)
