from pathlib import Path

import pytest

from struct_agent.adapters.etabs.contracts import ResidentialSpec
from struct_agent.adapters.etabs.opensees_reference import run_reference
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
