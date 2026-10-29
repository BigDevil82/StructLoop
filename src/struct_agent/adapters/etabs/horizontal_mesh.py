"""Explicit shell subdivisions, preserving the parent mass/loading protocol."""
from __future__ import annotations

import math
from typing import Any

from struct_agent.schemas import LayoutCandidate,Member
from .residential_input import ResidentialInput


def wall_mesh_points(member: Member, divisions: int) -> list[tuple[float,float]]:
    """Metre coordinates shared by both diagnostic solvers, rounded to 1 um."""
    if divisions not in (1,2,4):
        raise ValueError('Controlled horizontal shell divisions are 1, 2 or 4')
    return [tuple(round(member.start[k]+j/divisions*(member.end[k]-member.start[k]),6)
                  for k in (0,1)) for j in range(divisions+1)]


def split_shell_layout(layout: LayoutCandidate, divisions: int) -> tuple[LayoutCandidate,list[int]]:
    if divisions not in (1,2,4):
        raise ValueError('Controlled horizontal shell divisions are 1, 2 or 4')
    members,origins = [],[]
    for index,member in enumerate(layout.members):
        if member.role!='wall':
            members.append(member)
            origins.append(index)
            continue
        points = wall_mesh_points(member,divisions)
        for j,(left,right) in enumerate(zip(points,points[1:])):
            members.append(Member(member_id=f'{member.member_id}__h{j}',start=left,end=right,role='wall'))
            origins.append(index)
    old_length = sum(math.dist(m.start,m.end) for m in layout.members if m.role=='wall')
    new_length = sum(math.dist(m.start,m.end) for m in members if m.role=='wall')
    if not math.isclose(old_length,new_length,rel_tol=1e-10,abs_tol=1e-8):
        raise ValueError('Horizontal mesh changed physical wall length')
    return layout.model_copy(update={'members':tuple(members)}),origins


def restore_parent_floor_protocol(build: Any,data: ResidentialInput,origins: list[int]) -> dict[str,Any]:
    """Refinement adds floor nodes, never new floors/masses or a new centroid.

    The upstream builder's endpoint-count inertia is a prescribed diagnostic
    protocol. Recompute its diaphragm equations about the original centroid
    after subdivision, instead of silently changing that engineering input.
    """
    import openseespy.opensees as ops
    before,after = [],[]
    for master,slaves,floor in zip(build.master_nodes,build.floor_story_nodes,data.floors):
        before.append({'master':master,'coordinates_m':ops.nodeCoord(master),'mass':ops.nodeMass(master)})
        for slave in slaves:
            ops.remove('mp',slave)
        ops.setNodeCoord(master,1,data.centre_xy_m[0])
        ops.setNodeCoord(master,2,data.centre_xy_m[1])
        ops.mass(master,floor.mass_kg,floor.mass_kg,0.,0.,0.,floor.inertia_kg_m2)
        ops.rigidDiaphragm(3,master,*slaves)
        coordinates,mass = ops.nodeCoord(master),ops.nodeMass(master)
        expected_mass = [floor.mass_kg,floor.mass_kg,0.,0.,0.,floor.inertia_kg_m2]
        if not all(math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9) for a,b in zip(mass,expected_mass)):
            raise ValueError('Parent floor mass/inertia restoration failed')
        if not all(math.isclose(a,b,abs_tol=1e-9) for a,b in zip(coordinates[:2],data.centre_xy_m)):
            raise ValueError('Parent floor centre restoration failed')
        after.append({'master':master,'coordinates_m':coordinates,'mass':mass})
    for beam in build.beam_element_units:
        beam.beam_id = origins[beam.beam_id]
    for wall in build.wall_mesh_element_units:
        wall.wall_id = origins[wall.wall_id]
    return {'original_centre_xy_m':data.centre_xy_m,'builder_before_correction':before,'readback_after_correction':after,
        'floor_masses_and_inertia_restored':True,'floor_diaphragms_rebuilt_about_parent_centre':True,
        'source_member_indices':origins,'added_physical_stories':0,'added_mass':0.}
