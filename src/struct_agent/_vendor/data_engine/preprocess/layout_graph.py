"""
布局图构建模块

功能：
1. 根据校准后的房间布局构建图结构（NetworkX DiGraph）
2. 提取节点特征：几何信息（Box, Area）+ 剪力墙分布（Label）
3. 提取边特征：邻接关系、重合长度、相对方位（Top/Bottom/Left/Right）
4. 可视化：在平面图上叠加显示图拓扑结构

图结构说明：
- 节点：每个房间对应一个节点
- 边：相邻房间（共享边）之间建立有向边
- 节点特征：归一化几何特征 + 剪力墙向量 + 约束掩码
- 边特征：共享边长度、位置、方向等
"""
import os
from typing import List
import networkx as nx
import numpy as np
import torch
from shapely.geometry import Point, Polygon
from torch_geometric.data import Data
from struct_agent._vendor.shearwall_pred.utils import get_file_category, mask_to_constraint_vector

class LayoutGraphBuilder:
    """
    布局图构建器

    将房间布局转换为图结构，用于GNN模型输入
    """

    def __init__(self, dxf_path: str, rooms: List[Polygon], room_indices: List[int]=None):
        """
        Args:
            rooms: 校准后的房间多边形列表
            room_indices: 房间的原始索引列表（用于追踪），默认自动生成 0..N-1
        """
        self.dxf_path = dxf_path
        self.rooms = rooms
        self.num_rooms = len(rooms)
        self.room_indices = room_indices if room_indices else list(range(self.num_rooms))
        self._compute_normalization_params()
        self.graph = nx.DiGraph()
        self._init_nodes()
        self._build_edges()

    def _compute_normalization_params(self):
        """
        计算户型整体的包围盒和归一化参数

        目的：将所有房间的坐标归一化到[-1, 1]范围，
             使模型对不同尺度的户型具有更好的泛化能力
        """
        all_bounds = [room.bounds for room in self.rooms]
        total_minx = min((b[0] for b in all_bounds))
        total_miny = min((b[1] for b in all_bounds))
        total_maxx = max((b[2] for b in all_bounds))
        total_maxy = max((b[3] for b in all_bounds))
        self.total_center_x = (total_minx + total_maxx) / 2
        self.total_center_y = (total_miny + total_maxy) / 2
        self.scale_factor = max(total_maxx - total_minx, total_maxy - total_miny)
        if self.scale_factor < 1e-06:
            self.scale_factor = 1.0

    def _init_nodes(self):
        """
        初始化图节点及基础几何特征

        每个节点包含：
        - poly: 房间多边形
        - geo_feature: 归一化几何特征向量(9维)
        - sw_vector: 剪力墙向量(16维) - 后续通过add_analysis_results添加
        - masks: 可布置区域掩码 - 后续添加
        """
        for i, room in enumerate(self.rooms):
            room_id = self.room_indices[i]
            minx, miny, maxx, maxy = room.bounds
            center_x = (minx + maxx) / 2
            center_y = (miny + maxy) / 2
            width = maxx - minx
            height = maxy - miny
            area = width * height
            norm_minx = (minx - self.total_center_x) / (self.scale_factor / 2)
            norm_miny = (miny - self.total_center_y) / (self.scale_factor / 2)
            norm_maxx = (maxx - self.total_center_x) / (self.scale_factor / 2)
            norm_maxy = (maxy - self.total_center_y) / (self.scale_factor / 2)
            norm_width = width / (self.scale_factor / 2)
            norm_height = height / (self.scale_factor / 2)
            norm_area = area / self.scale_factor ** 2
            norm_cx = (center_x - self.total_center_x) / (self.scale_factor / 2)
            norm_cy = (center_y - self.total_center_y) / (self.scale_factor / 2)
            geo_feature = np.array([norm_minx, norm_miny, norm_maxx, norm_maxy, norm_width, norm_height, norm_area, norm_cx, norm_cy], dtype=np.float32)
            self.graph.add_node(room_id, poly=room, geo_feature=geo_feature, sw_vector=None, masks=None)

    def _get_relative_position(self, src_bounds, tgt_bounds) -> np.ndarray:
        """
        判断 Target 相对于 Source 的方位
        Returns:
            One-hot vector: [Top, Bottom, Left, Right]
        """
        src_cx = (src_bounds[0] + src_bounds[2]) / 2
        src_cy = (src_bounds[1] + src_bounds[3]) / 2
        tgt_cx = (tgt_bounds[0] + tgt_bounds[2]) / 2
        tgt_cy = (tgt_bounds[1] + tgt_bounds[3]) / 2
        dx = tgt_cx - src_cx
        dy = tgt_cy - src_cy
        direction = np.zeros(4, dtype=np.float32)
        if abs(dy) > abs(dx):
            if dy > 0:
                direction[0] = 1.0
            else:
                direction[1] = 1.0
        elif dx < 0:
            direction[2] = 1.0
        else:
            direction[3] = 1.0
        return direction

    def _build_edges(self):
        """
        构建边：检测邻接关系并计算边特征
        规则：如果两个房间相交或接触（共享边），则建立双向边
        """
        for i in range(self.num_rooms):
            for j in range(self.num_rooms):
                if i == j:
                    continue
                room_i = self.rooms[i]
                room_j = self.rooms[j]
                id_i = self.room_indices[i]
                id_j = self.room_indices[j]
                if not room_i.intersects(room_j) and (not room_i.touches(room_j)):
                    continue
                intersection = room_i.intersection(room_j)
                if intersection.is_empty or isinstance(intersection, Point):
                    continue
                shared_length = intersection.length
                if shared_length < 400:
                    continue
                if isinstance(intersection, Polygon):
                    shared_length = intersection.length / 2
                centroid = intersection.centroid
                direction_vec = self._get_relative_position(room_i.bounds, room_j.bounds)
                is_horizontal = direction_vec[0] == 1.0 or direction_vec[1] == 1.0
                norm_shared_length = shared_length / (self.scale_factor / 2)
                norm_overlap_cx = (centroid.x - self.total_center_x) / (self.scale_factor / 2)
                norm_overlap_cy = (centroid.y - self.total_center_y) / (self.scale_factor / 2)
                edge_feature = np.concatenate([[norm_shared_length, norm_overlap_cx, norm_overlap_cy], direction_vec, [is_horizontal]]).astype(np.float32)
                self.graph.add_edge(id_i, id_j, feature=edge_feature, shared_geom=intersection)

    def add_analysis_results(self, analysis_results: List[dict]):
        """
        将 RoomAnalyzer 的分析结果（剪力墙向量等）添加到图节点中作为 Label 或 Feature
        """
        result_map = {res['room_index']: res for res in analysis_results}
        for node_id in self.graph.nodes:
            if node_id in result_map:
                res = result_map[node_id]
                self.graph.nodes[node_id]['sw_vector'] = np.array(res['sw_vector'], dtype=np.float32)
                self.graph.nodes[node_id]['masks'] = res['masks']

    def to_pyg_data(self) -> Data:
        """
        将内部图结构转换为 PyG Data 对象
        """
        x_list = []
        y_list = []
        mask_list = []
        nodes_list = list(self.graph.nodes(data=True))
        node_mapping = {node_id: i for i, (node_id, _) in enumerate(nodes_list)}
        for node_id, data in nodes_list:
            geo = data['geo_feature']
            masks = data.get('masks', [])
            sw_vector = data.get('sw_vector')
            if sw_vector is None:
                sw_vector = np.zeros(16, dtype=np.float32)
            constraint_vec = mask_to_constraint_vector(masks)
            x_feat = np.concatenate([geo, constraint_vec])
            x_list.append(x_feat)
            y_list.append(sw_vector)
            mask_list.append(constraint_vec)
        edge_index = []
        edge_attr = []
        for u, v, data in self.graph.edges(data=True):
            edge_index.append([node_mapping[u], node_mapping[v]])
            edge_attr.append(data['feature'])
        category = get_file_category(os.path.basename(self.dxf_path))
        category_vec = np.zeros((1, 3), dtype=np.float32)
        if category >= 0:
            category_vec[0, category] = 1.0
        data = Data(x=torch.tensor(np.array(x_list), dtype=torch.float), edge_index=torch.tensor(edge_index, dtype=torch.long).t().contiguous(), edge_attr=torch.tensor(np.array(edge_attr), dtype=torch.float), y=torch.tensor(np.array(y_list), dtype=torch.float), constraint_mask=torch.tensor(np.array(mask_list), dtype=torch.float), condition=torch.tensor(category_vec, dtype=torch.float))
        return data
