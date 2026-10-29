import math

import pytest

from struct_agent.adapters.etabs.contracts import ETABSConfig, ETABSRequest, StructuralBatchSpec, SubstructureSelection, ResidentialSpec
from struct_agent.adapters.etabs.structural_batch import subsystem_specs
from struct_agent.adapters.etabs.tolerance import assess_pair, assess_comparison
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec


@pytest.mark.parametrize('a,b,passed', [(20.,20.99,True), (20.,21.,False), (20.,21.01,False),
    (-20.,-20.99,True), (0.,0.,True), (0.,1e-20,False), (1e-20,2e-20,False)])
def test_strict_five_percent_rule_including_small_and_zero_responses(a: float, b: float, passed: bool) -> None:
    result = assess_pair(a, b)
    assert result['within_tolerance'] == passed
    assert (result['followup'] == 'CLOSED_NO_CALIBRATION') == passed


@pytest.mark.parametrize('bad', [math.nan, math.inf, -math.inf])
def test_failed_nonfinite_output_is_not_accepted(bad: float) -> None:
    with pytest.raises(ValueError):
        assess_pair(1., bad)


def test_subsystem_preserves_source_members_slab_and_conditions(
        spec: ProjectSpec, layout: LayoutCandidate, design: DesignCandidate) -> None:
    # Synthetic selector fixture; never part of a real comparison report.
    other = layout.members[0].model_copy(update={'member_id':'second', 'start':(0.,0.), 'end':(0.,2.)})
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),
        layout=layout.model_copy(update={'members':(*layout.members,other)}), design=design)
    selection = SubstructureSelection(name='L_wall', member_ids=('wall_0','second'))
    batch = StructuralBatchSpec(residential=parent, selections=(selection,))
    request = ETABSRequest(config=ETABSConfig(beam_theory='euler_comparison'), spec=batch)
    assert ETABSRequest.model_validate_json(request.model_dump_json()) == request
    sub = subsystem_specs(batch)['L_wall']
    assert sub.layout.members == parent.layout.members
    assert sub.layout.slabs == parent.layout.slabs
    assert sub.project == parent.project
    assert sub.design.layout_id == sub.layout.layout_id != parent.layout.layout_id
    assert sub.design.values == parent.design.values
    with pytest.raises(ValueError):
        StructuralBatchSpec(residential=parent, selections=(selection,selection))
    with pytest.raises(ValueError):
        StructuralBatchSpec(residential=parent,
            selections=(SubstructureSelection(name='L_wall',member_ids=('missing','wall_0')),))


def test_all_floors_modes_and_story_drifts_are_assessed() -> None:
    rows = [dict(story=s, component=k, etabs=value*s, opensees=value*s*1.01)
        for s in (1,2) for k,value in (('u1',1.),('u2',.01),('r3',.001))]
    data = {'periods':[{'etabs_mode':1,'etabs_period_s':1.,'opensees_period_s':1.01}],
        'static':{'ROOF_X':rows, 'ROOF_Y':rows}}
    result = assess_comparison(data, 2.9)
    assert result['status'] == 'WITHIN_5_PERCENT'
    assert result['total'] == result['passed'] == 21
    # A small coupled response must not disappear behind the primary values.
    rows[1]['opensees'] *= 2
    result = assess_comparison(data, 2.9)
    assert result['status'] == 'PARTIAL_EXCEEDANCE'
    assert result['passed'] < result['total']
    assert result['categories']['coupled_response']['max_relative_difference'] > 1.
    with pytest.raises(ValueError):
        assess_comparison(data, 0.)
