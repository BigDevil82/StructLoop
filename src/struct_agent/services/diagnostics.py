"""Read-only member diagnostics and numerical replay comparisons."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from typing import Any, Literal
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec, RoomGraph
from struct_agent.services.analysis import AnalysisService

from struct_agent.schemas.diagnostics import MemberDiagnostic


def compare_responses(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Use the pre-existing upstream regression tolerance; never alter either record."""
    rows = {}
    for name in sorted(actual.keys() | expected.keys()):
        a, e = actual.get(name), expected.get(name)
        present = name in actual and name in expected
        if type(a) in (int, float) and type(e) in (int, float):
            passed = present and math.isclose(a, e, rel_tol=1e-5, abs_tol=1e-8)
        else:
            passed = present and type(a) is type(e) and a == e
        rows[name] = {"actual": a, "expected": e, "passed": passed}
    return rows


def member_summary(members: tuple[MemberDiagnostic, ...]) -> dict[str, Any]:
    """Counts are member-story checks; unique_member_count is plan members."""
    groups = {"wall": tuple(m for m in members if m.role == "wall"),
              "beam": tuple(m for m in members if m.role != "wall")}
    result = {}
    for kind, items in groups.items():
        worst = max(items, key=lambda m: m.utilization, default=None)
        failed = tuple(m for m in items if not m.shear_passed)
        result[kind] = {"member_story_count": len(items), "unique_member_count": len({m.member_id for m in items}),
            "shear_failed_count": len(failed), "reinforcement_unchecked_count": sum(not m.reinforcement_checked for m in items),
            "shear_failed_and_reinforcement_unchecked_count": sum(not m.reinforcement_checked for m in failed),
            "reinforcement_failed_count": sum(m.reinforcement_passed is False for m in items),
            "reinforcement_messages": dict(Counter(msg for m in items for msg in m.reinforcement_messages)),
            "members_below_rcgnn_topology_min_0_1m": sorted({m.member_id for m in items if m.length_m < .1-1e-8}),
            "worst_shear": None if worst is None else {**worst.model_dump(), "utilization": worst.utilization}}
    return result


def load_members(path: Path, *, expected_fidelity: Literal['full','mock']='full') -> tuple[MemberDiagnostic, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["fidelity"] != expected_fidelity or payload["units"] != {"length": "m", "force": "N", "stress": "Pa"}:
        raise ValueError("Diagnostic report fidelity/units do not match the evaluator")
    return tuple(MemberDiagnostic.model_validate_json(json.dumps(row)) for row in payload["members"])


def design_review_evidence(layout: LayoutCandidate, rooms: RoomGraph, design: DesignCandidate,
        spec: ProjectSpec, *, evaluation_id: str, raw: dict[str, Any],
        directory: Path, fidelity: Literal['full','mock']) -> dict[str, Any]:
    """Supply actual plan and checked results, not paths. XY m, N, Pa.

    Every physical member is represented; story failures are never top-k filtered.
    The governing shear row is supplemented with all failing/unchecked stories.
    """
    import hashlib
    from shapely.geometry import LineString, Polygon
    from struct_agent.services.model_review import review_geometry
    from struct_agent.adapters.fea import native_topology
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import beam_spans
    members=load_members(directory/'members.json',expected_fidelity=fidelity)
    checks=json.loads((directory/'checks.json').read_text(encoding='utf-8'))
    groups: dict[str,list[MemberDiagnostic]]={}
    for member in members:
        groups.setdefault(member.member_id,[]).append(member)
    rows=[]
    for member_id,items in groups.items():
        worst=max(items,key=lambda m:m.utilization)
        rows.append({'member_id':member_id,'source_member_ids':worst.source_member_ids,
            'role':worst.role,'start_m':worst.start_m,'end_m':worst.end_m,
            'width_m':worst.width_m,'depth_m':worst.depth_m,'concrete_grade':worst.concrete_grade,
            'governing_shear':{'story':worst.story,'utilization':worst.utilization,
                'design_shear_n':worst.shear_n,'control_combo':worst.control_combo,
                'combined_fe_shear_n':worst.combo_shear_n[worst.control_combo],
                'physical_span_m':worst.physical_span_m,'coupling':worst.coupling},
            'checked_stories':sorted({m.story for m in items}),
            'problems':[{'story':m.story,'shear_passed':m.shear_passed,
                'reinforcement_passed':m.reinforcement_passed,'messages':sorted(set(m.reinforcement_messages))}
                for m in items if not m.shear_passed or m.reinforcement_passed is not True]})
    polygons=[Polygon(p) for p in rooms.room_polygons]
    topology=native_topology(layout)
    spans=[{'source_member_ids':[layout.members[i].member_id for i in s.source_ids],
        'start_m':(s.start.x,s.start.y),'end_m':(s.end.x,s.end.y),'axis_span_m':s.length,'coupling':s.coupling}
        for s in beam_spans(topology.beams,topology.walls)]
    plan=layout.model_dump(mode='json')
    for member in plan['members']:
        line=LineString([member['start'],member['end']])
        member['adjacent_room_indices']=[i for i,p in enumerate(polygons) if line.intersection(p.boundary.buffer(.002)).length>.002]
    return {'evaluation_id':evaluation_id,'fidelity':fidelity,
        'layout_sha256':hashlib.sha256(layout.model_dump_json().encode()).hexdigest(),
        'units':{'length':'m','force':'N','stress':'Pa','coordinates':'global_xy'},
        'layout':plan,'design':design.model_dump(mode='json'),'conditions':spec.model_dump(mode='json'),
        'rooms':{'polygons':rooms.room_polygons,'allowed_half_edge_intervals':rooms.masks,
            'adjacency_edges':rooms.edge_index,
            'semantics':'Room use labels unavailable. Masks are normalized intervals on 8 ordered half-edges; exclusions include openings. No visual image was supplied.'},
        'raw_response':raw,'global_checks':checks['overall'],'direction_checks':checks['directions'],
        'geometry_review':review_geometry(layout,design=design).model_dump(),
        'member_checks':rows,'analysis_beam_spans':spans,
        'coverage':{'member_story_rows':len(members),'physical_members':len(rows),
            'aggregation':'Governing shear per physical member plus every failed or unchecked story; full plan has every source segment.',
            'engineering_scope':'Existing implemented checks and continuous reinforcement design; not complete detailing or engineering release.'}}


def get_design_overview(evidence: dict[str, Any]) -> dict[str, Any]:
    """Small global summary; no full plan, room polygons or story-check arrays."""
    from shapely.geometry import LineString
    plan=evidence['layout'];checks=evidence['member_checks']
    xs=[p[0] for m in plan['members'] for p in (m['start'],m['end'])]
    ys=[p[1] for m in plan['members'] for p in (m['start'],m['end'])]
    failed=[m for m in checks if m['problems']]
    short=sorted(plan['members'],key=lambda m:LineString([m['start'],m['end']]).length)[:5]
    return {k:evidence[k] for k in ('evaluation_id','layout_sha256','fidelity','units','design','conditions','raw_response','coverage')} | {
        'plan_summary':{'bounds_m':[min(xs),min(ys),max(xs),max(ys)],
            'source_member_counts':dict(Counter(m['role'] for m in plan['members'])),
            'room_count':len(evidence['rooms']['polygons'])},
        'attention_members':[{'member_id':m['member_id'],'source_member_ids':m['source_member_ids'],
            'governing_shear':m['governing_shear'],'failed_story_count':len(m['problems'])}
            for m in sorted(failed,key=lambda m:-m['governing_shear']['utilization'])[:8]],
        'shortest_axis_segments':[{'member_id':m['member_id'],'role':m['role'],
            'axis_length_m':LineString([m['start'],m['end']]).length} for m in short],
        'geometry_issue_counts':dict(Counter(i['code'] for i in evidence['geometry_review']['issues'])),
        'query_tools':{'get_design_overview':{},'inspect_member':{'member_id':'exact source or physical member ID'},
            'inspect_region':{'bounds_m':'[xmin,ymin,xmax,ymax], global XY metres','offset':0,'limit':12}},
        'interpretation':{'physical_span_m':'Existing support-axis span, NOT verified face-to-face clear span.',
            'beam_grouping':'Beam diagnostic IDs may be FE subdivisions of one support span; inspect_member returns exact analysis-span source IDs.',
            'capabilities':'Connected-wall compound section checks exist. Independent column stability/detailing is incomplete. Geometry length/thickness flags are screening, not proof that compound checks were omitted.',
            'architecture':'Room use labels unavailable; interval masks alone do not establish construction intent.'}}


def inspect_member(evidence: dict[str, Any], member_id: str, *, provenance: dict[str, Any] | None=None) -> dict[str, Any]:
    """Deterministic axes, contacts, room adjacency and wall-footprint coverage.

    Plan lengths m, global XY. Footprint coverage of a beam AXIS is a geometric
    warning, not a 3D joint design or permission to retype/delete the member.
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    plan=evidence['layout']['members'];by_id={m['member_id']:m for m in plan}
    diagnostics=[m for m in evidence['member_checks'] if m['member_id']==member_id or member_id in m['source_member_ids']]
    ids=(member_id,) if member_id in by_id else tuple(s for m in diagnostics for s in m['source_member_ids'])
    if not ids:raise ValueError('Unknown member ID')
    selected=[by_id[i] for i in ids];axis=unary_union([LineString([m['start'],m['end']]) for m in selected])
    contacts=[]
    for m in selected:
        for endpoint in ('start','end'):
            p=Point(m[endpoint])
            neighbours=[{'member_id':n['member_id'],'role':n['role'],'start':n['start'],'end':n['end'],
                'contact':'endpoint' if min(Point(n[k]).distance(p) for k in ('start','end'))<=1e-6 else 'interior'}
                for n in plan if n['member_id'] not in ids and LineString([n['start'],n['end']]).distance(p)<=1e-6]
            contacts.append({'member_id':m['member_id'],'endpoint':endpoint,'point_m':m[endpoint],'connected_members':neighbours})
    coverage=[]
    if any(m['role']!='wall' for m in selected):
        for key in ('tw_bot','tw_mid','tw_top'):
            thickness=float(evidence['design']['values'][key]);overlaps=[]
            for wall in plan:
                if wall['role']!='wall':continue
                footprint=LineString([wall['start'],wall['end']]).buffer(thickness/2,cap_style=2)
                covered=axis.intersection(footprint).length
                if covered>1e-8:overlaps.append({'member_id':wall['member_id'],'covered_axis_m':covered,
                    'footprint':footprint})
            exposed=axis.difference(unary_union([w['footprint'] for w in overlaps])).length
            coverage.append({'wall_thickness_parameter':key,'thickness_m':thickness,
                'wall_covered_axis_m':axis.length-exposed,'exposed_axis_m':exposed,
                'walls':[{'member_id':w['member_id'],'covered_axis_m':w['covered_axis_m']} for w in overlaps]})
    stages={};chains=[]
    def overlaps_axis(row: dict[str, Any]) -> bool:
        # mm->m conversions can differ by 1e-13 m; exact line intersection
        # would silently lose true provenance. A crossing point is not overlap.
        line=LineString([row['start'],row['end']])
        return line.intersection(axis.buffer(1e-6,cap_style=2)).length>1e-5
    if provenance is not None:
        if provenance['layout_sha256']!=evidence['layout_sha256']:raise ValueError('Stale generation provenance')
        for name,rows in provenance['stages'].items():
            stages[name]=[r for r in rows if overlaps_axis(r)]
        chains=[c for c in provenance['preprocessing_beam_chains']
            if any(overlaps_axis(m) for m in c['members'])]
    room_ids=sorted({i for m in selected for i in m['adjacent_room_indices']})
    return {'evaluation_id':evidence['evaluation_id'],'layout_sha256':evidence['layout_sha256'],
        'requested_member_id':member_id,'members':selected,'axis_length_m':axis.length,
        'endpoint_connections':contacts,'wall_footprint_axis_coverage':coverage,
        'adjacent_rooms':[{'room_index':i,'polygon':evidence['rooms']['polygons'][i],
            'allowed_half_edge_intervals':evidence['rooms']['allowed_half_edge_intervals'][i]} for i in room_ids],
        'checks':diagnostics,'analysis_spans':[s for s in evidence['analysis_beam_spans'] if set(ids).intersection(s['source_member_ids'])],
        'generation_provenance':{'available':provenance is not None,'stages':stages,
            'preprocessing_beam_chains':chains,
            'chain_rule':provenance['preprocessing_chain_rule'] if provenance is not None else 'Unknown'},
        'model_representation':'Source axes passed to native_topology unchanged; full-stiffness elasticBeamColumn joins source endpoints. Existing physical_span_m is support-axis distance, not a wall-face opening.',
        'design_shear_rule':'For seismic coupling beams the existing code takes max(abs(combined FE shear), 1.2*sum(abs(end moments))/support-axis span + gravity_bound). Very small axis spans can amplify design shear; design shear is not raw FE shear.',
        'anomalies':{'beam_axis_inside_wall_footprint':any(c['exposed_axis_m']<1e-7 for c in coverage),
            'axis_below_100mm':axis.length<.1},
        'limits':'Wall footprints use finite strip polygons, without end extension. Axis coverage does not establish full beam-volume overlap or construction intent. Resolve modelling/joint semantics before structural edits.'}


def inspect_region(evidence: dict[str, Any], bounds_m: tuple[float,float,float,float], *,
        offset: int=0, limit: int=12) -> dict[str, Any]:
    """Page deterministic intersecting axes; bounds global XY m, no distance guess."""
    from shapely.geometry import LineString, Polygon, box
    xmin,ymin,xmax,ymax=bounds_m
    if xmin>=xmax or ymin>=ymax or not all(math.isfinite(x) for x in bounds_m):raise ValueError('Invalid region bounds')
    if not 1<=limit<=32 or offset<0:raise ValueError('Region limit must be 1..32 and offset nonnegative')
    region=box(*bounds_m)
    rows=[m for m in evidence['layout']['members'] if LineString([m['start'],m['end']]).intersects(region)]
    selected=rows[offset:offset+limit];ids={m['member_id'] for m in selected}
    return {'evaluation_id':evidence['evaluation_id'],'layout_sha256':evidence['layout_sha256'],
        'bounds_m':bounds_m,'total_members':len(rows),'offset':offset,'next_offset':offset+limit if offset+limit<len(rows) else None,
        'members':selected,'checks':[m for m in evidence['member_checks'] if ids.intersection(m['source_member_ids'])],
        'intersecting_room_indices':[i for i,p in enumerate(evidence['rooms']['polygons']) if Polygon(p).intersects(region)],
        'geometry_issues':[i for i in evidence['geometry_review']['issues'] if ids.intersection(i['source_member_ids'])],
        'truncation':'Only the requested member page is returned; use next_offset for remaining members.'}


def evaluate_local_layout_candidates(service: 'AnalysisService', layout: 'LayoutCandidate',
        design: 'DesignCandidate', spec: 'ProjectSpec', rooms: 'RoomGraph',
        members: tuple[MemberDiagnostic, ...], *, steps_m: tuple[float,...]=(.1,.2),
        target_utilization: float=1., max_candidates: int=4) -> dict[str, Any]:
    """Evaluate bounded local proposals with unchanged sections and shared FEA budget.

    Reuse the existing constraint/cost ranking; solver failures stay in the record.
    Each layout has a fresh problem and no surrogate or calibration state.
    """
    from struct_agent.adapters.casino import CasinoProblem
    from struct_agent.adapters.design_search import local_layout_candidates
    from struct_agent.services.analysis import AnalysisFailed, BudgetExhausted
    from struct_agent._vendor.shearwall_optimization.surrogate_candidate import SurrogateCandidateEvaluator

    native={k:round(float(v)*1000) if k!='conc_bot' else v for k,v in design.values.items()}
    baseline_problem=CasinoProblem(layout,spec,service,layout_path=Path('unused'),seed=42)
    baseline=baseline_problem.evaluate(native)
    best_key=SurrogateCandidateEvaluator.rank_key(baseline)
    best_layout_id=layout.layout_id
    search=local_layout_candidates(layout,rooms,design,members,steps_m=steps_m,
        target_utilization=target_utilization,max_candidates=max_candidates)
    rows=[];termination='completed'
    for proposal in search.proposals:
        problem=CasinoProblem(proposal.layout,spec,service,layout_path=Path('unused'),seed=42)
        try:
            result=problem.evaluate(native)
        except BudgetExhausted:
            termination='budget_exhausted';break
        except AnalysisFailed as exc:
            rows.append({'proposal':proposal.model_dump(),'analysis':exc.record.model_dump(),
                'ranking_improved':False,'error':exc.record.error.model_dump()})
            continue
        key=SurrogateCandidateEvaluator.rank_key(result)
        improves=key<SurrogateCandidateEvaluator.rank_key(baseline)
        if key<best_key:best_key,best_layout_id=key,proposal.layout.layout_id
        rows.append({'proposal':proposal.model_dump(),'feasible':result.feasible,
            'objectives':result.objectives,'normalized_violations':result.metrics['normalized_violations'],
            'raw':next(r.raw for r in service.records if r.layout_id==proposal.layout.layout_id),
            'ranking_improved':improves})
    return {'termination':termination,'baseline_layout_id':layout.layout_id,
        'baseline_feasible':baseline.feasible,'baseline_objectives':baseline.objectives,
        'target_utilization':target_utilization,'target_is_search_trigger_not_code_limit':True,
        'generated_candidate_count':len(search.proposals),'evaluated_candidate_count':len(rows),
        'fea_attempts':len(service.records),'best_layout_id':best_layout_id,
        'candidates':rows,'rejected':search.rejected,
        'architectural_checks':'room masks, fixed axes, member roles, branch nodes, residual lengths',
        'scope':'repeated standard floor; continuous-steel section checks, not bar detailing',
        'agent_action_added':False,'member_role_changes_allowed':False}


def write_report(path: Path, members: tuple[MemberDiagnostic, ...], *, parity_passed: bool | None = None) -> None:
    lines = ["# 构件级有限元诊断（冒烟条件）", "",
        f"当前正确实现的独立计算。可选同协议复算对照：{parity_passed}。", "",
        "指标按上游定义为 V/(βc·fc·b·h0)，利用率为该指标/原有限值。力 N，尺寸 m，应力 Pa。",
        "h0采用截面尺寸扣除40mm纵筋合力点距离；梁跨按墙支座间共线构件识别，保留中间接入节点。",
        "基本组合剪力与调整后的设计剪力分别保存，按设计剪力/对应限值选择控制组合；全部墙肢逐组合设计。", "",
        "本报告用于定位控制构件，未改变几何、荷载、限值或原算法，不是工程签审。", ""]
    for kind, title in (("wall", "墙肢"), ("beam", "梁")):
        items = tuple(m for m in members if (m.role == "wall") == (kind == "wall"))
        lines += [f"## {title}控制项（利用率前 15 个构件-楼层）", "",
            "| 构件ID | 层 | 长度 m | b m | h0 m | V kN | 指标 | 限值 | 利用率 | 配筋检查 | 控制组合 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for m in sorted(items, key=lambda m: m.utilization, reverse=True)[:15]:
            design = "未执行" if not m.reinforcement_checked else ("通过" if m.reinforcement_passed else "不通过")
            lines.append(f"| {m.member_id} | {m.story} | {m.length_m:.6f} | {m.width_m:.3f} | {m.effective_depth_m:.6f} | "
                f"{m.shear_n/1000:.3f} | {m.shear_ratio:.6f} | {m.shear_limit:g} | {m.utilization:.3f} | {design} | {m.control_combo} |")
        messages = Counter(msg for m in items for msg in m.reinforcement_messages)
        lines += ["", f"配筋设计消息（构件-楼层计数）：{dict(messages)}", ""]
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
