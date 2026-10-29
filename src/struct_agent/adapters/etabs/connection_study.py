"""Isolate resolved end offsets and beam-to-wall bending transfer in one batch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any

from struct_agent.io.artifacts import create_run, sha256, write_json
from struct_agent.schemas import ErrorRecord
from .client import ETABSClient
from .comparison import compare
from .contracts import ConnectionStudySpec, ETABSConfig, ResidentialSpec
from .exceedance_causes import failed_metric_effect
from .opensees_reference import run_reference
from .reference_mesh import ReferenceMesh
from .residential import build_and_analyze
from .runtime import run_verification
from .tolerance import assess_comparison


def build_study(client: ETABSClient, request: ConnectionStudySpec, directory: Path,
                config: ETABSConfig) -> dict[str, Any]:
    """Read generated line elements; skip a redundant zero-offset solve."""
    spec = request.residential
    results = {}
    modes = list(request.modes)
    for mode in modes:
        target = directory/mode
        create_run(target,seed=0,inputs={'parent_manifest':directory/'manifest.json'},
            config={'spec':spec.model_dump(mode='json'),
                'etabs':config.model_dump(mode='json') | {'connection_mode':mode}})
        print(f'STAGE connection_study_{mode}',flush=True)
        result = build_and_analyze(client,spec,target,beam_theory='euler_comparison',connection_mode=mode,
            wall_vertical_subdivisions=config.wall_vertical_subdivisions,release_scope=request.release_scope)
        write_json(target/'worker_result.json',{'status':'SUCCESS' if result['verified'] else 'INVALID_RESULT','result':result})
        results[mode] = result['verified']
        if mode == 'default':
            resolved = json.loads((target/'analysis_connections.json').read_text(encoding='utf-8'))['resolved']
            if not resolved['all_resolved_end_lengths_zero']:
                modes.append('zero_offsets')
    return {'verified':all(results.values()),'cases':results,
        'zero_offset_solve_skipped': 'zero_offsets' not in results,
        'engineering_feasibility':'NOT_EVALUATED'}


def run_study(source: Path, directory: Path, report: Path) -> dict[str, Any]:
    source, directory, report = source.resolve(), directory.resolve(), report.resolve()
    if report.exists():
        raise FileExistsError(report)
    index = Path('configs/structural_comparison_evidence.json')
    for value in json.loads(index.read_text(encoding='utf-8'))['artifacts'].values():
        if sha256(Path(value['path'])) != value['sha256']:
            raise ValueError('Structural comparison evidence changed')
    old = source/'etabs'/'wall_beam'
    manifest = json.loads((old/'manifest.json').read_text(encoding='utf-8'))
    spec = ResidentialSpec.model_validate_json(json.dumps(manifest['config']['spec']))
    original = json.loads((source/'assessment.json').read_text(encoding='utf-8'))['structures']['wall_beam']
    create_run(directory,seed=0,inputs={'source_manifest':old/'manifest.json',
        'source_assessment':source/'assessment.json','source_index':index},
        config={'purpose':'BEAM_WALL_MOMENT_TRANSFER_CAUSE','spec':spec.model_dump(mode='json')})
    try:
        outcome = run_verification(ConnectionStudySpec(residential=spec),directory/'etabs',
            ETABSConfig(beam_theory='euler_comparison',timeout_s=600.))
        if outcome['status'] != 'SUCCESS':
            raise RuntimeError(f"Connection study failed: {outcome['status']}; inspect retained worker error")
        probes = (
            ('rigid_mvlem', 'default', source/'opensees'/'wall_beam', None),
            ('rigid_shell', 'default', Path('outputs/current/exceedance_wall_beam_shell_01').resolve(), None),
            ('rigid_midpoint', 'default', directory/'opensees'/'rigid_midpoint',ReferenceMesh(center_of_rotation=.5)),
            ('pinned_mvlem', 'pinned_bending', directory/'opensees'/'pinned_mvlem',ReferenceMesh(beam_bending_released=True)),
            ('pinned_midpoint', 'pinned_bending', directory/'opensees'/'pinned_midpoint',
                ReferenceMesh(beam_bending_released=True,center_of_rotation=.5)),
            ('pinned_shell', 'pinned_bending', directory/'opensees'/'pinned_shell',
                ReferenceMesh(beam_bending_released=True,wall_formulation='shell_dkgq')))
        if not outcome['payload']['result']['zero_offset_solve_skipped']:
            probes += (('zero_offsets_mvlem','zero_offsets',source/'opensees'/'wall_beam',None),
                ('zero_offsets_shell','zero_offsets',Path('outputs/current/exceedance_wall_beam_shell_01').resolve(),None))
        effects, inputs = {}, {}
        for name, mode, opensees, mesh in probes:
            print('PROBE '+name,flush=True)
            if mesh is not None:
                run_reference(spec,opensees,mesh=mesh)
            comparison = compare(directory/'etabs'/mode,opensees,directory/'comparisons'/name)
            assessment = assess_comparison(comparison,spec.project.story_height_m)
            effects[name] = failed_metric_effect(original,assessment)
            inputs[name] = directory/'comparisons'/name/'comparison.json'
        default = directory/'etabs'/'default'
        resolved = json.loads((default/'analysis_connections.json').read_text(encoding='utf-8'))
        baseline = json.loads((default/'worker_result.json').read_text(encoding='utf-8'))['result']
        previous = json.loads((old/'worker_result.json').read_text(encoding='utf-8'))['result']
        # Compare the failed IDs only; do not reopen passed response metrics.
        reproduction = []
        for metric in original['metrics']:
            if not metric['within_tolerance'] and metric['category'] in ('primary_displacement','coupled_response'):
                case, level, component = metric['id'].rsplit('_',2)
                story = int(level[1:])
                a = previous['static'][case]['floors'][story-1][0][component]
                b = baseline['static'][case]['floors'][story-1][0][component]
                reproduction.append({'id':metric['id'],'absolute_difference':abs(b-a)})
        result = {'purpose':'BEAM_WALL_MOMENT_TRANSFER_CAUSE','effects':effects,
            'resolved_original_connections':resolved,'failed_response_reproduction':reproduction,
            'zero_offset_solve_skipped':outcome['payload']['result']['zero_offset_solve_skipped'],
            'production_implementation':'UNCHANGED','engineering_feasibility':'NOT_EVALUATED'}
        write_json(directory/'results.json',result)
        create_run(report,seed=0,inputs={**inputs,'results':directory/'results.json'},
            config={'purpose':'BEAM_WALL_CONNECTION_DIAGNOSIS'})
        write_json(report/'results.json',result)
        lines = ['# 梁墙连接弯矩通道诊断','',
            '保持原图构件、12层条件、截面、楼层质量、加载点和边界；仅改变两端弯曲释放和显式端区设置。',
            '原已通过项保持关闭。本批反事实不替换生产数据。','',
            f"实际分析线单元端区全零：{resolved['resolved']['all_resolved_end_lengths_zero']}。",
            f"因此跳过重复零端区求解：{result['zero_offset_solve_skipped']}。",'',
            '| 诊断 | 原超限项 | 在探针中进入5%以内 |','|---|---:|---:|']
        lines += [f"| {name} | {value['original_failed_count']} | {value['below_5_percent_in_probe']} |"
            for name,value in effects.items()]
        lines += ['','梁端释放已通过属性读回和两软件近零端弯矩检查；原始力向量与工件均保留。',
            '本批结果与归因边界见仓库说明；原始证据：`'+str(directory)+'`。','']
        (report/'report.md').write_text('\n'.join(lines),encoding='utf-8')
        return result
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),
            context={'operation':'beam wall connection study','directory':str(directory)},attempt=1)
        write_json(directory/'error.json',record.model_dump())
        raise


def run_whole_fine(source: Path, directory: Path, report: Path) -> dict[str, Any]:
    """One additional 12-story four-panel paired case; original masses retained."""
    source, directory, report = source.resolve(), directory.resolve(), report.resolve()
    if report.exists():
        raise FileExistsError(report)
    original_path = source/'assessment.json'
    manifest_path = source/'archived_inputs'/'residential_mesh4'/'etabs'/'manifest.json'
    spec = ResidentialSpec.model_validate_json(json.dumps(json.loads(manifest_path.read_text(encoding='utf-8'))['config']['spec']))
    original = json.loads(original_path.read_text(encoding='utf-8'))['structures']['residential_mesh4']
    create_run(directory,seed=0,inputs={'source_manifest':manifest_path,'source_assessment':original_path},
        config={'purpose':'WHOLE_BUILDING_CONNECTION_CAUSE','spec':spec.model_dump(mode='json'),
            'changes':'beam bending releases and explicit zero offsets; no mass/geometry/material change'})
    try:
        outcome = run_verification(ConnectionStudySpec(residential=spec,modes=('pinned_bending',),release_scope='wall_to_wall'),directory/'etabs',
            ETABSConfig(beam_theory='euler_comparison',wall_vertical_subdivisions=4,timeout_s=1200.))
        if outcome['status'] != 'SUCCESS':
            raise RuntimeError(f"Whole-building connection study failed: {outcome['status']}")
        effects, inputs = {}, {}
        for name, mesh in (
                ('pinned_mvlem',ReferenceMesh(vertical_subdivisions=4,fiber_refinement=2,beam_bending_released=True,beam_release_scope='wall_to_wall')),
                ('pinned_shell',ReferenceMesh(vertical_subdivisions=4,wall_formulation='shell_dkgq',beam_bending_released=True,beam_release_scope='wall_to_wall'))):
            print('WHOLE_PROBE '+name,flush=True)
            target = directory/'opensees'/name
            run_reference(spec,target,mesh=mesh)
            comparison = compare(directory/'etabs'/'pinned_bending',target,directory/'comparisons'/name)
            effects[name] = failed_metric_effect(original,assess_comparison(comparison,spec.project.story_height_m))
            inputs[name] = directory/'comparisons'/name/'comparison.json'
        result = {'purpose':'WHOLE_BUILDING_CONNECTION_CAUSE','effects':effects,'stories':spec.project.stories,
            'wall_vertical_subdivisions':4,'production_implementation':'UNCHANGED','engineering_feasibility':'NOT_EVALUATED'}
        write_json(directory/'results.json',result)
        create_run(report,seed=0,inputs={**inputs,'results':directory/'results.json'},
            config={'purpose':'WHOLE_BUILDING_CONNECTION_CAUSE'})
        write_json(report/'results.json',result)
        text = ['# 整栋细网格梁墙弯矩通道对照','',
            '同一12层住宅，每层4片；两端同时释放梁弯曲、显式零端区，原几何/材料/质量/加载点保持不变。',
            '仅比较原超限项；反事实不替换生产模型。','',
            '| 诊断 | 原超限项 | 探针中进入5%以内 |','|---|---:|---:|']
        text += [f"| {name} | {value['original_failed_count']} | {value['below_5_percent_in_probe']} |" for name,value in effects.items()]
        (report/'report.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
        return result
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),
            context={'operation':'whole building connection study','directory':str(directory)},attempt=1)
        write_json(directory/'error.json',record.model_dump())
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('outputs/current/structural_comparison_01'))
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--whole-building-fine',action='store_true')
    args = parser.parse_args()
    result = (run_whole_fine if args.whole_building_fine else run_study)(args.source,args.run,args.report)
    print({name:row['below_5_percent_in_probe'] for name,row in result['effects'].items()})


if __name__ == '__main__':
    main()
