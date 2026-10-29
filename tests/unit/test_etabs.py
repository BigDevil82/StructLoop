import math
import numpy as np

import pytest

from struct_agent.adapters.etabs.benchmark import expected
from struct_agent.adapters.etabs.client import checked, rows
from struct_agent.adapters.etabs.contracts import CantileverSpec, ETABSConfig, ETABSRequest, ResidentialSpec
from struct_agent.adapters.etabs.residential_input import prepare
from struct_agent.adapters.etabs.results import roof_equilibrium
from struct_agent.adapters.etabs.comparison import modal_mac
from struct_agent.adapters.etabs.residential import beam_modifiers
from struct_agent.schemas import ProjectSpec, DesignCandidate, LayoutCandidate


def test_cantilever_closed_form_includes_shear_and_tip_mass() -> None:
    spec = CantileverSpec()
    result = expected(spec)
    assert result['tip_x_m'] == pytest.approx(.00142425)
    assert result['base_fx_n'] == -10000.
    assert result['base_my_nm'] == -30000.
    assert result['first_period_s'] == pytest.approx(2*math.pi*math.sqrt(.00142425))


@pytest.mark.parametrize('value',[None,True,[],[1.,'wrong'],[2]])
def test_invalid_api_return_cannot_be_treated_as_success(value: object) -> None:
    with pytest.raises((TypeError, RuntimeError)):
        checked(value,'test operation')


def test_api_out_values_are_preserved() -> None:
    assert checked(['created_name',0],'create') == ('created_name',)
    assert checked(0,'save') == ()


def test_strict_worker_request_roundtrips_paths_through_json() -> None:
    request = ETABSRequest(config=ETABSConfig(),spec=CantileverSpec())
    assert ETABSRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValueError):
        ETABSRequest.model_validate_json('{"config":{},"spec":{"kind":"shell"}}')


def test_result_rows_preserve_repeated_modes_and_reject_missing_values() -> None:
    assert rows((2,['X','Y'],[.2,.2]),('direction','period'),operation='modes') == [
        {'direction':'X','period':.2},{'direction':'Y','period':.2}]
    for values in ((0,[],[]),(2,['X'],[.2,.3]),(1,['X'])):
        with pytest.raises(ValueError):
            rows(values,('direction','period'),operation='modes')


def test_residential_protocol_mass_and_story_count(spec: ProjectSpec,layout: LayoutCandidate,design: DesignCandidate) -> None:
    short = spec.model_copy(update={'stories':12,'condition_id':'test_12'})
    candidate = design.model_copy(update={'condition_id':'test_12'})
    request = ResidentialSpec(project=short,layout=layout,design=candidate)
    data = prepare(request)
    assert len(data.floors)==12 and data.floors[-1].elevation_m==pytest.approx(34.8)
    # Independent 4m wall, t=0.2, h=2.9, rho=2550; 16m² at 6kPa/9.81.
    assert data.floors[0].mass_kg==pytest.approx(4*.2*2.9*2550+16*6000/9.81)
    assert ETABSRequest.model_validate_json(ETABSRequest(config=ETABSConfig(),spec=request).model_dump_json()).spec==request
    assert spec.stories==28  # Do not mutate the original project conditions.
    with pytest.raises(ValueError,match='at most 12'):
        ResidentialSpec(project=spec,layout=layout,design=design)


def test_base_moment_uses_reported_reference_point() -> None:
    reference,point=(1.,2.,0.),(5.,8.,10.)
    reaction=dict(fx=-100.,fy=0.,fz=0.,mx=0.,my=-1000.,mz=600.)
    assert all(roof_equilibrium(reaction,reference,point,100.,'X').values())
    reaction['my']=0.
    assert not roof_equilibrium(reaction,reference,point,100.,'X')['my']


def test_mass_weighted_mac_handles_mode_swaps_and_sign_scaling() -> None:
    a=np.array([[1.,0.],[0.,1.]])
    b=np.array([[0.,-20.],[5.,0.]])
    np.testing.assert_allclose(modal_mac(a,b,np.array([2.,3.])),[[0.,1.],[1.,0.]])
    with pytest.raises(ValueError,match='Zero mode'):
        modal_mac(a,np.zeros((1,2)),np.ones(2))


def test_euler_diagnostic_changes_only_two_shear_modifiers() -> None:
    baseline = beam_modifiers('timoshenko')
    comparison = beam_modifiers('euler_comparison')
    assert baseline==[1.]*8
    assert [i for i,(a,b) in enumerate(zip(baseline,comparison)) if a!=b]==[1,2]
    assert comparison[1]==comparison[2]==1e6
    with pytest.raises(ValueError):
        ETABSRequest(config=ETABSConfig(beam_theory='euler_comparison'),spec=CantileverSpec())
    with pytest.raises(ValueError):
        ETABSRequest(config=ETABSConfig(wall_vertical_subdivisions=2),spec=CantileverSpec())


def test_reciprocity_audit_detects_case_component_misassignment() -> None:
    from struct_agent.adapters.etabs.x_report import compliance_audit
    data={'static':{'ROOF_X':{'floors':[{'u1':2.,'u2':.1}]},'ROOF_Y':{'floors':[{'u1':.1,'u2':3.}]}}}
    audit=compliance_audit(data,1.,'opensees')
    assert audit['reciprocity_check'] and audit['positive_work']
    for force in (0.,-1.,float('nan'),float('inf')):
        with pytest.raises(ValueError):
            compliance_audit(data,force,'opensees')
    data['static']['ROOF_Y']['floors'][0]['u1']=1.
    assert not compliance_audit(data,1.,'opensees')['reciprocity_check']
