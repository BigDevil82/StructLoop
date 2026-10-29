import pytest

from struct_agent.adapters.etabs.exceedance_causes import beam_quadrature_profile, failed_metric_effect
from struct_agent.adapters.etabs.reference_mesh import ReferenceMesh


def test_independent_beam_quadrature_explains_low_floor_error_concentration() -> None:
    coarse = beam_quadrature_profile(.4,1)
    midpoint = beam_quadrature_profile(.5,1)
    fine = beam_quadrature_profile(.4,4)
    # Exact unit-load cantilever tip flexibility H^3/(3EI), H=12, EI=1.
    assert coarse[-1]['continuous'] == pytest.approx(12**3/3)
    assert coarse[0]['relative_difference'] == pytest.approx(.193142857142857)
    assert coarse[0]['relative_difference'] > 7*coarse[-1]['relative_difference']
    assert abs(midpoint[0]['relative_difference']) < .015
    assert abs(fine[0]['relative_difference']) < abs(coarse[0]['relative_difference'])
    for center, count in ((.3,1),(.4,0),(.4,True)):
        with pytest.raises(ValueError):
            beam_quadrature_profile(center,count)


def test_cause_report_only_reopens_previously_failed_metric_ids() -> None:
    original = {'metrics':[
        dict(id='closed',category='period',within_tolerance=True,relative_difference=.03,absolute_difference=.01),
        dict(id='failed',category='primary_drift',within_tolerance=False,relative_difference=.2,absolute_difference=.002)]}
    probe = {'metrics':[
        dict(id='closed',within_tolerance=False,relative_difference=.4,absolute_difference=.1),
        dict(id='failed',within_tolerance=True,relative_difference=.01,absolute_difference=.0001)]}
    result = failed_metric_effect(original,probe)
    assert result['original_failed_count'] == result['below_5_percent_in_probe'] == 1
    assert [m['id'] for m in result['metrics']] == ['failed']
    assert result['production_status'] == 'UNCHANGED_DIAGNOSTIC_COUNTERFACTUAL_ONLY'
    with pytest.raises(ValueError):
        failed_metric_effect(original,{'metrics':[]})


def test_mvlem_options_are_not_silently_ignored_for_shells() -> None:
    assert ReferenceMesh().center_of_rotation == .4
    assert ReferenceMesh().plate_poisson is None
    for values in ({'center_of_rotation':.5}, {'plate_poisson':.2}, {'fiber_refinement':2}):
        with pytest.raises(ValueError):
            ReferenceMesh(wall_formulation='shell_dkgq',**values)
