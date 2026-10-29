import numpy as np
import pytest

from struct_agent.adapters.etabs.contracts import ResidentialSpec,InterfaceCase,InterfaceBatchSpec,ETABSConfig,ETABSRequest
from struct_agent.adapters.etabs.interface_geometry import BeamInterface,interface_geometry,interface_residual
from struct_agent.schemas import Member,ProjectSpec,LayoutCandidate,DesignCandidate


def test_interface_residual_uses_offset_cross_product_and_detects_chain_errors() -> None:
    groups = [{'master':1,'slaves':[2],'offsets_m':[[0.,0.,.25]]}]
    master = np.array([.1,.2,.3,.001,.002,.003])
    slave = master.copy()
    slave[:3] += np.cross(master[3:],[0.,0.,.25])
    values = {'1':master.tolist(),'2':slave.tolist()}
    assert interface_residual(groups,values)['verified']
    values['2'][0] += 1e-5
    assert not interface_residual(groups,values)['verified']


def test_faces_come_from_beam_depth_and_do_not_extend_wall_or_add_floors(
        spec: ProjectSpec,layout: LayoutCandidate,design: DesignCandidate) -> None:
    beam = Member(member_id='b',start=(4.,0.),end=(5.,0.),role='primary')
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),
        layout=layout.model_copy(update={'members':(*layout.members,beam)}),design=design)
    rigid = interface_geometry(parent,2,BeamInterface(rigid=True))
    point = interface_geometry(parent,2,BeamInterface())
    assert rigid['story_levels']==point['story_levels']
    depth = float(design.values['hb_main'])
    for group in rigid['groups']:
        assert group['depth_m']==depth
        assert all(0.<abs(p[2]-group['master_xyz_m'][2])<=depth/2+1e-8 for p in group['slaves_xyz_m'])
        assert all(0.<p[2]<=12*2.9 for p in group['slaves_xyz_m'])
    assert rigid['added_mass']==rigid['added_diaphragms']==0
    with pytest.raises(ValueError):
        interface_geometry(parent,2,BeamInterface(face_nodes=False,rigid=True))


def test_interface_request_keeps_bounded_cases_and_euler_scope(
        spec: ProjectSpec,layout: LayoutCandidate,design: DesignCandidate) -> None:
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),layout=layout,design=design)
    case = InterfaceCase(name='rigid_4_h2',subdivisions=4,rigid=True,horizontal_subdivisions=2,edge_constraints=False)
    batch = InterfaceBatchSpec(residential=parent,cases=(case,))
    request = ETABSRequest(config=ETABSConfig(beam_theory='euler_comparison'),spec=batch)
    assert ETABSRequest.model_validate_json(request.model_dump_json())==request
    with pytest.raises(ValueError,match='Unique'):
        InterfaceBatchSpec(residential=parent,cases=(case,case))
    with pytest.raises(ValueError,match='Euler'):
        ETABSRequest(config=ETABSConfig(),spec=batch)
    with pytest.raises(ValueError):
        InterfaceCase(name='../outside',subdivisions=4,rigid=True)
