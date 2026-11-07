"""Normalize DXF infill walls into footprint polygons for layout evidence."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def infill_wall_footprints(
    dxf: str | Path,
    raw_walls: list,
    *,
    axis_engine_home: str | Path | None = None,
) -> tuple[tuple[tuple[float, float], ...], ...] | None:
    """Use closed DXF polygons directly, or the axis engine for double-line walls.

    None means that the wall evidence could not be normalized. In particular,
    two-point contour edges are never passed off as filled wall polygons.
    """
    if not raw_walls:
        return None
    if all(len(wall) >= 4 for wall in raw_walls):
        return tuple(
            tuple((point.x / 1000.0, point.y / 1000.0) for point in wall)
            for wall in raw_walls
        )
    home = axis_engine_home or os.environ.get("AXIS_ENGINE_HOME")
    if not home:
        return None
    root = Path(home).resolve()
    if not (root / "axis_engine" / "cad_processor.py").is_file():
        raise FileNotFoundError(f"Axis engine not found under {root}")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from axis_engine.cad_processor import CADLayoutProcessor

    processor = CADLayoutProcessor(
        dxf, wall_layers=["INFILL_WALLS"], opening_layers=["__NO_OPENINGS__"]
    )
    polygon = processor.build_geometry().wall_polygon
    if polygon.is_empty:
        return None
    return tuple(
        tuple((x / 1000.0, y / 1000.0) for x, y in part.exterior.coords)
        for part in polygon.geoms
    )
