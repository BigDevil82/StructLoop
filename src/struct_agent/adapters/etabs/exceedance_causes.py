"""Bounded counterfactuals for failed structural metrics; no fitted parameters."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any

from struct_agent.io.artifacts import create_run, sha256, write_json
from struct_agent.schemas import ErrorRecord
from .comparison import compare
from .contracts import ResidentialSpec, StructuralBatchSpec
from .opensees_reference import run_reference
from .reference_mesh import ReferenceMesh
from .structural_batch import subsystem_specs
from .tolerance import assess_comparison


def beam_quadrature_profile(center: float, subdivisions: int) -> list[dict[str, float]]:
    """Dimensionless 12-story constant-EI beam under a unit tip force.

    H=12, h=1/subdivisions, EI=1. No shear or section/fitting factor. The
    continuous integral is int_0^z (H-x)(z-x) dx. Discrete MVLEM rotations
    sample the integrand at (j+c)h. This is an explanation of quadrature,
    not an exact analytical solution for a coupled residential wall system.
    """
    if center not in (.4, .5) or type(subdivisions) is not int or subdivisions not in (1,2,4):
        raise ValueError('Bounded independent quadrature controls required')
    result = []
    h = 1/subdivisions
    for story in range(1,13):
        z = float(story)
        exact = 12*z*z/2-z**3/6
        # Integral of (12-x)(z-x) = 12*z^2/2-z^3/6.
        discrete = sum((12-(j+center)*h)*(z-(j+center)*h)*h for j in range(story*subdivisions))
        result.append({'story':story, 'continuous':exact, 'discrete':discrete,
            'relative_difference':discrete/exact-1})
    return result


def failed_metric_effect(original: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    """Only examine previously failed IDs; passed items remain closed."""
    indexed = {m['id']:m for m in probe['metrics']}
    failed = [m for m in original['metrics'] if not m['within_tolerance']]
    if not failed or any(m['id'] not in indexed for m in failed):
        raise ValueError('No failed metrics or incomplete diagnostic output')
    rows = [{'id':m['id'], 'category':m['category'],
        'original_relative_difference':m['relative_difference'],
        'probe_relative_difference':indexed[m['id']]['relative_difference'],
        'original_absolute_difference':m['absolute_difference'],
        'probe_absolute_difference':indexed[m['id']]['absolute_difference'],
        'below_5_percent_in_probe':indexed[m['id']]['within_tolerance']} for m in failed]
    return {'original_failed_count':len(rows),
        'below_5_percent_in_probe':sum(r['below_5_percent_in_probe'] for r in rows),
        'metrics':rows, 'production_status':'UNCHANGED_DIAGNOSTIC_COUNTERFACTUAL_ONLY'}


def run_causes(source: Path, directory: Path, report: Path) -> dict[str, Any]:
    """Reuse actual ETABS evidence and vary the OpenSees element formulation."""
    source, directory, report = source.resolve(), directory.resolve(), report.resolve()
    if report.exists():
        raise FileExistsError(report)
    index = Path('configs/structural_comparison_evidence.json')
    evidence = json.loads(index.read_text(encoding='utf-8'))
    for item in evidence['artifacts'].values():
        if sha256(Path(item['path'])) != item['sha256']:
            raise ValueError('Structural comparison evidence changed')
    original = json.loads((source/'assessment.json').read_text(encoding='utf-8'))['structures']
    source_manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    batch = StructuralBatchSpec.model_validate_json(json.dumps(source_manifest['config']['batch']))
    subsystems = subsystem_specs(batch)
    cases = {
        'T_wall':(subsystems['T_wall'], source/'etabs'/'T_wall'),
        'residential_mesh1':(batch.residential, source/'archived_inputs'/'residential_mesh1'/'etabs'),
        'residential_mesh4':(batch.residential, source/'archived_inputs'/'residential_mesh4'/'etabs')}
    probes = (
        ('T_midpoint', 'T_wall', ReferenceMesh(center_of_rotation=.5)),
        ('residential_midpoint', 'residential_mesh1', ReferenceMesh(center_of_rotation=.5)),
        ('T_fibers4', 'T_wall', ReferenceMesh(fiber_refinement=4)),
        ('T_shell', 'T_wall', ReferenceMesh(wall_formulation='shell_dkgq')),
        ('residential_shell_coarse', 'residential_mesh1', ReferenceMesh(wall_formulation='shell_dkgq')),
        ('residential_shell_fine', 'residential_mesh4', ReferenceMesh(wall_formulation='shell_dkgq',vertical_subdivisions=4)),
        ('residential_nu_match', 'residential_mesh4', ReferenceMesh(vertical_subdivisions=4,fiber_refinement=2,plate_poisson=.2)),
        ('residential_midpoint_fine', 'residential_mesh4', ReferenceMesh(vertical_subdivisions=4,fiber_refinement=2,center_of_rotation=.5)))
    create_run(directory, seed=0, inputs={'source_manifest':source/'manifest.json',
        'source_assessment':source/'assessment.json', 'source_index':index},
        config={'purpose':'CAUSE_ISOLATION_NOT_CALIBRATION',
            'probes':[{'name':n,'source':s,'options':m.model_dump()} for n,s,m in probes]})
    # Freeze all executed Python source before the native calculations.
    package = Path(__file__).resolve().parents[2]
    snapshot = {}
    for file in sorted(package.rglob('*.py')):
        relative = file.relative_to(package.parent)
        target = directory/'source'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file.read_bytes())
        snapshot[str(relative)] = sha256(target)
    write_json(directory/'source_snapshot.json', snapshot)
    try:
        effects, inputs = {}, {}
        for name, key, mesh in probes:
            print(f'PROBE {name}', flush=True)
            spec, etabs = cases[key]
            run_reference(spec, directory/'opensees'/name, mesh=mesh)
            comparison = compare(etabs, directory/'opensees'/name, directory/'comparisons'/name)
            assessment = assess_comparison(comparison, spec.project.story_height_m)
            effects[name] = {'source':key, 'options':mesh.model_dump(),
                **failed_metric_effect(original[key],assessment)}
            inputs[name] = directory/'comparisons'/name/'comparison.json'
        result = {'purpose':'CAUSE_ISOLATION_NOT_CALIBRATION', 'effects':effects,
            'beam_quadrature':{f'c{c}_n{n}':beam_quadrature_profile(c,n) for c in (.4,.5) for n in (1,2,4)},
            'production_implementation':'UNCHANGED', 'engineering_feasibility':'NOT_EVALUATED'}
        write_json(directory/'results.json', result)
        create_run(report, seed=0, inputs={**inputs, 'results':directory/'results.json', 'source_index':index},
            config={'purpose':'FAILED_STRUCTURAL_METRIC_CAUSES'})
        write_json(report/'results.json', result)
        lines = ['# 结构超限原因的成组检查', '',
            '只检查先前超限的指标；原已通过项目保持关闭。所有ETABS结果均复用真实原件。',
            '本批变化仅为诊断反事实，不修改E、墙厚、源图、设计条件或生产实现，也不把探针结果替换原工程结果。',
            'c=0.5来自独立的中点积分对照，不是拟合参数；ShellDKGQ以相同膜厚与0.63³板弯曲修正替换MVLEM。', '',
            '| 诊断 | 原超限项数 | 探针中降至5%以内 |', '|---|---:|---:|']
        lines += [f"| {name} | {row['original_failed_count']} | {row['below_5_percent_in_probe']} |"
            for name,row in effects.items()]
        lines += ['', '指标明细及原/探针绝对差异、相对差异见results.json。达到5%及以上的项目不删除。',
            '独立连续梁/离散积分推导仅解释低层误差形状，不是整栋解析真值。因果结论与剩余问题见仓库说明。',
            '原始证据：`'+str(directory)+'`。', '']
        (report/'report.md').write_text('\n'.join(lines), encoding='utf-8')
        return result
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),
            context={'operation':'exceedance cause batch','directory':str(directory)},attempt=1)
        write_json(directory/'error.json', record.model_dump())
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('outputs/current/structural_comparison_01'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = run_causes(args.source, args.run, args.report)
    print({name:row['below_5_percent_in_probe'] for name,row in result['effects'].items()})


if __name__ == '__main__':
    main()
