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
