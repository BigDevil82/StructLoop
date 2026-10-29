"""No commercial solver required: experiment bounds, references and pairing."""
import copy
import math

import pytest

from struct_agent.adapters.etabs.contracts import ETABSConfig, ETABSRequest, ResidentialSpec, SingleWallSpec
from struct_agent.adapters.etabs.wall_input import WallCase, beam_reference, response_checks, wall_cases
from struct_agent.adapters.etabs.wall_study import compare_cases
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec


@pytest.fixture
def study(spec: ProjectSpec, layout: LayoutCandidate, design: DesignCandidate) -> SingleWallSpec:
    return SingleWallSpec(source_member_id='wall_0', residential=ResidentialSpec(
        project=spec.model_copy(update={'stories':12}), layout=layout, design=design))


def test_wall_source_and_mesh_are_explicit_bounded_and_json_roundtrips(study: SingleWallSpec) -> None:
    request = ETABSRequest(spec=study, config=ETABSConfig())
    assert ETABSRequest.model_validate_json(request.model_dump_json()) == request
    for updates in ({'subdivisions':()}, {'subdivisions':(2, 1)}, {'subdivisions':(1, 1)},
                    {'subdivisions':(16,)}, {'source_member_id':'missing'}, {'fibers':1}):
        with pytest.raises(ValueError):
            SingleWallSpec(**(study.model_dump() | updates))
    with pytest.raises(ValueError):
        ETABSRequest(spec=study, config=ETABSConfig(wall_vertical_subdivisions=2))


def test_only_physical_floors_are_diaphagms_and_uniform_thickness_is_explicit(study: SingleWallSpec) -> None:
    cases = wall_cases(study)
    assert len(cases) == 10
    assert len({c.case_id for c in cases}) == 10
    assert all(c.height_m == pytest.approx(34.8) and c.length_m == 4. for c in cases)
    assert all(c.thickness_m == study.residential.design.values['tw_bot'] for c in cases)
    assert [c.panels for c in cases[:4]] == [12, 24, 48, 96]
    assert cases[-1].poisson == cases[-2].poisson == 0.


def test_independent_beam_energy_limit_and_shear_units(study: SingleWallSpec) -> None:
    case = wall_cases(study)[0]
    theory = beam_reference(case)
    f, h, l, t, e = case.tip_force_n, case.height_m, case.length_m, case.thickness_m, case.elastic_modulus_pa
    assert theory['bending_m'] == pytest.approx(4*f*h**3/(e*t*l**3))
    assert theory['shear_m'] == pytest.approx(6*f*h/(5*case.shear_modulus_pa*l*t))
    fine = case.model_copy(update={'subdivisions':8, 'fibers':128})
    assert abs(beam_reference(fine)['mvlem_discrete_m']/theory['timoshenko_m']-1) < .004
    # Direct quadrature of lever arms, independent of the closed sum in production.
    dz = h/case.panels
    inertia = t*l**3/12*(1-1/case.fibers**2)
    direct = sum(f*dz*((j+.6)*dz)**2/(e*inertia) for j in range(case.panels))+theory['shear_m']
    assert theory['mvlem_discrete_m'] == pytest.approx(direct)


def test_equilibrium_uses_moment_reference_and_checks_all_displacement_values(study: SingleWallSpec) -> None:
    case = wall_cases(study)[0]
    displacement = [[[.001, 0., 0., 0., 0., 0.] for _ in range(2)] for _ in range(case.panels+1)]
    reaction = dict(fx=-case.tip_force_n, fy=0., fz=0., mx=0., my=-case.tip_force_n*case.height_m, mz=0.)
    assert all(response_checks(case, displacement, reaction, (0., 0., 0.)).values())
    displacement[1][1][4] = math.nan
    assert not response_checks(case, displacement, reaction, (0., 0., 0.))['finite_displacements']
    reaction['my'] = 0.
    assert not response_checks(case, displacement, reaction, (0., 0., 0.))['my']


def test_comparison_rejects_missing_failed_mismatched_or_duplicate_cases(study: SingleWallSpec) -> None:
    case: WallCase = wall_cases(study)[0]
    # Explicit synthetic records for the comparison function only.
    record = dict(case=case.model_dump(), verified=True, checks={'balanced':True}, tip_x_m=.002,
        beam_reference={'timoshenko_m':.002}, beam_relative_difference=0., discrete_verified=True)
    assert compare_cases([record], [record])[0]['etabs_over_opensees_minus_one'] == 0.
    for records in ([], [record, record]):
        with pytest.raises(ValueError):
            compare_cases([record], records)
    for key, value in (('verified', False), ('tip_x_m', math.nan), ('checks', {'fx':False})):
        bad = copy.deepcopy(record)
        bad[key] = value
        with pytest.raises(ValueError):
            compare_cases([record], [bad])
    bad = copy.deepcopy(record)
    bad['case']['poisson'] = .1
    with pytest.raises(ValueError):
        compare_cases([record], [bad])
