"""Rigid-body patch check: rule out a simple global rotation-sign mismatch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from struct_agent.io.artifacts import create_run,write_json
from .contracts import ResidentialSpec
from .residential_input import prepare
from .patch_boundary import prescribe_field


def rotation_patch(spec: ResidentialSpec, formulation: str) -> dict[str,Any]:
    import openseespy.opensees as ops
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import wall_shear_stiffness
    if formulation not in ('mvlem','shell_dkgq','shell_asd'):
        raise ValueError('Unsupported diagnostic element')
    data = prepare(spec)
    wall = next(m for m in data.layout.members if m.role=='wall' and abs(m.start[1]-m.end[1])<1e-8)
    length = abs(wall.end[0]-wall.start[0])
    height,thickness = spec.project.story_height_m,data.floors[0].wall_thickness_m
    e,nu = data.elastic_modulus_pa,data.poisson
    xyz = np.array([[0.,0.,0.],[length,0.,0.],[length,0.,height],[0.,0.,height]])
    results = []
    try:
        for axis in range(3):
            ops.wipe()
            ops.model('basic','-ndm',3,'-ndf',6)
            for tag,point in enumerate(xyz,1):
                ops.node(tag,*point)
            if formulation=='mvlem':
                ops.uniaxialMaterial('Elastic',1,e)
                ops.uniaxialMaterial('Elastic',2,wall_shear_stiffness(length,thickness,height,e/(2*(1+nu))))
                count = 8
                ops.element('MVLEM_3D',1,1,2,3,4,count,'-thick',*([thickness]*count),
                    '-width',*([length/count]*count),'-rho',*([.01]*count),
                    '-matConcrete',*([1]*count),'-matSteel',*([1]*count),'-matShear',2,'-CoR',.4)
            else:
                ops.section('ElasticMembranePlateSection',1,e,nu,thickness,0.,.63**3)
                ops.element('ShellDKGQ' if formulation=='shell_dkgq' else 'ASDShellQ4',1,1,2,3,4,1)
            rotation = np.zeros(3)
            rotation[axis] = 1e-5
            prescribe_field({tag:np.r_[np.cross(rotation,point),rotation] for tag,point in enumerate(xyz,1)},float(np.sqrt(e*thickness)))
            force = np.asarray(ops.eleForce(1)).reshape(4,6)
            scaled = force.copy()
            scaled[:,3:] /= max(length,height)
            residual = float(np.max(abs(scaled))/(e*thickness*min(length,height)*1e-5))
            results.append({'axis':'XYZ'[axis],'residual':residual,'global_nodal_force_n_nm':force.tolist(),
                'passed':residual<1e-8})
        return {'formulation':formulation,'solver':ops.version(),'verified':all(r['passed'] for r in results),
            'rotations':results,'scope':'infinitesimal rigid rotation; not a continuum accuracy certification'}
    finally:
        ops.wipe()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    args = parser.parse_args()
    spec = ResidentialSpec.model_validate_json(json.dumps(json.loads(args.source_manifest.read_text(encoding='utf-8'))['config']['spec']))
    create_run(args.run,seed=0,inputs={'manifest':args.source_manifest,'executed_patch_source':Path(__file__),
        'prescribed_field_source':Path(__file__).with_name('patch_boundary.py')},
        config={'purpose':'RIGID_ROTATION_PATCH','spec':spec.model_dump(mode='json')})
    for name in ('joint_patch.py','patch_boundary.py'):
        (args.run/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    result = {name:rotation_patch(spec,name) for name in ('mvlem','shell_dkgq','shell_asd')}
    write_json(args.run/'results.json',result)
    print({name:row['verified'] for name,row in result.items()})


if __name__ == '__main__':
    main()
