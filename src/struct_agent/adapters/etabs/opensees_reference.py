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


def run_reference(spec: ResidentialSpec, directory: Path, *, mesh: ReferenceMesh | None=None) -> dict[str,Any]:
    import openseespy.opensees as ops
    from struct_agent.adapters.fea import native_topology, native_params
    from struct_agent.adapters.physics import analysis_signature
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import MVLEMFrameBuilder
    from struct_agent._vendor.shearwall_modeling.parametric.analysis import build_model_config_from_params
    directory = directory.resolve()
    mesh = mesh or ReferenceMesh()
    create_run(directory,seed=0,inputs={},config={'purpose':'ELASTIC_LATERAL_DIAGNOSTIC',
        'spec':spec.model_dump(mode='json'),'diagnostic_mesh':mesh.model_dump()})
    started = perf_counter()
    try:
        ops.logFile(str(directory/'opensees.log'),'-noEcho')
        data = prepare(spec)
        cfg = build_model_config_from_params(native_params(spec.design,spec.project),num_modes=12)
        build = MVLEMFrameBuilder(logging.getLogger('reference')).build(native_topology(data.layout),cfg)
        mesh_info = refine(build,cfg,mesh)
        write_json(directory/'mesh.json',mesh_info)
        masses = [ops.nodeMass(p,1) for p in build.master_nodes]
        inertia = [ops.nodeMass(p,6) for p in build.master_nodes]
        if any(not math.isclose(a,b,rel_tol=1e-10) for a,b in zip(masses,[f.mass_kg for f in data.floors])):
            raise ValueError('Independent geometric mass calculation differs from MVLEM builder')
        if any(not math.isclose(a,b,rel_tol=1e-10) for a,b in zip(inertia,[f.inertia_kg_m2 for f in data.floors])):
            raise ValueError('Prescribed torsional inertia differs from MVLEM builder')
        ops.constraints('Transformation')
        ops.numberer('RCM')
        ops.system('UmfPack')
        eigenvalues = list(ops.eigen('-genBandArpack',12))
        if len(eigenvalues)!=12 or any(not math.isfinite(e) or e<=0. for e in eigenvalues):
            raise ValueError('Invalid MVLEM eigenvalues')
        periods = [2*math.pi/math.sqrt(e) for e in eigenvalues]
        shapes = [[[ops.nodeEigenvector(p,mode,dof) for dof in (1,2,6)] for p in build.master_nodes] for mode in range(1,13)]
        bases = sorted({p for u in build.wall_base_units for p in u.base_nodes})
        static,checks = {},{}
        for index,direction in enumerate(('X','Y'),1):
            ops.reset()
            ops.wipeAnalysis()
            ops.constraints('Transformation')
            ops.numberer('RCM')
            ops.system('UmfPack')
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
            ops.remove('loadPattern',index)
        result = {'purpose':'RESIDENTIAL_ELASTIC_LATERAL_DIAGNOSTIC','units':'N_m_kg_s','solver':ops.version(),
            'analysis_signature':analysis_signature(),'periods_s':periods,'floor_mode_shapes':shapes,
            'static':static,'checks':checks,'verified':all(all(c.values()) for c in checks.values()),
            'floor_inputs':[asdict(f) for f in data.floors], 'elapsed_s':perf_counter()-started,
            'diagnostic_mesh':mesh.model_dump(),
            'engineering_feasibility':'NOT_EVALUATED','reinforcement':'NOT_EVALUATED'}
        write_json(directory/'result.json',result)
        return result
    except Exception as error:
        write_json(directory/'error.json',{'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()})
        raise
    finally:
        ops.wipe()
