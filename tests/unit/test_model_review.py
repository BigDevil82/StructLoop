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
