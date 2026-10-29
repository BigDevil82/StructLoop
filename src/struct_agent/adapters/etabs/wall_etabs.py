"""Dedicated-instance ShellThin wall study; every case keeps its native files."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from struct_agent.io.artifacts import write_json
from .client import ETABSClient, rows
from .contracts import SingleWallSpec
from .residential import DISPLACEMENT_FIELDS
from .wall_input import WallCase, beam_reference, response_checks, wall_cases


def solve_wall(client: ETABSClient, case: WallCase, directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory/'input.json', case.model_dump())
    m, call = client.model, client.call
    call('InitializeWall', m.InitializeNewModel, 10)
    call('NewWallBlank', m.File.NewBlank)
    call('WallUnits', m.SetPresentUnits, 10)
    call('WallStories', m.Story.SetStories_2, 0., case.stories,
        [f'S{i}' for i in range(1, case.stories+1)], [case.story_height_m]*case.stories,
        [True]*case.stories, ['']*case.stories, [False]*case.stories, [0.]*case.stories, [0]*case.stories)
    call('WallMaterial', m.PropMaterial.SetMaterial, 'ELASTIC', 2)
    call('WallElastic', m.PropMaterial.SetMPIsotropic, 'ELASTIC', case.elastic_modulus_pa, case.poisson, 0.)
    call('WallZeroDensity', m.PropMaterial.SetWeightAndMass, 'ELASTIC', 2, 0.)
    call('WallSection', m.PropArea.SetWall, 'WALL', 1, 1, 'ELASTIC', case.thickness_m)
    modifiers = [1., 1., 1., .63**3, .63**3, .63**3, 1., 1., 1., 1.]
    call('WallModifiers', m.PropArea.SetModifiers, 'WALL', modifiers)
    material = call('ReadWallElastic', m.PropMaterial.GetMPIsotropic, 'ELASTIC')
    section = call('ReadWallSection', m.PropArea.GetWall, 'WALL')
    actual_modifiers = call('ReadWallModifiers', m.PropArea.GetModifiers, 'WALL')[0]
    if (not math.isclose(material[0], case.elastic_modulus_pa, rel_tol=1e-12)
            or not math.isclose(material[1], case.poisson, abs_tol=1e-12)
            or list(actual_modifiers) != modifiers or section[:3] != (1, 1, 'ELASTIC')
            or not math.isclose(section[3], case.thickness_m, rel_tol=1e-12)):
        raise ValueError('Single-wall material/section readback mismatch')
    nodes, geometry = [], []
    for level in range(case.panels+1):
        pair = []
        for side in range(2):
            coord = ((side-.5)*case.length_m, 0., level*case.height_m/case.panels)
            name, = call('AddWallNode', m.PointObj.AddCartesian, *coord, '')
            restraint = [True]*6 if level == 0 else [False, True, False, True, False, True]
            call('WallRestraint', m.PointObj.SetRestraint, name, restraint)
            actual = call('ReadWallCoord', m.PointObj.GetCoordCartesian, name)
            if (len(actual) != 3 or any(abs(a-b) > 1e-8 for a, b in zip(actual, coord))
                    or list(call('ReadWallRestraint', m.PointObj.GetRestraint, name)[0]) != restraint):
                raise ValueError('Single-wall node geometry/restraint readback mismatch')
            pair.append(name)
            geometry.append({'node':name, 'xyz_m':actual, 'restraint':restraint})
        nodes.append(pair)
        if level and level % case.subdivisions == 0 and case.diaphragm == 'physical_floors':
            # NewBlank already defines D1; SetDiaphragm rejects redefining it
            # in ETABS 18.1. Use names owned by this diagnostic only.
            label = f'SL_WALL_D{level//case.subdivisions}'
            call('DefineWallDiaphragm', m.Diaphragm.SetDiaphragm, label, False)
            for name in pair:
                call('AssignWallDiaphragm', m.PointObj.SetDiaphragm, name, 3, label)
                if call('ReadWallDiaphragm', m.PointObj.GetDiaphragm, name)[-1] != label:
                    raise ValueError('Single-wall diaphragm assignment readback mismatch')
    areas = []
    for lower, upper in zip(nodes, nodes[1:]):
        corners = [*lower, upper[1], upper[0]]
        result = call('AddWallPanel', m.AreaObj.AddByPoint, 4, corners, '', 'WALL')
        name = result[-1]
        connectivity = call('ReadWallPanel', m.AreaObj.GetPoints, name)
        if connectivity[0] != 4 or list(connectivity[1]) != corners:
            raise ValueError('Single-wall panel connectivity readback mismatch')
        areas.append({'object':name, 'corners':corners})
    counts = {'areas':call('WallAreaCount', m.AreaObj.GetNameList)[0],
        'points':call('WallPointCount', m.PointObj.GetNameList)[0]}
    if counts != {'areas':case.panels, 'points':2*(case.panels+1)}:
        raise ValueError(f'Single-wall object count mismatch: {counts}')
    write_json(directory/'model_mapping.json', {'nodes':geometry, 'areas':areas, 'counts':counts,
        'material':material, 'section':section, 'modifiers':actual_modifiers,
        'added_floor_mass':0, 'added_floor_beams':0, 'new_mesh_level_diaphragms':0})
    call('WallLoadPattern', m.LoadPatterns.Add, 'TIP_X', 8, 0., True)
    for name in nodes[-1]:
        call('WallTipLoad', m.PointObj.SetLoadForce, name, 'TIP_X', [case.tip_force_n/2, 0., 0., 0., 0., 0.], True)
    call('DisableWallDefaultCases', m.Analyze.SetRunCaseFlag, '', False, True)
    call('EnableWallTip', m.Analyze.SetRunCaseFlag, 'TIP_X', True)
    call('SaveWallBeforeAnalysis', m.File.Save, str(directory/'model.EDB'))
    call('RunWallAnalysis', m.Analyze.RunAnalysis)
    raw_status = call('WallCaseStatus', m.Analyze.GetCaseStatus)
    state = dict(zip(raw_status[1], raw_status[2]))
    if state.get('TIP_X') != 4:
        raise RuntimeError(f'Wall case not finished: {case.case_id}: {state}')
    call('DeselectWallOutput', m.Results.Setup.DeselectAllCasesAndCombosForOutput)
    call('SelectWallOutput', m.Results.Setup.SetCaseSelectedForOutput, 'TIP_X')
    displacement = []
    for pair in nodes:
        values = []
        for name in pair:
            records = rows(call('WallJointDispl', m.Results.JointDispl, name, 0),
                DISPLACEMENT_FIELDS, operation='WallJointDispl')
            if len(records) != 1 or records[0]['case'] != 'TIP_X':
                raise ValueError('Unexpected single-wall displacement case/count')
            values.append([records[0][k] for k in ('u1', 'u2', 'u3', 'r1', 'r2', 'r3')])
        displacement.append(values)
    raw_reaction = call('WallBaseReact', m.Results.BaseReact)
    reactions = rows(raw_reaction[:-3], ('case', 'step_type', 'step', 'fx', 'fy', 'fz', 'mx', 'my', 'mz'),
        operation='WallBaseReact')
    if len(reactions) != 1 or reactions[0]['case'] != 'TIP_X':
        raise ValueError('Unexpected single-wall reaction case/count')
    checks = response_checks(case, displacement, reactions[0], raw_reaction[-3:])
    tip = sum(node[0] for node in displacement[-1])/2
    theory = beam_reference(case)
    result = {'case':case.model_dump(), 'checks':checks, 'verified':all(checks.values()),
        'tip_x_m':tip, 'displacement':displacement, 'base_reaction':reactions[0],
        'reaction_reference_xyz_m':raw_reaction[-3:], 'beam_reference':theory,
        'beam_relative_difference':tip/theory['timoshenko_m']-1, 'case_status':state,
        'engineering_feasibility':'NOT_EVALUATED'}
    write_json(directory/'result.json', result)
    return result


def build_and_analyze(client: ETABSClient, spec: SingleWallSpec, directory: Path) -> dict[str, Any]:
    results = []
    for case in wall_cases(spec):
        print(f'STAGE single_wall_{case.case_id}', flush=True)
        results.append(solve_wall(client, case, directory/case.case_id))
    return {'purpose':'RESIDENTIAL_DERIVED_SINGLE_WALL_DIAGNOSTIC', 'units':'N_m_kg_s',
        'verified':all(r['verified'] for r in results), 'cases':results,
        'engineering_feasibility':'NOT_EVALUATED'}
