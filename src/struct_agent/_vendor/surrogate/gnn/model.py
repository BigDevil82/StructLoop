from __future__ import annotations
import torch
import torch.nn as nn
from torch_geometric.nn import GINEConv, SAGEConv, global_max_pool, global_mean_pool

class ParamEncoder(nn.Module):

    def __init__(self, num_dim: int, cat_cardinalities: list[int], emb_dims: list[int], hidden_dim: int, dropout: float):
        super().__init__()
        self.num_bn = nn.BatchNorm1d(num_dim)
        self.embs = nn.ModuleList([nn.Embedding(cardinality, emb_dim) for cardinality, emb_dim in zip(cat_cardinalities, emb_dims)])
        in_dim = num_dim + int(sum(emb_dims))
        self.mlp = nn.Sequential(nn.Linear(in_dim, hidden_dim), nn.ReLU(inplace=True), nn.Dropout(dropout), nn.Linear(hidden_dim, hidden_dim), nn.ReLU(inplace=True))

    def forward(self, p_num: torch.Tensor, p_cat: torch.Tensor) -> torch.Tensor:
        p_num = self.num_bn(p_num)
        emb = [layer(p_cat[:, i]) for i, layer in enumerate(self.embs)]
        x = torch.cat([p_num] + emb, dim=1)
        return self.mlp(x)

class LayoutParamGNN(nn.Module):

    def __init__(self, node_dim: int, edge_dim: int, graph_feat_dim: int, param_num_dim: int, param_cat_cardinalities: list[int], param_emb_dims: list[int], hidden_dim: int=128, gnn_layers: int=3, dropout: float=0.2, conv_type: str='sage'):
        super().__init__()
        if conv_type not in {'sage', 'gine'}:
            raise ValueError(f'Unknown conv_type: {conv_type}')
        self.conv_type = conv_type
        self.node_proj = nn.Linear(node_dim, hidden_dim)
        self.convs = nn.ModuleList()
        self.norms = nn.ModuleList()
        for _ in range(gnn_layers):
            if conv_type == 'gine':
                mlp = nn.Sequential(nn.Linear(hidden_dim, hidden_dim), nn.ReLU(inplace=True), nn.Linear(hidden_dim, hidden_dim))
                self.convs.append(GINEConv(mlp, edge_dim=edge_dim))
            else:
                self.convs.append(SAGEConv(hidden_dim, hidden_dim))
            self.norms.append(nn.BatchNorm1d(hidden_dim))
        self.edge_proj = nn.Sequential(nn.Linear(edge_dim, hidden_dim // 2), nn.ReLU(inplace=True), nn.Linear(hidden_dim // 2, hidden_dim // 2), nn.ReLU(inplace=True))
        self.param_encoder = ParamEncoder(num_dim=param_num_dim, cat_cardinalities=param_cat_cardinalities, emb_dims=param_emb_dims, hidden_dim=hidden_dim, dropout=dropout)
        fusion_in = hidden_dim * 2 + hidden_dim // 2 + graph_feat_dim + hidden_dim
        self.classifier = nn.Sequential(nn.Linear(fusion_in, hidden_dim), nn.ReLU(inplace=True), nn.Dropout(dropout), nn.Linear(hidden_dim, 1))

    def forward(self, data) -> torch.Tensor:
        x = self.node_proj(data.x)
        for conv, bn in zip(self.convs, self.norms):
            if self.conv_type == 'gine':
                h = conv(x, data.edge_index, data.edge_attr)
            else:
                h = conv(x, data.edge_index)
            x = torch.relu(bn(h) + x)
        g_mean = global_mean_pool(x, data.batch)
        g_max = global_max_pool(x, data.batch)
        edge_h = self.edge_proj(data.edge_attr)
        edge_batch = data.batch[data.edge_index[0]]
        edge_mean = global_mean_pool(edge_h, edge_batch)
        graph_feat = data.graph_feat
        p_num = data.p_num
        p_cat = data.p_cat
        p_emb = self.param_encoder(p_num, p_cat)
        z = torch.cat([g_mean, g_max, edge_mean, graph_feat, p_emb], dim=1)
        logits = self.classifier(z).squeeze(1)
        return logits

def auto_param_emb_dims(cardinalities: list[int]) -> list[int]:
    return [min(16, max(4, (card + 1) // 2)) for card in cardinalities]
