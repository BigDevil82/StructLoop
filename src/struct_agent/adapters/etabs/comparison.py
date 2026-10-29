"""Report independent model differences; never infer engineering compliance."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from struct_agent.io.artifacts import create_run, write_json


def modal_mac(a: np.ndarray, b: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Modes a[M,D], b[N,D], weights[D]; float64, common floor XYZ coordinates."""
    if a.ndim!=2 or b.ndim!=2 or a.shape[1]!=b.shape[1] or weights.shape!=(a.shape[1],):
        raise ValueError('Mode shape dimensions differ')
    if not all(np.isfinite(x).all() for x in (a,b,weights)) or np.any(weights<=0):
        raise ValueError('Finite modes and strictly positive mass weights required')
    na,nb = (a*a*weights).sum(1),(b*b*weights).sum(1)
    if np.any(na<=0) or np.any(nb<=0):
        raise ValueError('Zero mode shape')
    return np.clip(((a*weights)@b.T)**2/(na[:,None]*nb[None,:]),0.,1.)


def compare(etabs_directory: Path, reference_directory: Path, directory: Path) -> dict[str,Any]:
    from scipy.optimize import linear_sum_assignment
    epath,opath = etabs_directory/'worker_result.json',reference_directory/'result.json'
    e = json.loads(epath.read_text(encoding='utf-8'))['result']
    o = json.loads(opath.read_text(encoding='utf-8'))
    em = json.loads((etabs_directory/'manifest.json').read_text(encoding='utf-8'))
    om = json.loads((reference_directory/'manifest.json').read_text(encoding='utf-8'))
    if em['config']['spec']!=om['config']['spec'] or not e['verified'] or not o['verified']:
        raise ValueError('Different inputs or invalid source analyses')
    weights = np.array([[f['mass_kg'],f['mass_kg'],f['inertia_kg_m2']] for f in o['floor_inputs']]).ravel()
    ea = np.array([[[row[k] for k in ('u1','u2','r3')] for row in floor] for floor in e['floor_mode_shapes']])
    ea = ea.transpose(1,0,2).reshape(len(e['modes']),-1)
    oa = np.array(o['floor_mode_shapes']).reshape(len(o['periods_s']),-1)
    mac = modal_mac(ea,oa,weights)
    ii,jj = linear_sum_assignment(-mac)
    modes = [{'etabs_mode':int(i+1),'opensees_mode':int(j+1),'mac':float(mac[i,j]),
        'etabs_period_s':e['modes'][i]['period'],'opensees_period_s':o['periods_s'][j],
        'relative_difference_to_etabs':o['periods_s'][j]/e['modes'][i]['period']-1} for i,j in zip(ii,jj)]
    static = {}
    for case in ('ROOF_X','ROOF_Y'):
        rows = []
        for story,(ee,oo) in enumerate(zip(e['static'][case]['floors'],o['static'][case]['floors']),1):
            for component in ('u1','u2','r3'):
                a,b = ee[0][component],oo[component]
                rows.append({'story':story,'component':component,'etabs':a,'opensees':b,'difference':b-a,
                    'relative_difference_to_etabs':None if abs(a)<1e-12 else (b-a)/abs(a)})
        static[case] = rows
    result = {'status':'DIFFERENCES_REPORTED_NOT_ACCEPTANCE','periods':modes,'mass_weighted_mac_matrix':mac.tolist(),
        'static':static,'units':'N_m_kg_s','engineering_feasibility':'NOT_EVALUATED',
        'scope':'Identical prescribed lateral masses, endpoint-based rotational inertia, roof forces and rigid diaphragms; not gravity/seismic/rebar validation'}
    create_run(directory,seed=0,inputs={'etabs_result':epath,'opensees_result':opath,
        'etabs_manifest':etabs_directory/'manifest.json','opensees_manifest':reference_directory/'manifest.json'},
        config={'purpose':'12_story_independent_elastic_model_comparison'})
    write_json(directory/'comparison.json',result)
    lines = ['# 12层住宅弹性模型对照','',
        '质量和水平加载一致；周期按质量加权MAC一对一匹配。差异尚待解释，不是工程验收或配筋验证。','',
        '| ETABS阶次 | OpenSees阶次 | ETABS T/s | OpenSees T/s | 相对ETABS差异 | MAC |',
        '|---|---|---|---|---|---|']
    for mode in modes:
        lines.append(f"| {mode['etabs_mode']} | {mode['opensees_mode']} | {mode['etabs_period_s']:.6f} | {mode['opensees_period_s']:.6f} | {mode['relative_difference_to_etabs']:.2%} | {mode['mac']:.6f} |")
    lines += ['','## 屋顶水平加载响应','',
        '| 加载方向 | ETABS屋顶主方向位移/mm | OpenSees位移/mm | 相对ETABS差异 |',
        '|---|---|---|---|']
    for case,component in (('ROOF_X','u1'),('ROOF_Y','u2')):
        row=next(row for row in static[case] if row['story']==len(o['floor_inputs']) and row['component']==component)
        lines.append(f"| {case} | {row['etabs']*1000:.6f} | {row['opensees']*1000:.6f} | {row['relative_difference_to_etabs']:.2%} |")
    lines += ['','全部耦合位移/扭转分量保存在comparison.json；不删除差异较大的小量。',
        '当前仅对齐弹性水平诊断。恒活载、反应谱、规范组合、配筋和几何修复尚未完成独立复核。',
        '本例保留未修复短墙/短梁以诊断，不允许作为工程可行方案或进入正式优化。']
    (directory/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result
