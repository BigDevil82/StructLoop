import math
from types import SimpleNamespace as NS

import pytest

from struct_agent._vendor.shearwall_modeling.analysis.combinations import cqc
from struct_agent._vendor.shearwall_modeling.analysis.uls_combinations import LoadCombinationDef, ULSCombinationAnalyzer
from struct_agent._vendor.shearwall_modeling.analysis import member_forces


def test_signed_combinations_and_negative_shear_envelope() -> None:
    combos = [LoadCombinationDef('plus', 'Seismic', {'Dead': 1., 'EqX': 1.}),
              LoadCombinationDef('minus', 'Seismic', {'Dead': 1., 'EqX': -1.})]
    analyzer = ULSCombinationAnalyzer(NS(), combos)
    forces = {'Dead': {(1, 1): (5., -2., -10.)}, 'EqX': {(1, 1): (2., 4., 30.)}}
    plus = analyzer._combine_one_force((1, 1), combos[0], forces)
    minus = analyzer._combine_one_force((1, 1), combos[1], forces)
    assert plus == (7., 2., 20.) and minus == (3., -6., -40.)
    envelope = analyzer._build_envelope({'plus': {(1, 1): plus}, 'minus': {(1, 1): minus}})[1, 1]
    assert envelope.max_shear_n == 40. and envelope.max_shear_combo == 'minus'
    assert envelope.max_moment_n_m == 6.


def test_zero_force_has_control_combo_and_missing_case_fails() -> None:
    combo = LoadCombinationDef('zero', 'NonSeismic', {'Dead': 1.})
    analyzer = ULSCombinationAnalyzer(NS(), [combo])
    assert analyzer._build_envelope({'zero': {(1, 1): (0., 0., 0.)}})[1, 1].max_shear_combo == 'zero'
    with pytest.raises(ValueError, match='Missing member effect'):
        analyzer._combine_one_force((1, 1), combo, {})


def test_governing_combination_uses_utilization_not_largest_shear() -> None:
    analyzer = ULSCombinationAnalyzer(NS(), [LoadCombinationDef('gravity', 'NonSeismic', {'Dead':1.}),
                                           LoadCombinationDef('earthquake', 'Seismic', {'EqX':1.})])
    envelope = analyzer._build_envelope({'gravity':{(1,1):(0.,0.,180.)},'earthquake':{(1,1):(0.,0.,-170.)}})[1,1]
    assert envelope.max_shear_n == 170. and envelope.max_shear_combo == 'earthquake'


@pytest.mark.parametrize('angle', [0., math.pi/2, math.pi/4])
def test_wall_section_force_uses_wall_axis(angle: float, monkeypatch: pytest.MonkeyPatch) -> None:
    x, y = math.cos(angle), math.sin(angle)
    # In-plane 30 N per node, plus transverse 100 N that must not enter V_in_plane.
    node = [30*x-100*y, 30*y+100*x, 1000., 0., 0., 0.]
    monkeypatch.setattr(member_forces.ops, 'eleResponse', lambda *args: node+node+[0.]*12)
    monkeypatch.setattr(member_forces.ops, 'eleNodes', lambda *args: [1, 2, 3, 4])
    unit = NS(wall_id=1, element_tags=[1], bottom_nodes=[1, 2],
        member=NS(start=NS(x=0., y=0.), end=NS(x=2*x, y=2*y)), node_coords={1:(0.,0.,0.), 2:(2*x,2*y,0.)})
    axial, moment, shear = member_forces.extract_wall_force_tuple(unit)
    assert axial == 2000. and moment == pytest.approx(0.) and shear == pytest.approx(60.)


def test_cqc_matches_ansys_one_percent_close_mode_example() -> None:
    # ANSYS Technology Showcase 12.7: f=4.857/5.017 Hz, damping=1%, rho=0.276.
    eigenvalues = [(2*math.pi*f)**2 for f in (4.857, 5.017)]
    response = cqc([1., 1.], eigenvalues, [.01, .01], [1., 1.])
    rho = (response**2-2.)/2.
    assert rho == pytest.approx(.276, abs=.001)
    assert cqc([3., -4.], [1., 4.], [0., 0.], [1., 1.]) == 5.


@pytest.mark.parametrize('eigenvalues', [[0.], [-1.], [float('nan')]])
def test_invalid_cqc_inputs_fail(eigenvalues: list[float]) -> None:
    with pytest.raises(ValueError):
        cqc([1.], eigenvalues, [.05], [1.])


def test_reinforcement_pipeline_checks_every_modeled_wall() -> None:
    import logging
    from struct_agent._vendor.shearwall_modeling.design.pipeline import ReinforcementDesignPipeline
    checked = []
    pipeline = ReinforcementDesignPipeline(NS(), NS(), NS(resolve_story_profiles=lambda: [NS(story=1, material=NS())]), logging.getLogger('test'))
    demands = [NS(story=1, length_m=.1), NS(story=1, length_m=1.)]
    pipeline.extractor = NS(extract=lambda result: ([], demands))
    def design(demand: NS, material: NS) -> NS:
        checked.append(demand.length_m)
        return NS(is_passed=False)
    pipeline.wall_designer = NS(design=design)
    result = pipeline.run()
    assert checked == [.1, 1.] and len(result.wall_results) == 2
