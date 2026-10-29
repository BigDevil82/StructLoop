import json
from pathlib import Path

import pytest
import numpy as np

from struct_agent.adapters.etabs.contracts import ResidentialSpec
from struct_agent.adapters.etabs.interface_geometry import BeamInterface
from struct_agent.adapters.etabs.opensees_reference import run_reference
from struct_agent.adapters.etabs.reference_mesh import ReferenceMesh
from struct_agent.schemas import Member,ProjectSpec,LayoutCandidate,DesignCandidate


@pytest.mark.real
@pytest.mark.parametrize('formulation,horizontal',[('mvlem',1),('shell_dkgq',1),('shell_dkgq',2)])
def test_finite_beam_interface_preserves_stiffness_mass_and_exact_nested_constraints(
        tmp_path: Path,spec: ProjectSpec,layout: LayoutCandidate,design: DesignCandidate,
        formulation: str,horizontal: int) -> None:
    members = tuple(Member(member_id=f'm{i}',start=a,end=b,role=role) for i,(a,b,role) in enumerate((
        ((0.,0.),(1.,0.),'wall'),((0.,0.),(0.,3.),'wall'),
        ((3.,0.),(4.,0.),'wall'),((4.,0.),(4.,3.),'wall'),((1.,0.),(3.,0.),'primary'))))
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),
        layout=layout.model_copy(update={'members':members}),design=design)
    mesh_options = ReferenceMesh(vertical_subdivisions=2,wall_formulation=formulation,horizontal_subdivisions=horizontal)
    result = run_reference(parent,tmp_path/'rigid',mesh=mesh_options,
        interface=BeamInterface(rigid=True),static_only=True,handler='Lagrange',joint_rotation=True,solver='SparseGeneral')
    assert result['verified'] and result['periods_s']==[]
    assert all(row['interface_constraints']['verified'] for row in result['static'].values())
    mesh = json.loads((tmp_path/'rigid/mesh.json').read_text(encoding='utf-8'))
    assert mesh['beam_elements']==12 and len(mesh['interface_groups'])==24
    assert not mesh['removed_beam_tags'] and not mesh['released_beam_tags']
    if horizontal>1:
        from struct_agent.adapters.etabs.residential_input import prepare
        data = prepare(parent)
        protocol = json.loads((tmp_path/'rigid/horizontal_mesh_protocol.json').read_text(encoding='utf-8'))
        assert protocol['original_centre_xy_m']==list(data.centre_xy_m)
        assert protocol['floor_masses_and_inertia_restored']
        assert protocol['added_physical_stories']==0 and protocol['added_mass']==0.
    checks = json.loads((tmp_path/'rigid/joint_checks.json').read_text(encoding='utf-8'))
    assert checks['verified']
    assert result['static']['ROOF_X']['roof_xy_load_factors']==[1.,0.]
    assert result['static']['ROOF_Y']['roof_xy_load_factors']==[0.,1.]
    separate = run_reference(parent,tmp_path/'separate',mesh=mesh_options,
        interface=BeamInterface(rigid=True),static_only=True,handler='Lagrange',solver='SparseGeneral',
        reuse_static_factorization=False,joint_rotation=True)
    assert json.loads((tmp_path/'separate/joint_checks.json').read_text(encoding='utf-8'))['verified']
    for case in ('ROOF_X','ROOF_Y'):
        # Compare the entire displacement field in common length units. Tiny
        # symmetry-zero components are sensitive to cancellation when moving
        # from X to Y; they are included, without dividing by their own zero.
        points = [p for m in parent.layout.members for p in (m.start,m.end)]
        radius = max(np.linalg.norm(np.asarray(a)-b) for a in points for b in points)
        left = np.array([[row[k] for k in ('u1','u2','r3')] for row in result['static'][case]['floors']])
        right = np.array([[row[k] for k in ('u1','u2','r3')] for row in separate['static'][case]['floors']])
        weights = np.array([1.,1.,radius])
        relative = np.linalg.norm((left-right)*weights)/np.linalg.norm(right*weights)
        assert relative<1e-7


@pytest.mark.real
def test_lagrange_and_transformation_reproduce_the_same_original_model(
        tmp_path: Path,spec: ProjectSpec,layout: LayoutCandidate,design: DesignCandidate) -> None:
    second = layout.members[0].model_copy(update={'member_id':'other','end':(0.,3.)})
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),
        layout=layout.model_copy(update={'members':(*layout.members,second)}),design=design)
    a = run_reference(parent,tmp_path/'transform',static_only=True)
    b = run_reference(parent,tmp_path/'lagrange',static_only=True,handler='Lagrange')
    assert a['verified'] and b['verified']
    for case in ('ROOF_X','ROOF_Y'):
        for left,right in zip(a['static'][case]['floors'],b['static'][case]['floors']):
            for key in ('u1','u2','r3'):
                assert left[key]==pytest.approx(right[key],rel=1e-8,abs=1e-12)
