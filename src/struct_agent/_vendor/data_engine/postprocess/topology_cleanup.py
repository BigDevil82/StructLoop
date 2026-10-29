"""Numerical endpoint snapping and wall/beam typing, native XY in mm."""
from __future__ import annotations

from collections import Counter
import math
from typing import Any

from shapely.geometry import LineString


def clean_segments(segments: list[dict[str, Any]], *, snap_tolerance: float,
                   min_wall_length: float) -> list[dict[str, Any]]:
    """Collapse only numerical gaps within snap tolerance; retain boundary links.

    Preserve the predicted structural role, including unresolved short walls.
    Unpredicted gaps remain beams. A snap cluster stays within tolerance of its fixed anchor;
    chained nearby points cannot accumulate an arbitrarily large displacement.
    """
    if not 0 < snap_tolerance < min_wall_length:
        raise ValueError('Require 0 < snap tolerance < minimum wall length')
    usable = [s for s in segments if s['geometry'].length > 1e-8]
    endpoints = [tuple(p) for s in usable for p in (s['geometry'].coords[0], s['geometry'].coords[-1])]
    counts = Counter(endpoints)
    anchors: list[tuple[float, float]] = []
    mapping = {}
    for point in sorted(counts, key=lambda p: (-counts[p], p)):
        if not all(math.isfinite(v) for v in point):
            raise ValueError('Nonfinite topology endpoint')
        close = [(math.dist(point, anchor), anchor) for anchor in anchors
                 if math.dist(point, anchor) <= snap_tolerance]
        anchor = min(close)[1] if close else point
        if not close:
            anchors.append(anchor)
        mapping[point] = anchor
    result = []
    seen: dict[tuple, int] = {}
    for segment in usable:
        coords = segment['geometry'].coords
        a, b = mapping[tuple(coords[0])], mapping[tuple(coords[-1])]
        # Topology uses whole-mm nodes, so determine type/length after rounding.
        a, b = tuple(round(v) for v in a), tuple(round(v) for v in b)
        if a == b:
            continue
        line = LineString([a, b])
        kind = segment['type']
        key = tuple(sorted((a, b)))
        row = {'geometry': line, 'type': kind, 'length': line.length}
        if key in seen:
            if kind == 'shearwall':
                result[seen[key]] = row
        else:
            seen[key] = len(result)
            result.append(row)
    return result
