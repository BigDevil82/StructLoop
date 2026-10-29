"""Geometry-derived beam-height interfaces; no fitted stiffness or new mass."""
from __future__ import annotations

from typing import Any

import numpy as np

from struct_agent.schemas.base import Contract
from .contracts import ResidentialSpec
from .residential_input import prepare


class BeamInterface(Contract):
    face_nodes: bool = True
    rigid: bool = False


def interface_geometry(spec: ResidentialSpec, subdivisions: int, interface: BeamInterface) -> dict[str,Any]:
    """Coordinates are global local-origin XYZ, m; levels are story fractions.

    The vertical line at each supported beam end spans its actual half-depth
    above/below the beam centre, clipped to the existing wall height at roof.
    The rigid option is a stated plane-section idealization, not a calibrated
    material property. Point and rigid runs share exactly the same wall mesh.
    """
    if subdivisions not in (1,2,4,8,16) or (interface.rigid and not interface.face_nodes):
        raise ValueError('A bounded mesh and face nodes for rigid interfaces are required')
    data = prepare(spec)
    h,n = spec.project.story_height_m,spec.project.stories
    walls = {p for m in data.layout.members if m.role=='wall' for p in (m.start,m.end)}
    depths: dict[tuple[float,float],float] = {}
    for beam in data.layout.members:
        if beam.role=='wall':
            continue
        depth = float(spec.design.values['hb_main' if beam.role=='primary' else 'hb_sec'])
        for point in (beam.start,beam.end):
            if point in walls:
                depths[point] = max(depths.get(point,0.),depth)
    levels = {round(story+step/subdivisions,12) for story in range(n) for step in range(subdivisions+1)}
    if interface.face_nodes:
        for story in range(1,n+1):
            for depth in depths.values():
                levels.update(round(value,12) for value in (story-depth/(2*h),story+depth/(2*h)) if 0.<value<n)
    ordered = sorted(levels)
    story_levels = [[level for level in ordered if story-1-1e-10<=level<=story+1e-10] for story in range(1,n+1)]
    groups = []
    if interface.rigid:
        for story in range(1,n+1):
            for point,depth in sorted(depths.items()):
                slaves = [level for level in ordered if abs(level-story)*h<=depth/2+1e-9 and abs(level-story)>1e-9]
                groups.append({'story':story,'point':list(point),'depth_m':depth,
                    'master_xyz_m':[*point,story*h],
                    'slaves_xyz_m':[[*point,level*h] for level in slaves],
                    'slave_levels':slaves,'roof_clipped':story==n})
    return {'options':interface.model_dump(),'subdivisions':subdivisions,'levels':ordered,
        'story_levels':story_levels,'groups':groups,'wall_panels_per_source':sum(len(x)-1 for x in story_levels),
        'rigid_link_count':sum(len(g['slave_levels']) for g in groups),'added_mass':0.,'added_diaphragms':0}


def interface_residual(groups: list[dict[str,Any]], displacements: dict[str,list[float]]) -> dict[str,Any]:
    """Small-rotation rigid-body equations, u_s=u_m+theta cross offset."""
    translation,rotation = 0.,0.
    for group in groups:
        master = np.asarray(displacements[str(group['master'])])
        for slave,offset in zip(group['slaves'],group['offsets_m']):
            u = np.asarray(displacements[str(slave)])
            translation = max(translation,float(np.max(abs(u[:3]-master[:3]-np.cross(master[3:],offset)))))
            rotation = max(rotation,float(np.max(abs(u[3:]-master[3:]))))
    return {'max_translation_residual_m':translation,'max_rotation_residual_rad':rotation,
        'verified':translation<1e-8 and rotation<1e-9}


def aggregation_targets(plan: dict[str,Any], geometry: dict[str,Any] | None) -> dict[tuple[float,...],tuple[str,np.ndarray]]:
    """Map wall nodal forces to interface centres, preserving r cross F."""
    mapping = {tuple(round(v,6) for v in xyz):(key,np.zeros(3)) for key,xyz in plan['points'].items()}
    if geometry is not None:
        for group in geometry['groups']:
            centre = np.asarray(group['master_xyz_m'])
            key = next(key for key,xyz in plan['points'].items() if np.max(abs(centre-xyz))<1e-7)
            for xyz in group['slaves_xyz_m']:
                mapping[tuple(round(v,6) for v in xyz)] = key,np.asarray(xyz)-centre
    return mapping
