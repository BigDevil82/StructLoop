"""Affine in-plane strain checks distinguish macro and continuum assumptions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any

import numpy as np

from struct_agent.io.artifacts import create_run,write_json
from struct_agent.schemas import ErrorRecord
from .contracts import ResidentialSpec
from .residential_input import prepare
from .patch_boundary import prescribe_field


def membrane_patch(spec: ResidentialSpec, formulation: str) -> dict[str,Any]:
    """Float64 global XYZ: affine strain on an XZ wall, no beam or fitting.

    Compare section-integrated normal resultants, not enriched corner moments.
    Measurement validity is distinct from matching 2D isotropic plane stress.
    The macro's vertical uniaxial response is checked independently; no
    unsupported assumption about its horizontal stiffness is fitted here.
    """
    import openseespy.opensees as ops
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import wall_shear_stiffness
    if formulation not in ('mvlem','shell_dkgq'):
        raise ValueError('A controlled macro or shell formulation required')
    data = prepare(spec)
    wall = next(m for m in data.layout.members if m.role=='wall' and abs(m.start[1]-m.end[1])<1e-8)
    length,height = abs(wall.end[0]-wall.start[0]),spec.project.story_height_m
    thickness,e,nu = data.floors[0].wall_thickness_m,data.elastic_modulus_pa,data.poisson
    xyz = np.array([[0.,0.,0.],[length,0.,0.],[length,0.,height],[0.,0.,height]])
    rows = []
    try:
        for name,strain in (('free_poisson_axial',np.array([-nu*1e-5,1e-5])),
                             ('restrained_transverse',np.array([1e-5,0.]))):
            ops.wipe()
            ops.model('basic','-ndm',3,'-ndf',6)
            for node,point in enumerate(xyz,1):
                ops.node(node,*point)
            if formulation=='mvlem':
                ops.uniaxialMaterial('Elastic',1,e)
                ops.uniaxialMaterial('Elastic',2,wall_shear_stiffness(length,thickness,height,e/(2*(1+nu))))
                count = 8
                ops.element('MVLEM_3D',1,1,2,3,4,count,'-thick',*([thickness]*count),
                    '-width',*([length/count]*count),'-rho',*([.01]*count),
                    '-matConcrete',*([1]*count),'-matSteel',*([1]*count),'-matShear',2,'-CoR',.4)
            else:
                ops.section('ElasticMembranePlateSection',1,e,nu,thickness,0.,.63**3)
                ops.element('ShellDKGQ',1,1,2,3,4,1)
            values = {node:np.array([strain[0]*point[0],0.,strain[1]*point[2],0.,0.,0.]) for node,point in enumerate(xyz,1)}
            prescribe_field(values,float(np.sqrt(e*thickness)))
            force = np.asarray(ops.eleForce(1)).reshape(4,6)
            connectivity = list(ops.eleNodes(1))
            by_node = {node:force[i] for i,node in enumerate(connectivity)}
            measured = np.array([sum(by_node[node][0] for node in (2,3))/(thickness*height),
                sum(by_node[node][2] for node in (3,4))/(thickness*length)])
            continuum = e/(1-nu**2)*np.array([[1.,nu],[nu,1.]])@strain
            plane_stress = bool(np.allclose(measured,continuum,rtol=1e-7,atol=1e-5))
            valid = bool(np.isfinite(force).all() and np.isfinite(measured).all())
            if name=='free_poisson_axial':
                valid = valid and bool(np.isclose(measured[1],e*strain[1],rtol=1e-7,atol=1e-5))
            if formulation=='shell_dkgq':
                valid = valid and plane_stress
            rows.append({'case':name,'strain_xx_zz':strain.tolist(),'measured_stress_xx_zz_pa':measured.tolist(),
                'plane_stress_expected_pa':continuum.tolist(),'plane_stress_equivalent':plane_stress,
                'global_nodal_force_n_nm':force.tolist(),'force_node_order':connectivity,'measurement_verified':valid})
        return {'formulation':formulation,'solver':ops.version(),'E_pa':e,'nu':nu,
            'verified':all(r['measurement_verified'] for r in rows),'cases':rows,
            'scope':'constitutive distinction only; no attribution of a whole-building error percentage'}
    finally:
        ops.wipe()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    args = parser.parse_args()
    spec = ResidentialSpec.model_validate_json(json.dumps(json.loads(args.source_manifest.read_text(encoding='utf-8'))['config']['spec']))
    create_run(args.run,seed=0,inputs={'manifest':args.source_manifest,'executed_source':Path(__file__),
        'prescribed_field_source':Path(__file__).with_name('patch_boundary.py')},
        config={'purpose':'AFFINE_MEMBRANE_IDEALIZATION_CHECK','spec':spec.model_dump(mode='json')})
    (args.run/'executed_source.py').write_bytes(Path(__file__).read_bytes())
    (args.run/'patch_boundary.py').write_bytes(Path(__file__).with_name('patch_boundary.py').read_bytes())
    try:
        result = {name:membrane_patch(spec,name) for name in ('mvlem','shell_dkgq')}
        write_json(args.run/'results.json',result)
        print({name:row['verified'] for name,row in result.items()})
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),
            context={'operation':'affine membrane patch','directory':str(args.run)},attempt=1)
        write_json(args.run/'error.json',record.model_dump())
        raise


if __name__=='__main__':
    main()
