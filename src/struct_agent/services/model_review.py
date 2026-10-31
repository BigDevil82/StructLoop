"""Preflight model semantics; software policies are not universal code limits."""
from __future__ import annotations

from typing import Literal
from pydantic import Field

from struct_agent.schemas import DesignCandidate, LayoutCandidate, RoomGraph
from struct_agent.schemas.base import Contract
from struct_agent.adapters.fea import native_topology
from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import wall_piers, beam_spans


class GeometryIssue(Contract):
    code: Literal['SHORT_WALL_PIER', 'COLUMN_OR_COMPOSITE_DESIGN_REQUIRED', 'BEAM_SPAN_REVIEW']
    source_member_ids: tuple[str, ...] = Field(min_length=1)
    length_m: float = Field(gt=0.)
    ratio: float | None = Field(default=None, gt=0.)


class ModelGeometryReview(Contract):
    wall_merge_review_threshold_m: float = Field(gt=0.)
    physical_wall_pier_count: int = Field(ge=1)
    mesh_wall_segment_count: int = Field(ge=1)
    requires_model_repair: bool
    issues: tuple[GeometryIssue, ...]
    interpretation: str = 'Model review only; absence of listed issues is not engineering validation.'


def review_geometry(layout: LayoutCandidate, *, design: DesignCandidate | None = None,
                    wall_merge_review_threshold_m: float = .18) -> ModelGeometryReview:
    """Flag short physical piers, rather than every short FE subdivision.

    The 180 mm review policy is sourced from the installed YJK-A manual's model
    conversion chapter. It is NOT a general minimum wall length from a code.
    Ratios below are routing indicators, not substitute capacity checks.
    """
    if wall_merge_review_threshold_m <= 0:
        raise ValueError('Positive model review threshold required')
    topology = native_topology(layout)
    walls = topology.walls
    piers = wall_piers(walls)
    issues = []
    thickness = max(float(design.values[k]) for k in ('tw_bot','tw_mid','tw_top')) if design else None
    for pier in piers:
        source = tuple(layout.members[i].member_id for i in pier.source_ids)
        length = pier.member.length
        if length <= wall_merge_review_threshold_m+1e-8:
            issues.append(GeometryIssue(code='SHORT_WALL_PIER', source_member_ids=source, length_m=length))
        if thickness is not None and length / thickness < 4.:
            issues.append(GeometryIssue(code='COLUMN_OR_COMPOSITE_DESIGN_REQUIRED', source_member_ids=source,
                length_m=length, ratio=length/thickness))
    if design:
        for span in beam_spans(topology.beams,walls):
            depth = max(float(design.values['hb_main' if layout.members[i].role == 'primary' else 'hb_sec']) for i in span.source_ids)
            length = span.length
            if length / depth < 2.:
                issues.append(GeometryIssue(code='BEAM_SPAN_REVIEW', source_member_ids=tuple(layout.members[i].member_id for i in span.source_ids),
                    length_m=length, ratio=length/depth))
    return ModelGeometryReview(wall_merge_review_threshold_m=wall_merge_review_threshold_m,
        physical_wall_pier_count=len(piers), mesh_wall_segment_count=len(walls),
        requires_model_repair=any(i.code=='SHORT_WALL_PIER' for i in issues), issues=tuple(issues))


def review_local_layout_change(original: LayoutCandidate, candidate: LayoutCandidate, rooms: RoomGraph,
                               *, design: DesignCandidate) -> tuple[str, ...]:
    """Check one collinear wall-tip move against architecture and node connectivity.

    Global XY metres. Room masks constrain ADDED wall centreline, including every
    incident room's exclusions. Existing accepted walls are not reclassified.
    The repeated standard floor changes on every storey; slab polygons stay fixed.
    """
    import math
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    from struct_agent._vendor.data_engine.preprocess.room_analyzer import get_room_edges

    if original.slabs != candidate.slabs:
        return ('slab_or_architectural_geometry_changed',)
    if tuple((m.member_id,m.role) for m in original.members) != tuple((m.member_id,m.role) for m in candidate.members):
        return ('member_identity_or_role_changed',)
    floor=unary_union([Polygon(p) for p in original.slabs])
    architecture=unary_union([Polygon(p) for p in rooms.room_polygons])
    if floor.hausdorff_distance(architecture)>.002:
        return ('room_graph_does_not_match_layout',)
    changes=[(a,b) for a,b in zip(original.members,candidate.members) if a!=b]
    if len(changes)!=2 or sum(a.role=='wall' for a,_ in changes)!=1:
        return ('require_one_wall_and_one_beam_joint',)
    old_points=[];new_points=[]
    for a,b in changes:
        for x,y in zip((a.start,a.end),(b.start,b.end)):
            if x!=y:old_points.append(x);new_points.append(y)
        dx,dy=a.end[0]-a.start[0],a.end[1]-a.start[1]
        if any(abs(dx*(p[1]-a.start[1])-dy*(p[0]-a.start[0]))/math.hypot(dx,dy)>1e-7 for p in (b.start,b.end)):
            return ('member_axis_changed',)
        # Never pass the far end, reverse a member, or introduce a vanishing member.
        if (b.end[0]-b.start[0])*dx+(b.end[1]-b.start[1])*dy<=0:
            return ('member_reversed',)
        # Existing short coupling beams may be lengthened incrementally. Do not
        # require a repair to jump directly above the span/depth review threshold.
        minimum=.18 if a.role=='wall' else min(math.dist(a.start,a.end),
            2*float(design.values['hb_main' if a.role=='primary' else 'hb_sec']))
        if math.dist(b.start,b.end)<=minimum+1e-8:
            return ('residual_wall_too_short' if a.role=='wall' else 'residual_beam_span_too_short',)
    if len(old_points)!=2 or old_points[0]!=old_points[1] or new_points[0]!=new_points[1]:
        return ('joint_not_moved_together',)
    old,new=old_points[0],new_points[0]
    touching=[m for m in original.members if LineString([m.start,m.end]).distance(Point(old))<1e-7]
    if len(touching)!=2:
        return ('branch_or_support_node_is_fixed',)
    if any(m not in [a for a,_ in changes] and LineString([m.start,m.end]).distance(Point(new))<.002 for m in original.members):
        return ('new_joint_collides_with_other_member',)
    old_lines=unary_union([LineString([a.start,a.end]) for a,_ in changes])
    new_lines=unary_union([LineString([b.start,b.end]) for _,b in changes])
    if old_lines.hausdorff_distance(new_lines)>1e-7:
        return ('structural_axis_or_support_coverage_changed',)
    wall_before,wall_after=next((a,b) for a,b in changes if a.role=='wall')
    added=LineString([wall_after.start,wall_after.end]).difference(LineString([wall_before.start,wall_before.end]))
    if added.length>1e-8:
        boundaries=[];forbidden=[]
        for poly,mask in zip(rooms.room_polygons,rooms.masks):
            for edge_index,edge in enumerate(get_room_edges(Polygon(poly))):
                midpoint=edge.interpolate(.5,normalized=True)
                halves=(LineString([edge.coords[0],midpoint]),LineString([midpoint,edge.coords[-1]]))
                for side,half in enumerate(halves):
                    allowed=unary_union([LineString([half.interpolate(a,normalized=True),half.interpolate(b,normalized=True)])
                        for a,b in mask[2*edge_index+side] if b>a])
                    boundaries.append(half)
                    forbidden.append(half.difference(allowed))
        if added.difference(unary_union(boundaries).buffer(.002,cap_style=2)).length>1e-7:
            return ('wall_growth_outside_architectural_edge',)
        if added.intersection(unary_union(forbidden).buffer(.001,cap_style=2)).length>.002:
            return ('wall_growth_intersects_door_window_or_nonbuildable_interval',)
    if review_geometry(candidate,design=design).requires_model_repair:
        return ('new_short_physical_wall_requires_preprocessing',)
    return ()
