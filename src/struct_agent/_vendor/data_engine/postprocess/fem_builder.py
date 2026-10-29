from typing import Dict, List, Optional, Set, Tuple
import numpy as np
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Polygon
from shapely.ops import unary_union
from struct_agent._vendor.data_engine.preprocess.room_analyzer import _walls_from_vector, get_room_edges
from .topology_cleanup import clean_segments

class FEMTopologyBuilder:
    """
    基于线段运算的有限元拓扑构建器 v2.2

    核心改进：
    1. 用线段intersection/difference代替buffer，避免正交处间隙
    2. 按边分类后用区间减法精确计算梁位置
    3. snap对齐确保精确连接
    """

    def __init__(self, snap_tolerance: float=2.0, gap_tolerance: float=5.0, min_length: float=10.0):
        """
        Args:
            snap_tolerance: 坐标对齐容差
            gap_tolerance: 区间合并容差（合并相邻的剪力墙段）
            min_length: 最小构件长度
        """
        self.snap_tolerance = snap_tolerance
        self.gap_tolerance = gap_tolerance
        self.min_length = min_length
        self.raw_walls: List[LineString] = []
        self.room_edges: List[LineString] = []
        self.room_polys: List[Polygon] = []
        self.nodes: List[Tuple[float, float]] = []
        self.elements: List[dict] = []

    def add_room(self, room_poly: Polygon, sw_vector: np.ndarray, masks: List=None):
        """收集房间几何信息"""
        self.room_polys.append(room_poly)
        self.room_edges.extend(get_room_edges(room_poly))
        walls_geom = _walls_from_vector(room_poly, sw_vector, masks)
        if not walls_geom.is_empty:
            if isinstance(walls_geom, LineString):
                self.raw_walls.append(walls_geom)
            elif hasattr(walls_geom, 'geoms'):
                self.raw_walls.extend(list(walls_geom.geoms))
        else:
            print('  [FEMBuilder] 警告: 房间没有检测到剪力墙')

    def build(self) -> dict:
        print('  [FEMBuilder] 正在构建拓扑 (Interval-based)...')
        skeleton_lines = self._merge_collinear_lines(self.room_edges)
        wall_lines = self._merge_collinear_lines(self.raw_walls) if self.raw_walls else []
        print(f'    边界线: {len(self.room_edges)} -> {len(skeleton_lines)} (merged)')
        print(f'    剪力墙: {len(self.raw_walls)} -> {len(wall_lines)} (merged)')
        segments = []
        for skel_line in skeleton_lines:
            overlapping_walls = self._find_overlapping_segments(skel_line, wall_lines)
            if not overlapping_walls:
                segments.append({'geometry': skel_line, 'type': 'beam', 'length': skel_line.length})
            else:
                wall_segs, beam_segs = self._subtract_wall_from_edge(skel_line, overlapping_walls)
                segments.extend(wall_segs)
                segments.extend(beam_segs)
        segments = self._split_at_intersections(segments)
        segments = clean_segments(segments, snap_tolerance=self.snap_tolerance, min_wall_length=self.min_length)
        segments = self._merge_collinear_same_type_segments(segments)
        self._build_topology(segments)
        self._classify_beams_by_length_distribution()
        return self._format_result()

    def _merge_collinear_lines(self, lines: List[LineString]) -> List[LineString]:
        """合并共线线段"""
        if not lines:
            return []
        horizontal: Dict[int, List[Tuple[int, int]]] = {}
        vertical: Dict[int, List[Tuple[int, int]]] = {}
        others: List[LineString] = []
        tolerance = 2
        for line in lines:
            coords = list(line.coords)
            if len(coords) < 2:
                continue
            p1, p2 = (coords[0], coords[-1])
            x1, y1 = (int(round(p1[0])), int(round(p1[1])))
            x2, y2 = (int(round(p2[0])), int(round(p2[1])))
            if abs(y1 - y2) < tolerance:
                y_key = y1
                x_min, x_max = (min(x1, x2), max(x1, x2))
                if y_key not in horizontal:
                    horizontal[y_key] = []
                horizontal[y_key].append((x_min, x_max))
            elif abs(x1 - x2) < tolerance:
                x_key = x1
                y_min, y_max = (min(y1, y2), max(y1, y2))
                if x_key not in vertical:
                    vertical[x_key] = []
                vertical[x_key].append((y_min, y_max))
            else:
                others.append(line)
        merged_lines = []
        for y, intervals in horizontal.items():
            merged = self._merge_intervals(intervals)
            for x_min, x_max in merged:
                if x_max - x_min >= 1:
                    merged_lines.append(LineString([(x_min, y), (x_max, y)]))
        for x, intervals in vertical.items():
            merged = self._merge_intervals(intervals)
            for y_min, y_max in merged:
                if y_max - y_min >= 1:
                    merged_lines.append(LineString([(x, y_min), (x, y_max)]))
        merged_lines.extend(others)
        return merged_lines

    def _merge_intervals(self, intervals: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """合并重叠或相邻的区间"""
        if not intervals:
            return []
        sorted_intervals = sorted(intervals, key=lambda x: x[0])
        merged = [list(sorted_intervals[0])]
        for start, end in sorted_intervals[1:]:
            if start <= merged[-1][1] + self.gap_tolerance:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return [(m[0], m[1]) for m in merged]

    def _find_overlapping_segments(self, skel_line: LineString, wall_lines: List[LineString]) -> List[Tuple[float, float]]:
        """
        找出与边界线共线且重叠的剪力墙区间

        Returns:
            区间列表，每个区间是 (start_ratio, end_ratio) 在 [0, 1] 范围内
        """
        skel_coords = list(skel_line.coords)
        if len(skel_coords) < 2:
            return []
        p1, p2 = (np.array(skel_coords[0]), np.array(skel_coords[-1]))
        skel_vec = p2 - p1
        skel_len = np.linalg.norm(skel_vec)
        if skel_len < 1:
            return []
        skel_dir = skel_vec / skel_len
        is_horizontal = abs(skel_dir[1]) < 0.1
        is_vertical = abs(skel_dir[0]) < 0.1
        if not (is_horizontal or is_vertical):
            return []
        overlapping = []
        tolerance = self.snap_tolerance
        for wall in wall_lines:
            wall_coords = list(wall.coords)
            if len(wall_coords) < 2:
                continue
            w1, w2 = (np.array(wall_coords[0]), np.array(wall_coords[-1]))
            if is_horizontal:
                if abs(w1[1] - p1[1]) > tolerance or abs(w2[1] - p1[1]) > tolerance:
                    continue
                skel_x_min, skel_x_max = (min(p1[0], p2[0]), max(p1[0], p2[0]))
                wall_x_min, wall_x_max = (min(w1[0], w2[0]), max(w1[0], w2[0]))
                inter_min = max(skel_x_min, wall_x_min)
                inter_max = min(skel_x_max, wall_x_max)
                if inter_max > inter_min + 1:
                    ratio_min = (inter_min - skel_x_min) / (skel_x_max - skel_x_min)
                    ratio_max = (inter_max - skel_x_min) / (skel_x_max - skel_x_min)
                    overlapping.append((ratio_min, ratio_max))
            elif is_vertical:
                if abs(w1[0] - p1[0]) > tolerance or abs(w2[0] - p1[0]) > tolerance:
                    continue
                skel_y_min, skel_y_max = (min(p1[1], p2[1]), max(p1[1], p2[1]))
                wall_y_min, wall_y_max = (min(w1[1], w2[1]), max(w1[1], w2[1]))
                inter_min = max(skel_y_min, wall_y_min)
                inter_max = min(skel_y_max, wall_y_max)
                if inter_max > inter_min + 1:
                    ratio_min = (inter_min - skel_y_min) / (skel_y_max - skel_y_min)
                    ratio_max = (inter_max - skel_y_min) / (skel_y_max - skel_y_min)
                    overlapping.append((ratio_min, ratio_max))
        return overlapping

    def _subtract_wall_from_edge(self, skel_line: LineString, wall_intervals: List[Tuple[float, float]]) -> Tuple[List[dict], List[dict]]:
        """
        从边界线中减去剪力墙区间，得到剪力墙和梁

        Args:
            skel_line: 边界线
            wall_intervals: 剪力墙区间列表 [(ratio_min, ratio_max), ...]

        Returns:
            (wall_segments, beam_segments)
        """
        if not wall_intervals:
            return ([], [{'geometry': skel_line, 'type': 'beam', 'length': skel_line.length}])
        sorted_intervals = sorted(wall_intervals, key=lambda x: x[0])
        merged = [[sorted_intervals[0][0], sorted_intervals[0][1]]]
        for start, end in sorted_intervals[1:]:
            if start <= merged[-1][1] + self.gap_tolerance / skel_line.length:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        wall_intervals = [(m[0], m[1]) for m in merged]
        beam_intervals = []
        current = 0.0
        for w_start, w_end in wall_intervals:
            beam_intervals.append((current, w_start))
            current = max(current, w_end)
        beam_intervals.append((current, 1.0))
        coords = list(skel_line.coords)
        p1, p2 = (np.array(coords[0]), np.array(coords[-1]))
        vec = p2 - p1
        wall_segments = []
        beam_segments = []
        for w_start, w_end in wall_intervals:
            start_pt = tuple(p1 + vec * w_start)
            end_pt = tuple(p1 + vec * w_end)
            line = LineString([start_pt, end_pt])
            if line.length > 1e-8:
                wall_segments.append({'geometry': line, 'type': 'shearwall', 'length': line.length})
        for b_start, b_end in beam_intervals:
            start_pt = tuple(p1 + vec * b_start)
            end_pt = tuple(p1 + vec * b_end)
            line = LineString([start_pt, end_pt])
            if line.length > 1e-8:
                beam_segments.append({'geometry': line, 'type': 'beam', 'length': line.length})
        return (wall_segments, beam_segments)

    def _extract_lines(self, geom) -> List[LineString]:
        """从混合几何体中提取 LineString"""
        lines = []
        if geom.is_empty:
            return lines
        if isinstance(geom, LineString):
            lines.append(geom)
        elif isinstance(geom, (MultiLineString, GeometryCollection)):
            for g in geom.geoms:
                if isinstance(g, LineString):
                    lines.append(g)
                elif isinstance(g, MultiLineString):
                    lines.extend(g.geoms)
        return lines

    def _split_at_intersections(self, segments: List[dict]) -> List[dict]:
        """
        在所有构件的交叉点处打断，确保相交处产生共享节点。

        处理两类情况：
        1. 两条线段相交（十字交叉、T字交叉）→ 在交点处打断
        2. 一条线段的端点落在另一条线段内部 → 在该端点处打断

        只处理水平/垂直线段的正交相交。
        """
        tolerance = self.snap_tolerance
        split_ratios: Dict[int, List[float]] = {i: [] for i in range(len(segments))}
        for i in range(len(segments)):
            line_i = segments[i]['geometry']
            ci = list(line_i.coords)
            pi1, pi2 = (np.array(ci[0]), np.array(ci[-1]))
            vec_i = pi2 - pi1
            len_i = np.linalg.norm(vec_i)
            if len_i < 1:
                continue
            is_h_i = abs(vec_i[1]) < tolerance
            is_v_i = abs(vec_i[0]) < tolerance
            if not (is_h_i or is_v_i):
                continue
            for j in range(i + 1, len(segments)):
                line_j = segments[j]['geometry']
                cj = list(line_j.coords)
                pj1, pj2 = (np.array(cj[0]), np.array(cj[-1]))
                vec_j = pj2 - pj1
                len_j = np.linalg.norm(vec_j)
                if len_j < 1:
                    continue
                is_h_j = abs(vec_j[1]) < tolerance
                is_v_j = abs(vec_j[0]) < tolerance
                if not (is_h_j or is_v_j):
                    continue
                if is_h_i == is_h_j:
                    self._check_collinear_splits(pi1, pi2, len_i, pj1, pj2, len_j, is_h_i, tolerance, split_ratios, i, j)
                else:
                    self._check_orthogonal_intersection(pi1, pi2, vec_i, len_i, is_h_i, pj1, pj2, vec_j, len_j, tolerance, split_ratios, i, j)
        result = []
        for idx, seg in enumerate(segments):
            ratios = split_ratios[idx]
            if not ratios:
                result.append(seg)
                continue
            ratios = sorted(set(ratios))
            if not ratios:
                result.append(seg)
                continue
            coords = list(seg['geometry'].coords)
            p1, p2 = (np.array(coords[0]), np.array(coords[-1]))
            vec = p2 - p1
            breakpoints = [0.0] + ratios + [1.0]
            for k in range(len(breakpoints) - 1):
                r_start = breakpoints[k]
                r_end = breakpoints[k + 1]
                start_pt = tuple(p1 + vec * r_start)
                end_pt = tuple(p1 + vec * r_end)
                new_line = LineString([start_pt, end_pt])
                if new_line.length >= 1:
                    result.append({'geometry': new_line, 'type': seg['type'], 'length': new_line.length})
        n_splits = len(result) - len(segments)
        if n_splits > 0:
            print(f'    交叉打断: {len(segments)} -> {len(result)} 段 (+{n_splits})')
        return result

    def _check_collinear_splits(self, pi1, pi2, len_i, pj1, pj2, len_j, is_horizontal, tolerance, split_ratios, i, j):
        """检查共线线段的端点是否落在对方内部，若是则添加打断点"""
        if is_horizontal:
            if abs(pi1[1] - pj1[1]) > tolerance:
                return
            xi_min, xi_max = (min(pi1[0], pi2[0]), max(pi1[0], pi2[0]))
            xj_min, xj_max = (min(pj1[0], pj2[0]), max(pj1[0], pj2[0]))
            for xp in [pj1[0], pj2[0]]:
                if xi_min + tolerance < xp < xi_max - tolerance:
                    r = abs(xp - pi1[0]) / len_i
                    split_ratios[i].append(r)
            for xp in [pi1[0], pi2[0]]:
                if xj_min + tolerance < xp < xj_max - tolerance:
                    r = abs(xp - pj1[0]) / len_j
                    split_ratios[j].append(r)
        else:
            if abs(pi1[0] - pj1[0]) > tolerance:
                return
            yi_min, yi_max = (min(pi1[1], pi2[1]), max(pi1[1], pi2[1]))
            yj_min, yj_max = (min(pj1[1], pj2[1]), max(pj1[1], pj2[1]))
            for yp in [pj1[1], pj2[1]]:
                if yi_min + tolerance < yp < yi_max - tolerance:
                    r = abs(yp - pi1[1]) / len_i
                    split_ratios[i].append(r)
            for yp in [pi1[1], pi2[1]]:
                if yj_min + tolerance < yp < yj_max - tolerance:
                    r = abs(yp - pj1[1]) / len_j
                    split_ratios[j].append(r)

    def _check_orthogonal_intersection(self, pi1, pi2, vec_i, len_i, is_h_i, pj1, pj2, vec_j, len_j, tolerance, split_ratios, i, j):
        """检查正交线段是否相交，若是则在交点处添加打断点"""
        if is_h_i:
            h_y = pi1[1]
            h_xmin, h_xmax = (min(pi1[0], pi2[0]), max(pi1[0], pi2[0]))
            v_x = pj1[0]
            v_ymin, v_ymax = (min(pj1[1], pj2[1]), max(pj1[1], pj2[1]))
        else:
            h_y = pj1[1]
            h_xmin, h_xmax = (min(pj1[0], pj2[0]), max(pj1[0], pj2[0]))
            v_x = pi1[0]
            v_ymin, v_ymax = (min(pi1[1], pi2[1]), max(pi1[1], pi2[1]))
        if not (h_xmin + tolerance < v_x < h_xmax - tolerance and v_ymin + tolerance < h_y < v_ymax - tolerance):
            in_h = h_xmin - tolerance <= v_x <= h_xmax + tolerance
            in_v = v_ymin - tolerance <= h_y <= v_ymax + tolerance
            if not (in_h and in_v):
                return
        cross_x, cross_y = (v_x, h_y)
        if len_i > 1:
            ri = np.dot(np.array([cross_x, cross_y]) - pi1, vec_i) / (len_i * len_i)
            split_ratios[i].append(ri)
        if len_j > 1:
            rj = np.dot(np.array([cross_x, cross_y]) - pj1, vec_j) / (len_j * len_j)
            split_ratios[j].append(rj)

    def _segment_endpoint_keys(self, line: LineString) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """将线段端点离散化为整数网格键值，便于拓扑判断。"""
        coords = list(line.coords)
        p0 = (round(coords[0][0]), round(coords[0][1]))
        p1 = (round(coords[-1][0]), round(coords[-1][1]))
        return (p0, p1)

    def _build_endpoint_segment_map(self, segments: List[dict]) -> Dict[Tuple[int, int], List[int]]:
        """构建端点到构件索引的映射。"""
        endpoint_map: Dict[Tuple[int, int], List[int]] = {}
        for idx, seg in enumerate(segments):
            k0, k1 = self._segment_endpoint_keys(seg['geometry'])
            endpoint_map.setdefault(k0, []).append(idx)
            endpoint_map.setdefault(k1, []).append(idx)
        return endpoint_map

    def _merge_collinear_same_type_segments(self, segments: List[dict]) -> List[dict]:
        """按端点度数=2且共线同类型的条件，迭代合并构件。"""
        merged = list(segments)
        while True:
            endpoint_map = self._build_endpoint_segment_map(merged)
            consumed = set()
            next_segments = []
            for endpoint_key, idxs in endpoint_map.items():
                if len(idxs) != 2:
                    continue
                i, j = (idxs[0], idxs[1])
                if i in consumed or j in consumed:
                    continue
                seg_i = merged[i]
                seg_j = merged[j]
                if seg_i.get('type') != seg_j.get('type'):
                    continue
                if not self._are_segments_collinear(seg_i['geometry'], seg_j['geometry']):
                    continue
                new_line = self._merge_two_segments(seg_i['geometry'], seg_j['geometry'], endpoint_key)
                next_segments.append({'geometry': new_line, 'type': seg_i['type'], 'length': new_line.length})
                consumed.add(i)
                consumed.add(j)
            if not consumed:
                break
            for idx, seg in enumerate(merged):
                if idx not in consumed:
                    next_segments.append(seg)
            merged = next_segments
        return merged

    def _are_segments_collinear(self, line_a: LineString, line_b: LineString) -> bool:
        """判断两条线段是否近似共线（支持水平/垂直）。"""
        tol = self.snap_tolerance
        a0, a1 = (np.array(line_a.coords[0]), np.array(line_a.coords[-1]))
        b0, b1 = (np.array(line_b.coords[0]), np.array(line_b.coords[-1]))
        va = a1 - a0
        vb = b1 - b0
        is_h_a = abs(va[1]) < tol
        is_v_a = abs(va[0]) < tol
        is_h_b = abs(vb[1]) < tol
        is_v_b = abs(vb[0]) < tol
        if is_h_a and is_h_b:
            return abs(a0[1] - b0[1]) < tol
        if is_v_a and is_v_b:
            return abs(a0[0] - b0[0]) < tol
        return False

    def _merge_two_segments(self, line_a: LineString, line_b: LineString, shared_key: Tuple[int, int]) -> LineString:
        """合并两条共享端点的共线线段为一条最长线段。"""
        points = [tuple(line_a.coords[0]), tuple(line_a.coords[-1]), tuple(line_b.coords[0]), tuple(line_b.coords[-1])]
        remaining = [pt for pt in points if (round(pt[0]), round(pt[1])) != shared_key]
        if len(remaining) >= 2:
            p_start, p_end = (remaining[0], remaining[1])
        else:
            max_dist = -1.0
            p_start, p_end = (points[0], points[1])
            for i in range(len(points)):
                for j in range(i + 1, len(points)):
                    dist = float(np.linalg.norm(np.array(points[i]) - np.array(points[j])))
                    if dist > max_dist:
                        max_dist = dist
                        p_start, p_end = (points[i], points[j])
        return LineString([p_start, p_end])

    def _build_topology(self, segments: List[dict]):
        """构建节点和构件列表"""
        self.nodes = []
        self.elements = []
        node_map = {}

        def get_node_id(pt):
            key = (round(pt[0]), round(pt[1]))
            if key not in node_map:
                node_map[key] = len(self.nodes)
                self.nodes.append(key)
            return node_map[key]
        for seg in segments:
            line = seg['geometry']
            coords = list(line.coords)
            u = get_node_id(coords[0])
            v = get_node_id(coords[-1])
            if u == v:
                continue
            self.elements.append({'id': len(self.elements), 'start_node': u, 'end_node': v, 'start_coord': self.nodes[u], 'end_coord': self.nodes[v], 'type': seg['type'], 'length': seg['length']})

    def _classify_beams_by_length_distribution(self):
        """
        基于梁长分布自适应划分主梁/次梁。

        策略：
        1. 收集全部梁长度；
        2. 在排序后的所有可行切分点中，寻找能最大化类间方差的阈值；
        3. 若分布缺乏明显双峰特征，则不强行分类，统一记为主梁。
        """
        beam_indices = [idx for idx, element in enumerate(self.elements) if element['type'] == 'beam']
        beam_lengths = [self.elements[idx]['length'] for idx in beam_indices]
        if not beam_lengths:
            return
        for idx in beam_indices:
            self.elements[idx]['beam_role'] = 'primary'
        if len(beam_lengths) < 3:
            print('    梁分类: 梁数量过少，默认全部视为主梁')
            return
        lengths = np.array(sorted((float(length) for length in beam_lengths)), dtype=float)
        total_mean = float(np.mean(lengths))
        total_var = float(np.var(lengths))
        if total_var <= 1e-06:
            print('    梁分类: 梁长分布几乎无差异，默认全部视为主梁')
            return
        best_score = -1.0
        best_threshold = None
        best_split = None
        min_group_size = max(1, len(lengths) // 5)
        for split_idx in range(min_group_size, len(lengths) - min_group_size + 1):
            left = lengths[:split_idx]
            right = lengths[split_idx:]
            if left[-1] >= right[0]:
                continue
            w0 = len(left) / len(lengths)
            w1 = len(right) / len(lengths)
            mean0 = float(np.mean(left))
            mean1 = float(np.mean(right))
            between_var = w0 * (mean0 - total_mean) ** 2 + w1 * (mean1 - total_mean) ** 2
            if between_var > best_score:
                best_score = between_var
                best_threshold = (left[-1] + right[0]) / 2.0
                best_split = (mean0, mean1, len(left), len(right))
        if best_threshold is None or best_split is None:
            print('    梁分类: 未找到稳定切分点，默认全部视为主梁')
            return
        separability = best_score / total_var
        mean_short, mean_long, _, _ = best_split
        if separability < 0.55:
            print(f'    梁分类: 梁长分布可分性不足 (score={separability:.2f})，默认全部视为主梁')
            return
        secondary_count = 0
        primary_count = 0
        for idx in beam_indices:
            role = 'secondary' if self.elements[idx]['length'] < best_threshold else 'primary'
            self.elements[idx]['beam_role'] = role
            if role == 'secondary':
                secondary_count += 1
            else:
                primary_count += 1
        print(f'    梁分类: threshold={best_threshold:.1f}, 主梁={primary_count} (avg={mean_long:.1f}), 次梁={secondary_count} (avg={mean_short:.1f})')

    def validate_topology(self, result: Optional[dict]=None) -> dict:
        """
        校核拓扑中是否存在孤立点与异常构件。

        检查内容：
        1. 孤立点: 在节点列表中，但没有任何构件连接的点。
        2. 悬挑构件: 仅一端节点度为 1 的构件（另一端连接到主结构）。
        3. 非主连通分量: 不在最大连通分量中的节点和构件（常见于漂浮子结构）。

        Args:
            result: 可选，build() 返回的结果。若不提供则使用当前实例的 self.nodes/self.elements。

        Returns:
            拓扑校核报告字典。
        """
        if result is None:
            nodes = self.nodes
            members = self.elements
        else:
            nodes = result.get('nodes', [])
            members = result.get('members', [])
        num_nodes = len(nodes)
        degree = [0 for _ in range(num_nodes)]
        adjacency: Dict[int, Set[int]] = {i: set() for i in range(num_nodes)}
        member_ids_in_graph: Set[int] = set()
        for member in members:
            u = member['start_node']
            v = member['end_node']
            if 0 <= u < num_nodes:
                degree[u] += 1
            if 0 <= v < num_nodes:
                degree[v] += 1
            if 0 <= u < num_nodes and 0 <= v < num_nodes:
                adjacency[u].add(v)
                adjacency[v].add(u)
                member_ids_in_graph.add(member['id'])
        isolated_node_ids = [i for i, d in enumerate(degree) if d == 0]
        dangling_members = []
        for member in members:
            u = member['start_node']
            v = member['end_node']
            du = degree[u] if 0 <= u < num_nodes else 0
            dv = degree[v] if 0 <= v < num_nodes else 0
            if (du <= 1) != (dv <= 1):
                dangling_members.append({'id': member['id'], 'start_node': u, 'end_node': v, 'start_degree': du, 'end_degree': dv, 'type': member.get('type'), 'length': member.get('length')})
        visited = set()
        components = []
        for node_id in range(num_nodes):
            if node_id in visited:
                continue
            if degree[node_id] == 0:
                visited.add(node_id)
                continue
            stack = [node_id]
            comp_nodes = set()
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                comp_nodes.add(cur)
                for nxt in adjacency[cur]:
                    if nxt not in visited:
                        stack.append(nxt)
            if comp_nodes:
                components.append(comp_nodes)
        largest_comp_nodes: Set[int] = max(components, key=len) if components else set()
        floating_node_ids = sorted([n for n in range(num_nodes) if degree[n] > 0 and n not in largest_comp_nodes])
        floating_member_ids = []
        for member in members:
            if member['start_node'] in floating_node_ids and member['end_node'] in floating_node_ids:
                floating_member_ids.append(member['id'])
        has_issue = bool(isolated_node_ids or dangling_members or floating_member_ids)
        report = {'ok': not has_issue, 'summary': {'num_nodes': num_nodes, 'num_members': len(members), 'num_isolated_nodes': len(isolated_node_ids), 'num_dangling_members': len(dangling_members), 'num_connected_components': len(components), 'num_floating_nodes': len(floating_node_ids), 'num_floating_members': len(floating_member_ids)}, 'isolated_nodes': [{'id': i, 'coord': nodes[i]} for i in isolated_node_ids], 'dangling_members': dangling_members, 'floating_components': {'node_ids': floating_node_ids, 'member_ids': floating_member_ids}}
        if report['ok']:
            print('    拓扑校核通过: 未发现孤立点/悬挑构件/漂浮子结构')
        else:
            print(f"    拓扑校核警告: 孤立点={report['summary']['num_isolated_nodes']}, 悬挑构件={report['summary']['num_dangling_members']}, 漂浮构件={report['summary']['num_floating_members']}")
        return report

    def _compute_slabs(self) -> List[List[Tuple]]:
        """
        计算楼板区域，覆盖所有房间及其间的空洞。

        做法：
        1. 合并所有 room_polys 得到整体轮廓（可能含 holes）
        2. 对每个连通区域：将外轮廓作为一块楼板
        3. 对该区域内部的每个 hole（空洞）：也作为一块楼板（填满过道/大厅等）

        Returns:
            楼板坐标列表，每个楼板为角点 (x, y) 列表（首尾不重复）
        """
        if not self.room_polys:
            return []
        merged = unary_union(self.room_polys)
        if isinstance(merged, Polygon):
            polys = [merged]
        else:
            polys = list(merged.geoms)
        slabs = []
        for poly in polys:
            if poly.is_empty:
                continue
            for interior in poly.interiors:
                slabs.append(list(interior.coords)[:-1])
        for room in self.room_polys:
            slabs.append(list(room.exterior.coords)[:-1])
        total_slab_area = sum((Polygon(slab).area for slab in slabs))
        print(f'    计算楼板: {len(slabs)} 块, 总面积约 {total_slab_area:.2f} 平方单位')
        return slabs

    def _format_result(self) -> dict:
        slabs = self._compute_slabs()
        validation = self.validate_topology()
        return {'nodes': self.nodes, 'members': self.elements, 'slabs': slabs, 'validation': validation, 'statistics': {'num_nodes': len(self.nodes), 'min_xy': np.min(self.nodes, axis=0).tolist(), 'max_xy': np.max(self.nodes, axis=0).tolist(), 'num_members': len(self.elements), 'num_shearwalls': sum((1 for m in self.elements if m['type'] == 'shearwall')), 'num_beams': sum((1 for m in self.elements if m['type'] == 'beam')), 'num_primary_beams': sum((1 for m in self.elements if m['type'] == 'beam' and m.get('beam_role') == 'primary')), 'num_secondary_beams': sum((1 for m in self.elements if m['type'] == 'beam' and m.get('beam_role') == 'secondary')), 'num_slabs': len(slabs), 'total_sw_length': sum((m['length'] for m in self.elements if m['type'] == 'shearwall')), 'total_beam_length': sum((m['length'] for m in self.elements if m['type'] == 'beam'))}}
