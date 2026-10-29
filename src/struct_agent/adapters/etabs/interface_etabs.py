"""Fixed six-DOF rigid links: no user-selected penalty stiffness."""
from __future__ import annotations

from typing import Any

from .client import ETABSClient,rows
from .interface_geometry import interface_residual


def add_interfaces(client: ETABSClient, nodes: dict[Any,str], geometry: dict[str,Any]) -> list[dict[str,Any]]:
    m,call = client.model,client.call
    if not geometry['groups']:
        return []
    call('DefineFixedInterface',m.PropLink.SetLinear,'BEAM_FACE_RIGID',[True]*6,[True]*6,[0.]*6,[0.]*6,0.,0.)
    raw = call('ReadFixedInterface',m.PropLink.GetLinear,'BEAM_FACE_RIGID')
    if not all(raw[0]) or not all(raw[1]) or any(raw[2]) or any(raw[3]):
        raise ValueError('Rigid interface property readback mismatch')
    groups = []
    for group in geometry['groups']:
        point = tuple(group['point'])
        master = nodes[group['story'],point]
        slaves = [nodes[level,point] for level in group['slave_levels']]
        links = []
        for slave in slaves:
            name, = call('AddFixedInterface',m.LinkObj.AddByPoint,master,slave,'',False,'BEAM_FACE_RIGID')
            if tuple(call('ReadFixedInterfaceEnds',m.LinkObj.GetPoints,name)) != (master,slave):
                raise ValueError('Rigid interface connectivity mismatch')
            links.append(name)
        groups.append({'master':master,'slaves':slaves,'links':links,
            'offsets_m':[[0.,0.,xyz[2]-group['master_xyz_m'][2]] for xyz in group['slaves_xyz_m']]})
    return groups


def read_interface_residual(client: ETABSClient, groups: list[dict[str,Any]]) -> dict[str,Any]:
    m,call = client.model,client.call
    data = {}
    for node in {n for g in groups for n in (g['master'],*g['slaves'])}:
        values = rows(call('ReadInterfaceMotion',m.Results.JointDispl,node,0),
            ('object','element','case','step_type','step','u1','u2','u3','r1','r2','r3'),operation='ReadInterfaceMotion')
        if len(values)!=1:
            raise ValueError('Exactly one static interface response required')
        data[str(node)] = [values[0][key] for key in ('u1','u2','u3','r1','r2','r3')]
    return interface_residual(groups,data)
