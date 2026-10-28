"""
基于图神经网络的剪力墙分布预测模型

模型架构：
1. 输入编码：节点特征(25维) + 边特征(8维) → 隐藏层(128维)
2. 图卷积：3层GATv2（图注意力网络v2），带残差连接
3. 输出解码：MLP → 分类logits(16) + 回归logits(16)

输出：
- 分类：每个位置是否有剪力墙 (二分类概率)
- 回归：剪力墙的长度比例 (0-1之间的连续值)
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.data import Data
from torch_geometric.nn import BatchNorm, GATv2Conv
from struct_agent._vendor.shearwall_pred.config import model_config

class FiLMLayer(nn.Module):

    def __init__(self, in_dim, cond_emb_dim):
        super().__init__()
        self.scale = nn.Linear(cond_emb_dim, in_dim)
        self.shift = nn.Linear(cond_emb_dim, in_dim)

    def forward(self, x, cond_emb):
        gamma = self.scale(cond_emb)
        beta = self.shift(cond_emb)
        return x * (1 + gamma) + beta

class ShearWallGNN(nn.Module):
    """剪力墙分布预测的图神经网络"""

    def __init__(self, node_in_dim: int=model_config.NODE_FEATURE_DIM, edge_in_dim: int=model_config.EDGE_FEATURE_DIM, hidden_dim: int=model_config.HIDDEN_DIM, cond_dim=3, cond_emb_dim=32, out_dim: int=model_config.OUTPUT_DIM, num_heads: int=model_config.GAT_HEADS, dropout: float=model_config.DROPOUT):
        """
        Args:
            node_in_dim: 节点输入特征维度 (默认25 = 几何9 + 约束16)
            edge_in_dim: 边输入特征维度 (默认8)
            hidden_dim: 隐藏层维度
            out_dim: 输出维度 (默认32 = 分类16 + 回归16)
            num_heads: GAT注意力头数
            dropout: Dropout比例
        """
        super(ShearWallGNN, self).__init__()
        self.cond_dim = cond_dim
        self.node_encoder = nn.Linear(node_in_dim, hidden_dim)
        self.edge_encoder = nn.Linear(edge_in_dim, hidden_dim)
        self.cond_projector = nn.Sequential(nn.Linear(cond_dim, cond_emb_dim), nn.ReLU(), nn.Linear(cond_emb_dim, cond_emb_dim))
        self.film1 = FiLMLayer(hidden_dim, cond_emb_dim)
        self.film2 = FiLMLayer(hidden_dim, cond_emb_dim)
        self.film3 = FiLMLayer(hidden_dim, cond_emb_dim)
        self.conv1 = GATv2Conv(hidden_dim, hidden_dim, heads=num_heads, concat=False, edge_dim=hidden_dim)
        self.bn1 = BatchNorm(hidden_dim)
        self.conv2 = GATv2Conv(hidden_dim, hidden_dim, heads=num_heads, concat=False, edge_dim=hidden_dim)
        self.bn2 = BatchNorm(hidden_dim)
        self.conv3 = GATv2Conv(hidden_dim, hidden_dim, heads=num_heads, concat=False, edge_dim=hidden_dim)
        self.bn3 = BatchNorm(hidden_dim)
        self.decoder = nn.Sequential(nn.Linear(hidden_dim, hidden_dim), nn.ReLU(), nn.Dropout(dropout), nn.Linear(hidden_dim, hidden_dim // 2), nn.ReLU(), nn.Linear(hidden_dim // 2, out_dim))

    def forward(self, data: Data, condition: torch.Tensor=None) -> tuple[torch.Tensor, torch.Tensor]:
        """
        前向传播

        Args:
            data: PyG Data对象，包含 x, edge_index, edge_attr

        Returns:
            (classification_prob, regression_ratio):
                - classification_prob: 分类概率 (N, 16)，表示每个位置是否有墙
                - regression_ratio: 回归比例 (N, 16)，表示墙的长度比例
        """
        x, edge_index, edge_attr = (data.x, data.edge_index, data.edge_attr)
        batch = data.batch
        raw_condition = condition if condition is not None else data.condition
        cond_emb = self.cond_projector(raw_condition)
        node_cond_emb = cond_emb[batch]
        x = F.relu(self.node_encoder(x))
        edge_attr = F.relu(self.edge_encoder(edge_attr))
        x_residual = x
        x = self.conv1(x, edge_index, edge_attr=edge_attr)
        x = self.bn1(x)
        x = self.film1(x, node_cond_emb)
        x = F.relu(x) + x_residual
        x_residual = x
        x = self.conv2(x, edge_index, edge_attr=edge_attr)
        x = self.bn2(x)
        x = self.film2(x, node_cond_emb)
        x = F.relu(x) + x_residual
        x_residual = x
        x = self.conv3(x, edge_index, edge_attr=edge_attr)
        x = self.bn3(x)
        x = self.film3(x, node_cond_emb)
        x = F.relu(x) + x_residual
        out = self.decoder(x)
        classification_logits = out[:, :16]
        regression_logits = out[:, 16:]
        classification_prob = torch.sigmoid(classification_logits)
        regression_ratio = torch.sigmoid(regression_logits)
        return (classification_prob, regression_ratio)
