"""Current MVLEM builder under the same prescribed lateral diagnostic inputs."""
from __future__ import annotations

from dataclasses import asdict
import logging
import math
from pathlib import Path
from time import perf_counter
import traceback
from typing import Any

from struct_agent.io.artifacts import create_run, write_json
from .contracts import ResidentialSpec
from .residential_input import prepare
from .results import roof_equilibrium
from .reference_mesh import ReferenceMesh,refine
from .interface_geometry import BeamInterface,interface_geometry,interface_residual


def run_reference(spec: ResidentialSpec, directory: Path, *, mesh: ReferenceMesh | None=None,
                  joint_rotation: bool=False, interface: BeamInterface | None=None,
                  static_only: bool=False, handler: str='Transformation',solver: str | None=None,
                  reuse_static_factorization: bool=True) -> dict[str,Any]:
    import openseespy.opensees as ops
    from struct_agent.adapters.fea import native_topology, native_params
    from struct_agent.adapters.physics import analysis_signature
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import MVLEMFrameBuilder
    from struct_agent._vendor.shearwall_modeling.parametric.analysis import build_model_config_from_params
    directory = directory.resolve()
    mesh = mesh or ReferenceMesh()
    solver = solver or ('SparseGeneral' if handler=='Lagrange' else 'UmfPack')
    if joint_rotation and (mesh.remove_beam_stiffness or mesh.beam_bending_released):
        raise ValueError('Joint diagnostic requires all beam stiffness and default connections')
    if handler not in ('Transformation','Lagrange'):
        raise ValueError('Unsupported diagnostic constraint handler')
    if solver not in ('UmfPack','SparseGeneral'):
        raise ValueError('Unsupported fixed diagnostic sparse solver')
    if interface is not None and (not static_only or mesh.remove_beam_stiffness or mesh.beam_bending_released):
        raise ValueError('Interface comparison requires a static full-beam model')
    if interface is not None and interface.rigid and handler!='Lagrange':
        raise ValueError('Nested rigid interfaces require the Lagrange handler')
    geometry = interface_geometry(spec,mesh.vertical_subdivisions,interface) if interface is not None else None
    create_run(directory,seed=0,inputs={},config={'purpose':'ELASTIC_LATERAL_DIAGNOSTIC',
        'spec':spec.model_dump(mode='json'),'diagnostic_mesh':mesh.model_dump(),'joint_rotation':joint_rotation,
        'interface':interface.model_dump() if interface is not None else None,'static_only':static_only,'handler':handler,'linear_solver':solver,
        'reuse_static_factorization':reuse_static_factorization})
    started = perf_counter()
    try:
        ops.logFile(str(directory/'opensees.log'),'-noEcho')
        data = prepare(spec)
        constraint_scale = math.sqrt(data.elastic_modulus_pa*data.floors[0].wall_thickness_m) if handler=='Lagrange' else 1.
        cfg = build_model_config_from_params(native_params(spec.design,spec.project),num_modes=12)
        topology_layout = data.layout
        origins = None
        if mesh.horizontal_subdivisions>1:
            from .horizontal_mesh import split_shell_layout
            topology_layout,origins = split_shell_layout(data.layout,mesh.horizontal_subdivisions)
        build = MVLEMFrameBuilder(logging.getLogger('reference')).build(native_topology(topology_layout),cfg)
        if origins is not None:
            from .horizontal_mesh import restore_parent_floor_protocol
            correction = restore_parent_floor_protocol(build,data,origins)
            write_json(directory/'horizontal_mesh_protocol.json',correction)
        mesh_info = refine(build,cfg,mesh,interface=geometry)
        write_json(directory/'mesh.json',mesh_info)
        masses = [ops.nodeMass(p,1) for p in build.master_nodes]
        inertia = [ops.nodeMass(p,6) for p in build.master_nodes]
        if any(not math.isclose(a,b,rel_tol=1e-10) for a,b in zip(masses,[f.mass_kg for f in data.floors])):
            raise ValueError('Independent geometric mass calculation differs from MVLEM builder')
        if any(not math.isclose(a,b,rel_tol=1e-10) for a,b in zip(inertia,[f.inertia_kg_m2 for f in data.floors])):
            raise ValueError('Prescribed torsional inertia differs from MVLEM builder')
        periods,shapes = [],[]
        if not static_only:
            if handler=='Lagrange':
                ops.constraints(handler,constraint_scale,constraint_scale)
            else:
                ops.constraints(handler)
            ops.numberer('RCM')
            ops.system(solver,*(['-piv'] if solver=='SparseGeneral' else []))
            eigenvalues = list(ops.eigen('-genBandArpack',12))
            if len(eigenvalues)!=12 or any(not math.isfinite(e) or e<=0. for e in eigenvalues):
                raise ValueError('Invalid MVLEM eigenvalues')
            periods = [2*math.pi/math.sqrt(e) for e in eigenvalues]
            shapes = [[[ops.nodeEigenvector(p,mode,dof) for dof in (1,2,6)] for p in build.master_nodes] for mode in range(1,13)]
        bases = sorted({p for u in build.wall_base_units for p in u.base_nodes})
        joint = None
        if joint_rotation:
            from .joint_mechanics import joint_plan
            from .joint_results import opensees_joint_case,opensees_joint_probes
            from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import _beam_section_props
            plan = joint_plan(spec)
            beam = build.beam_element_units[0]
            area,j,iy,iz = _beam_section_props(beam.width,beam.depth)
            material = cfg.resolve_story_profiles()[0].material
            joint = {'plan':plan,'section':{'E':float(material.E),'G':float(material.G),
                'A':area,'J':j,'Iy':iy,'Iz':iz},'cases':{},'units':'N_m_rad'}
        static,checks = {},{}
        reuse = interface is not None and static_only and reuse_static_factorization
        if reuse:
            ops.wipeAnalysis()
            if handler=='Lagrange':
                ops.constraints(handler,constraint_scale,constraint_scale)
            else:
                ops.constraints(handler)
            ops.numberer('RCM')
            ops.system(solver,*(['-piv'] if solver=='SparseGeneral' else []))
            for index,axis in enumerate((0,1),1):
                factors = [0.,1.,0.] if index==1 else [0.,0.,1.]
                ops.timeSeries('Path',index,'-time',0.,1.,2.,'-values',*factors)
                ops.pattern('Plain',index,index)
                load = [0.]*6
                load[axis] = spec.roof_force_n
                ops.load(build.master_nodes[-1],*load)
            ops.algorithm('Linear','-factorOnce')
            ops.integrator('LoadControl',1.)
            ops.analysis('Static')
        for index,direction in enumerate(('X','Y'),1):
            if not reuse:
                ops.reset()
                ops.wipeAnalysis()
                if handler=='Lagrange':
                    ops.constraints(handler,constraint_scale,constraint_scale)
                else:
                    ops.constraints(handler)
                ops.numberer('RCM')
                ops.system(solver,*(['-piv'] if solver=='SparseGeneral' else []))
                ops.timeSeries('Linear',index)
                ops.pattern('Plain',index,index)
                force = [0.]*6
                force[0 if direction=='X' else 1] = spec.roof_force_n
                ops.load(build.master_nodes[-1],*force)
                ops.algorithm('Linear')
                ops.integrator('LoadControl',1.)
                ops.analysis('Static')
            if ops.analyze(1)!=0:
                raise RuntimeError(f'MVLEM static case {direction} failed')
            factors = [float(ops.getLoadFactor(tag)) for tag in (1,2)] if reuse else None
            if reuse and factors != ([1.,0.] if index==1 else [0.,1.]):
                raise ValueError('Linear reused factorization did not isolate the requested roof load')
            ops.reactions()
            reaction = [0.]*6
            for p in bases:
                r,x = ops.nodeReaction(p),ops.nodeCoord(p)
                for i in range(6): reaction[i] += r[i]
                reaction[3] += x[1]*r[2]-x[2]*r[1]
                reaction[4] += x[2]*r[0]-x[0]*r[2]
                reaction[5] += x[0]*r[1]-x[1]*r[0]
            named = dict(zip(('fx','fy','fz','mx','my','mz'),reaction))
            floors = [{'u1':ops.nodeDisp(p,1),'u2':ops.nodeDisp(p,2),'r3':ops.nodeDisp(p,6)} for p in build.master_nodes]
            checks[direction] = roof_equilibrium(named,(0.,0.,0.),(*data.centre_xy_m,data.floors[-1].elevation_m),spec.roof_force_n,direction)
            checks[direction]['finite_floors'] = all(math.isfinite(v) for row in floors for v in row.values())
            static['ROOF_'+direction] = {'floors':floors,'base_reactions':named}
            if reuse:
                static['ROOF_'+direction]['roof_xy_load_factors'] = factors
            if mesh_info.get('interface_groups'):
                groups = mesh_info['interface_groups']
                values = {str(tag):list(ops.nodeDisp(tag)) for group in groups for tag in (group['master'],*group['slaves'])}
                residual = interface_residual(groups,values)
                static['ROOF_'+direction]['interface_constraints'] = residual
                checks[direction]['interface_constraints'] = residual['verified']
            if mesh.beam_bending_released:
                local = {str(b.element_tag):list(ops.eleResponse(b.element_tag,'localForce'))
                    for b in build.beam_element_units if b.element_tag in mesh_info['released_beam_tags']}
                if any(len(row) != 12 or not all(math.isfinite(v) for v in row) for row in local.values()):
                    raise ValueError('Missing released-beam force vectors')
                maximum = max(abs(row[i]) for row in local.values() for i in (4,5,10,11))
                limit = spec.roof_force_n*max(1.,*(b.length for b in build.beam_element_units))*1e-7
                checks[direction]['released_beam_bending_zero'] = maximum <= limit
                static['ROOF_'+direction]['beam_local_forces_n_nm'] = local
                static['ROOF_'+direction]['max_released_end_moment_nm'] = maximum
            if joint is not None:
                joint['cases']['ROOF_'+direction] = opensees_joint_case(plan,build,interface=geometry)
            if not reuse:
                ops.remove('loadPattern',index)
        if reuse:
            for index in (1,2):
                ops.remove('loadPattern',index)
        if joint is not None:
            from .joint_mechanics import assess_joint
            joint['cases'].update(opensees_joint_probes(plan,build,bases,interface=geometry,handler=handler,constraint_scale=constraint_scale,solver=solver))
            write_json(directory/'joint_raw.json',joint)
            assessment = assess_joint(joint)
            write_json(directory/'joint_checks.json',assessment)
            if not assessment['verified']:
                raise ValueError('OpenSees joint mechanics checks failed; inspect retained native vectors')
        result = {'purpose':'RESIDENTIAL_ELASTIC_LATERAL_DIAGNOSTIC','units':'N_m_kg_s','solver':ops.version(),
            'analysis_signature':analysis_signature(),'periods_s':periods,'floor_mode_shapes':shapes,
            'static':static,'checks':checks,'verified':all(all(c.values()) for c in checks.values()),
            'floor_inputs':[asdict(f) for f in data.floors], 'elapsed_s':perf_counter()-started,
            'diagnostic_mesh':mesh.model_dump(),
            'interface':interface.model_dump() if interface is not None else None,'static_only':static_only,
            'constraint_equation_scale':constraint_scale,'constraint_scale_definition':'sqrt(E*t_first_floor); exact Lagrange equations, not a penalty spring',
            'engineering_feasibility':'NOT_EVALUATED','reinforcement':'NOT_EVALUATED'}
        write_json(directory/'result.json',result)
        return result
    except Exception as error:
        write_json(directory/'error.json',{'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()})
        raise
    finally:
        ops.wipe()
