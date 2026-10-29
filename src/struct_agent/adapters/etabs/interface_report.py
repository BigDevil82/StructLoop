"""Recompute a single reviewable summary from immutable interface batches."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from struct_agent.io.artifacts import create_run,write_json
from .contracts import InterfaceCase
from .interface_study import static_comparison
from .tolerance import assess_comparison,assess_pair


def read(path: Path) -> dict[str,Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def summarize(runs: list[Path],directory: Path) -> dict[str,Any]:
    records,inputs = [],{}
    for run in runs:
        run = run.resolve()
        results = read(run/'results.json')
        manifest = read(run/'manifest.json')
        etabs = Path(results.get('etabs_directory',str(run/'etabs')))
        inputs[run.name+'_results'] = run/'results.json'
        inputs[run.name+'_manifest'] = run/'manifest.json'
        spec = manifest['config']['spec']
        for item in results['cases']:
            case = InterfaceCase.model_validate(item)
            target = etabs/case.name
            native = read(target/'worker_result.json')
            if native['status']!='SUCCESS' or not read(target/'solver_health.json')['verified']:
                raise ValueError(f'Invalid ETABS evidence: {target}')
            inputs[run.name+'_'+case.name+'_etabs'] = target/'worker_result.json'
            for name,stored in results['assessments'][case.name].items():
                reference = run/'opensees'/case.name/name
                actual = read(reference/'result.json')
                comparison = assess_comparison(static_comparison(native['result'],actual),spec['project']['story_height_m'])
                if comparison!=stored:
                    raise ValueError(f'Stored comparison differs from raw responses: {reference}')
                inputs[run.name+'_'+case.name+'_'+name] = reference/'result.json'
                probes = None
                if (reference/'joint_checks.json').is_file():
                    a,b = (read(p/'joint_checks.json') for p in (target,reference))
                    if not a['verified'] or not b['verified']:
                        raise ValueError('Failed joint mechanics evidence')
                    probes = {key:assess_pair(a['flexibility_rad_per_nm'][i][i],b['flexibility_rad_per_nm'][i][i])
                        for i,key in enumerate(('I_MX','I_MY','J_MX','J_MY'))}
                roof = {load:{key:{'etabs':native['result']['static'][load]['floors'][-1][0][key],
                    'opensees':actual['static'][load]['floors'][-1][key]}
                    for key in ('u1','u2','r3')} for load in ('ROOF_X','ROOF_Y')}
                for components in roof.values():
                    for values in components.values():
                        values.update(assess_pair(values['etabs'],values['opensees']))
                records.append({'run':run.name,'whole_building':results['whole_building'],
                    'case':case.model_dump(),'formulation':name,'spec_key':json.dumps(spec,sort_keys=True),
                    'assessment':comparison,'roof':roof,'unit_moment_compliance':probes})
    convergence,horizontal_changes = [],[]
    for row in records:
        c = row['case']
        candidates = [p for p in records if p['formulation']==row['formulation'] and p['spec_key']==row['spec_key']
            and all(p['case'][k]==c[k] for k in ('rigid','face_nodes','horizontal_subdivisions','edge_constraints'))
            and p['case']['subdivisions']<c['subdivisions']]
        if not candidates:
            continue
        prior = max(candidates,key=lambda p:p['case']['subdivisions'])
        changes = {solver:{axis:(row['roof'][load][component][solver]/prior['roof'][load][component][solver]-1)
            for axis,load,component in (('X','ROOF_X','u1'),('Y','ROOF_Y','u2'))}
            for solver in ('etabs','opensees')}
        convergence.append({'whole_building':row['whole_building'],'formulation':row['formulation'],
            'from':prior['case'],'to':c,'roof_relative_change':changes})
    for row in records:
        c = row['case']
        candidates = [p for p in records if p['formulation']==row['formulation'] and p['spec_key']==row['spec_key']
            and all(p['case'][k]==c[k] for k in ('rigid','face_nodes','subdivisions','edge_constraints'))
            and p['case']['horizontal_subdivisions']<c['horizontal_subdivisions']]
        if candidates:
            prior = max(candidates,key=lambda p:p['case']['horizontal_subdivisions'])
            horizontal_changes.append({'whole_building':row['whole_building'],'formulation':row['formulation'],
                'from':prior['case'],'to':c,'roof_relative_change':{solver:{axis:
                    row['roof'][load][component][solver]/prior['roof'][load][component][solver]-1
                    for axis,load,component in (('X','ROOF_X','u1'),('Y','ROOF_Y','u2'))}
                    for solver in ('etabs','opensees')}})
    for row in records:
        row.pop('spec_key')
    inputs['executed_report_source'] = Path(__file__)
    create_run(directory,seed=0,inputs=inputs,config={'purpose':'FULL_STIFFNESS_BEAM_WALL_RESOLUTION',
        'executed_report_source':str(Path(__file__).resolve()),'scope':'static only; no production acceptance'})
    (directory/'executed_report_source.py').write_bytes(Path(__file__).read_bytes())
    result = {'records':records,'vertical_mesh_changes':convergence,'horizontal_mesh_changes':horizontal_changes,
        'production_implementation_changed':False,
        'actual_coupled_building_accepted':False,'unavoidability_proven':False,
        'scope':'120 static metrics per pair, no modal or design verification'}
    write_json(directory/'summary.json',result)
    lines = ['# 保留全部梁刚度的梁墙连接与整栋对照','',
        '本表由原始双端响应重算，所有超限项保留在 summary.json；小于5%的项关闭。',
        '有限连接区是明确的建模对照假设，未替换生产建模器，也不指定任一软件或细网格为真值。','',
        '| 范围 | 连接/竖向网格 | 墙单元 | 静力通过 | 主位移最大差 | 主层间位移最大差 | 屋顶X差 | 屋顶Y差 |',
        '|---|---|---|---:|---:|---:|---:|---:|']
    for row in records:
        a = row['assessment']
        maximum = [100*a['categories'][key]['max_relative_difference'] for key in ('primary_displacement','primary_drift')]
        roof = [100*row['roof'][load][component]['relative_difference']
            for load,component in (('ROOF_X','u1'),('ROOF_Y','u2'))]
        lines.append(f"| {'整栋' if row['whole_building'] else '墙梁子结构'} | {row['case']['name']} | {row['formulation']} | "
            f"{a['passed']}/{a['total']} | {maximum[0]:.3f}% | {maximum[1]:.3f}% | {roof[0]:.3f}% | {roof[1]:.3f}% |")
    lines += ['','完整解释、无效试算及尚缺的双向网格证据见 docs/beam_wall_resolution.md。']
    (directory/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',type=Path,nargs='+',required=True)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    result = summarize(args.runs,args.report)
    print({'valid_pairs':len(result['records']),'scope':result['scope']})


if __name__=='__main__':
    main()
