"""Inference only: native RC-GNN features -> one deterministic wall layout."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from struct_agent.schemas import LayoutCandidate, Member, RoomGraph
from .geometry import layout_from_legacy


def graph_from_dxf(path: Path, *, category: int) -> RoomGraph:
    """Prepared upstream DXF layer convention, in mm; not arbitrary DWG parsing."""
    from struct_agent._vendor.shearwall_pred.utils import build_graph_from_dxf
    builder = build_graph_from_dxf(str(path), mode="none")
    data = builder.to_pyg_data()
    nodes = list(builder.graph.nodes(data=True))
    payload = {
        "feature_version": "rcgnn_25_8_v1", "length_unit": "m",
        "native_feature_length_unit": "mm", "coordinate_system": "global_xy",
        "x": data.x.tolist(), "edge_index": data.edge_index.tolist(),
        "edge_attr": data.edge_attr.tolist(), "category": category,
        "room_polygons": [[[float(x)/1000., float(y)/1000.] for x,y in a['poly'].exterior.coords]
                          for _,a in nodes],
        "masks": [a['masks'] for _,a in nodes],
    }
    # JSON mode accepts arrays but still rejects coercion of primitive types.
    import json
    return RoomGraph.model_validate_json(json.dumps(payload))


class RCGNNAdapter:
    def __init__(self, checkpoints: tuple[Path, ...], *, device: str = "cpu") -> None:
        if not checkpoints or any(not p.is_file() for p in checkpoints):
            raise FileNotFoundError("BLOCKED: RC-GNN checkpoint(s) missing")
        import torch
        from struct_agent._vendor.shearwall_pred.model import ShearWallGNN
        self.device = torch.device(device)
        self.models = []
        self.checkpoints = checkpoints
        for path in checkpoints:
            model = ShearWallGNN()
            model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
            self.models.append(model.to(self.device).eval())

    def predict(self, graph: RoomGraph) -> np.ndarray:
        """Return float32 ratios Shape [N,16], dimensionless native half-edge order."""
        import torch
        from torch_geometric.data import Batch, Data
        data = Data(x=torch.tensor(graph.x, dtype=torch.float32),
                    edge_index=torch.tensor(graph.edge_index, dtype=torch.long).reshape(2,-1),
                    edge_attr=torch.tensor(graph.edge_attr, dtype=torch.float32).reshape(-1,8),
                    condition=torch.nn.functional.one_hot(torch.tensor([graph.category]), 3).float())
        batch = Batch.from_data_list([data]).to(self.device)
        with torch.no_grad():
            outputs = [model(batch) for model in self.models]
            prob = torch.stack([v[0] for v in outputs]).mean(0)
            ratio = torch.stack([v[1] for v in outputs]).mean(0)
            prediction = ((prob > 0.5) * ratio).cpu().numpy()
        prediction[prediction < 0.1] = 0.
        if prediction.shape != (len(graph.x), 16) or not np.isfinite(prediction).all():
            raise ValueError("Invalid RC-GNN prediction")
        return prediction

    def generate(self, graph: RoomGraph, *, layout_id: str) -> LayoutCandidate:
        return layout_from_prediction(graph, self.predict(graph), layout_id=layout_id)


def preprocess_short_members(layout: LayoutCandidate) -> LayoutCandidate:
    """Flip physical chains <=180 mm into adjacent longer opposite-type chains.

    Work in global XY mm; return public geometry in m. Collinear subdivisions
    are grouped before applying the threshold. Apply flips simultaneously,
    retain junctions and preserve the original primary/secondary beam roles.
    """
    import networkx as nx
    from shapely.geometry import LineString
    from struct_agent._vendor.data_engine.postprocess.fem_builder import FEMTopologyBuilder

    segments = [{"geometry": LineString([tuple(round(v*1000, 6) for v in p)
                 for p in (m.start, m.end)]), "type": "shearwall" if m.role == "wall" else "beam"}
                for m in layout.members]
    endpoints: dict[tuple[float, float], list[int]] = defaultdict(list)
    graph = nx.Graph()
    graph.add_nodes_from(range(len(segments)))
    for i, segment in enumerate(segments):
        segment["length"] = segment["geometry"].length
        for point in segment["geometry"].coords:
            endpoints[point].append(i)

    def parallel(i: int, j: int) -> bool:
        p, q = segments[i]["geometry"].coords
        r, s = segments[j]["geometry"].coords
        return abs((q[0]-p[0])*(s[1]-r[1])-(q[1]-p[1])*(s[0]-r[0])) < (
            1e-8*segments[i]["length"]*segments[j]["length"])

    for indices in endpoints.values():
        for position, i in enumerate(indices):
            for j in indices[position+1:]:
                if segments[i]["type"] == segments[j]["type"] and parallel(i, j):
                    graph.add_edge(i, j)
    groups = list(nx.connected_components(graph))
    lengths = {i: sum(segments[j]["length"] for j in group) for group in groups for i in group}
    flips = {}
    for group in groups:
        i = min(group)
        if lengths[i] > 180.+1e-6:
            continue
        neighbors = {j for k in group for p in segments[k]["geometry"].coords for j in endpoints[p]}-group
        if any(segments[j]["type"] != segments[i]["type"] and lengths[j] > 180.+1e-6
               and parallel(i, j) for j in neighbors):
            flips.update({k: "beam" if segments[i]["type"] == "shearwall" else "shearwall" for k in group})
    for i, kind in flips.items():
        segments[i]["type"] = kind

    builder = FEMTopologyBuilder()
    builder._build_topology(builder._merge_collinear_same_type_segments(segments))
    members = []
    for element in builder.elements:
        role = "wall"
        if element["type"] == "beam":
            line = LineString([element["start_coord"], element["end_coord"]])
            roles = {layout.members[i].role for i, segment in enumerate(segments)
                     if layout.members[i].role != "wall" and line.intersection(segment["geometry"]).length > 1e-6}
            if len(roles) != 1:
                raise ValueError(f"Merged beam roles need review: {element['id']}: {sorted(roles)}")
            role = roles.pop()
        members.append(Member(member_id=f"{element['type']}_{element['id']}",
            start=tuple(v/1000 for v in element["start_coord"]),
            end=tuple(v/1000 for v in element["end_coord"]), role=role))
    return LayoutCandidate.model_validate({**layout.model_dump(), "members": tuple(members)})


def layout_from_prediction(graph: RoomGraph, ratios: np.ndarray, *, layout_id: str,
                           symmetry_axis_mm: float | None = None) -> LayoutCandidate:
    """Retain upstream topology construction, including beam roles and slabs."""
    from shapely.geometry import Polygon
    from struct_agent._vendor.data_engine.postprocess.fem_builder import FEMTopologyBuilder
    if ratios.shape != (len(graph.x), 16) or not np.isfinite(ratios).all() or np.any((ratios < 0)|(ratios > 1)):
        raise ValueError("Expected finite ratio[N,16] in [0,1]")
    builder = FEMTopologyBuilder(gap_tolerance=200., min_length=100.)
    for poly, mask, row in zip(graph.room_polygons, graph.masks, ratios):
        builder.add_room(Polygon([(x*1000.,y*1000.) for x,y in poly]), row, mask)
    if symmetry_axis_mm is not None:
        from .symmetry import union_walls
        builder.raw_walls = union_walls(builder.raw_walls, builder.room_edges,
                                       axis_mm=symmetry_axis_mm, min_length_mm=builder.min_length)
    result = builder.build()
    if not result["validation"]["ok"]:
        raise ValueError(f"Invalid generated topology: {result['validation']}")
    raw: dict[str, Any] = {"shearwalls": [], "beams": [], "slabs": result["slabs"]}
    for m in result["members"]:
        item = {"start": m['start_coord'], "end": m['end_coord']}
        if m["type"] == "shearwall":
            raw["shearwalls"].append(item)
        else:
            item["beam_role"] = m.get("beam_role", "primary")
            raw["beams"].append(item)
    layout = layout_from_legacy(raw, unit="mm", layout_id=layout_id,
                               source="rcgnn" if symmetry_axis_mm is None else "rcgnn_symmetry_union")
    return preprocess_short_members(layout)
