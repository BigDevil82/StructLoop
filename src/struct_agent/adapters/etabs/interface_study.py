"""Batch beam-face/mesh controls through to the full residential structure."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any

from struct_agent.io.artifacts import create_run,write_json,sha256
from struct_agent.schemas import ErrorRecord
from .client import ETABSClient
from .contracts import ResidentialSpec,ETABSConfig,InterfaceBatchSpec,InterfaceCase
from .interface_geometry import BeamInterface
from .opensees_reference import run_reference
from .reference_mesh import ReferenceMesh
from .residential import build_and_analyze
from .runtime import run_verification
from .tolerance import assess_comparison


def load_json(path: Path) -> dict[str,Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def build_interface_batch(client: ETABSClient, request: InterfaceBatchSpec,
                          directory: Path, config: ETABSConfig) -> dict[str,Any]:
    cases = {}
    for case in request.cases:
        target = directory/case.name
        create_run(target,seed=0,inputs={'parent_manifest':directory/'manifest.json'},config={
            'spec':request.residential.model_dump(mode='json'),'case':case.model_dump(),
            'etabs':config.model_dump(mode='json')|{'wall_vertical_subdivisions':case.subdivisions},'static_only':True})
        print('INTERFACE_ETABS '+case.name,flush=True)
        result = build_and_analyze(client,request.residential,target,beam_theory='euler_comparison',
            wall_vertical_subdivisions=case.subdivisions,connection_mode='default',
            interface=BeamInterface(face_nodes=case.face_nodes,rigid=case.rigid),
            static_only=True,joint_rotation=request.joint_probes,
            horizontal_subdivisions=case.horizontal_subdivisions,edge_constraints=case.edge_constraints)
        if case.horizontal_subdivisions>1 or case.edge_constraints is not None:
            from .area_mesh_audit import inspect_area_mesh
            audit = inspect_area_mesh(client,generate=False)
            write_json(target/'area_mesh.json',audit)
            if not audit['all_one_to_one_corner_match']:
                raise ValueError('Generated shell mesh differs from explicitly controlled objects')
            if case.edge_constraints is False and audit['edge_constraints_enabled']:
                raise ValueError('Unexpected native edge constraints')
        write_json(target/'worker_result.json',{'status':'SUCCESS' if result['verified'] else 'INVALID_RESULT','result':result})
        cases[case.name] = result['verified']
    return {'verified':all(cases.values()),'cases':cases,'scope':'static transfer and drift; modal comparison excluded'}


def static_comparison(etabs: dict[str,Any], opensees: dict[str,Any]) -> dict[str,Any]:
    if not etabs['verified'] or not opensees['verified']:
        raise ValueError('Successfully verified source results required')
    static = {}
    for case in ('ROOF_X','ROOF_Y'):
        e,o = etabs['static'][case]['floors'],opensees['static'][case]['floors']
        if len(e)!=12 or len(o)!=12:
            raise ValueError('All twelve floors required')
        static[case] = [{'story':i,'component':key,'etabs':left[0][key],'opensees':right[key]}
            for i,(left,right) in enumerate(zip(e,o),1) for key in ('u1','u2','r3')]
    return {'periods':[],'static':static,'scope':'120 static displacement/twist/drift metrics; no modal claim'}


def source_spec(source: Path, whole: bool) -> tuple[ResidentialSpec,Path]:
    manifest = source/('archived_inputs/residential_mesh4/etabs/manifest.json' if whole else 'etabs/wall_beam/manifest.json')
    spec = ResidentialSpec.model_validate_json(json.dumps(load_json(manifest)['config']['spec']))
    return spec,manifest


def run_batch(source: Path,directory: Path,report: Path, *, whole: bool,
               cases: tuple[InterfaceCase,...],formulations: tuple[str,...]=('mvlem','shell_dkgq'),
               resume_etabs: Path | None=None,solver: str='SparseGeneral') -> dict[str,Any]:
    source,directory,report = (p.resolve() for p in (source,directory,report))
    if report.exists():
        raise FileExistsError(report)
    if not formulations or len(set(formulations))!=len(formulations) or not set(formulations)<={'mvlem','shell_dkgq'}:
        raise ValueError('A nonempty unique list of controlled wall formulations is required')
    if 'mvlem' in formulations and any(c.horizontal_subdivisions>1 for c in cases):
        raise ValueError('Horizontal subdivision is a shell-only control')
    spec,manifest = source_spec(source,whole)
    request = InterfaceBatchSpec(residential=spec,cases=cases,joint_probes=not whole)
    prior = resume_etabs.resolve() if resume_etabs is not None else None
    inputs = {'source_manifest':manifest}
    if prior is not None:
        prior_request = InterfaceBatchSpec.model_validate_json(json.dumps(load_json(prior/'request.json')['spec']))
        if prior_request != request or load_json(prior/'outcome.json')['status']!='SUCCESS':
            raise ValueError('Resume requires identical requested inputs and a successful native ETABS batch')
        inputs.update({'prior_etabs_manifest':prior/'manifest.json','prior_etabs_outcome':prior/'outcome.json'})
        inputs.update({f'etabs_{case.name}':prior/case.name/'worker_result.json' for case in cases})
    create_run(directory,seed=0,inputs=inputs,config={'purpose':'BEAM_INTERFACE_AND_MESH',
        'whole_building':whole,'cases':[case.model_dump() for case in cases],'spec':spec.model_dump(mode='json'),
        'formulations':formulations,'resume_etabs':str(prior) if prior is not None else None,
        'linear_solver':solver})
    try:
        if prior is None:
            outcome = run_verification(request,directory/'etabs',ETABSConfig(beam_theory='euler_comparison',timeout_s=1200.))
            if outcome['status']!='SUCCESS':
                raise RuntimeError(f"Interface ETABS batch failed: {outcome['status']}; inspect retained native errors")
        etabs_root = prior or directory/'etabs'
        # Resume freezes the corrected OpenSees execution independently of
        # the earlier successful ETABS worker's source snapshot.
        snapshots = {}
        package = Path(__file__).resolve().parents[2]
        for path in sorted(package.rglob('*.py')):
            relative = path.relative_to(package.parent)
            target = directory/'reference_source'/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(path.read_bytes())
            snapshots[str(relative)] = sha256(target)
        write_json(directory/'reference_source_snapshot.json',snapshots)
        assessments = {}
        for case in cases:
            etabs = load_json(etabs_root/case.name/'worker_result.json')['result']
            entries = {}
            for formulation in formulations:
                print('INTERFACE_OPENSEES '+case.name+' '+formulation,flush=True)
                target = directory/'opensees'/case.name/formulation
                opensees = run_reference(spec,target,mesh=ReferenceMesh(vertical_subdivisions=case.subdivisions,
                    horizontal_subdivisions=case.horizontal_subdivisions,wall_formulation=formulation),
                    interface=BeamInterface(face_nodes=case.face_nodes,rigid=case.rigid),
                    static_only=True,handler='Lagrange',joint_rotation=not whole,solver=solver)
                comparison = static_comparison(etabs,opensees)
                entries[formulation] = assess_comparison(comparison,spec.project.story_height_m)
                write_json(target/'static_comparison.json',comparison)
            assessments[case.name] = entries
        result = {'purpose':'BEAM_INTERFACE_AND_MESH','whole_building':whole,'assessments':assessments,
            'cases':[case.model_dump() for case in cases],'static_metrics_per_pair':120,
            'etabs_directory':str(etabs_root),
            'production_implementation':'UNCHANGED','engineering_feasibility':'NOT_EVALUATED'}
        write_json(directory/'results.json',result)
        create_run(report,seed=0,inputs={'results':directory/'results.json'},config={'purpose':result['purpose']})
        write_json(report/'results.json',result)
        lines = ['# 保留梁刚度的连接区与网格对照','',
            '相同网格下比较直接共节点与按实际梁高定义的刚性截面接口；不改变梁截面、材料、质量、楼层及加载。',
            '本批仅检查静力传递、楼层位移/扭转和层间位移角，不声称模态或工程校核完成。','',
            '| 工况 | 墙单元 | 静力120项通过数 |','|---|---|---:|']
        for case,entries in assessments.items():
            lines += [f"| {case} | {name} | {row['passed']}/{row['total']} |" for name,row in entries.items()]
        (report/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        return result
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),
            context={'operation':'beam interface batch','directory':str(directory)},attempt=1)
        write_json(directory/'error.json',record.model_dump())
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('outputs/current/structural_comparison_01'))
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--whole-building',action='store_true')
    parser.add_argument('--subdivisions',type=int,nargs='+',default=[2,4])
    parser.add_argument('--include-point-controls',action='store_true')
    parser.add_argument('--horizontal-subdivisions',type=int,nargs='+',choices=(1,2,4),default=[1])
    parser.add_argument('--disable-edge-constraints',action='store_true')
    parser.add_argument('--formulations',nargs='+',choices=('mvlem','shell_dkgq'),default=['mvlem','shell_dkgq'])
    parser.add_argument('--resume-etabs',type=Path)
    parser.add_argument('--solver',choices=('UmfPack','SparseGeneral'),default='SparseGeneral')
    args = parser.parse_args()
    cases = tuple(InterfaceCase(name=f'{kind}_{n}'+(f'_h{h}' if h>1 else ''),subdivisions=n,
        rigid=(kind=='rigid'),horizontal_subdivisions=h,
        edge_constraints=False if args.disable_edge_constraints else None)
        for kind in (('point','rigid') if args.include_point_controls else ('rigid',))
        for n in args.subdivisions for h in args.horizontal_subdivisions)
    result = run_batch(args.source,args.run,args.report,whole=args.whole_building,cases=cases,
        formulations=tuple(args.formulations),resume_etabs=args.resume_etabs,solver=args.solver)
    print({case:{key:value['passed'] for key,value in entries.items()} for case,entries in result['assessments'].items()})


if __name__=='__main__':
    main()
