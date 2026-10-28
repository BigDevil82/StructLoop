"""Inference only: native RC-GNN features -> one deterministic wall layout."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from struct_agent.schemas import LayoutCandidate, RoomGraph
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
    return layout_from_legacy(raw, unit="mm", layout_id=layout_id,
                              source="rcgnn" if symmetry_axis_mm is None else "rcgnn_symmetry_union")
