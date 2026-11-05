"""Preflight routing is separate from numerical and structural feasibility."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from struct_agent.adapters.casino import CasinoConfig, create_optimizer
from struct_agent.schemas import LayoutCandidate, DesignCandidate, ProjectSpec, RoomGraph
from struct_agent.services.model_review import review_geometry
from struct_agent.services.analysis import AnalysisService


def test_a_short_subdivision_of_a_long_pier_does_not_block_model_review() -> None:
    layout = LayoutCandidate.model_validate_json(json.dumps(dict(layout_id='synthetic',source='test_only',
        length_unit='m',coordinate_system='global_xy', members=[
            dict(member_id='short_mesh',start=[0.,0.],end=[.1,0.],role='wall'),
            dict(member_id='long_mesh',start=[.1,0.],end=[2.4,0.],role='wall')],
        slabs=[[[0.,0.],[3.,0.],[0.,3.]]])))
    review = review_geometry(layout)
    assert review.physical_wall_pier_count == 1 and review.mesh_wall_segment_count == 2
    assert not review.requires_model_repair and not review.issues


def test_column_like_walls_and_low_segment_depth_ratio_require_special_review(layout: LayoutCandidate,
        design: DesignCandidate) -> None:
    from struct_agent.schemas import Member
    candidate = layout.model_copy(update={'members': (
        Member(member_id='w',start=(0.,0.),end=(.7,0.),role='wall'),
        Member(member_id='b',start=(.7,0.),end=(1.,0.),role='primary'))})
    review = review_geometry(candidate, design=design)
    assert not review.requires_model_repair
    assert {i.code for i in review.issues} == {'COLUMN_OR_COMPOSITE_DESIGN_REQUIRED','BEAM_SPAN_REVIEW'}


def test_unresolved_short_physical_wall_stops_real_ga_before_any_solver_call(layout: LayoutCandidate,
        rooms: RoomGraph, spec: ProjectSpec, tmp_path: Path) -> None:
    from struct_agent.schemas import Member
    candidate = layout.model_copy(update={'members': (Member(member_id='tiny',start=(0.,0.),end=(.1,0.),role='wall'),)})
    def unexpected_call(*args: object, **kwargs: object) -> None:
        pytest.fail('Preflight must reject before invoking real FEA')
    service = AnalysisService(NS(fidelity='full',evaluate=unexpected_call),budget=1,directory=tmp_path/'analyses')
    with pytest.raises(ValueError,match='model repair before real parameter optimization'):
        create_optimizer(candidate,rooms,spec,service,CasinoConfig(seed=42),directory=tmp_path/'optimization')
    report = json.loads((tmp_path/'optimization/geometry_review.json').read_text(encoding='utf-8'))
    assert report['requires_model_repair'] and report['issues'][0]['source_member_ids'] == ['tiny']
    assert not service.records


def test_beam_branch_does_not_turn_one_span_into_two_short_beams(layout: LayoutCandidate,design: DesignCandidate) -> None:
    from struct_agent.schemas import Member
    from struct_agent.adapters.fea import native_topology
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import beam_spans
    members=(Member(member_id='wl',start=(-2.,0.),end=(0.,0.),role='wall'),
        Member(member_id='wr',start=(1.,0.),end=(3.,0.),role='wall'),
        Member(member_id='b1',start=(0.,0.),end=(.8,0.),role='secondary'),
        Member(member_id='b2',start=(.8,0.),end=(1.,0.),role='secondary'),
        Member(member_id='branch',start=(.8,0.),end=(.8,2.),role='primary'))
    candidate=layout.model_copy(update={'members':members})
    topology=native_topology(candidate)
    spans=beam_spans(topology.beams,topology.walls)
    assert next(s for s in spans if 2 in s.source_ids).source_ids==(2,3)
    assert next(s for s in spans if 2 in s.source_ids).length==1.
    review=review_geometry(candidate,design=design)
    assert not any(i.code=='BEAM_SPAN_REVIEW' for i in review.issues)
    support=Member(member_id='midwall',start=(.8,0.),end=(.8,-2.),role='wall')
    topology=native_topology(candidate.model_copy(update={'members':members+(support,)}))
    spans=beam_spans(topology.beams,topology.walls)
    assert next(s for s in spans if 2 in s.source_ids).source_ids==(2,)


def test_local_wall_growth_honours_both_rooms_on_a_shared_boundary() -> None:
    from tests.unit.test_search_feedback import local_case
    from struct_agent.adapters.design_search import local_layout_candidates
    layout,rooms,design,diagnostic=local_case()
    second=((0.,3.),(4.,3.),(4.,6.),(0.,6.))
    layout=layout.model_copy(update={'slabs':layout.slabs+(second,)})
    mask=list(rooms.masks[0]);mask[4]=((0.,.5),)  # Second room's bottom edge blocks x>1.
    rooms=rooms.model_copy(update={'x':rooms.x*2,'room_polygons':layout.slabs,'masks':rooms.masks+(tuple(mask),)})
    result=local_layout_candidates(layout,rooms,design,(diagnostic(0),),steps_m=(.1,))
    assert not result.proposals and any('nonbuildable_interval' in x for x in result.rejected)


def test_local_review_rejects_retyping_slabs_and_wrong_architecture() -> None:
    from tests.unit.test_search_feedback import local_case
    from struct_agent.services.model_review import review_local_layout_change
    layout,rooms,design,_=local_case()
    changed=layout.members[0].model_copy(update={'role':'secondary'})
    candidate=layout.model_copy(update={'members':(changed,)+layout.members[1:]})
    assert review_local_layout_change(layout,candidate,rooms,design=design)==('member_identity_or_role_changed',)
    rooms=rooms.model_copy(update={'room_polygons':(((10.,0.),(14.,0.),(14.,3.),(10.,3.)),)})
    assert review_local_layout_change(layout,layout,rooms,design=design)==('room_graph_does_not_match_layout',)


@pytest.mark.parametrize('branch_length', [.25, 2.])
def test_generated_stub_repair_distinguishes_small_group_from_real_wall_host(layout, rooms, design, branch_length):
    import hashlib
    from struct_agent.schemas import Member
    from struct_agent.schemas.state import LayoutRepairModification
    from struct_agent.services.model_review import inspect_layout_relations
    from struct_agent.adapters.design_search import apply_layout_repair
    candidate=layout.model_copy(update={'members':(
        Member(member_id='left_support',start=(0.,0.),end=(0.,3.),role='wall'),
        Member(member_id='left_beam',start=(0.,3.),end=(1.9,3.),role='secondary'),
        Member(member_id='stub',start=(1.9,3.),end=(2.1,3.),role='wall'),
        Member(member_id='right_beam',start=(2.1,3.),end=(4.,3.),role='primary'),
        Member(member_id='right_support',start=(4.,3.),end=(4.,0.),role='wall'),
        Member(member_id='stub_branch',start=(2.,3.),end=(2.,3.-branch_length),role='wall'))})
    design=design.model_copy(update={'layout_id':candidate.layout_id,'values':dict(design.values,tw_bot=.2,tw_mid=.18,tw_top=.16)})
    rooms=rooms.model_copy(update={'room_polygons':candidate.slabs})
    instruction=LayoutRepairModification.model_validate_json(json.dumps(dict(operation='repair_generated_layout',source_evaluation_id='test',
        source_layout_sha256=hashlib.sha256(candidate.model_dump_json().encode()).hexdigest(),
        repairs=[{'kind':'remove_unsupported_wall_group','member_ids':['stub']},
                 {'kind':'unify_beam_span','member_ids':['stub'],'beam_role':'primary'}])))
    facts=inspect_layout_relations(candidate,rooms,design)
    if branch_length==2.:
        assert not facts['small_wall_groups']
        with pytest.raises(ValueError,match='attached long walls'):
            apply_layout_repair(candidate,rooms,design,instruction)
    else:
        assert set(facts['small_wall_groups'][0]['source_member_ids'])=={'stub','stub_branch'}
        repaired=apply_layout_repair(candidate,rooms,design,instruction)
        assert [m.member_id for m in repaired.members]==[m.member_id for m in candidate.members]
        assert all(m.role=='primary' for m in repaired.members if m.member_id in ('left_beam','stub','right_beam'))
        assert next(m for m in repaired.members if m.member_id=='stub_branch').role=='secondary'
        with pytest.raises(ValueError,match='protected'):
            apply_layout_repair(candidate,rooms,design,instruction,protected_member_ids=frozenset({'left_beam'}))


def test_opening_repair_preserves_beam_axis_and_refuses_real_branch(layout, rooms, design):
    import hashlib
    from struct_agent.schemas import Member
    from struct_agent.schemas.state import LayoutRepairModification
    from struct_agent.adapters.design_search import apply_layout_repair
    from struct_agent.services.model_review import inspect_layout_relations
    candidate=layout.model_copy(update={'members':(
        Member(member_id='host',start=(0.,0.),end=(0.,3.),role='wall'),
        Member(member_id='return',start=(0.,3.),end=(1.1,3.),role='wall'),
        Member(member_id='beam',start=(1.1,3.),end=(3.,3.),role='secondary'))})
    rooms=rooms.model_copy(update={'opening_polygons':(((1.,2.9),(2.,2.9),(2.,3.1),(1.,3.1)),)})
    rooms=rooms.model_copy(update={'room_polygons':candidate.slabs})
    design=design.model_copy(update={'layout_id':candidate.layout_id})
    def instruction(l):
        return LayoutRepairModification.model_validate_json(json.dumps(dict(operation='repair_generated_layout',source_evaluation_id='test',
            source_layout_sha256=hashlib.sha256(l.model_dump_json().encode()).hexdigest(),
            repairs=[{'kind':'align_opening_edges','member_ids':['return']}])))
    repaired=apply_layout_repair(candidate,rooms,design,instruction(candidate))
    assert repaired.members[1].end==repaired.members[2].start==(.999,3.)
    assert not inspect_layout_relations(repaired,rooms,design)['opening_conflicts']
    preview=inspect_layout_relations(candidate,rooms,design)['opening_conflicts'][0]['align_opening_edges_preflight']
    assert preview['eligible'] and preview['new_joint_m']==(.999,3.)
    split=candidate.model_copy(update={'members':(candidate.members[0],
        Member(member_id='long_flange',start=(0.,3.),end=(.942,3.),role='wall'),
        candidate.members[1].model_copy(update={'start':(.942,3.)}),candidate.members[2])})
    preview=inspect_layout_relations(split,rooms,design)['opening_conflicts'][0]['align_opening_edges_preflight']
    assert preview['eligible'] and preview['remaining_source_segment_m']<.18
    assert preview['remaining_physical_wall_pier_m']==pytest.approx(.999)
    assert apply_layout_repair(split,rooms,design,instruction(split)).members[2].end==(.999,3.)
    branch=Member(member_id='fixed_branch',start=(1.1,3.),end=(1.1,1.),role='wall')
    branched=candidate.model_copy(update={'members':candidate.members+(branch,)})
    with pytest.raises(ValueError,match='branch/support'):
        apply_layout_repair(branched,rooms,design,instruction(branched))
