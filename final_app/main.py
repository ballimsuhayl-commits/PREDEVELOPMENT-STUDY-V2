"""Production runtime overlay for property_system.

This module keeps the single-file core intact while hardening road-frontage grouping:
adjacent cadastral edges that meet at a real parcel corner are separate street frontages
when their direction changes materially or they reference different roads. Curved/segmented
edges on the same side remain grouped.
"""
from __future__ import annotations

import os
from typing import List, Sequence

import property_system as core
from property_system import *  # re-export the full public runtime surface


def _norm_road_name(value):
    return " ".join(str(value or "").upper().split())


def _same_frontage_side(a: core.EdgeClassification, b: core.EdgeClassification, max_turn_deg: float = 35.0) -> bool:
    if not a.frontage or not b.frontage:
        return False
    # A parcel corner is a new frontage side even when the same road name appears on
    # both edges (e.g. curved/roundabout metadata duplicated across a corner).
    turn = core._angle_difference(core._angle_deg(a.edge), core._angle_deg(b.edge))
    if turn > max_turn_deg:
        return False
    an, bn = _norm_road_name(a.nearest_road_name), _norm_road_name(b.nearest_road_name)
    if an and bn and an != bn:
        return False
    return True


def frontage_side_groups(classes: Sequence[core.EdgeClassification], max_turn_deg: float = 35.0) -> List[List[int]]:
    """Group road-facing boundary segments into physical street-frontage sides.

    Unlike plain cyclic contiguity, this splits at a meaningful parcel-corner turn or a
    road-name change. That is required for true 1/2/3+ frontage accounting on corner and
    island-like sites.
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

    # Closed parcel ring: merge the end and start only when they are genuinely the same
    # physical frontage side. At a 90-degree corner they remain separate.
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
    # Non-frontage runs still use ordinary closed-ring contiguity; they are subsequently
    # classified as side/rear by their relation to the primary frontage.
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
APP_VERSION = core.APP_VERSION + "+frontage-sides.1"
core.APP_VERSION = APP_VERSION


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "5000")), reload=False)
