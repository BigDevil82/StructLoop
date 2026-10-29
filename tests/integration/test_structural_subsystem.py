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
