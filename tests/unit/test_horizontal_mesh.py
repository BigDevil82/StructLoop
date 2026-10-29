import math
import pytest

from struct_agent.adapters.etabs.horizontal_mesh import split_shell_layout,wall_mesh_points
from struct_agent.adapters.etabs.reference_mesh import ReferenceMesh
from struct_agent.schemas import LayoutCandidate,Member


def test_horizontal_shell_mesh_preserves_beams_and_source_ids(layout: LayoutCandidate) -> None:
    beam = Member(member_id='b',start=(4.,0.),end=(6.,0.),role='primary')
    parent = layout.model_copy(update={'members':(*layout.members,beam)})
    split,origins = split_shell_layout(parent,4)
    assert origins==[0,0,0,0,1]
    assert split.members[-1]==beam and parent.members==(*layout.members,beam)
    assert [m.start for m in split.members[:-1]]==wall_mesh_points(layout.members[0],4)[:-1]
    assert sum(math.dist(m.start,m.end) for m in split.members if m.role=='wall')==pytest.approx(4.)
    with pytest.raises(ValueError,match='shell refinement'):
        ReferenceMesh(horizontal_subdivisions=2)
