from __future__ import annotations
import numpy as np
import torch
from struct_agent._vendor.data_engine.preprocess.layout_graph import LayoutGraphBuilder
from struct_agent._vendor.shearwall_pred.utils import mask_to_constraint_vector
ROOM_GRAPH_FEATURE_VERSION = 'room_v2'
KIND_TO_ID = {'wall': 0, 'primary_beam': 1, 'secondary_beam': 2}
AXIS_TO_ID = {'horizontal': 0, 'vertical': 1}

def _build_room_graph_data(graph_builder: LayoutGraphBuilder) -> dict[str, torch.Tensor]:
    graph = graph_builder.graph
    if graph.number_of_nodes() == 0:
        raise ValueError('empty room graph')
    nodes = list(graph.nodes(data=True))
    node_mapping = {node_id: i for i, (node_id, _) in enumerate(nodes)}
    xs = []
    areas = []
    sw_sums = []
    for _, attrs in nodes:
        geo = np.asarray(attrs['geo_feature'], dtype=np.float32)
        constraint = mask_to_constraint_vector(attrs.get('masks') or [])
        sw_vector = attrs.get('sw_vector')
        if sw_vector is None:
            sw_vector = np.zeros(16, dtype=np.float32)
        sw_vector = np.asarray(sw_vector, dtype=np.float32)
        xs.append(np.concatenate([geo, constraint, sw_vector]))
        areas.append(float(attrs['poly'].area))
        sw_sums.append(float(sw_vector.sum()))
    edge_index = []
    edge_attr = []
    for u, v, attrs in graph.edges(data=True):
        edge_index.append([node_mapping[u], node_mapping[v]])
        edge_attr.append(np.asarray(attrs['feature'], dtype=np.float32))
    if not edge_index:
        edge_index = [[0, 0]]
        edge_attr = [np.zeros(8, dtype=np.float32)]
    n = max(graph.number_of_nodes(), 1)
    max_edges = max(n * (n - 1), 1)
    scale = max(float(getattr(graph_builder, 'scale_factor', 1.0)), 1.0)
    total_area = float(np.sum(areas))
    total_sw = float(np.sum(sw_sums))
    graph_feat = np.array([float(n / 64.0), float(graph.number_of_edges() / 256.0), float(graph.number_of_edges() / max_edges), total_area / (scale * scale), total_area / (n * scale * scale), total_sw / (16.0 * n), float(np.mean(sw_sums) / 16.0) if sw_sums else 0.0], dtype=np.float32)
    return {'x': torch.tensor(np.asarray(xs, dtype=np.float32)), 'edge_index': torch.tensor(np.asarray(edge_index, dtype=np.int64)).t().contiguous(), 'edge_attr': torch.tensor(np.asarray(edge_attr, dtype=np.float32)), 'graph_feat': torch.tensor(graph_feat[None, :])}
