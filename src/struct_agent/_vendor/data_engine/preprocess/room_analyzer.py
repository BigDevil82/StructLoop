"""
房间剪力墙分析模块

功能：
1. 分析房间边缘的剪力墙分布
2. 计算可布置区域掩码（排除门窗等）
3. 生成16维特征向量（4边×2半边×2端点）
4. 提供墙体重建和IoU计算工具
"""
from typing import List, Tuple
import numpy as np
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import unary_union

def get_room_edges(room_poly: Polygon) -> List[LineString]:
    """
    获取房间的四条边（按顺序：上、右、下、左）

    Args:
        room_poly: 房间多边形（假设为矩形）

    Returns:
        edges: 4条边的LineString列表
            - 上边：从左上到右上
            - 右边：从右上到右下
            - 下边：从左下到右下
            - 左边：从左上到左下
    """
    minx, miny, maxx, maxy = room_poly.bounds
    tl, tr, bl, br = (Point(minx, maxy), Point(maxx, maxy), Point(minx, miny), Point(maxx, miny))
    return [LineString([tl, tr]), LineString([tr, br]), LineString([bl, br]), LineString([tl, bl])]

class RoomAnalyzer:
    """
    房间剪力墙分析器

    职责：
    1. 分析房间每条边上的剪力墙分布
    2. 计算可布置区域（剪力墙+填充墙的并集）
    3. 生成16维特征向量作为Ground Truth
    """

    def __init__(self, sw_polys: List[Polygon], infill_polys: List[Polygon]):
        """
        Args:
            sw_polys: 剪力墙多边形列表
            infill_polys: 填充墙多边形列表
        """
        self.sw_union = unary_union(sw_polys).buffer(0)
        self.buildable_union = unary_union(sw_polys + infill_polys).buffer(0)

    def _compute_intervals(self, edge: LineString, poly_union: Polygon, threshold: float=0.1) -> List[Tuple[float, float]]:
        """
        计算边与多边形集合的交集区间（归一化到[0,1]）

        Args:
            edge: 房间边线段
            poly_union: 墙体多边形的并集
            threshold: 区间长度阈值（小于此值的区间将被忽略）

        Returns:
            intervals: 归一化区间列表 [(start, end), ...]
                      区间已合并且按起始位置排序
        """
        intersection = edge.intersection(poly_union)
        if intersection.is_empty or edge.length == 0:
            return []
        geoms = []
        if isinstance(intersection, LineString):
            geoms = [intersection]
        elif isinstance(intersection, MultiLineString):
            geoms = list(intersection.geoms)
        elif isinstance(intersection, (Point, Polygon)):
            return []
        elif hasattr(intersection, 'geoms'):
            geoms = [g for g in intersection.geoms if isinstance(g, LineString)]
        intervals = []
        for geom in geoms:
            d1 = edge.project(Point(geom.coords[0]), normalized=True)
            d2 = edge.project(Point(geom.coords[-1]), normalized=True)
            start, end = sorted([d1, d2])
            if end - start > threshold:
                intervals.append((start, end))
        intervals.sort()
        merged = []
        for start, end in intervals:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def _compute_anchor_ratios(self, intervals: List[Tuple[float, float]]) -> Tuple[float, float]:
        """
        计算边两端的剪力墙比例

        逻辑：
        - 如果第一个区间从0开始，则起始端有墙，比例为该区间长度
        - 如果最后一个区间延伸到1，则结束端有墙，比例为从末尾算起的长度

        Args:
            intervals: 归一化区间列表

        Returns:
            (start_ratio, end_ratio): 起始端和结束端的墙体比例
        """
        if not intervals:
            return (0.0, 0.0)
        start_ratio = intervals[0][1] if intervals[0][0] < 0.001 else 0.0
        end_ratio = 1.0 - intervals[-1][0] if intervals[-1][1] > 1.0 - 0.001 else 0.0
        return (start_ratio, end_ratio)

    def process_room(self, room_poly: Polygon) -> Tuple[np.ndarray, List[List[Tuple[float, float]]]]:
        """
        处理单个房间，计算剪力墙向量和可布置区域掩码

        Returns:
            sw_vector: 16维向量 [4条边 × 2半边 × 2端点]
            masks: 4个列表，每条边的可布置区间
        """
        edges = get_room_edges(room_poly)
        sw_vector = []
        masks = []
        for edge in edges:
            p_mid = edge.interpolate(0.5, normalized=True)
            halves = [LineString([edge.coords[0], p_mid]), LineString([p_mid, edge.coords[-1]])]
            for half in halves:
                sw_intervals = self._compute_intervals(half, self.sw_union)
                start_ratio, end_ratio = self._compute_anchor_ratios(sw_intervals)
                sw_vector.extend([start_ratio, end_ratio])
                buildable_intervals = self._compute_intervals(half, self.buildable_union)
                masks.append(buildable_intervals)
        return (np.array(sw_vector), masks)

def _walls_from_vector(room_poly: Polygon, sw_vector: np.ndarray, masks: List[List[Tuple[float, float]]]=None) -> MultiLineString:
    """
    从剪力墙向量重建墙体线段 (修复了掩码裁剪逻辑)

    Args:
        room_poly: 房间多边形
        sw_vector: 16维剪力墙向量
        masks: 列表长度应为8 (4条边x2半边)，每个元素为该半边上的可布置区间列表 [(s, e), ...]
    """
    edges = get_room_edges(room_poly)
    sw_ratios = sw_vector.reshape(4, 2, 2)
    result_walls = []
    half_edge_idx = 0
    for i, edge in enumerate(edges):
        p_mid = edge.interpolate(0.5, normalized=True)
        halves = [LineString([edge.coords[0], p_mid]), LineString([p_mid, edge.coords[-1]])]
        for j, half in enumerate(halves):
            start_ratio, end_ratio = sw_ratios[i][j]
            current_half_walls = []
            if start_ratio > 0.001:
                w_start = half.interpolate(0, normalized=True)
                w_end = half.interpolate(start_ratio, normalized=True)
                current_half_walls.append(LineString([w_start, w_end]))
            if end_ratio > 0.001:
                w_start = half.interpolate(1.0 - end_ratio, normalized=True)
                w_end = half.interpolate(1.0, normalized=True)
                current_half_walls.append(LineString([w_start, w_end]))
            if not current_half_walls:
                half_edge_idx += 1
                continue
            if masks:
                valid_intervals = masks[half_edge_idx]
                if valid_intervals:
                    mask_lines = []
                    for s, e in valid_intervals:
                        p_s = half.interpolate(s, normalized=True)
                        p_e = half.interpolate(e, normalized=True)
                        mask_lines.append(LineString([p_s, p_e]))
                    pred_union = unary_union(current_half_walls)
                    mask_union = unary_union(mask_lines)
                    final_walls = pred_union.intersection(mask_union)
                    if not final_walls.is_empty:
                        if isinstance(final_walls, LineString):
                            result_walls.append(final_walls)
                        elif isinstance(final_walls, MultiLineString):
                            result_walls.extend(final_walls.geoms)
                else:
                    pass
            else:
                result_walls.extend(current_half_walls)
            half_edge_idx += 1
    return MultiLineString(result_walls) if result_walls else MultiLineString([])
