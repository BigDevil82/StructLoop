import numpy as np
import pytest

from struct_agent.adapters.etabs.joint_mechanics import euler_end_forces,joint_plan
from struct_agent.adapters.etabs.contracts import JointRotationSpec,ResidentialSpec,ETABSConfig,ETABSRequest
from struct_agent.schemas import DesignCandidate,LayoutCandidate,ProjectSpec,Member


def test_independent_beam_law_has_rigid_body_null_modes_and_correct_strong_bending() -> None:
    section = dict(E=30e9,G=12.5e9,A=.125,J=.001788,Iy=.25*.5**3/12,Iz=.5*.25**3/12)
    length = 1.8
    u = np.zeros((2,6))
    u[:,:3] = [1.,2.,3.]
    u[:,3:] = [4.,5.,6.]
    u[1,:3] += np.cross(u[0,3:],[length,0.,0.])
    np.testing.assert_allclose(euler_end_forces(u,length,section),0.,atol=1e-5)
    # Exact tip response for a cantilever under a positive global-Y moment:
    # UZ=-ML²/(2EI), RY=ML/EI. Root force zero, opposing end moments.
    u[:] = 0.
    moment = 1000.
    u[1,2] = -moment*length**2/(2*section['E']*section['Iy'])
    u[1,4] = moment*length/(section['E']*section['Iy'])
    f = euler_end_forces(u,length,section)
    np.testing.assert_allclose(f[:,4],[-moment,moment],atol=1e-9)
    np.testing.assert_allclose(f[:,:3],0.,atol=1e-9)
    with pytest.raises(ValueError):
        euler_end_forces(np.zeros((2,3)),length,section)


def test_joint_schema_binds_a_full_beam_to_two_source_walls(
        spec: ProjectSpec,layout: LayoutCandidate,design: DesignCandidate) -> None:
    members = tuple(Member(member_id=f'm{i}',start=a,end=b,role=role) for i,(a,b,role) in enumerate((
        ((0.,0.),(1.,0.),'wall'),((0.,0.),(0.,3.),'wall'),
        ((3.,0.),(4.,0.),'wall'),((4.,0.),(4.,3.),'wall'),((1.,0.),(3.,0.),'primary'))))
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),
        layout=layout.model_copy(update={'members':members}),design=design)
    request = ETABSRequest(spec=JointRotationSpec(residential=parent),config=ETABSConfig(beam_theory='euler_comparison'))
    assert ETABSRequest.model_validate_json(request.model_dump_json())==request
    plan = joint_plan(parent)
    assert len(plan['probes'])==4 and len(plan['beams'])==12
    assert all(p['moment_nm']==1000. and p['dof'] in (3,4) for p in plan['probes'].values())
    with pytest.raises(ValueError,match='12-story'):
        JointRotationSpec(residential=parent.model_copy(update={'project':parent.project.model_copy(update={'stories':1})}))
    with pytest.raises(ValueError):
        JointRotationSpec(residential=ResidentialSpec(project=spec.model_copy(update={'stories':12}),layout=layout,design=design))
