"""Bounded single-wall experiment and auditable comparison, outside GA labels."""
from __future__ import annotations

import math
from pathlib import Path
import traceback
from typing import Any

from struct_agent.io.artifacts import create_run, sha256, write_json
from struct_agent.schemas import ErrorRecord
from .contracts import ETABSConfig, SingleWallSpec
from .runtime import run_verification
from .wall_input import wall_cases
from .wall_opensees import solve_wall


def compare_cases(etabs: list[dict[str, Any]], opensees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match full conditions, never silently drop a missing/failed case."""
    def index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result = {r['case']['case_id']:r for r in records}
        if not result or len(result) != len(records):
            raise ValueError('Missing or duplicate wall cases')
        return result
    left, right = index(etabs), index(opensees)
    if left.keys() != right.keys():
        raise ValueError('Incomplete paired wall study')
    rows = []
    for key, a in left.items():
        b = right[key]
        if a['case'] != b['case']:
            raise ValueError(f'Wall conditions differ: {key}')
        if any(not r['verified'] or not r['checks'] or not all(r['checks'].values())
                or not math.isfinite(r['tip_x_m']) or r['tip_x_m'] <= 0. for r in (a, b)):
            raise ValueError(f'Failed/invalid wall response: {key}')
        rows.append({'case_id':key, 'etabs_tip_mm':a['tip_x_m']*1000,
            'opensees_tip_mm':b['tip_x_m']*1000,
            'beam_estimate_mm':a['beam_reference']['timoshenko_m']*1000,
            'etabs_over_opensees_minus_one':a['tip_x_m']/b['tip_x_m']-1,
            'etabs_beam_relative_difference':a['beam_relative_difference'],
            'opensees_beam_relative_difference':b['beam_relative_difference'],
            'opensees_discrete_verified':b['discrete_verified']})
    return rows


def run_wall_study(spec: SingleWallSpec, directory: Path, report: Path, config: ETABSConfig,
                   *, inputs: dict[str, Path]) -> dict[str, Any]:
    """Fixed adapter entry; preserve every failure and immutable source snapshot."""
    directory, report = directory.resolve(), report.resolve()
    if report.exists():
        raise FileExistsError(report)
    create_run(directory, seed=0, inputs=inputs, config=spec.model_dump(mode='json'))
    write_json(directory/'request.json', spec.model_dump(mode='json'))
    try:
        outcome = run_verification(spec, directory/'etabs', config)
        if outcome['status'] != 'SUCCESS':
            raise RuntimeError(f"ETABS single-wall study {outcome['status']}; see etabs/outcome.json")
        cases = wall_cases(spec)
        native = [solve_wall(case, directory/'opensees'/case.case_id) for case in cases]
        # Independent section-refinement control at fixed finest vertical mesh.
        controls = []
        for fibers in (32, 128):
            case = next(c for c in cases if c.case_id == f'none_n{spec.subdivisions[-1]}')
            case = case.model_copy(update={'fibers':fibers, 'case_id':f'none_fibers{fibers}'})
            controls.append(solve_wall(case, directory/'opensees'/case.case_id))
        write_json(directory/'opensees_results.json', {'cases':native, 'fiber_controls':controls})
        rows = compare_cases(outcome['payload']['result']['cases'], native)
        result = {'status':'DIFFERENCES_REPORTED_NOT_ACCEPTANCE',
            'mesh_status':'MESH_CONVERGENCE_NOT_ESTABLISHED', 'rows':rows,
            'engineering_feasibility':'NOT_EVALUATED', 'source_member_id':spec.source_member_id,
            'opensees_version':native[0]['solver_version'], 'etabs_version':outcome['payload']['version'],
            'all_mvlem_discrete_verified':all(r['discrete_verified'] for r in native+controls),
            'fiber_controls':[{'fibers':r['case']['fibers'], 'tip_mm':r['tip_x_m']*1000,
                'discrete_verified':r['discrete_verified']} for r in controls]}
        write_json(directory/'comparison.json', result)
        create_run(report, seed=0, inputs={
            'study_manifest':directory/'manifest.json', 'etabs_outcome':directory/'etabs'/'outcome.json',
            'opensees_results':directory/'opensees_results.json', 'comparison':directory/'comparison.json'},
            config={'purpose':'SINGLE_WALL_DIAGNOSTIC_REPORT', 'raw_run':str(directory)})
        write_json(report/'comparison.json', result)
        evidence = {str(p.relative_to(directory)):sha256(p) for p in sorted(directory.rglob('*')) if p.is_file()}
        write_json(report/'evidence_hashes.json', evidence)
        text = ['# 同条件单片墙诊断', '',
            f'原始证据：`{directory}`。来源：`{spec.residential.layout.layout_id}/{spec.source_member_id}`。', '',
            '墙转入全局XZ平面；底部六自由度固定，其他节点仅限制UY/RX/RZ。',
            '顶端两角各施加一半水平力；物理楼层刚性楼板在本平面等价于同层两端UX相等，UZ/RY不约束。',
            '全高统一底区墙厚；无质量、自重、重力、梁、显式楼板或几何非线性。中间网格不增加楼层约束。',
            'ShellThin与MVLEM的面内泊松效应及运动学仍不同；nu=0为独立材料控制，不用于拟合住宅。',
            '连续Timoshenko梁解是细长墙的理论参照，不能作为夹固弹性壳的精确解或统一验收标准。', '',
            '| 工况 | ETABS/mm | OpenSees/mm | 梁估计/mm | ETABS/OS−1 |',
            '|---|---:|---:|---:|---:|']
        text += [f"| {r['case_id']} | {r['etabs_tip_mm']:.9f} | {r['opensees_tip_mm']:.9f} | "
            f"{r['beam_estimate_mm']:.9f} | {r['etabs_over_opensees_minus_one']:.4%} |" for r in rows]
        text += ['', 'MVLEM独立离散解核对：'+str(result['all_mvlem_discrete_verified']), '',
            '状态：DIFFERENCES_REPORTED_NOT_ACCEPTANCE / MESH_CONVERGENCE_NOT_ESTABLISHED。',
            '整体平衡和有限响应检查不等于网格收敛；未对L/T形墙、墙梁或住宅整栋作可靠性结论。',
            '未改变生产建模器、物理指纹或历史标签，未进行参数优化或模型训练。', '']
        (report/'report.md').write_text('\n'.join(text), encoding='utf-8')
        return result
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__, message=str(error), traceback=traceback.format_exc(),
            context={'operation':'single-wall study', 'directory':str(directory)}, attempt=1)
        write_json(directory/'error.json', record.model_dump())
        raise
