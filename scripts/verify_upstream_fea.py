"""Development-only numerical regression against read-only original OpenSees code.

Run with the upstream Python using -B (no writes of upstream bytecode). Outputs
are exclusively created in a new StructLoop directory. This is not a benchmark.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--layout',type=Path,required=True)
    parser.add_argument('--record',type=Path,required=True)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    # Validate all explicit inputs before importing the controlled reference backend.
    layout = json.loads(args.layout.resolve().read_text(encoding='utf-8'))
    record = json.loads(args.record.resolve().read_text(encoding='utf-8'))
    spec = json.loads(args.spec.resolve().read_text(encoding='utf-8'))
    migrated = record['analysis']['raw']
    args.output.mkdir(parents=True,exist_ok=False)
    source = args.source.resolve()
    sys.path.insert(0,str(source))
    import os
    os.chdir(args.output.resolve())  # original ops.log remains in this new regression run
    from src.shearwall_modeling.core.domain import FEMInput, PlanMember, BeamMember, BeamRole, Point2D
    from src.shearwall_modeling.parametric.analysis import analyze_parametric_model
    from src.shearwall_modeling.parametric.types import DatasetGenerationConfig, ParametricModelParams
    assert record['design']['condition_id'] == spec['condition_id']
    values = record['design']['values']
    native = {k:round(v*1000) if k != 'conc_bot' else v for k,v in values.items()}
    params = ParametricModelParams(**native,N=spec['stories'],hs=round(spec['slab_thickness_m']*1000),
        h_story=spec['story_height_m'],intensity=spec['intensity'],site_class=spec['site_class'],
        seismic_group=spec['seismic_group'],conc_mid=native['conc_bot'],conc_top=native['conc_bot'])
    walls, beams = [], []
    for i,m in enumerate(layout['members']):
        base = dict(m_id=i,start=Point2D(*m['start']),end=Point2D(*m['end']))
        if m['role'] == 'wall':
            walls.append(PlanMember(cate='shearwall',**base))
        else:
            beams.append(BeamMember(cate='beam',role=BeamRole(m['role']),**base))
    topology = FEMInput(walls,beams,[[Point2D(*p) for p in poly] for poly in layout['slabs']])
    result = asdict(analyze_parametric_model(topology,params,DatasetGenerationConfig(
        builder_name='mvlem_frame',input_unit_scale_to_m=1.,enable_auto_scale=False,seed=0,scale_seed=0)))
    comparisons = {}
    for name,expected in migrated.items():
        actual = result[name]
        if isinstance(expected,bool) or isinstance(expected,str):
            passed = actual == expected
        elif expected is None:
            passed = isinstance(actual,float) and not math.isfinite(actual)
        else:
            passed = math.isclose(actual,expected,rel_tol=1e-5,abs_tol=1e-8)
        comparisons[name] = {'expected':expected,'actual':actual,'passed':passed}
    def safe(value: object) -> object:
        if isinstance(value,float) and not math.isfinite(value):
            return None
        if isinstance(value,dict):
            return {k:safe(v) for k,v in value.items()}
        return value
    with Path('comparison.json').open('x',encoding='utf-8') as stream:
        json.dump(safe(comparisons),stream,ensure_ascii=False,indent=2,allow_nan=False)
    failures = [k for k,v in comparisons.items() if not v['passed']]
    print(f'Original/migrated FEA fields: {len(comparisons)}; failures: {failures}')
    if failures:
        raise AssertionError(f'FEA regression mismatch: {failures}')


if __name__ == '__main__':
    main()
