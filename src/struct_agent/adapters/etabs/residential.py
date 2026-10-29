"""12-story lateral model diagnostic, with source-ID mapping and no code verdict."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from struct_agent.io.artifacts import write_json
from .client import ETABSClient, rows
from .contracts import ResidentialSpec
from .residential_input import prepare
from .results import roof_equilibrium

DISPLACEMENT_FIELDS = ('object','element','case','step_type','step','u1','u2','u3','r1','r2','r3')


def beam_modifiers(theory: Literal['timoshenko','euler_comparison']) -> list[float]:
    """One-factor diagnostic: only shear deformation is suppressed, not EI/GJ."""
    if theory not in ('timoshenko','euler_comparison'):
        raise ValueError('Unknown beam comparison theory')
    scale = 1. if theory=='timoshenko' else 1e6
    return [1.,scale,scale,1.,1.,1.,1.,1.]


def build_and_analyze(client: ETABSClient, spec: ResidentialSpec, directory: Path, *,
                      beam_theory: Literal['timoshenko','euler_comparison']='timoshenko',
                      wall_vertical_subdivisions: int=1,
                      connection_mode: Literal['default','zero_offsets','pinned_bending','walls_only'] | None=None,
                      release_scope: Literal['all','wall_to_wall']='all',
                      joint_rotation: bool=False) -> dict[str,Any]:
    from struct_agent.adapters.fea import native_topology
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import wall_piers
    data = prepare(spec)
    if joint_rotation and connection_mode != 'default':
        raise ValueError('Joint rotation diagnostic retains default full-stiffness beam connections')
    if not 1<=wall_vertical_subdivisions<=4:
        raise ValueError('Bounded wall subdivision count required')
    if connection_mode not in (None,'default','zero_offsets','pinned_bending','walls_only'):
        raise ValueError('Unknown diagnostic beam connection mode')
    m, call, v = client.model, client.call, spec.design.values
    call('InitializeNewModel',m.InitializeNewModel,10)
    call('NewBlank',m.File.NewBlank)
    call('SetPresentUnits',m.SetPresentUnits,10)
    n = len(data.floors)
    call('SetStories',m.Story.SetStories_2,0.,n,[f'S{i}' for i in range(1,n+1)],
        [f.height_m for f in data.floors],[True]*n,['']*n,[False]*n,[0.]*n,[0]*n)
    call('SetMaterial',m.PropMaterial.SetMaterial,'COMMON_ELASTIC',2)
    call('SetElastic',m.PropMaterial.SetMPIsotropic,'COMMON_ELASTIC',data.elastic_modulus_pa,data.poisson,0.)
    call('ZeroElementDensity',m.PropMaterial.SetWeightAndMass,'COMMON_ELASTIC',2,0.)
    for role in ('primary','secondary'):
        suffix = 'main' if role=='primary' else 'sec'
        call('BeamSection '+role,m.PropFrame.SetRectangle,role,'COMMON_ELASTIC',float(v['hb_'+suffix]),float(v['bb_'+suffix]))
        call('BeamModifiers '+role,m.PropFrame.SetModifiers,role,beam_modifiers(beam_theory))
    modifiers = {role:call('ReadBeamModifiers '+role,m.PropFrame.GetModifiers,role)[0] for role in ('primary','secondary')}
    if any(list(value)!=beam_modifiers(beam_theory) for value in modifiers.values()):
        raise ValueError('Beam theory modifier readback mismatch')
    for thickness in sorted({f.wall_thickness_m for f in data.floors}):
        prop = f'W{round(thickness*1000)}'
        call('WallSection '+prop,m.PropArea.SetWall,prop,1,1,'COMMON_ELASTIC',thickness)
        # Match MVLEM_3D's documented 0.63 out-of-plane thickness multiplier.
        call('WallModifiers '+prop,m.PropArea.SetModifiers,prop,[1.,1.,1.,.63**3,.63**3,.63**3,1.,1.,1.,1.])
    if connection_mode == 'walls_only':
        material = call('ReadElasticMaterial',m.PropMaterial.GetMPIsotropic,'COMMON_ELASTIC')
        walls = {}
        for thickness in sorted({f.wall_thickness_m for f in data.floors}):
            prop = f'W{round(thickness*1000)}'
            definition = call('ReadWallDefinition',m.PropArea.GetWall,prop)
            values = call('ReadWallModifiers',m.PropArea.GetModifiers,prop)[0]
            if tuple(definition[:4]) != (1,1,'COMMON_ELASTIC',thickness) or list(values) != [1.,1.,1.,.63**3,.63**3,.63**3,1.,1.,1.,1.]:
                raise ValueError('Wall stiffness readback mismatch')
            walls[prop] = {'definition':definition,'modifiers':values}
        expected = (data.elastic_modulus_pa,data.poisson,0.,data.elastic_modulus_pa/(2*(1+data.poisson)))
        if len(material) != 4 or not all(math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8) for a,b in zip(material,expected)):
            raise ValueError('Material stiffness readback mismatch')
        write_json(directory/'stiffness_readback.json',{'material_E_nu_alpha_G':material,'walls':walls,'verified':True})
    piers = wall_piers(native_topology(data.layout).walls)
    source_to_pier = {index:f'P{pier.pier_id}' for pier in piers for index in pier.source_ids}
    existing = set(call('ExistingPiers',m.PierLabel.GetNameList)[1])
    for label in sorted(set(source_to_pier.values())-existing):
        call('DefinePier',m.PierLabel.SetPier,label)
    wall_points = {p for member in data.layout.members if member.role=='wall' for p in (member.start,member.end)}
    if connection_mode == 'pinned_bending' and release_scope == 'all' and any(
            member.start not in wall_points or member.end not in wall_points
            for member in data.layout.members if member.role != 'wall'):
        raise ValueError('All-end releases leave unsupported vertical joints')
    nodes = {}
    for level in range(n+1):
        for point in sorted(wall_points if level==0 else set(data.points)):
            name, = call('AddNode',m.PointObj.AddCartesian,*point,level*spec.project.story_height_m,'')
            nodes[level,point] = name
            if level==0:
                call('BaseFix',m.PointObj.SetRestraint,name,[True]*6)
            elif connection_mode == 'walls_only' and point not in wall_points:
                call('AuxiliaryNullDofs',m.PointObj.SetRestraint,name,[False,False,True,True,True,False])
    for story in range(1,n+1):
        for step in range(1,wall_vertical_subdivisions):
            level = story-1+step/wall_vertical_subdivisions
            for point in sorted(wall_points):
                name, = call('AddInternalWallNode',m.PointObj.AddCartesian,*point,level*spec.project.story_height_m,'')
                nodes[level,point] = name
    masters, mapping, connections = [], [], {}
    for floor in data.floors:
        story = floor.story
        diaphragm = f'SL_D{story}'
        call('RigidDiaphragm',m.Diaphragm.SetDiaphragm,diaphragm,False)
        for point in data.points:
            call('AssignDiaphragm',m.PointObj.SetDiaphragm,nodes[story,point],3,diaphragm)
        master, = call('AddMaster',m.PointObj.AddCartesian,*data.centre_xy_m,floor.elevation_m,'',f'MASTER_{story}','Global',True)
        call('MasterDiaphragm',m.PointObj.SetDiaphragm,master,3,diaphragm)
        call('MasterRestraint',m.PointObj.SetRestraint,master,[False,False,True,True,True,False])
        call('FloorMass',m.PointObj.SetMass,master,[floor.mass_kg,floor.mass_kg,0.,0.,0.,floor.inertia_kg_m2],0,False,True)
        masters.append(master)
        for index,member in enumerate(data.layout.members):
            a,b = nodes[story,member.start],nodes[story,member.end]
            if member.role=='wall':
                for part in range(wall_vertical_subdivisions):
                    lower,upper = story-1+part/wall_vertical_subdivisions,story-1+(part+1)/wall_vertical_subdivisions
                    result = call('AddWall',m.AreaObj.AddByPoint,4,
                        [nodes[lower,member.start],nodes[lower,member.end],nodes[upper,member.end],nodes[upper,member.start]],
                        '',f'W{round(floor.wall_thickness_m*1000)}')
                    name = result[-1]
                    call('WallPier',m.AreaObj.SetPier,name,source_to_pier[index])
                    mapping.append({'story':story,'source_id':member.member_id,'role':member.role,
                        'etabs_object':name,'mesh_piece':part})
            else:
                if connection_mode == 'walls_only':
                    continue
                name, = call('AddBeam',m.FrameObj.AddByPoint,a,b,'',member.role)
                if connection_mode is not None:
                    release_this = connection_mode == 'pinned_bending' and (release_scope == 'all'
                        or (member.start in wall_points and member.end in wall_points))
                    if connection_mode in ('zero_offsets','pinned_bending'):
                        call('ExplicitZeroEndOffsets',m.FrameObj.SetEndLengthOffset,name,False,0.,0.,0.)
                    if release_this:
                        release = [False,False,False,False,True,True]
                        call('ReleaseBothBendingAxes',m.FrameObj.SetReleases,name,release,release,[0.]*6,[0.]*6)
                    assigned = {'bending_released':release_this,
                        'offsets':call('ReadConnectionOffsets',m.FrameObj.GetEndLengthOffset,name),
                        'releases':call('ReadConnectionReleases',m.FrameObj.GetReleases,name)}
                    if connection_mode in ('zero_offsets','pinned_bending') and tuple(assigned['offsets']) != (False,0.,0.,0.):
                        raise ValueError('Explicit zero-offset readback mismatch')
                    if release_this and any(list(a) != release for a in assigned['releases'][:2]):
                        raise ValueError('Bending release readback mismatch')
                    connections[name] = assigned
                mapping.append({'story':story,'source_id':member.member_id,'role':member.role,'etabs_object':name})
        print(f'STAGE residential_floor_{story}_built',flush=True)
    call('PrescribedMassSource',m.PropMaterial.SetMassSource_1,False,True,False,0,[],[])
    mass_source = call('MassSourceReadback',m.PropMaterial.GetMassSource_1)
    expected_mass = [[f.mass_kg,f.mass_kg,0.,0.,0.,f.inertia_kg_m2] for f in data.floors]
    actual_mass = [call('ReadMasterMass',m.PointObj.GetMass,p)[0] for p in masters]
    if any(len(aa)!=6 or any(not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-6) for a,b in zip(aa,bb))
           for aa,bb in zip(actual_mass,expected_mass)):
        raise ValueError('Prescribed mass readback mismatch')
    area_names = call('ReadAreaNames',m.AreaObj.GetNameList)
    frame_names = call('ReadFrameNames',m.FrameObj.GetNameList)
    point_names = call('ReadPointNames',m.PointObj.GetNameList)
    count_checks = {'walls':area_names[0]==n*wall_vertical_subdivisions*sum(member.role=='wall' for member in data.layout.members),
        'beams':frame_names[0]==(0 if connection_mode == 'walls_only' else n*sum(member.role!='wall' for member in data.layout.members)),
        'points':point_names[0]==len(nodes)+len(masters)}
    coordinate_error = 0.
    for (level,point),name in nodes.items():
        actual = call('ReadNodeCoord',m.PointObj.GetCoordCartesian,name)
        expected = (*point,level*spec.project.story_height_m)
        coordinate_error = max(coordinate_error,max(abs(a-b) for a,b in zip(actual,expected)))
    if not all(count_checks.values()) or coordinate_error>1e-7:
        raise ValueError(f'Model geometry/count readback mismatch: {count_checks}, error={coordinate_error}')
    write_json(directory/'geometry_readback.json',{'counts':{'areas':area_names[0],'frames':frame_names[0],'points':point_names[0]},
        'count_checks':count_checks,'max_coordinate_error_m':coordinate_error,
        'beam_section_properties':{role:call('ReadBeamSection',m.PropFrame.GetSectProps,role) for role in ('primary','secondary')},
        'beam_theory':beam_theory,'beam_modifiers':modifiers,'wall_vertical_subdivisions':wall_vertical_subdivisions})
    write_json(directory/'model_mapping.json',{'origin_xy_m':data.origin_xy_m,'centre_xy_m':data.centre_xy_m,
        'source_members':len(data.layout.members),'objects':mapping,'masters':masters,'mass_kg':actual_mass,
        'mass_source':mass_source,'slab_stiffness':'rigid diaphragm only, matching MVLEM protocol',
        'removed_beam_stiffness':connection_mode == 'walls_only',
        'auxiliary_null_dof_nodes':[name for (level,point),name in nodes.items()
            if connection_mode == 'walls_only' and level>=1 and float(level).is_integer() and point not in wall_points],
        'preflight':'Unrepaired short members retained for diagnostic only; no engineering feasibility verdict'})
    for direction in ('X','Y'):
        case = 'ROOF_'+direction
        call('AddRoofPattern',m.LoadPatterns.Add,case,8,0.,True)
        force = [0.]*6
        force[0 if direction=='X' else 1] = spec.roof_force_n
        call('RoofLoad',m.PointObj.SetLoadForce,masters[-1],case,force,True)
    call('ModalCase',m.LoadCases.ModalEigen.SetCase,'MODAL_CHECK')
    call('DisableDefaultCases',m.Analyze.SetRunCaseFlag,'',False,True)
    joint_cases = {}
    if joint_rotation:
        from .joint_mechanics import joint_plan
        plan = joint_plan(spec)
        for case,probe in plan['probes'].items():
            xyz = plan['points'][probe['point']]
            point = nodes[1,(xyz[0],xyz[1])]
            call('AddJointMomentPattern',m.LoadPatterns.Add,case,8,0.,True)
            force = [0.]*6
            force[probe['dof']] = probe['moment_nm']
            call('JointMomentLoad',m.PointObj.SetLoadForce,point,case,force,True)
        joint_cases = plan['probes']
    cases = ('ROOF_X','ROOF_Y','MODAL_CHECK',*joint_cases)
    for case in cases:
        call('Enable '+case,m.Analyze.SetRunCaseFlag,case,True)
    call('SaveBeforeAnalysis',m.File.Save,str(directory/'model.EDB'))
    print('STAGE residential_analysis',flush=True)
    call('RunAnalysis',m.Analyze.RunAnalysis)
    status = call('CaseStatus',m.Analyze.GetCaseStatus)
    state = dict(zip(status[1],status[2]))
    if any(state.get(case)!=4 for case in cases):
        raise RuntimeError(f'Residential cases incomplete: {state}')
    from .solver_health import solver_health
    health = solver_health(directory/'model.LOG')
    write_json(directory/'solver_health.json',health)
    if not health['verified']:
        raise RuntimeError(f'Unsafe native solver stability result: {health}')
    if connection_mode is not None and connection_mode != 'walls_only':
        from .connection_audit import analysis_line_connections
        connections = {'assignments':connections, 'resolved':analysis_line_connections(client,list(connections))}
        write_json(directory/'analysis_connections.json',connections)
    outputs, checks = {}, {}
    for case in cases[:2]:
        call('DeselectOutput',m.Results.Setup.DeselectAllCasesAndCombosForOutput)
        call('SelectOutput',m.Results.Setup.SetCaseSelectedForOutput,case)
        floors = [rows(call('FloorDispl',m.Results.JointDispl,p,0),DISPLACEMENT_FIELDS,operation='FloorDispl') for p in masters]
        raw = call('BaseReaction',m.Results.BaseReact)
        reactions = rows(raw[:-3],('case','step_type','step','fx','fy','fz','mx','my','mz'),operation='BaseReaction')
        if len(reactions)!=1 or reactions[0]['case']!=case or any(len(f)!=1 or f[0]['case']!=case for f in floors):
            raise ValueError('Unexpected static result count/case')
        checks[case] = roof_equilibrium(reactions[0],raw[-3:],(*data.centre_xy_m,data.floors[-1].elevation_m),
            spec.roof_force_n,case[-1])
        checks[case]['finite_floor_responses'] = all(math.isfinite(f[0][key]) for f in floors for key in ('u1','u2','r3'))
        outputs[case] = {'floors':floors,'base_reactions':reactions,'reaction_reference_xyz_m':raw[-3:]}
        if connection_mode is not None:
            beam_forces = {}
            for item in mapping:
                if item['role'] == 'wall':
                    continue
                name = item['etabs_object']
                beam_forces[name] = rows(call('ConnectionBeamForce',m.Results.FrameForce,name,0),
                    ('object','object_station','element','element_station','case','step_type','step',
                     'p','v2','v3','t','m2','m3'),operation='ConnectionBeamForce')
                if any(row['case'] != case or not all(math.isfinite(row[k]) for k in ('p','v2','v3','t','m2','m3'))
                        for row in beam_forces[name]):
                    raise ValueError('Invalid connection beam-force output')
            outputs[case]['beam_forces_n_nm'] = beam_forces
            if connection_mode == 'pinned_bending':
                maximum = max(abs(row[k]) for name,values in beam_forces.items()
                    if connections['assignments'][name]['bending_released'] for row in values for k in ('m2','m3'))
                span = max(math.dist(member.start,member.end) for member in data.layout.members if member.role != 'wall')
                checks[case]['released_beam_bending_zero'] = maximum <= spec.roof_force_n*max(1.,span)*1e-7
                outputs[case]['max_released_end_moment_nm'] = maximum
    if joint_rotation:
        from .joint_results import etabs_joint_results
        from .joint_mechanics import assess_joint
        joint = etabs_joint_results(client,spec,nodes,mapping)
        write_json(directory/'joint_raw.json',joint)
        assessment = assess_joint(joint)
        write_json(directory/'joint_checks.json',assessment)
        if not assessment['verified']:
            raise ValueError('Joint mechanics checks failed; inspect retained native vectors')
    call('DeselectOutput',m.Results.Setup.DeselectAllCasesAndCombosForOutput)
    call('SelectModal',m.Results.Setup.SetCaseSelectedForOutput,'MODAL_CHECK')
    call('AllModeShapes',m.Results.Setup.SetOptionModeShape,1,12,True)
    modal = rows(call('ModalPeriod',m.Results.ModalPeriod),
        ('case','step_type','api_step','period','frequency','omega','eigenvalue'),operation='ModalPeriod')
    shapes = [rows(call('ModeShape',m.Results.ModeShape,p,0),DISPLACEMENT_FIELDS,operation='ModeShape') for p in masters]
    if any(len(shape)!=len(modal) or [r['step'] for r in shape]!=list(range(1,len(modal)+1)) for shape in shapes):
        raise ValueError('All ordered mode shapes are required, not the default first-mode-only output')
    table = call('ModalTable',m.DatabaseTables.GetTableForDisplayArray,'Modal Periods And Frequencies',[],'')
    records = [dict(zip(table[2],table[4][i:i+len(table[2])])) for i in range(0,len(table[4]),len(table[2]))]
    if table[3]!=len(modal) or [int(row['Mode']) for row in records]!=list(range(1,len(modal)+1)) or any(row['Case']!='MODAL_CHECK' for row in records):
        raise ValueError('Official modal table does not confirm the ordered mode identities')
    write_json(directory/'modal_table.json',{'fields':table[2],'count':table[3],'data':table[4]})
    checks['modal'] = {'positive_finite':all(math.isfinite(r['period']) and r['period']>0. and r['eigenvalue']>0. for r in modal),
        'case_matches':all(r['case']=='MODAL_CHECK' for r in modal)}
    # Geometry was saved before solving. Do not issue a second Save: in this
    # installation it removes the native solver files after results are read.
    return {'purpose':'RESIDENTIAL_ELASTIC_LATERAL_DIAGNOSTIC','units':'N_m_kg_s',
        'verified':all(all(check.values()) for check in checks.values()),'checks':checks,
        'case_status':state,'static':outputs,'modes':modal,'floor_mode_shapes':shapes,'beam_theory':beam_theory,
        'wall_vertical_subdivisions':wall_vertical_subdivisions,
        'connection_mode':connection_mode,
        'prescribed_floor_masses_kg':[f.mass_kg for f in data.floors],
        'engineering_feasibility':'NOT_EVALUATED','reinforcement':'NOT_EVALUATED'}
