"""Build a fresh, layout-bound FuseGNN room_v2 context for each optimization."""
from __future__ import annotations

import hashlib
from pathlib import Path

from struct_agent.io.artifacts import write_json
from struct_agent.schemas import LayoutCandidate, RoomGraph
from .geometry import legacy_topology


def prepare_context(layout: LayoutCandidate, rooms: RoomGraph, directory: Path) -> Path:
    """Re-encode actual walls with upstream interval rules; never reuse another cache.

    Native room_v2: x float32[N,41], edges float32[E,8], graph_feat float32[1,7].
    Geometry is converted to mm before applying the original room encoder.
    """
    import numpy as np
    import pandas as pd
    import torch
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union
    from struct_agent._vendor.data_engine.preprocess.layout_graph import LayoutGraphBuilder
    from struct_agent._vendor.data_engine.preprocess.room_analyzer import RoomAnalyzer
    from struct_agent._vendor.surrogate.gnn.graph_data import _build_room_graph_data
    from struct_agent._vendor.surrogate.features.layout_features import _extract_one_layout
    directory.mkdir(parents=True, exist_ok=False)
    # Digest name avoids traversal and binds paths/cache keys to the full topology.
    digest = hashlib.sha256(layout.model_dump_json().encode()).hexdigest()
    layout_path = directory / f"{digest}.json"
    write_json(layout_path, legacy_topology(layout))
    polygons = [Polygon([(x*1000.,y*1000.) for x,y in p]) for p in rooms.room_polygons]
    builder = LayoutGraphBuilder(digest, polygons)
    analyzer = RoomAnalyzer([], [])
    analyzer.sw_union = unary_union([LineString([(x*1000., y*1000.) for x,y in (m.start,m.end)])
                                     for m in layout.members if m.role == "wall"])
    for i, poly in enumerate(polygons):
        vector, _ = analyzer.process_room(poly)
        node = builder.graph.nodes[i]
        node.update(geo_feature=np.asarray(rooms.x[i][:9], dtype=np.float32),
                    masks=rooms.masks[i], sw_vector=vector)
    builder.graph.remove_edges_from(list(builder.graph.edges))
    for u,v,attrs in zip(rooms.edge_index[0], rooms.edge_index[1], rooms.edge_attr):
        builder.graph.add_edge(u,v, feature=np.asarray(attrs, dtype=np.float32))
    cache = _build_room_graph_data(builder)
    torch.save(cache, directory / f"{digest}.pt")
    pd.DataFrame([_extract_one_layout(layout_path, 1., 0.15)]).to_parquet(directory / "layout_features.parquet", index=False)
    write_json(directory / "binding.json", {"layout_sha256": digest,
        "room_graph_sha256": hashlib.sha256(rooms.model_dump_json().encode()).hexdigest(),
        "feature_version": "room_v2", "reencoded_from_actual_wall_lines": True})
    return layout_path
