from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class LayoutFeatureConfig:
    layout_dir: str = 'data\\dxf\\cad_json_data\\fem_raw'
    xy_scale_to_m: float = 0.001
    boundary_band_ratio: float = 0.15

def extract_layout_features(cfg: LayoutFeatureConfig) -> pd.DataFrame:
    layout_paths = sorted(Path(cfg.layout_dir).glob('*.json'))
    if not layout_paths:
        raise ValueError(f'No layout json files found in {cfg.layout_dir}.')
    rows = [_extract_one_layout(path, cfg.xy_scale_to_m, cfg.boundary_band_ratio) for path in layout_paths]
    return pd.DataFrame(rows).sort_values('layout_id').reset_index(drop=True)

def merge_layout_features(sample_df: pd.DataFrame, feature_df: pd.DataFrame, *, on: str='layout_id') -> pd.DataFrame:
    merged = sample_df.merge(feature_df, on=on, how='left', validate='many_to_one')
    missing = int(merged.filter(like='bbox_').isna().all(axis=1).sum())
    if missing > 0:
        raise ValueError(f'Missing layout features for {missing} samples.')
    return merged

def _extract_one_layout(path: Path, xy_scale_to_m: float, boundary_band_ratio: float) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding='utf-8'))
    layout_id = path.stem
    walls = data.get('shearwalls', [])
    beams = data.get('beams', [])
    wall_segments = [_segment_record(item, xy_scale_to_m) for item in walls]
    beam_segments = [_segment_record(item, xy_scale_to_m) for item in beams]
    all_points: list[tuple[float, float]] = []
    for seg in wall_segments + beam_segments:
        all_points.append((seg['x1'], seg['y1']))
        all_points.append((seg['x2'], seg['y2']))
    if not all_points:
        raise ValueError(f'layout {layout_id} has no walls/beams.')
    xs = np.array([p[0] for p in all_points], dtype=float)
    ys = np.array([p[1] for p in all_points], dtype=float)
    x_min = float(xs.min())
    x_max = float(xs.max())
    y_min = float(ys.min())
    y_max = float(ys.max())
    bbox_x = x_max - x_min
    bbox_y = y_max - y_min
    bbox_area = bbox_x * bbox_y
    aspect_ratio = bbox_x / max(bbox_y, 1e-09)
    cx_plan = 0.5 * (x_min + x_max)
    cy_plan = 0.5 * (y_min + y_max)
    wall_lengths = np.array([seg['length'] for seg in wall_segments], dtype=float)
    wall_mid_x = np.array([seg['mx'] for seg in wall_segments], dtype=float) if wall_segments else np.array([])
    wall_mid_y = np.array([seg['my'] for seg in wall_segments], dtype=float) if wall_segments else np.array([])
    num_walls = int(len(wall_segments))
    wall_total_length = float(wall_lengths.sum()) if num_walls else 0.0
    wall_mean_length = float(wall_lengths.mean()) if num_walls else 0.0
    wall_max_length = float(wall_lengths.max()) if num_walls else 0.0
    wall_min_length = float(wall_lengths.min()) if num_walls else 0.0
    wall_std_length = float(wall_lengths.std(ddof=0)) if num_walls else 0.0
    wall_x_length, wall_y_length, wall_x_count, wall_y_count = _direction_stats(wall_segments)
    wall_xy_ratio = wall_x_length / max(wall_y_length, 1e-09)
    if wall_total_length > 1e-09:
        cx_wall = float(np.average(wall_mid_x, weights=wall_lengths))
        cy_wall = float(np.average(wall_mid_y, weights=wall_lengths))
        wall_x_std = float(np.sqrt(np.average((wall_mid_x - cx_wall) ** 2, weights=wall_lengths)))
        wall_y_std = float(np.sqrt(np.average((wall_mid_y - cy_wall) ** 2, weights=wall_lengths)))
    else:
        cx_wall = cx_plan
        cy_wall = cy_plan
        wall_x_std = 0.0
        wall_y_std = 0.0
    ecc_center = float(np.hypot(cx_wall - cx_plan, cy_wall - cy_plan))
    ecc_center_norm = ecc_center / max(np.hypot(bbox_x, bbox_y), 1e-09)
    quad_1, quad_2, quad_3, quad_4 = _quadrant_ratios(wall_segments, cx_plan, cy_plan, wall_total_length)
    num_main_beams, num_sec_beams, main_len, sec_len = _beam_stats(beams, xy_scale_to_m)
    beam_total_length = main_len + sec_len
    beam_wall_count_ratio = (num_main_beams + num_sec_beams) / max(num_walls, 1)
    beam_wall_length_ratio = beam_total_length / max(wall_total_length, 1e-09)
    num_joints, avg_degree, max_degree, num_components = _topology_stats(walls, beams)
    ixx_wall, iyy_wall, j_wall = _wall_second_moments(wall_segments, cx_plan, cy_plan)
    wall_xy_imbalance = abs(wall_x_length - wall_y_length) / max(wall_x_length + wall_y_length, 1e-09)
    boundary_wall_ratio = _boundary_wall_ratio(wall_segments, x_min, x_max, y_min, y_max, boundary_band_ratio)
    return {'layout_id': layout_id, 'bbox_x': bbox_x, 'bbox_y': bbox_y, 'bbox_area': bbox_area, 'aspect_ratio': aspect_ratio, 'num_walls': num_walls, 'wall_total_length': wall_total_length, 'wall_mean_length': wall_mean_length, 'wall_max_length': wall_max_length, 'wall_min_length': wall_min_length, 'wall_std_length': wall_std_length, 'wall_x_total': wall_x_length, 'wall_y_total': wall_y_length, 'wall_xy_ratio': wall_xy_ratio, 'wall_x_count': wall_x_count, 'wall_y_count': wall_y_count, 'cx_wall': cx_wall, 'cy_wall': cy_wall, 'ecc_center': ecc_center, 'ecc_center_norm': ecc_center_norm, 'wall_x_std': wall_x_std, 'wall_y_std': wall_y_std, 'quad_1': quad_1, 'quad_2': quad_2, 'quad_3': quad_3, 'quad_4': quad_4, 'num_main_beams': num_main_beams, 'num_sec_beams': num_sec_beams, 'main_beam_total_length': main_len, 'sec_beam_total_length': sec_len, 'beam_total_length': beam_total_length, 'beam_wall_count_ratio': beam_wall_count_ratio, 'beam_wall_length_ratio': beam_wall_length_ratio, 'num_joints': num_joints, 'avg_degree': avg_degree, 'max_degree': max_degree, 'num_components': num_components, 'Ixx_wall': ixx_wall, 'Iyy_wall': iyy_wall, 'J_wall': j_wall, 'wall_xy_imbalance': wall_xy_imbalance, 'boundary_wall_ratio': boundary_wall_ratio}

def _segment_record(item: dict[str, Any], xy_scale_to_m: float) -> dict[str, float]:
    x1 = float(item['start'][0]) * xy_scale_to_m
    y1 = float(item['start'][1]) * xy_scale_to_m
    x2 = float(item['end'][0]) * xy_scale_to_m
    y2 = float(item['end'][1]) * xy_scale_to_m
    length = float(np.hypot(x2 - x1, y2 - y1))
    return {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'mx': 0.5 * (x1 + x2), 'my': 0.5 * (y1 + y2), 'dx': x2 - x1, 'dy': y2 - y1, 'length': length}

def _direction_stats(segments: list[dict[str, float]]) -> tuple[float, float, int, int]:
    x_total = 0.0
    y_total = 0.0
    x_count = 0
    y_count = 0
    for seg in segments:
        if abs(seg['dx']) >= abs(seg['dy']):
            x_total += seg['length']
            x_count += 1
        else:
            y_total += seg['length']
            y_count += 1
    return (x_total, y_total, x_count, y_count)

def _quadrant_ratios(wall_segments: list[dict[str, float]], cx_plan: float, cy_plan: float, wall_total_length: float) -> tuple[float, float, float, float]:
    if wall_total_length <= 1e-09:
        return (0.0, 0.0, 0.0, 0.0)
    q = [0.0, 0.0, 0.0, 0.0]
    for seg in wall_segments:
        mx = seg['mx']
        my = seg['my']
        length = seg['length']
        if mx >= cx_plan and my >= cy_plan:
            q[0] += length
        elif mx < cx_plan and my >= cy_plan:
            q[1] += length
        elif mx < cx_plan and my < cy_plan:
            q[2] += length
        else:
            q[3] += length
    return (q[0] / wall_total_length, q[1] / wall_total_length, q[2] / wall_total_length, q[3] / wall_total_length)

def _beam_stats(beams: list[dict[str, Any]], xy_scale_to_m: float) -> tuple[int, int, float, float]:
    num_main = 0
    num_sec = 0
    len_main = 0.0
    len_sec = 0.0
    for beam in beams:
        dx = (float(beam['end'][0]) - float(beam['start'][0])) * xy_scale_to_m
        dy = (float(beam['end'][1]) - float(beam['start'][1])) * xy_scale_to_m
        length = float(np.hypot(dx, dy))
        role = str(beam.get('beam_role', 'primary')).strip().lower()
        if role == 'secondary':
            num_sec += 1
            len_sec += length
        else:
            num_main += 1
            len_main += length
    return (num_main, num_sec, len_main, len_sec)

def _topology_stats(walls: list[dict[str, Any]], beams: list[dict[str, Any]]) -> tuple[int, float, int, int]:
    adjacency: dict[int, set[int]] = {}

    def add_edge(u: int, v: int) -> None:
        if u == v:
            return
        adjacency.setdefault(u, set()).add(v)
        adjacency.setdefault(v, set()).add(u)
    for item in walls + beams:
        if 'start_node' not in item or 'end_node' not in item:
            continue
        add_edge(int(item['start_node']), int(item['end_node']))
    if not adjacency:
        return (0, 0.0, 0, 0)
    nodes = list(adjacency.keys())
    degrees = [len(adjacency[n]) for n in nodes]
    num_joints = len(nodes)
    avg_degree = float(np.mean(degrees)) if degrees else 0.0
    max_degree = int(max(degrees)) if degrees else 0
    visited: set[int] = set()
    components = 0
    for node in nodes:
        if node in visited:
            continue
        components += 1
        stack = [node]
        visited.add(node)
        while stack:
            cur = stack.pop()
            for nxt in adjacency[cur]:
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append(nxt)
    return (num_joints, avg_degree, max_degree, components)

def _wall_second_moments(wall_segments: list[dict[str, float]], cx_plan: float, cy_plan: float) -> tuple[float, float, float]:
    if not wall_segments:
        return (0.0, 0.0, 0.0)
    ixx = 0.0
    iyy = 0.0
    for seg in wall_segments:
        length = seg['length']
        dx = seg['mx'] - cx_plan
        dy = seg['my'] - cy_plan
        ixx += length * dy * dy
        iyy += length * dx * dx
    return (ixx, iyy, ixx + iyy)

def _boundary_wall_ratio(wall_segments: list[dict[str, float]], x_min: float, x_max: float, y_min: float, y_max: float, boundary_band_ratio: float) -> float:
    if not wall_segments:
        return 0.0
    span = min(x_max - x_min, y_max - y_min)
    band = max(0.0, boundary_band_ratio * span)
    boundary_count = 0
    for seg in wall_segments:
        mx = seg['mx']
        my = seg['my']
        is_boundary = abs(mx - x_min) <= band or abs(mx - x_max) <= band or abs(my - y_min) <= band or (abs(my - y_max) <= band)
        if is_boundary:
            boundary_count += 1
    return boundary_count / max(len(wall_segments), 1)
