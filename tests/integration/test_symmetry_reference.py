"""Compare minimal symmetry migration against the trusted local upstream source."""
import ast
from pathlib import Path
from typing import Iterable, List, Sequence

import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from struct_agent.adapters.symmetry import union_walls
from struct_agent.schemas import RoomGraph
from struct_agent._vendor.data_engine.postprocess.fem_builder import FEMTopologyBuilder

pytestmark = pytest.mark.real


def test_union_matches_local_upstream_on_engineering_graph() -> None:
    source = Path("E:/Common/Desktop/Research/deepLearning/codes/Png2Dxf/src/data_engine/postprocess/symmetry_postprocess.py")
    if not source.is_file():
        pytest.fail("BLOCKED: trusted local upstream symmetry reference unavailable")
    # Extract only pure geometry helpers; do not import plotting/CAD application.
    names = {"_safe_union", "_buffer_lines", "_extract_lines", "mirror_geometry", "symmetrize_raw_walls"}
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    selected = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    namespace = dict(globals(), DEFAULT_WALL_THICKNESS=200.)
    exec(compile(selected, str(source), "exec"), namespace)
    run = Path("outputs/reference/rcgnn_upstream")
    graph = RoomGraph.model_validate_json((run / "room_graph.json").read_text(encoding="utf-8"))
    ratios = np.load(run / "ratios.npy", allow_pickle=False)
    builder = FEMTopologyBuilder(gap_tolerance=200., min_length=100.)
    for poly, mask, row in zip(graph.room_polygons, graph.masks, ratios):
        builder.add_room(Polygon([(x*1000., y*1000.) for x, y in poly]), row, mask)
    expected = namespace["symmetrize_raw_walls"](builder.raw_walls, builder.room_edges,
        axis_x=728266., mode="union", min_length=100.)
    actual = union_walls(builder.raw_walls, builder.room_edges, axis_mm=728266.)
    assert [line.wkb for line in actual] == [line.wkb for line in expected]
    assert len(actual) > 0
