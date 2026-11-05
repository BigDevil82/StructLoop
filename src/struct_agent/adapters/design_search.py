"""Bounded discrete proposals; improvements are accepted only after evaluation.

Dimensions here are native integer mm, concrete is a grade string. Increasing
sections need not improve all constraints because stiffness redistributes loads.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
import hashlib
import json
import math

from struct_agent._vendor.shearwall_optimization.core.contracts import EvaluationResult, VariableSpec
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec, RoomGraph, Member
from struct_agent.schemas.diagnostics import MemberDiagnostic
from struct_agent.schemas.layout import WallTipMove, LocalLayoutProposal, LocalLayoutSearch
from struct_agent.schemas.state import DesignModification, ParameterModification, LayoutRepairModification


def apply_design_modification(layout: LayoutCandidate, rooms: RoomGraph, design: DesignCandidate,
        instruction: DesignModification, *, protected_member_ids: frozenset[str]=frozenset()) -> LayoutCandidate:
    """Compile an Agent's signed wall-length change; coordinates global XY m.

    This executes no analysis and changes neither sections nor architectural data.
    """
    from struct_agent.services.model_review import review_local_layout_change
    by_id={m.member_id:m for m in layout.members}
    if design.layout_id!=layout.layout_id:
        raise ValueError('Design/layout mismatch')
    if instruction.source_layout_sha256!=hashlib.sha256(layout.model_dump_json().encode()).hexdigest():
        raise ValueError('Stale source layout')
    ids={instruction.target_member_id,instruction.connected_member_id}
    if ids-set(by_id) or ids&protected_member_ids:
        raise ValueError('Unknown or protected target member')
    wall,beam=by_id[instruction.target_member_id],by_id[instruction.connected_member_id]
    if wall.role!='wall' or beam.role=='wall':
        raise ValueError('A wall and its connected beam are required')
    joint=getattr(wall,instruction.endpoint)
    if joint not in (beam.start,beam.end):
        raise ValueError('Selected endpoint is not shared by the wall and beam')
    root=wall.end if instruction.endpoint=='start' else wall.start
    length=math.dist(root,joint)
    moved=tuple(round(joint[i]+instruction.delta_length_m*(joint[i]-root[i])/length,6) for i in range(2))
    changed=[]
    for member in layout.members:
        data=member.model_dump()
        if member.member_id in ids:
            data.update(start=moved if member.start==joint else member.start,
                        end=moved if member.end==joint else member.end)
        changed.append(Member.model_validate(data))
    digest=hashlib.sha256(json.dumps([m.model_dump() for m in changed],sort_keys=True).encode()).hexdigest()[:12]
    candidate=LayoutCandidate.model_validate({**layout.model_dump(),'layout_id':f'{layout.layout_id}_agent_{digest}',
        'source':'agent_design_modification','members':tuple(changed)})
    issues=review_local_layout_change(layout,candidate,rooms,design=design)
    if issues:
        raise ValueError(', '.join(issues))
    return candidate


def apply_parameter_modification(layout: LayoutCandidate, design: DesignCandidate, spec: ProjectSpec,
        instruction: ParameterModification, *, protected_member_ids: frozenset[str]=frozenset()) -> DesignCandidate:
    """Validate partial section/material edits without changing geometry or conditions.

    Public lengths m, whole mm required by the backend. Variables are shared by
    their role/storey zones; conc_bot currently sets all three concrete zones.
    """
    from .fea import native_params
    if design.layout_id != layout.layout_id:
        raise ValueError('Design/layout mismatch')
    if instruction.source_layout_sha256 != hashlib.sha256(layout.model_dump_json().encode()).hexdigest():
        raise ValueError('Stale source layout')
    values = {**design.values, **instruction.parameter_updates}
    changed = {k for k in values if values[k] != design.values[k]}
    if not changed:
        raise ValueError('Parameter update does not change the current design')
    roles = {'conc_bot': {'wall', 'primary', 'secondary'},
        'tw_bot': {'wall'}, 'tw_mid': {'wall'}, 'tw_top': {'wall'},
        'hb_main': {'primary'}, 'bb_main': {'primary'},
        'hb_sec': {'secondary'}, 'bb_sec': {'secondary'}}
    affected = set().union(*(roles[k] for k in changed))
    by_id = {m.member_id: m for m in layout.members}
    if protected_member_ids-set(by_id):
        raise ValueError('Unknown protected member')
    if any(by_id[k].role in affected for k in protected_member_ids):
        raise ValueError('Shared parameter update affects a protected member')
    digest = hashlib.sha256(json.dumps([layout.layout_id, design.condition_id, values], sort_keys=True).encode()).hexdigest()[:16]
    candidate = DesignCandidate(design_id=f'agent_parameters_{digest}', layout_id=layout.layout_id,
        condition_id=design.condition_id, values=values)
    native_params(candidate, spec)  # Exact domains, condition binding and mm conversion; no FEA.
    return candidate


def apply_layout_repair(layout: LayoutCandidate, rooms: RoomGraph, design: DesignCandidate,
        instruction: LayoutRepairModification, *,
        protected_member_ids: frozenset[str] = frozenset()) -> LayoutCandidate:
    """Repair reviewed generated geometry, retaining every source ID and axis.

    The Agent selects objects/repair types, not coordinates or FE element types.
    All changes remain trials until full FEA and explicit adoption.
    """
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    from struct_agent.services.model_review import inspect_layout_relations
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import beam_spans, wall_piers
    from .fea import native_topology
    if design.layout_id != layout.layout_id or instruction.source_layout_sha256 != hashlib.sha256(layout.model_dump_json().encode()).hexdigest():
        raise ValueError('Stale source layout or design mismatch')
    architecture = unary_union([Polygon(p) for p in rooms.room_polygons])
    components = (architecture,) if architecture.geom_type == 'Polygon' else architecture.geoms
    expected_floor = unary_union([Polygon(p.exterior) for p in components])
    if unary_union([Polygon(p) for p in layout.slabs]).hausdorff_distance(expected_floor) > .002:
        raise ValueError('Room graph does not match layout')
    candidate = layout
    for step in instruction.repairs:
        by_id = {m.member_id: m for m in candidate.members}
        selected = set(step.member_ids)
        if selected-set(by_id):
            raise ValueError('Unknown repair member')
        relations = inspect_layout_relations(candidate, rooms, design)
        members = list(candidate.members)
        if step.kind == 'remove_unsupported_wall_group':
            group = next((g for g in relations['small_wall_groups'] if selected <= set(g['source_member_ids'])), None)
            if group is None:
                raise ValueError('No complete unsupported short-wall group: attached long walls cannot be retyped')
            ids = set(group['source_member_ids'])
            members = [m.model_copy(update={'role': 'secondary'}) if m.member_id in ids else m for m in members]
        elif step.kind == 'trim_wall_return':
            if len(selected) != 1:
                raise ValueError('Inspect and select one wall-end return')
            m = by_id[next(iter(selected))]
            if m.role != 'wall' or math.dist(m.start, m.end) > .18:
                raise ValueError('Only an existing wall-end return of at most 180 mm can be repaired')
            topology = native_topology(candidate)
            pier = next(p for p in wall_piers(topology.walls) if candidate.members.index(m) in p.source_ids)
            if pier.member.length < .8:
                raise ValueError('Wall return must belong to a longer physical wall')
            contacts = [[n for n in members if n != m and LineString([n.start, n.end]).distance(Point(p)) < 1e-7]
                        for p in (m.start, m.end)]
            if not any(len(c) == 1 and c[0].role != 'wall' for c in contacts):
                raise ValueError('Return has no free wall/beam tip; real branch/support nodes cannot be crossed')
            members = [n.model_copy(update={'role': 'secondary'}) if n == m else n for n in members]
        elif step.kind == 'unify_beam_span':
            if any(by_id[i].role == 'wall' for i in selected):
                raise ValueError('Select beam members, not walls, for beam section classification')
            ids = {candidate.members[i].member_id for span in beam_spans(native_topology(candidate).beams,
                    native_topology(candidate).walls)
                   if selected.intersection(candidate.members[i].member_id for i in span.source_ids)
                   for i in span.source_ids}
            members = [m.model_copy(update={'role': step.beam_role}) if m.member_id in ids else m for m in members]
        else:
            if rooms.opening_polygons is None:
                raise ValueError('Original opening geometry is unavailable; cannot align openings')
            openings = unary_union([Polygon(p) for p in rooms.opening_polygons])
            for member_id in selected:
                i = next(i for i, m in enumerate(members) if m.member_id == member_id)
                m = members[i]
                if m.role != 'wall':
                    raise ValueError('Opening alignment requires a wall')
                line = LineString([m.start, m.end])
                if line.intersection(openings).length < 1e-7:
                    raise ValueError(f'{member_id} does not intrude into an opening')
                remaining = line.difference(openings.buffer(.001, join_style=2))
                if remaining.geom_type != 'LineString' or remaining.length < 1e-6:
                    raise ValueError('Opening would split or remove wall; no automatic repair')
                a, b = list(remaining.coords)[0], list(remaining.coords)[-1]
                if math.dist(a, m.start) > math.dist(b, m.start):
                    a, b = b, a
                a, b = tuple(round(v, 6) for v in a), tuple(round(v, 6) for v in b)
                moves = [(old, new) for old, new in ((m.start, a), (m.end, b)) if math.dist(old, new) > 1e-8]
                if len(moves) != 1:
                    raise ValueError('Repair must move one free endpoint')
                old, new = moves[0]
                touching = [j for j, n in enumerate(members) if j != i and LineString([n.start, n.end]).distance(Point(old)) < 1e-7]
                if len(touching) != 1 or members[touching[0]].role == 'wall':
                    raise ValueError('Opening repair cannot move branch/support nodes')
                j = touching[0]
                beam = members[j]
                if old not in (beam.start, beam.end):
                    raise ValueError('Opening repair requires an existing shared endpoint')
                members[i] = m.model_copy(update={'start': a, 'end': b})
                members[j] = beam.model_copy(update={'start': new if beam.start == old else beam.start,
                                                     'end': new if beam.end == old else beam.end})
        candidate = LayoutCandidate.model_validate({**candidate.model_dump(), 'members': tuple(members)})
    changed = {a.member_id for a, b in zip(layout.members, candidate.members) if a != b}
    if not changed or changed & protected_member_ids:
        raise ValueError('Repair is unchanged or affects a protected member')
    before_axis = unary_union([LineString([m.start, m.end]) for m in layout.members])
    after_axis = unary_union([LineString([m.start, m.end]) for m in candidate.members])
    if before_axis.hausdorff_distance(after_axis) > 1e-7:
        raise ValueError('Repair changes structural axis coverage')
    old_walls = unary_union([LineString([m.start, m.end]) for m in layout.members if m.role == 'wall'])
    new_walls = unary_union([LineString([m.start, m.end]) for m in candidate.members if m.role == 'wall'])
    if new_walls.difference(old_walls.buffer(1e-8)).length > 1e-7:
        raise ValueError('Repair cannot add unreviewed wall geometry')
    from struct_agent.services.model_review import review_geometry
    if review_geometry(candidate).requires_model_repair:
        raise ValueError('Repair leaves an unsupported physical short wall')
    digest = hashlib.sha256(candidate.model_dump_json().encode()).hexdigest()[:12]
    return candidate.model_copy(update={'layout_id': f'{layout.layout_id}_repair_{digest}', 'source': 'reviewed_generation_repair'})


def ordered_domain(variable: VariableSpec) -> list[Any]:
    return sorted(variable.domain, key=lambda v: int(v[1:]) if variable.name == "conc_bot" else v)


def feedback_candidates(x: dict[str, Any], result: EvaluationResult, variables: list[VariableSpec],
                        repair: Callable[[dict[str, Any]], dict[str, Any]],
                        evaluated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Try reduced cost after feasibility, targeted capacity changes before it.

    Proposed values never alter engineering conditions or bypass failed checks.
    Exhausting these moves is not a proof that the layout is infeasible.
    """
    domains = {v.name: ordered_domain(v) for v in variables}
    violations = result.metrics.get("normalized_violations", {})
    active = {k for k, v in violations.items() if v > 0}
    if result.feasible:
        groups = [(v.name,) for v in variables]
        direction = -1
    else:
        names = []
        if any("wall" in k or k in ("max_drift_ratio", "torsion_ratio", "period_ratio", "min_stiffness_ratio") for k in active):
            names.extend(("tw_bot", "tw_mid", "tw_top"))
        if any("beam" in k for k in active):
            names.extend(("bb_main", "bb_sec"))
        names.append("conc_bot")
        groups = [tuple(names)] + [(name,) for name in names]
        # Depth changes are evaluated separately: deeper short beams may attract
        # greater shear and should not be treated as monotonic capacity repair.
        groups += [("hb_main",), ("hb_sec",)]
        direction = 1
    moves = [(group, direction) for group in groups]
    if not result.feasible and any('beam' in k for k in active):
        moves += [((name,), -1) for name in ('hb_main', 'hb_sec')]
    proposals = []
    for group, direction in moves:
        candidate = dict(x)
        for name in group:
            values = domains[name]
            index = values.index(candidate[name])
            candidate[name] = values[min(len(values)-1, max(0, index+direction))]
        candidate = repair(candidate)
        if candidate != x and candidate not in evaluated and candidate not in proposals:
            proposals.append(candidate)
    return proposals


def local_layout_candidates(layout: LayoutCandidate, rooms: RoomGraph, design: DesignCandidate,
                            members: tuple[MemberDiagnostic, ...], *, steps_m: tuple[float, ...]=(.1,.2),
                            target_utilization: float=1., max_candidates: int=8,
                            protected_member_ids: frozenset[str]=frozenset()) -> LocalLayoutSearch:
    """Feedback-guided wall-tip moves; roles, axes, floor geometry stay fixed.

    Beam shear: retract a neighbouring wall tip to test a longer coupling span.
    Wall shear/reinforcement: extend that wall on an existing collinear beam.
    These are hypotheses, never predicted improvements or whole-member retyping.
    target_utilization below one requests margin; it does not change code limits.
    """
    from struct_agent.services.model_review import review_local_layout_change
    if design.layout_id!=layout.layout_id:
        raise ValueError('Design/layout mismatch')
    if not 0<target_utilization<=1 or max_candidates<1 or not steps_m:
        raise ValueError('Require 0 < target utilization <= 1, candidates and steps')
    if any(not math.isfinite(s) or s<=0 or abs(s*1000-round(s*1000))>1e-7 for s in steps_m):
        raise ValueError('Local steps require positive whole millimetres')
    by_id={m.member_id:m for m in layout.members}
    if protected_member_ids-set(by_id):
        raise ValueError('Protected member ID not present in layout')
    parent_hash=hashlib.sha256(layout.model_dump_json().encode()).hexdigest()
    rooms_hash=hashlib.sha256(rooms.model_dump_json().encode()).hexdigest()
    controls=[];seen_controls=set();rejected=[]
    for item in sorted(members,key=lambda m:(m.reinforcement_passed is not False,-m.utilization,m.native_id,m.story)):
        sources=item.source_member_ids or (item.member_id,)
        if any(s not in by_id or by_id[s].role!=item.role for s in sources):
            raise ValueError(f'Diagnostic source members do not match layout: {sources}')
        # A geometry match prevents accidental use of another layout's feedback.
        from shapely.geometry import LineString
        from shapely.ops import unary_union
        if unary_union([LineString([by_id[s].start,by_id[s].end]) for s in sources]).hausdorff_distance(
                LineString([item.start_m,item.end_m]))>1e-6:
            raise ValueError(f'Diagnostic geometry does not match layout: {sources}')
        if item.utilization<=target_utilization and item.reinforcement_passed is not False:
            continue
        key=(sources,item.role)
        if key in seen_controls:continue
        seen_controls.add(key)
        if item.role!='wall' and item.utilization<=target_utilization:
            rejected.append(f'{item.member_id}: beam flexural/detailing failure has no implemented layout rule')
            continue
        controls.append((item,sources))
    buckets=[]
    for item,sources in controls:
        bucket=[]
        metric='beam_shear' if item.role!='wall' else 'wall_shear' if item.utilization>target_utilization else 'wall_reinforcement'
        operation='retract_wall_tip' if item.role!='wall' else 'extend_wall_tip'
        pairs=[]
        for source in sources:
            control=by_id[source]
            for joint in (control.start,control.end):
                neighbours=[m for m in layout.members if m.member_id!=source and joint in (m.start,m.end)]
                for other in neighbours:
                    wall,beam=(other,control) if item.role!='wall' else (control,other)
                    if wall.role=='wall' and beam.role!='wall':pairs.append((wall,beam,joint))
        for step in sorted(set(steps_m)):
            for wall,beam,joint in pairs:
                if {wall.member_id,beam.member_id}&protected_member_ids:
                    rejected.append(f'{item.member_id}: protected member at {joint}')
                    continue
                root=wall.end if wall.start==joint else wall.start
                length=math.dist(root,joint)
                direction=-1. if operation=='retract_wall_tip' else 1.
                moved=tuple(round(joint[i]+direction*step*(joint[i]-root[i])/length,6) for i in range(2))
                changed=[]
                for m in layout.members:
                    if m.member_id not in (wall.member_id,beam.member_id):changed.append(m);continue
                    data=m.model_dump()
                    data.update(start=moved if m.start==joint else m.start,end=moved if m.end==joint else m.end)
                    if data['start']==data['end']:break
                    changed.append(Member.model_validate(data))
                if len(changed)!=len(layout.members):
                    rejected.append(f'{item.member_id}: step {step} removes a member')
                    continue
                digest=hashlib.sha256((parent_hash+str([(m.start,m.end) for m in changed])).encode()).hexdigest()[:12]
                candidate=LayoutCandidate.model_validate({**layout.model_dump(),'layout_id':f'{layout.layout_id}_local_{digest}',
                    'source':'member_feedback_wall_tip_move','members':tuple(changed)})
                issues=review_local_layout_change(layout,candidate,rooms,design=design)
                if issues:
                    rejected.append(f'{item.member_id}: {operation} {step}m at {joint}: '+', '.join(issues))
                    continue
                mechanism='增大梁跨，试验连梁端弯矩对应的设计剪力能否降低' if item.role!='wall' else '沿可布置边界增加墙长，试验受剪或轴力—双向弯矩承载能力能否改善'
                failure='；墙配筋不通过：'+', '.join(item.reinforcement_messages) if metric=='wall_reinforcement' else ''
                reason=f'{item.member_id}第{item.story}层，受剪利用率{item.utilization:.4f}，搜索触发值{target_utilization:g}{failure}；{mechanism}；构件类别不变，效果由真实FEA确定'
                bucket.append(LocalLayoutProposal(parent_layout_sha256=parent_hash,room_graph_sha256=rooms_hash,
                    control_member_id=item.member_id,control_story=item.story,metric=metric,
                    control_utilization=item.utilization,operation=operation,
                    move=WallTipMove(wall_member_id=wall.member_id,beam_member_id=beam.member_id,before_m=joint,after_m=moved),
                    reason=reason,layout=candidate))
        if not bucket:rejected.append(f'{item.member_id}: no admissible collinear wall-tip move')
        buckets.append(bucket)
    # Round-robin keeps one controlling member from consuming the entire budget.
    proposals=[];seen=set()
    for index in range(max((len(b) for b in buckets),default=0)):
        for bucket in buckets:
            if index<len(bucket) and bucket[index].layout.layout_id not in seen:
                proposals.append(bucket[index]);seen.add(bucket[index].layout.layout_id)
                if len(proposals)==max_candidates:
                    return LocalLayoutSearch(proposals=tuple(proposals),rejected=tuple(dict.fromkeys(rejected)))
    return LocalLayoutSearch(proposals=tuple(proposals),rejected=tuple(dict.fromkeys(rejected)))
