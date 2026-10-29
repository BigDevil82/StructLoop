import pytest

from struct_agent.adapters.etabs.contracts import ConnectionStudySpec, ETABSConfig, ETABSRequest, ResidentialSpec
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec


def test_fixed_connection_study_schema_preserves_inputs_and_requires_beams(
        spec: ProjectSpec, design: DesignCandidate, layout: LayoutCandidate) -> None:
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),layout=layout,design=design)
    with pytest.raises(ValueError):
        ConnectionStudySpec(residential=parent)
    beam = layout.members[0].model_copy(update={'member_id':'beam','role':'primary','end':(0.,4.)})
    unsupported = parent.model_copy(update={'layout':layout.model_copy(update={'members':(*layout.members,beam)})})
    with pytest.raises(ValueError,match='unsupported vertical'):
        ConnectionStudySpec(residential=unsupported)
    second_wall = layout.members[0].model_copy(update={'member_id':'second','end':(0.,4.)})
    parent = parent.model_copy(update={'layout':layout.model_copy(update={'members':(*layout.members,second_wall,beam)})})
    request = ETABSRequest(spec=ConnectionStudySpec(residential=parent),config=ETABSConfig(beam_theory='euler_comparison'))
    assert ETABSRequest.model_validate_json(request.model_dump_json()) == request
    assert ETABSRequest(spec=ConnectionStudySpec(residential=parent,modes=('pinned_bending',)),
        config=ETABSConfig(beam_theory='euler_comparison',wall_vertical_subdivisions=4)).spec.modes == ('pinned_bending',)
    with pytest.raises(ValueError):
        ConnectionStudySpec(residential=parent,modes=('default',))
    with pytest.raises(ValueError,match='fixes Euler'):
        ETABSRequest(spec=request.spec,config=ETABSConfig())
