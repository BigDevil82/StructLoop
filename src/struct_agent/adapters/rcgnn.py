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
    from struct_agent._vendor.data_engine.preprocess.dxf_extractor import DXFExtractor
    extractor = DXFExtractor()
    extractor.extract_from_file(str(path))
    if not extractor.rooms:
        raise ValueError('Original DXF opening extraction failed; no room data returned')
    payload = {
        "feature_version": "rcgnn_25_8_v1", "length_unit": "m",
        "native_feature_length_unit": "mm", "coordinate_system": "global_xy",
        "x": data.x.tolist(), "edge_index": data.edge_index.tolist(),
        "edge_attr": data.edge_attr.tolist(), "category": category,
        "room_polygons": [[[float(x)/1000., float(y)/1000.] for x,y in a['poly'].exterior.coords]
                          for _,a in nodes],
        "masks": [a['masks'] for _,a in nodes],
        "opening_polygons": [[[float(p.x)/1000., float(p.y)/1000.] for p in points]
                             for points in extractor.doors + extractor.windows],
        "infill_wall_polygons": [[[float(p.x)/1000., float(p.y)/1000.] for p in points]
                                  for points in extractor.infill_walls],
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


def close_wall_junction_gaps(layout: LayoutCandidate, rooms: RoomGraph) -> tuple[LayoutCandidate, list[dict[str, Any]]]:
    """Extend a wall across a <=180 mm beam to a perpendicular wall endpoint.

    Global XY m. Require a unique, unbranched wall tip, unchanged existing joint,
    room-boundary alignment and original opening clearance. The 180 mm policy
    and 200 mm raw-DXF clearance are preprocessing screens, not code limits.
    Mask exceptions apply only here and are recorded, never granted to Agent edits.
    """
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    from struct_agent._vendor.data_engine.preprocess.room_analyzer import get_room_edges
    if rooms.opening_polygons is None:
        return layout, []
    polygons = [Polygon(p) for p in rooms.room_polygons]
    floor = unary_union([Polygon(p) for p in layout.slabs])
    architecture = unary_union(polygons)
    # Match the existing slab generator, which fills interior room-union holes.
    components = (architecture,) if architecture.geom_type == 'Polygon' else architecture.geoms
    expected_floor = unary_union([Polygon(p.exterior) for p in components])
    if floor.hausdorff_distance(expected_floor) > .002:
        raise ValueError('Room graph does not match layout for junction preprocessing')
    boundaries = unary_union([p.boundary for p in polygons]).buffer(.002)
    openings = [Polygon(p) for p in rooms.opening_polygons]
    members = {m.member_id: m for m in layout.members}
    lines = {key: LineString([m.start, m.end]) for key, m in members.items()}
    events = []
    for beam in layout.members:
        key = beam.member_id
        if beam.role == 'wall' or not 1e-8 < lines[key].length <= .18 + 1e-8:
            continue
        axis = lines[key]
        choices = []
        for a, b in ((beam.start, beam.end), (beam.end, beam.start)):
            at_tip = [m for k, m in members.items() if k != key and lines[k].distance(Point(a)) < 1e-8]
            if len(at_tip) != 1 or at_tip[0].role != 'wall':
                continue
            wall = at_tip[0]
            endpoint = 'start' if Point(wall.start).distance(Point(a)) < 1e-8 else 'end'
            if Point(getattr(wall, endpoint)).distance(Point(a)) >= 1e-8:
                continue
            dx, dy = b[0]-a[0], b[1]-a[1]
            wx, wy = wall.end[0]-wall.start[0], wall.end[1]-wall.start[1]
            length = lines[wall.member_id].length
            extended = wall.model_copy(update={endpoint: b})
            extended_line = LineString([extended.start, extended.end])
            if length <= .18 or abs(dx*wy-dy*wx) > 1e-8*axis.length*length:
                continue
            if abs(extended_line.length-length-axis.length) > 1e-8:
                continue
            supports = [m for k, m in members.items() if k != key and m.role == 'wall'
                and min(Point(m.start).distance(Point(b)), Point(m.end).distance(Point(b))) < 1e-8
                and abs(dx*(m.end[0]-m.start[0])+dy*(m.end[1]-m.start[1])) < 1e-8*axis.length*lines[k].length]
            if len(supports) != 1:
                continue
            joint_ends = Point(a).buffer(1e-7).union(Point(b).buffer(1e-7))
            if any(not axis.intersection(g).difference(joint_ends).is_empty
                   for k, g in lines.items() if k != key):
                continue
            choices.append((wall, extended, supports[0], extended_line))
        if len(choices) != 1 or axis.difference(boundaries).length > 1e-8:
            continue
        if axis.difference(floor.buffer(.002)).length > 1e-8:
            continue
        # Raw openings are not moved by the upstream 200 mm coordinate alignment.
        # Reject nearby openings too; do not infer an opening-free zone from masks.
        clearance = min((axis.distance(p) for p in openings), default=None)
        if clearance is not None and clearance <= .2:
            continue
        wall, extended, support, extended_line = choices[0]
        mask_differences = []
        for i, polygon in enumerate(polygons):
            if axis.intersection(polygon.boundary.buffer(.002)).length < axis.length-1e-8:
                continue
            allowed = []
            for edge_index, edge in enumerate(get_room_edges(polygon)):
                for half in (0, 1):
                    for lo, hi in rooms.masks[i][2*edge_index+half]:
                        allowed.append(LineString([edge.interpolate((half+v)/2, normalized=True) for v in (lo, hi)]))
            outside = axis.difference(unary_union(allowed).buffer(.002)).length
            if outside > 1e-8:
                mask_differences.append({'room_index': i, 'outside_mask_axis_m': outside})
        members[wall.member_id] = extended
        lines[wall.member_id] = extended_line
        del members[key], lines[key]
        events.append({'operation': 'close_wall_junction_gap', 'removed_beam_id': key,
            'extended_wall_id': wall.member_id, 'support_wall_id': support.member_id,
            'before_wall': wall.model_dump(mode='json'), 'after_wall': extended.model_dump(mode='json'),
            'removed_beam': beam.model_dump(mode='json'), 'extension_m': axis.length,
            'opening_clearance_m': clearance, 'opening_screen_m': .2,
            'mask_exceptions': mask_differences,
            'basis': 'Unique collinear wall tip joined to existing perpendicular wall endpoint; original openings checked.'})
    result = LayoutCandidate.model_validate({**layout.model_dump(), 'members': tuple(members.values())})
    return result, events


def _normalize_generated_slabs(layout: LayoutCandidate) -> LayoutCandidate:
    """Remove overlapping generated slab area before mass/load summation. XY m."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polygons = [Polygon(p) for p in layout.slabs]
    floor = unary_union(polygons)
    if sum(p.area for p in polygons)-floor.area <= 1e-8:
        return layout
    components = (floor,) if floor.geom_type == 'Polygon' else tuple(floor.geoms)
    if any(p.interiors for p in components):
        raise ValueError('Overlapping generated slabs contain unresolved interior openings')
    slabs = tuple(tuple((float(x),float(y)) for x,y in p.exterior.coords) for p in components)
    return layout.model_copy(update={'slabs':slabs})


def layout_from_prediction(graph: RoomGraph, ratios: np.ndarray, *, layout_id: str,
                           symmetry_axis_mm: float | None = None,
                           beam_grid_mode: str = "legacy") -> LayoutCandidate:
    """Build predicted walls; optional screening creates a trial beam grid."""
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
    prepared = close_wall_junction_gaps(preprocess_short_members(_normalize_generated_slabs(layout)), graph)[0]
    if beam_grid_mode == "legacy":
        return prepared
    if beam_grid_mode != "screened":
        raise ValueError("beam_grid_mode must be legacy or screened")
    from struct_agent.services.beam_layout import prune_redundant_beams
    return prune_redundant_beams(prepared, graph)


def trace_layout_generation(graph: RoomGraph, ratios: np.ndarray, layout: LayoutCandidate,
                            *, beam_grid_mode: str = "legacy") -> dict[str, Any]:
    """Read-only replay of the fixed generator; intermediate global XY in m.

    No trained inference or FEA is rerun. The final replay must match the supplied
    layout exactly; otherwise these stages cannot be cited as its provenance.
    """
    import hashlib
    from shapely.geometry import Polygon
    from struct_agent._vendor.data_engine.postprocess.fem_builder import FEMTopologyBuilder
    from struct_agent._vendor.data_engine.postprocess.topology_cleanup import clean_segments
    builder=FEMTopologyBuilder(gap_tolerance=200.,min_length=100.)
    for poly,mask,row in zip(graph.room_polygons,graph.masks,ratios):
        builder.add_room(Polygon([(x*1000,y*1000) for x,y in poly]),row,mask)
    stages={}
    def capture(name: str, segments: list[dict[str, Any]]) -> None:
        stages[name]=[{'role':'wall' if s['type']=='shearwall' else 'beam',
            'start':[float(v)/1000 for v in s['geometry'].coords[0]],
            'end':[float(v)/1000 for v in s['geometry'].coords[-1]],
            'axis_length_m':s['geometry'].length/1000} for s in segments]
    capture('predicted_wall_intervals',[{'geometry':g,'type':'shearwall'} for g in builder.raw_walls])
    skeleton=builder._merge_collinear_lines(builder.room_edges)
    walls=builder._merge_collinear_lines(builder.raw_walls)
    capture('merged_wall_intervals',[{'geometry':g,'type':'shearwall'} for g in walls])
    segments=[]
    for edge in skeleton:
        overlaps=builder._find_overlapping_segments(edge,walls)
        if overlaps:
            wall_parts,beam_parts=builder._subtract_wall_from_edge(edge,overlaps)
            segments.extend(wall_parts+beam_parts)
        else:
            segments.append({'geometry':edge,'type':'beam'})
    capture('boundary_minus_walls',segments)
    segments=builder._split_at_intersections(segments)
    capture('intersection_split',segments)
    segments=clean_segments(segments,snap_tolerance=builder.snap_tolerance,min_wall_length=builder.min_length)
    capture('numerical_cleanup',segments)
    segments=builder._merge_collinear_same_type_segments(segments)
    capture('collinear_merge',segments)
    builder._build_topology(segments)
    builder._classify_beams_by_length_distribution()
    result=builder._format_result()
    raw={'shearwalls':[],'beams':[],'slabs':result['slabs']}
    for m in result['members']:
        row={'start':m['start_coord'],'end':m['end_coord']}
        if m['type']=='shearwall':raw['shearwalls'].append(row)
        else:raw['beams'].append({**row,'beam_role':m['beam_role']})
    before=layout_from_legacy(raw,unit='mm',layout_id=layout.layout_id,source=layout.source)
    original_slab_area = sum(Polygon(p).area for p in before.slabs)
    before = _normalize_generated_slabs(before)
    replay=preprocess_short_members(before)
    stages['before_wall_junction_closure']=[m.model_dump(mode='json') for m in replay.members]
    replay,junction_closures=close_wall_junction_gaps(replay,graph)
    stages['before_redundant_beam_pruning']=[m.model_dump(mode='json') for m in replay.members]
    if beam_grid_mode == "screened":
        from struct_agent.services.beam_layout import prune_redundant_beams
        replay=prune_redundant_beams(replay,graph)
    elif beam_grid_mode != "legacy":
        raise ValueError("beam_grid_mode must be legacy or screened")
    if replay!=layout:
        raise ValueError('Generation replay differs from this layout; provenance is unavailable')
    stages['before_short_member_preprocessing']=[m.model_dump(mode='json') for m in before.members]
    stages['final_layout']=[m.model_dump(mode='json') for m in replay.members]
    from .fea import native_topology
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import wall_piers
    chains=[]
    for chain in wall_piers(native_topology(before).beams):
        parts=[before.members[i] for i in chain.source_ids]
        chains.append({'members':[m.model_dump(mode='json') for m in parts],
            'axis_chain_length_m':chain.member.length,'below_conversion_threshold':chain.member.length<=.18+1e-8})
    return {'verified':True,'layout_sha256':hashlib.sha256(layout.model_dump_json().encode()).hexdigest(),
        'units':'global_xy_m','stages':stages,'preprocessing_beam_chains':chains,
        'junction_closures':junction_closures,'original_openings_available':graph.opening_polygons is not None,
        'slab_preprocessing':{'original_area_m2':original_slab_area,
            'normalized_area_m2':sum(Polygon(p).area for p in before.slabs),
            'overlap_removed_m2':original_slab_area-sum(Polygon(p).area for p in before.slabs)},
        'preprocessing_chain_rule':'Endpoint-connected collinear beam chains are grouped without splitting at perpendicular wall supports; the 180mm test applies to the chain, not each FE beam segment.',
        'settings':{'snap_tolerance_m':.002,'wall_gap_merge_m':.2,'min_wall_length_m':.1,
                    'beam_grid_mode':beam_grid_mode},
        'scope':'Replayed generator and adapter preprocessing, not original construction intent or DXF semantic validation.'}
