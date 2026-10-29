"""Auditable one-factor/mesh study from immutable, actual solver results."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import numpy as np

from struct_agent.io.artifacts import create_run,write_json


def compliance_audit(result: dict[str,Any], force_n: float, backend: Literal['etabs','opensees']) -> dict[str,Any]:
    """Roof 2x2 compliance: rows are global UX/UY, columns are FX/FY."""
    if not np.isfinite(force_n) or force_n<=0. or backend not in ('etabs','opensees'):
        raise ValueError('Positive finite force and a supported backend required')
    matrix = []
    for component in ('u1','u2'):
        row = []
        for case in ('ROOF_X','ROOF_Y'):
            value = result['static'][case]['floors'][-1]
            row.append((value[0] if backend=='etabs' else value)[component]/force_n)
        matrix.append(row)
    c = np.asarray(matrix,dtype=np.float64)
    if not np.isfinite(c).all():
        raise ValueError('Invalid compliance input')
    defect = float(np.max(abs(c-c.T))/max(np.max(abs(c)),1e-30))
    eigenvalues = np.linalg.eigvalsh((c+c.T)/2)
    return {'compliance_m_per_n':c.tolist(),'relative_reciprocity_defect':defect,
        'reciprocity_check':defect<1e-7,'positive_work':bool(np.all(eigenvalues>0)),
        'meaning':'Linear response consistency check, not proof of correct structural stiffness'}


def build_report(etabs_runs: dict[str,Path], reference_runs: dict[str,Path], substructure_run: Path,
                 directory: Path) -> dict[str,Any]:
    inputs,records,physical_spec = {},{},None
    for backend,runs in (('etabs',etabs_runs),('opensees',reference_runs)):
        for name,run in runs.items():
            path = run/('worker_result.json' if backend=='etabs' else 'result.json')
            payload=json.loads(path.read_text(encoding='utf-8'))
            result=payload['result'] if backend=='etabs' else payload
            manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
            spec=manifest['config']['spec']
            if physical_spec is None: physical_spec=spec
            if spec!=physical_spec or not result['verified']:
                raise ValueError('Physical inputs differ or source analysis failed')
            inputs[name+'_result']=path
            inputs[name+'_manifest']=run/'manifest.json'
            floors=result['prescribed_floor_masses_kg'] if backend=='etabs' else [f['mass_kg'] for f in result['floor_inputs']]
            audit=compliance_audit(result,float(spec['roof_force_n']),backend)
            roof={}
            for case,component in (('ROOF_X','u1'),('ROOF_Y','u2')):
                row=result['static'][case]['floors'][-1]
                roof[case]=(row[0] if backend=='etabs' else row)[component]*1000
            records[name]={'backend':backend,'roof_primary_displacement_mm':roof,'audit':audit,
                'masses_kg':floors,'options':manifest['config'].get('diagnostic_mesh',manifest['config'].get('etabs',{}))}
    mass_arrays=[np.array(row['masses_kg']) for row in records.values()]
    if any(a.shape!=mass_arrays[0].shape or not np.allclose(a,mass_arrays[0],rtol=1e-10,atol=1e-8) for a in mass_arrays):
        raise ValueError('Mesh/theory study changed prescribed mass')
    if physical_spec is None or physical_spec['project']['stories']!=12:
        raise ValueError('This report requires the approved 12-story study')
    sources=json.loads((substructure_run/'results.json').read_text(encoding='utf-8'))
    if not sources['verified']:
        raise ValueError('Substructure analytical checks failed')
    inputs['substructures']=substructure_run/'results.json'
    result={'status':'MESH_CONVERGENCE_NOT_ESTABLISHED','stories':12,'records':records,
        'substructures':sources,'prescribed_masses_unchanged':True,'physical_inputs_equal':True,
        'engineering_acceptance':'NOT_VALIDATED','note':'Coarse-model agreement does not establish mesh convergence'}
    create_run(directory,seed=0,inputs=inputs,config={'purpose':'X_DISPLACEMENT_DIAGNOSIS','physical_spec':physical_spec})
    write_json(directory/'results.json',result)
    lines=['# X向位移、子结构与网格检查','',
        '所有住宅试验均为同一12层、同一截面/质量/诊断荷载。网格内节点不是新楼层。','',
        '| 试验 | X加载屋顶X位移/mm | Y加载屋顶Y位移/mm | 互易性归一化缺陷 |',
        '|---|---|---|---|']
    for name,row in records.items():
        roof=row['roof_primary_displacement_mm']
        lines.append(f"| {name} | {roof['ROOF_X']:.6f} | {roof['ROOF_Y']:.6f} | {row['audit']['relative_reciprocity_defect']:.3e} |")
    lines+=['','结论：梁剪切变形显著影响结果；整栋竖向网格敏感性更大，当前不能宣称整栋收敛或工程可靠性验收通过。',
        '1:1单元重建、仅截面纤维加密用于检查验证工具；较细竖向网格仍需结合两后端共同评估。',
        '当前研究未改变正式建模器默认值、原始布局、权重或既有数值结果。','',
        '单片墙解析验证限定为规定的平截面弹性梁化假定。该子结构通过不代表复杂住宅已收敛。']
    (directory/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result
