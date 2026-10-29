"""Native six-DOF displacements and full beam/wall nodal forces, SI/global."""
from __future__ import annotations

from typing import Any

import numpy as np

from .client import ETABSClient, rows
from .contracts import ResidentialSpec
from .joint_mechanics import joint_plan
from .residential_input import prepare


def etabs_joint_results(client: ETABSClient, spec: ResidentialSpec,
                        nodes: dict[Any,str], mapping: list[dict[str,Any]]) -> dict[str,Any]:
    plan, data = joint_plan(spec),prepare(spec)
    m, call = client.model,client.call
    coordinate_keys = {tuple(round(v,6) for v in xyz):key for key,xyz in plan['points'].items()}
    objects = {key:nodes[round(xyz[2]/spec.project.story_height_m),(xyz[0],xyz[1])]
        for key,xyz in plan['points'].items()}
    beams = {str(item['story']):item['etabs_object'] for item in mapping if item['role']!='wall'}
    axes = {story:np.array(call('JointBeamAxes',m.FrameObj.GetTransformationMatrix,name)[0]).reshape(3,3)
        for story,name in beams.items()}
    section = call('JointBeamSection',m.PropFrame.GetSectProps,plan['beam_role'])
    result = {'plan':plan,'section':{'E':data.elastic_modulus_pa,'G':data.elastic_modulus_pa/(2*(1+data.poisson)),
        'A':section[0],'J':section[3],'Iy':section[5],'Iz':section[4]},'cases':{},'units':'N_m_rad'}
    coordinates = {}
    for case in ('ROOF_X','ROOF_Y',*plan['probes']):
        call('JointDeselect',m.Results.Setup.DeselectAllCasesAndCombosForOutput)
        call('JointSelect',m.Results.Setup.SetCaseSelectedForOutput,case)
        displacements = {}
        for key,name in objects.items():
            values = rows(call('JointSixDof',m.Results.JointDispl,name,0),
                ('object','element','case','step_type','step','u1','u2','u3','r1','r2','r3'),operation='JointSixDof')
            if len(values)!=1 or values[0]['case']!=case:
                raise ValueError('One static six-DOF response per point required')
            displacements[key] = [values[0][k] for k in ('u1','u2','u3','r1','r2','r3')]
        forces = {}
        for story,name in beams.items():
            values = rows(call('JointFullBeamForce',m.Results.FrameForce,name,0),
                ('object','station','element','element_station','case','step_type','step','p','v2','v3','t','m2','m3'),
                operation='JointFullBeamForce')
            ends = []
            for position,sign in ((0.,-1.),(plan['beam_length_m'],1.)):
                endpoint = [r for r in values if abs(r['station']-position)<1e-8 and r['case']==case]
                if len(endpoint)!=1:
                    raise ValueError('Exactly one unoffset beam end result required')
                r = endpoint[0]
                vector = np.array([r[k] for k in ('p','v2','v3','t','m2','m3')]).reshape(2,3)
                ends.append((sign*(vector@axes[story].T)).ravel().tolist())
            forces[story] = ends
        wall_forces = {key:np.zeros(6) for key in plan['points']}
        raw_walls = {}
        for item in mapping:
            if item['role']!='wall':
                continue
            values = rows(call('JointWallNodalForces',m.Results.AreaJointForceShell,item['etabs_object'],0),
                ('object','element','point','case','step_type','step','f1','f2','f3','m1','m2','m3'),
                operation='JointWallNodalForces')
            raw_walls[item['etabs_object']] = values
            for r in values:
                if r['case']!=case:
                    raise ValueError('Unexpected shell-force case')
                point = r['point']
                if point not in coordinates:
                    coordinates[point] = call('JointElementPointCoord',m.PointElm.GetCoordCartesian,point)
                key = coordinate_keys.get(tuple(round(v,6) for v in coordinates[point]))
                if key is not None:
                    wall_forces[key] += [r[k] for k in ('f1','f2','f3','m1','m2','m3')]
        result['cases'][case] = {'displacements':displacements,'beam_forces':forces,
            'wall_forces':{key:value.tolist() for key,value in wall_forces.items()},'raw_wall_forces':raw_walls}
    return result


def opensees_joint_case(plan: dict[str,Any], build: Any) -> dict[str,Any]:
    import openseespy.opensees as ops
    coordinates = {tuple(round(v,6) for v in ops.nodeCoord(tag)):tag for tag in ops.getNodeTags()}
    points = {key:coordinates[tuple(round(v,6) for v in xyz)] for key,xyz in plan['points'].items()}
    displacements = {key:list(ops.nodeDisp(tag)) for key,tag in points.items()}
    beams = {str(b.story):b.element_tag for b in build.beam_element_units}
    if len(beams)!=len(plan['beams']) or not set(beams.values()).issubset(ops.getEleTags()):
        raise ValueError('Every full-stiffness source beam must remain present')
    beam_forces = {story:np.array(ops.eleForce(tag)).reshape(2,6).tolist() for story,tag in beams.items()}
    wall_forces = {key:np.zeros(6) for key in plan['points']}
    keys = {tag:key for key,tag in points.items()}
    raw_walls = {}
    for tag in set(ops.getEleTags())-set(beams.values()):
        ends = list(ops.eleNodes(tag))
        values = np.array(ops.eleForce(tag)).reshape(len(ends),6)
        raw_walls[str(tag)] = {'nodes':ends,'global_forces':values.tolist()}
        for node,force in zip(ends,values):
            if node in keys:
                wall_forces[keys[node]] += force
    return {'displacements':displacements,'beam_forces':beam_forces,
        'wall_forces':{key:value.tolist() for key,value in wall_forces.items()},'raw_wall_forces':raw_walls}


def opensees_joint_probes(plan: dict[str,Any], build: Any, bases: list[int]) -> dict[str,Any]:
    import openseespy.opensees as ops
    coordinates = {tuple(round(v,6) for v in ops.nodeCoord(tag)):tag for tag in ops.getNodeTags()}
    results = {}
    for index,(case,probe) in enumerate(plan['probes'].items(),101):
        point = coordinates[tuple(round(v,6) for v in plan['points'][probe['point']])]
        ops.reset()
        ops.wipeAnalysis()
        ops.constraints('Transformation')
        ops.numberer('RCM')
        ops.system('UmfPack')
        ops.timeSeries('Linear',index)
        ops.pattern('Plain',index,index)
        load = np.zeros(6)
        load[probe['dof']] = probe['moment_nm']
        ops.load(point,*load.tolist())
        ops.algorithm('Linear')
        ops.integrator('LoadControl',1.)
        ops.analysis('Static')
        if ops.analyze(1)!=0:
            raise RuntimeError(f'Joint moment probe failed: {case}')
        ops.reactions()
        reaction = np.zeros(6)
        for node in bases:
            f = np.asarray(ops.nodeReaction(node))
            reaction += f
            reaction[3:] += np.cross(ops.nodeCoord(node),f[:3])
        if not np.allclose(reaction,-load,atol=1e-5,rtol=1e-7):
            raise ValueError(f'Joint moment probe base equilibrium failed: {case}, {reaction}')
        results[case] = opensees_joint_case(plan,build)
        results[case]['base_reaction_global'] = reaction.tolist()
        ops.remove('loadPattern',index)
    return results
