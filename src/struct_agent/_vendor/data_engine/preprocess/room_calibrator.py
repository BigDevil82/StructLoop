"""
房间坐标校准模块

主要功能：
1. 将房间校准为标准矩形（使用 bounding box）
2. 对齐共享边：通过坐标聚类消除绘图误差
"""
from typing import List
from shapely.geometry import Polygon

class RoomCalibrator:
    """房间坐标校准器"""

    def __init__(self, alignment_threshold: float=200.0):
        """
        Args:
            alignment_threshold: 坐标对齐的阈值（小于此值的坐标将被合并）
        """
        self.alignment_threshold = alignment_threshold
        self.x_grid: List[float] = []
        self.y_grid: List[float] = []

    def _cluster_1d(self, values: List[float]) -> List[float]:
        """
        对一维坐标进行快速聚类
        逻辑：排序 -> 线性扫描 -> 平均值
        复杂度: O(N log N)
        """
        if not values:
            return []
        v = sorted(values)
        clusters = [[v[0]]]
        for x in v[1:]:
            if x - clusters[-1][-1] <= self.alignment_threshold:
                clusters[-1].append(x)
            else:
                clusters.append([x])
        centers = [sum(c) / len(c) for c in clusters]
        return centers

    def _snap_to_grid(self, val: float, grid: List[float]) -> float:
        """
        将数值吸附到最近的网格线
        """
        if not grid:
            return val
        nearest = min(grid, key=lambda g: abs(g - val))
        if abs(nearest - val) <= self.alignment_threshold:
            return nearest
        return val

    def calibrate_rooms(self, room_polys: List[Polygon]) -> List[Polygon]:
        """
        校准房间列表
        """
        if not room_polys:
            return []
        xs = []
        ys = []
        bounds_list = []
        for room in room_polys:
            minx, miny, maxx, maxy = room.bounds
            bounds_list.append((minx, miny, maxx, maxy))
            xs.extend([minx, maxx])
            ys.extend([miny, maxy])
        self.x_grid = self._cluster_1d(xs)
        self.y_grid = self._cluster_1d(ys)
        calibrated_rooms = []
        for minx, miny, maxx, maxy in bounds_list:
            nx1 = self._snap_to_grid(minx, self.x_grid)
            nx2 = self._snap_to_grid(maxx, self.x_grid)
            ny1 = self._snap_to_grid(miny, self.y_grid)
            ny2 = self._snap_to_grid(maxy, self.y_grid)
            if nx2 <= nx1:
                nx2 = nx1 + 1.0
            if ny2 <= ny1:
                ny2 = ny1 + 1.0
            new_poly = Polygon([(nx1, ny1), (nx2, ny1), (nx2, ny2), (nx1, ny2)])
            calibrated_rooms.append(new_poly)
        return calibrated_rooms

def calibrate_rooms(room_polys: List[Polygon], alignment_threshold: float=1.0) -> List[Polygon]:
    """
    便捷函数：校准房间列表

    Args:
        room_polys: 原始房间多边形列表
        alignment_threshold: 坐标对齐阈值

    Returns:
        校准后的房间多边形列表
    """
    calibrator = RoomCalibrator(alignment_threshold=alignment_threshold)
    return calibrator.calibrate_rooms(room_polys)
