from pathlib import Path

import pytest

from struct_agent.adapters.etabs.contracts import ResidentialSpec
from struct_agent.adapters.etabs.opensees_reference import run_reference
from struct_agent.adapters.etabs.reference_mesh import ReferenceMesh
from struct_agent.schemas import ProjectSpec, DesignCandidate, LayoutCandidate


@pytest.mark.real
def test_l_wall_subsystem_runs_with_shared_corner_and_prescribed_mass(
        tmp_path: Path, spec: ProjectSpec, design: DesignCandidate, layout: LayoutCandidate) -> None:
    second = layout.members[0].model_copy(update={'member_id':'perpendicular', 'end':(0.,2.)})
    model = layout.model_copy(update={'members':(*layout.members, second)})
    request = ResidentialSpec(project=spec.model_copy(update={'stories':12}), layout=model, design=design)
    result = run_reference(request, tmp_path/'subsystem')
    assert result['verified']
    assert len(result['periods_s']) == 12
    assert len(result['floor_inputs']) == 12
    assert all(all(check.values()) for check in result['checks'].values())


@pytest.mark.real
def test_diagnostic_shell_substitution_preserves_mass_geometry_and_solves(
        tmp_path: Path, spec: ProjectSpec, design: DesignCandidate, layout: LayoutCandidate) -> None:
    import json
    second = layout.members[0].model_copy(update={'member_id':'perpendicular', 'end':(0.,2.)})
    model = layout.model_copy(update={'members':(*layout.members,second)})
    request = ResidentialSpec(project=spec.model_copy(update={'stories':12}),layout=model,design=design)
    result = run_reference(request,tmp_path/'shell',mesh=ReferenceMesh(wall_formulation='shell_dkgq',vertical_subdivisions=2))
    assert result['verified'] and len(result['periods_s']) == 12
    mapping = json.loads((tmp_path/'shell'/'mesh.json').read_text())
    assert mapping['wall_elements'] == 48 and mapping['beam_elements'] == 0
    assert mapping['added_floor_masses'] == mapping['added_diaphragms'] == 0
    assert all(row['fibers_per_section'] is None for row in mapping['wall_mapping'])


@pytest.mark.real
@pytest.mark.parametrize('formulation',['mvlem','shell_dkgq'])
def test_bending_release_preserves_prescribed_mass_and_has_zero_beam_moments(
        tmp_path: Path, spec: ProjectSpec, design: DesignCandidate, layout: LayoutCandidate,
        formulation: str) -> None:
    # Two L walls coupled by one beam, matching the real diagnostic topology.
    from struct_agent.schemas import Member
    members = tuple(Member(member_id=f'm{i}',start=a,end=b,role=role) for i,(a,b,role) in enumerate((
        ((0.,0.),(1.,0.),'wall'),((0.,0.),(0.,3.),'wall'),
        ((3.,0.),(4.,0.),'wall'),((4.,0.),(4.,3.),'wall'),((1.,0.),(3.,0.),'primary'),
        ((1.,0.),(1.,-1.),'secondary'))))
    request = ResidentialSpec(project=spec.model_copy(update={'stories':12}),
        layout=layout.model_copy(update={'members':members}),design=design)
    result = run_reference(request,tmp_path/'released',mesh=ReferenceMesh(
        wall_formulation=formulation,beam_bending_released=True,beam_release_scope='wall_to_wall'))
    assert result['verified']
    assert all(row['released_beam_bending_zero'] for row in result['checks'].values())
    assert all(result['static'][case]['max_released_end_moment_nm'] < 1e-6 for case in ('ROOF_X','ROOF_Y'))
    import json
    info = json.loads((tmp_path/'released'/'mesh.json').read_text(encoding='utf-8'))
    assert info['beam_elements'] == 24 and len(info['released_beam_tags']) == 12


@pytest.mark.real
@pytest.mark.parametrize('formulation',['mvlem','shell_dkgq'])
def test_walls_only_removes_beams_preserves_parent_mass_and_fixes_only_null_dofs(
        tmp_path: Path, spec: ProjectSpec, design: DesignCandidate, layout: LayoutCandidate,
        formulation: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import openseespy.opensees as ops
    from struct_agent.adapters.etabs.residential_input import prepare
    from struct_agent.schemas import Member
    members = (*layout.members,Member(member_id='perpendicular',start=(0.,0.),end=(0.,3.),role='wall'),
        Member(member_id='auxiliary_beam',start=(4.,0.),end=(4.,2.),role='primary'))
    request = ResidentialSpec(project=spec.model_copy(update={'stories':12}),
        layout=layout.model_copy(update={'members':members}),design=design)
    fixed = []
    native_fix = ops.fix
    def recording_fix(tag: int, *dofs: int) -> None:
        fixed.append((tuple(ops.nodeCoord(tag)),dofs))
        native_fix(tag,*dofs)
    monkeypatch.setattr(ops,'fix',recording_fix)
    result = run_reference(request,tmp_path/'walls',mesh=ReferenceMesh(
        wall_formulation=formulation,remove_beam_stiffness=True,vertical_subdivisions=2))
    assert result['verified'] and len(result['periods_s']) == 12
    assert [r['mass_kg'] for r in result['floor_inputs']] == pytest.approx([f.mass_kg for f in prepare(request).floors])
    info = json.loads((tmp_path/'walls'/'mesh.json').read_text(encoding='utf-8'))
    assert info['beam_elements'] == 0 and len(info['removed_beam_tags']) == 12
    assert len(info['auxiliary_null_dof_nodes']) == 12
    assert info['wall_elements'] == 48
    assert len(fixed[-12:]) == 12
    assert all(coord[:2] == (4.,2.) and dofs == (0,0,1,1,1,0) for coord,dofs in fixed[-12:])
