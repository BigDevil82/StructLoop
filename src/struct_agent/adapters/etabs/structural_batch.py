"""One batch: source-derived L/T/wall-beam systems and archived whole building."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any
import zipfile

from struct_agent.io.artifacts import create_run, sha256, write_json
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec, ErrorRecord
from .client import ETABSClient
from .comparison import compare
from .contracts import ETABSConfig, ResidentialSpec, StructuralBatchSpec, StructuralBatchSettings
from .opensees_reference import run_reference
from .residential import build_and_analyze
from .runtime import run_verification
from .tolerance import assess_comparison, assess_pair


def subsystem_specs(batch: StructuralBatchSpec) -> dict[str, ResidentialSpec]:
    """Keep source segments and parent slab polygons, select members only.

    Slabs supply the prescribed diagnostic mass protocol, not shell stiffness
    or a claim of subsystem tributary floor area. Both solvers use that same
    mass. Source layout, original conditions and design are never edited.
    """
    result = {}
    for selection in batch.selections:
        parent = batch.residential
        members = tuple(m for m in parent.layout.members if m.member_id in selection.member_ids)
        layout = LayoutCandidate(**(parent.layout.model_dump() | {
            'layout_id':parent.layout.layout_id+'_'+selection.name, 'members':members,
            'source':'diagnostic_subset_of_'+parent.layout.layout_id}))
        design = parent.design.model_copy(update={'layout_id':layout.layout_id})
        result[selection.name] = ResidentialSpec(project=parent.project, layout=layout,
            design=design, roof_force_n=parent.roof_force_n)
    return result


def build_batch(client: ETABSClient, batch: StructuralBatchSpec, directory: Path,
                config: ETABSConfig) -> dict[str, Any]:
    """All subsystems use the same dedicated ETABS instance, no user attach."""
    results = {}
    for name, spec in subsystem_specs(batch).items():
        print(f'STAGE structural_batch_{name}', flush=True)
        target = directory/name
        create_run(target, seed=0, inputs={'parent_manifest':directory/'manifest.json'},
            config={'spec':spec.model_dump(mode='json'), 'etabs':config.model_dump(mode='json')})
        result = build_and_analyze(client, spec, target, beam_theory=config.beam_theory,
            wall_vertical_subdivisions=config.wall_vertical_subdivisions)
        write_json(target/'worker_result.json', {'status':'SUCCESS' if result['verified'] else 'INVALID_RESULT',
            'result':result})
        results[name] = result['verified']
    return {'verified':all(results.values()), 'cases':results, 'engineering_feasibility':'NOT_EVALUATED'}


def archived_pairs(archive: Path, directory: Path) -> dict[str, tuple[Path, Path]]:
    """Restore only named immutable result/manifest files, no model rerun."""
    index = json.loads(Path('docs/outputs_archive_index.json').read_text(encoding='utf-8'))
    if sha256(archive) != index['archive']['sha256']:
        raise ValueError('Historical evidence archive hash mismatch')
    pairs = {
        'residential_mesh1':('etabs_residential_12_euler_01', 'opensees_residential_12_02'),
        'residential_mesh2':('etabs_residential_12_euler_mesh2_01', 'opensees_residential_12_mesh2_01'),
        'residential_mesh4':('etabs_residential_12_euler_mesh4_01', 'opensees_residential_12_mesh4_01')}
    result = {}
    with zipfile.ZipFile(archive) as source:
        for name, runs in pairs.items():
            targets = []
            for backend, run in zip(('etabs', 'opensees'), runs):
                target = directory/name/backend
                target.mkdir(parents=True, exist_ok=False)
                for file in ('manifest.json', 'worker_result.json' if backend == 'etabs' else 'result.json'):
                    with (target/file).open('xb') as stream:
                        stream.write(source.read(run+'/'+file))
                targets.append(target)
            result[name] = (targets[0], targets[1])
    return result


def run_batch(batch: StructuralBatchSpec, directory: Path, report: Path, *, inputs: dict[str, Path]) -> dict[str, Any]:
    """Execute subsystems once, assess all building evidence in the same delivery."""
    directory, report = directory.resolve(), report.resolve()
    if report.exists():
        raise FileExistsError(report)
    config = ETABSConfig(timeout_s=600., beam_theory='euler_comparison')
    create_run(directory, seed=0, inputs=inputs, config={'batch':batch.model_dump(mode='json'),
        'acceptance_rule':'abs(OpenSees-ETABS)/abs(ETABS) < 0.05'})
    try:
        # Assess the complete building immediately; reuse its actual results.
        assessments = {}
        evidence = {}
        for name, (etabs, opensees) in archived_pairs(inputs['archive'], directory/'archived_inputs').items():
            comparison = compare(etabs, opensees, directory/'comparisons'/name)
            manifest = json.loads((etabs/'manifest.json').read_text(encoding='utf-8'))
            if manifest['config']['spec'] != batch.residential.model_dump(mode='json'):
                raise ValueError('Archived building differs from the current residential request')
            assessments[name] = assess_comparison(comparison, batch.residential.project.story_height_m)
            evidence[name] = directory/'comparisons'/name/'comparison.json'
        write_json(directory/'whole_building_assessment.json', assessments)
        outcome = run_verification(batch, directory/'etabs', config)
        if outcome['status'] != 'SUCCESS':
            raise RuntimeError(f"Structural batch failed: {outcome['status']}; inspect etabs/worker_error.json")
        for name, spec in subsystem_specs(batch).items():
            run_reference(spec, directory/'opensees'/name)
            comparison = compare(directory/'etabs'/name, directory/'opensees'/name, directory/'comparisons'/name)
            assessments[name] = assess_comparison(comparison, spec.project.story_height_m)
            evidence[name] = directory/'comparisons'/name/'comparison.json'
        single = json.loads(inputs['single_wall'].read_text(encoding='utf-8'))
        closed = [{'case_id':row['case_id'], **assess_pair(row['etabs_tip_mm'], row['opensees_tip_mm'])}
            for row in single['rows']]
        result = {'status':'STRUCTURAL_COMPARISON_COMPLETED', 'rule':'abs(OpenSees-ETABS)/abs(ETABS) < 0.05',
            'single_wall_closure':closed, 'structures':assessments,
            'engineering_feasibility':'NOT_EVALUATED', 'reinforcement':'NOT_EVALUATED',
            'note':'Passed metrics are closed without further checking/calibration; exceedances remain explicit.'}
        write_json(directory/'assessment.json', result)
        create_run(report, seed=0, inputs={**evidence, 'assessment':directory/'assessment.json',
            'single_wall':inputs['single_wall']}, config={'purpose':'BATCH_STRUCTURAL_COMPARISON_5_PERCENT'})
        write_json(report/'assessment.json', result)
        lines = ['# 结构层面批量对照：5%判据', '',
            '判据：|OpenSees−ETABS|/|ETABS| < 5%。通过项关闭，不再核查校准；等于5%及以上单列。',
            '分母仅为统一报告约定，不指定软件真值；精确双零通过，单零非零超限，小量不删除。',
            '整栋复用经哈希核验的真实归档；L/T/墙梁组合为本批真实求解。梁理论统一为Euler。',
            '子系统从当前住宅抽取原始构件，沿用12层和截面分区；保留父楼板多边形，仅用于双方一致的规定质量协议，',
            '不表示已经确认子系统实际分担面积或设计荷载。各层刚性楼板、固定底部、屋顶两向1MN诊断力一致。',
            '本报告完成弹性结构对照，不代替重力、地震谱、组合及配筋校核。', '',
            f'既有单墙：{sum(r["within_tolerance"] for r in closed)}/{len(closed)}项通过；取消水平离散/泊松补查。', '',
            '| 结构 | 类别 | 通过/总数 | 最大相对差异 |', '|---|---|---:|---:|']
        for name, assessment in assessments.items():
            for category, values in assessment['categories'].items():
                maximum = values['max_relative_difference']
                lines.append(f"| {name} | {category} | {values['passed']}/{values['total']} | "
                    +(f'{maximum:.2%}' if maximum is not None else '参考零值且存在非零差异')+' |')
        lines += ['', '逐项值、绝对差异、5%判定与待处理项均在assessment.json，不将超限项目汇总成通过。',
            '原始证据：`'+str(directory)+'`。生产网格、源布局、模型权重及历史计算结果未改写。', '']
        (report/'report.md').write_text('\n'.join(lines), encoding='utf-8')
        return result
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__, message=str(error), traceback=traceback.format_exc(),
            context={'operation':'structural batch', 'directory':str(directory)}, attempt=1)
        write_json(directory/'error.json', record.model_dump())
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/structural_comparison.json'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    settings = StructuralBatchSettings.model_validate_json(args.config.read_bytes())
    inputs = {key:getattr(settings, key) for key in ('layout', 'project', 'design', 'archive', 'single_wall')}
    inputs['config'] = args.config
    parent = ResidentialSpec(layout=LayoutCandidate.model_validate_json(inputs['layout'].read_bytes()),
        project=ProjectSpec.model_validate_json(inputs['project'].read_bytes()),
        design=DesignCandidate.model_validate_json(inputs['design'].read_bytes()))
    batch = StructuralBatchSpec(residential=parent, selections=settings.selections)
    result = run_batch(batch, args.run, args.report, inputs=inputs)
    print(result['status'])
    for name, assessment in result['structures'].items():
        print(f"{name}: {assessment['passed']}/{assessment['total']} within 5%; {assessment['status']}")


if __name__ == '__main__':
    main()
