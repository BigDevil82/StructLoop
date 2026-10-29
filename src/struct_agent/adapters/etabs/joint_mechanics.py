"""Fixed beam-wall probes and independent SI force/rotation checks."""
from __future__ import annotations

from typing import Any

import numpy as np

from .contracts import JointRotationSpec, ResidentialSpec
from .residential_input import prepare

MOMENT_NM = 1000.


def joint_plan(spec: ResidentialSpec) -> dict[str, Any]:
    """Global XYZ, translations m, rotations rad; no physical releases."""
    JointRotationSpec(residential=spec)
    data = prepare(spec)
    beam = next(m for m in data.layout.members if m.role != 'wall')
    points = {f'S{s}_P{i}':[*p,s*spec.project.story_height_m]
        for s in range(1,spec.project.stories+1) for i,p in enumerate(data.points)}
    beams = {}
    for story in range(1,spec.project.stories+1):
        ends = [f'S{story}_P{data.points.index(p)}' for p in (beam.start,beam.end)]
        walls = []
        for p in (beam.start,beam.end):
            candidates = [m for m in data.layout.members if m.role == 'wall'
                and p in (m.start,m.end) and abs(m.start[1]-m.end[1])<1e-8]
            if len(candidates) != 1:
                raise ValueError('Exactly one X-wall must meet each beam end for the section-rotation check')
            wall = candidates[0]
            pair = sorted((wall.start,wall.end))
            walls.append({'source_id':wall.member_id,'length_m':pair[1][0]-pair[0][0],
                'points':[f'S{story}_P{data.points.index(p)}' for p in pair]})
        beams[str(story)] = {'ends':ends,'adjacent_walls':walls}
    probes = {f'JOINT_{end}_{axis}':{'point':beams['1']['ends'][i],'dof':dof,'moment_nm':MOMENT_NM}
        for i,end in enumerate(('I','J')) for axis,dof in (('MX',3),('MY',4))}
    return {'points':points,'beams':beams,'probes':probes,'beam_source_id':beam.member_id,
        'beam_role':beam.role,'beam_length_m':beam.end[0]-beam.start[0]}


def euler_end_forces(displacement: np.ndarray, length: float, section: dict[str, float]) -> np.ndarray:
    """u[2,6] -> resisting f[2,6], float64, global XYZ, N/m/rad/Nm.

    Horizontal positive-X beam. All axial, bending and torsional terms remain.
    The vertical bending coordinates are (UZ,-RY), from the right-hand rule.
    """
    u = np.asarray(displacement,dtype=np.float64)
    if u.shape != (2,6) or not np.isfinite(u).all() or length <= 0.:
        raise ValueError('Finite two-end six-DOF displacements and a positive length required')
    f = np.zeros((2,6),dtype=np.float64)
    for dof, rigidity in ((0,section['E']*section['A']),(3,section['G']*section['J'])):
        value = rigidity/length*(u[0,dof]-u[1,dof])
        f[:,dof] = value,-value
    l = length
    k = np.array([[12,6*l,-12,6*l],[6*l,4*l*l,-6*l,2*l*l],
        [-12,-6*l,12,-6*l],[6*l,2*l*l,-6*l,4*l*l]],dtype=np.float64)/l**3
    for translation,rotation,inertia,sign in ((1,5,section['Iz'],1.),(2,4,section['Iy'],-1.)):
        indices = ((0,translation),(0,rotation),(1,translation),(1,rotation))
        signs = np.array([1.,sign,1.,sign])
        values = section['E']*inertia*(k@(np.array([u[i,j] for i,j in indices])*signs))*signs
        for (i,j),value in zip(indices,values):
            f[i,j] = value
    return f


def assess_joint(raw: dict[str, Any]) -> dict[str, Any]:
    """Check beam constitutive law, free joint DOFs and reciprocal compliance."""
    plan, section = raw['plan'],raw['section']
    checks, traces = [], {}
    for case, result in raw['cases'].items():
        trace = {}
        for story, beam in plan['beams'].items():
            u = np.array([result['displacements'][p] for p in beam['ends']])
            f = np.asarray(result['beam_forces'][story],dtype=np.float64)
            expected = euler_end_forces(u,plan['beam_length_m'],section)
            scale = np.array([1.,1.,1.,1/plan['beam_length_m'],1/plan['beam_length_m'],1/plan['beam_length_m']])
            residual = float(np.max(np.abs((f-expected)*scale))/max(1.,np.max(np.abs(f*scale))))
            checks.append(residual < 2e-5)
            chord = (u[1,2]-u[0,2])/plan['beam_length_m']
            wall_rotations = []
            for wall in beam['adjacent_walls']:
                left,right = (result['displacements'][p] for p in wall['points'])
                wall_rotations.append(-(right[2]-left[2])/wall['length_m'])
            trace[story] = {'end_ry_rad':u[:,4].tolist(),'wall_edge_ry_rad':wall_rotations,
                'beam_chord_slope':float(chord),'beam_end_my_nm':f[:,4].tolist(),
                'beam_constitutive_relative_residual':residual,
                'end_ry_minus_wall_edge_rad':(u[:,4]-wall_rotations).tolist()}
        balances = []
        for end, point in enumerate(plan['beams']['1']['ends']):
            wall = np.asarray(result['wall_forces'][point])
            beam = np.asarray(result['beam_forces']['1'][end])
            applied = np.zeros(6)
            if case in plan['probes'] and plan['probes'][case]['point'] == point:
                applied[plan['probes'][case]['dof']] = MOMENT_NM
            # Floor diaphragm acts on UX/UY/RZ only. These three components
            # must balance directly between the full beam and adjacent walls.
            dofs = [2,3,4]
            residual = wall[dofs]+beam[dofs]-applied[dofs]
            denominator = np.maximum(1.,np.maximum(abs(wall[dofs]),abs(beam[dofs])))
            balances.append({'point':point,'fz_mx_my_residual':residual.tolist(),
                'relative_residual':float(np.max(abs(residual)/denominator))})
            checks.append(balances[-1]['relative_residual']<1e-6)
        traces[case] = {'stories':trace,'joint_balances':balances}
    probes = list(plan['probes'].values())
    flexibility = np.array([[raw['cases'][case]['displacements'][p['point']][p['dof']]/MOMENT_NM
        for case in plan['probes']] for p in probes])
    reciprocity = float(np.linalg.norm(flexibility-flexibility.T)/np.linalg.norm(flexibility))
    checks += [reciprocity<1e-7,bool(np.linalg.eigvalsh((flexibility+flexibility.T)/2).min()>0.)]
    return {'verified':all(checks),'traces':traces,'flexibility_rad_per_nm':flexibility.tolist(),
        'reciprocity_relative_residual':reciprocity,'beam_stiffness':'ALL_COMPONENTS_RETAINED',
        'engineering_feasibility':'NOT_EVALUATED'}
