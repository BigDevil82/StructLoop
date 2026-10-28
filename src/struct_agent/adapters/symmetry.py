"""Minimal room-based union symmetry from upstream symmetry_postprocess.py.

Native coordinates are float64 XY in mm. Retains upstream 200 mm buffer
width and projection to buildable room edges; no training or geometric search.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence

from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


def detect_axis(dxf: Path, *, threshold: float = 0.85) -> tuple[float, float]:
    """Return native mm axis and room-union IoU; reject absent/asymmetric rooms."""
    from struct_agent._vendor.data_engine.preprocess.dxf_extractor import DXFExtractor
    if not 0. <= threshold <= 1.:
        raise ValueError("Symmetry threshold must be in [0,1]")
    extractor = DXFExtractor()
    extractor.extract_from_file(str(dxf))
    rooms = [Polygon([(p.x, p.y) for p in r.polygon]).buffer(0) for r in extractor.rooms if len(r.polygon) >= 3]
    reference = unary_union(rooms).buffer(0)
    if reference.is_empty:
        raise ValueError("Prepared DXF requires room polygons for symmetry detection")
    axis = (reference.bounds[0] + reference.bounds[2]) / 2.
    mirror = affinity.scale(reference, xfact=-1., yfact=1., origin=(axis, 0.))
    area = reference.union(mirror).area
    confidence = float((reference.intersection(mirror).area + 1e-6) / (area + 1e-6)) if area > 1e-6 else 0.
    if confidence < threshold:
        raise ValueError(f"Room symmetry IoU {confidence:.6f} below threshold {threshold}")
    return axis, confidence


def _buffer(lines: Sequence[LineString]) -> BaseGeometry:
    areas = [line.buffer(100., cap_style=2, join_style=2).buffer(0) for line in lines
             if not line.is_empty and line.length > 0]
    return unary_union(areas).buffer(0) if areas else GeometryCollection()


def _lines(geometry: BaseGeometry, min_length: float) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length >= min_length else []
    return [line for child in getattr(geometry, "geoms", ()) for line in _lines(child, min_length)]


def union_walls(raw: Sequence[LineString], boundaries: Sequence[LineString], *, axis_mm: float,
                min_length_mm: float = 100.) -> list[LineString]:
    """Upstream buffered union followed by clipping/projection, in native mm."""
    import math
    if not math.isfinite(axis_mm) or not math.isfinite(min_length_mm) or min_length_mm <= 0:
        raise ValueError("Finite axis and positive minimum wall length required")
    area, buildable = _buffer(raw), _buffer(boundaries)
    if area.is_empty or buildable.is_empty:
        return list(raw)
    mirror = affinity.scale(area, xfact=-1., yfact=1., origin=(axis_mm, 0.))
    clipped = area.union(mirror).intersection(buildable).buffer(0)
    return [segment for edge in boundaries for segment in _lines(edge.intersection(clipped), min_length_mm)]
