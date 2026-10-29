"""Full-stiffness beam-wall interface comparison, without beam end releases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any

from struct_agent.io.artifacts import create_run,write_json
from struct_agent.schemas import ErrorRecord
from .client import ETABSClient
from .comparison import compare
from .contracts import ETABSConfig,JointRotationSpec,ResidentialSpec
from .opensees_reference import run_reference
from .reference_mesh import ReferenceMesh
from .residential import build_and_analyze
from .runtime import run_verification
from .tolerance import assess_comparison,assess_pair


def build_joint_study(client: ETABSClient, request: JointRotationSpec,
                      directory: Path, config: ETABSConfig) -> dict[str,Any]:
    target = directory/'coupled'
    create_run(target,seed=0,inputs={'parent_manifest':directory/'manifest.json'},
        config={'spec':request.residential.model_dump(mode='json'),'etabs':config.model_dump(mode='json'),
            'joint_rotation':True,'beam_connections':'FULL_STIFFNESS_UNRELEASED'})
    result = build_and_analyze(client,request.residential,target,beam_theory='euler_comparison',
        wall_vertical_subdivisions=config.wall_vertical_subdivisions,connection_mode='default',joint_rotation=True)
    write_json(target/'worker_result.json',{'status':'SUCCESS' if result['verified'] else 'INVALID_RESULT','result':result})
    return {'verified':result['verified'],'engineering_feasibility':'NOT_EVALUATED'}


def run_joint_study(source: Path, directory: Path, report: Path) -> dict[str,Any]:
    source,directory,report = (p.resolve() for p in (source,directory,report))
    if report.exists():
        raise FileExistsError(report)
    manifest = source/'etabs'/'wall_beam'/'manifest.json'
    spec = ResidentialSpec.model_validate_json(json.dumps(json.loads(manifest.read_text(encoding='utf-8'))['config']['spec']))
    request = JointRotationSpec(residential=spec)
    create_run(directory,seed=0,inputs={'source_manifest':manifest,'prior_full_beam_result':
        Path('outputs/current/beam_wall_connection_01/etabs/default/worker_result.json')},
        config={'purpose':'FULL_STIFFNESS_JOINT_ROTATION_TRANSFER','spec':spec.model_dump(mode='json'),
            'unit_moment_nm':1000.,'beam_stiffness':'ALL_COMPONENTS_RETAINED','releases':False})
    try:
        outcome = run_verification(request,directory/'etabs',ETABSConfig(beam_theory='euler_comparison',timeout_s=600.))
        if outcome['status']!='SUCCESS':
            raise RuntimeError(f"Joint ETABS study failed: {outcome['status']}; inspect retained error and native vectors")
        assessments,interfaces,inputs = {},{},{}
        native = json.loads((directory/'etabs/coupled/joint_checks.json').read_text(encoding='utf-8'))
        interfaces['etabs'] = native
        for name,mesh in (('mvlem',ReferenceMesh()),('shell_dkgq',ReferenceMesh(wall_formulation='shell_dkgq')),
                ('shell_asd',ReferenceMesh(wall_formulation='shell_asd'))):
            print('JOINT_PROBE '+name,flush=True)
            target = directory/'opensees'/name
            run_reference(spec,target,mesh=mesh,joint_rotation=True)
            comparison = compare(directory/'etabs/coupled',target,directory/'comparisons'/name)
            assessments[name] = assess_comparison(comparison,spec.project.story_height_m)
            interfaces[name] = json.loads((target/'joint_checks.json').read_text(encoding='utf-8'))
            inputs[name] = target/'joint_raw.json'
        result = {'purpose':'FULL_STIFFNESS_JOINT_ROTATION_TRANSFER','assessments':assessments,'interfaces':interfaces,
            'flexibility_diagonal_comparisons':{name:[assess_pair(native['flexibility_rad_per_nm'][i][i],
                interfaces[name]['flexibility_rad_per_nm'][i][i]) for i in range(4)]
                for name in ('mvlem','shell_dkgq','shell_asd')},
            'production_implementation':'UNCHANGED','engineering_feasibility':'NOT_EVALUATED'}
        write_json(directory/'results.json',result)
        create_run(report,seed=0,inputs=inputs|{'results':directory/'results.json',
            'etabs_joint':directory/'etabs/coupled/joint_raw.json'},config={'purpose':result['purpose']})
        write_json(report/'results.json',result)
        lines = ['# 保留梁全部刚度的节点转角传递对照','',
            '原住宅抽取的12层墙梁子结构；不移除梁、不释放梁端、不拟合材料。',
            '增加梁端全局MX/MY各1kNm诊断，检查节点六自由度、内力、梁刚度方程、节点平衡和柔度互等性。','',
            '| 墙单元 | 原屋顶荷载132项通过数 |','|---|---:|']
        lines += [f"| {name} | {row['passed']}/{row['total']} |" for name,row in assessments.items()]
        lines += ['','单位弯矩不是设计荷载；原始内力和全部转角指标见results.json及joint_raw.json。','']
        (report/'report.md').write_text('\n'.join(lines),encoding='utf-8')
        return result
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),
            context={'operation':'full-stiffness joint study','directory':str(directory)},attempt=1)
        write_json(directory/'error.json',record.model_dump())
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('outputs/current/structural_comparison_01'))
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    result = run_joint_study(args.source,args.run,args.report)
    print({name:row['passed'] for name,row in result['assessments'].items()})


if __name__ == '__main__':
    main()
